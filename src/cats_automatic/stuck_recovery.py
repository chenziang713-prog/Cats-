from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from .actions import ActionResult
from .strategy_base import StrategyDecision


@dataclass(frozen=True)
class StuckRecoveryConfig:
    same_step_threshold: int = 10
    same_state_threshold: int = 10
    unknown_level_1_threshold: int = 3
    unknown_level_2_threshold: int = 5
    repeated_action_threshold: int = 3
    no_progress_threshold: int = 12
    close_ad_attempt_limit: int = 3
    recovery_cooldown_loops: int = 1
    max_same_recovery_reason: int = 3
    max_consecutive_press_back: int = 2


@dataclass
class StuckMonitorState:
    current_step: str = ""
    previous_step: str | None = None
    current_state: str = ""
    previous_state: str | None = None
    same_step_loops: int = 0
    same_state_loops: int = 0
    unknown_state_loops: int = 0
    repeated_action_count: int = 0
    last_action: str = ""
    last_action_screenshot_path: str = ""
    last_action_success: bool = False
    last_clicked_marker: str | None = None
    last_clicked_pos: tuple[int, int] | None = None
    last_progress_loop: int = 0
    recovery_attempts: int = 0
    last_recovery_reason: str = ""
    last_recovery_action: str = ""
    last_recovery_loop: int = 0
    last_recovery_screenshot_path: str = ""
    consecutive_press_back: int = 0
    same_recovery_reason_counts: Counter[str] = field(default_factory=Counter)

    def as_dict(self) -> dict[str, Any]:
        return {
            "current_step": self.current_step,
            "previous_step": self.previous_step,
            "current_state": self.current_state,
            "previous_state": self.previous_state,
            "same_step_loops": self.same_step_loops,
            "same_state_loops": self.same_state_loops,
            "unknown_state_loops": self.unknown_state_loops,
            "repeated_action_count": self.repeated_action_count,
            "last_action": self.last_action,
            "last_action_success": self.last_action_success,
            "last_clicked_marker": self.last_clicked_marker,
            "last_clicked_pos": None if self.last_clicked_pos is None else list(self.last_clicked_pos),
            "last_progress_loop": self.last_progress_loop,
            "recovery_attempts": self.recovery_attempts,
            "last_recovery_reason": self.last_recovery_reason,
            "last_recovery_action": self.last_recovery_action,
        }


@dataclass(frozen=True)
class RecoveryPlan:
    stuck_reason: str
    recovery_level: int
    recovery_action: str
    decision: StrategyDecision | None
    event: dict[str, Any]


class StuckRecoveryTracker:
    def __init__(self, config: StuckRecoveryConfig | None = None) -> None:
        self.config = config or StuckRecoveryConfig()
        self.state = StuckMonitorState()
        self._pending_recovery: RecoveryPlan | None = None

    def consume_pending_recovery(self, *, loop_index: int, screenshot_path: str) -> RecoveryPlan | None:
        plan = self._pending_recovery
        if plan is None:
            return None
        if (
            screenshot_path == self.state.last_recovery_screenshot_path
            and loop_index - self.state.last_recovery_loop <= self.config.recovery_cooldown_loops
        ):
            return None
        self._pending_recovery = None
        return plan

    def observe(
        self,
        *,
        loop_index: int,
        current_step: str,
        current_state: str,
        action: str,
        action_result: ActionResult,
        screenshot_path: str,
        step_changed: bool,
        clicked_marker: str | None = None,
        close_ad_attempts: int = 0,
    ) -> RecoveryPlan | None:
        previous_step = self.state.current_step or None
        previous_state = self.state.current_state or None
        action_success = bool(action_result.success)
        clicked_pos = action_result.clicked_pos

        self.state.previous_step = previous_step
        self.state.previous_state = previous_state
        self.state.current_step = current_step
        self.state.current_state = current_state
        self.state.same_step_loops = (
            self.state.same_step_loops + 1 if previous_step == current_step else 1
        )
        self.state.same_state_loops = (
            self.state.same_state_loops + 1 if previous_state == current_state else 1
        )
        self.state.unknown_state_loops = (
            self.state.unknown_state_loops + 1 if current_state == "UNKNOWN_PAGE" else 0
        )
        action_key = _action_key(action, clicked_marker, screenshot_path)
        last_key = _action_key(
            self.state.last_action,
            self.state.last_clicked_marker,
            self.state.last_action_screenshot_path,
        )
        self.state.repeated_action_count = (
            self.state.repeated_action_count + 1 if action_key == last_key else 1
        )
        self.state.last_action = action
        self.state.last_action_screenshot_path = screenshot_path
        self.state.last_action_success = action_success
        self.state.last_clicked_marker = clicked_marker
        self.state.last_clicked_pos = clicked_pos

        progress = self._is_progress(
            loop_index=loop_index,
            step_changed=step_changed,
            previous_state=previous_state,
            current_state=current_state,
        )
        if progress:
            self.state.last_progress_loop = loop_index
            self.state.same_step_loops = 1
            self.state.same_state_loops = 1
            if current_state != "UNKNOWN_PAGE":
                self.state.unknown_state_loops = 0
            self.state.repeated_action_count = 1
            if current_state in {"HOME_PAGE", "ACTIVITY_PAGE", "REWARD_PAGE"}:
                self.state.consecutive_press_back = 0
            return None

        reason = self._detect_stuck_reason(loop_index, close_ad_attempts)
        if reason is None:
            return None
        return self._plan_recovery(
            stuck_reason=reason,
            loop_index=loop_index,
            screenshot_path=screenshot_path,
        )

    def _is_progress(
        self,
        *,
        loop_index: int,
        step_changed: bool,
        previous_state: str | None,
        current_state: str,
    ) -> bool:
        if step_changed:
            return True
        if current_state == "FINISH" or self.state.current_step == "FINISH":
            return True
        if (
            previous_state is not None
            and previous_state != current_state
            and previous_state != "UNKNOWN_PAGE"
            and current_state != "UNKNOWN_PAGE"
        ):
            return True
        if (
            self.state.last_recovery_action
            and current_state in {"HOME_PAGE", "ACTIVITY_PAGE", "REWARD_PAGE"}
            and loop_index > self.state.last_recovery_loop
        ):
            return True
        return False

    def _detect_stuck_reason(self, loop_index: int, close_ad_attempts: int) -> str | None:
        if close_ad_attempts >= self.config.close_ad_attempt_limit:
            return "close_ad_attempt_limit"
        if self.state.unknown_state_loops >= self.config.unknown_level_1_threshold:
            return "unknown_state_stuck"
        if self.state.repeated_action_count >= self.config.repeated_action_threshold:
            return "repeated_action"
        if self.state.same_step_loops >= self.config.same_step_threshold:
            return "step_stuck"
        if self.state.same_state_loops >= self.config.same_state_threshold:
            return "state_stuck"
        if (
            self.state.last_progress_loop
            and loop_index - self.state.last_progress_loop >= self.config.no_progress_threshold
        ):
            return "no_progress_timeout"
        return None

    def _plan_recovery(
        self,
        *,
        stuck_reason: str,
        loop_index: int,
        screenshot_path: str,
    ) -> RecoveryPlan | None:
        if (
            screenshot_path == self.state.last_recovery_screenshot_path
            and loop_index - self.state.last_recovery_loop <= self.config.recovery_cooldown_loops
        ):
            return None
        if self.state.same_recovery_reason_counts[stuck_reason] >= self.config.max_same_recovery_reason:
            level = 3
        elif (
            stuck_reason == "unknown_state_stuck"
            and self.state.unknown_state_loops >= self.config.unknown_level_2_threshold
        ):
            level = 2
        elif stuck_reason in {"repeated_action", "close_ad_attempt_limit", "no_progress_timeout"}:
            level = 2
        else:
            level = 1

        if level == 2 and self.state.consecutive_press_back >= self.config.max_consecutive_press_back:
            level = 3
        self.state.recovery_attempts += 1
        self.state.same_recovery_reason_counts[stuck_reason] += 1
        self.state.last_recovery_reason = stuck_reason
        self.state.last_recovery_loop = loop_index
        self.state.last_recovery_screenshot_path = screenshot_path

        decision: StrategyDecision | None
        if level == 1:
            action = "wait"
            decision = StrategyDecision.action(
                "wait",
                params={"seconds": 1.0},
                reason="recovery_level_1_wait",
                wait_seconds=1.0,
            )
        elif level == 2:
            action = "press_back"
            self.state.consecutive_press_back += 1
            decision = StrategyDecision.keyevent(
                "BACK",
                "press_back",
                "recovery_level_2_press_back",
            )
        else:
            action = "reset_go_home"
            decision = None
        self.state.last_recovery_action = action

        event = {
            "stuck_detected": True,
            "stuck_reason": stuck_reason,
            "recovery_level": level,
            "recovery_action": action,
            "recovery_attempts": self.state.recovery_attempts,
            "same_step_loops": self.state.same_step_loops,
            "same_state_loops": self.state.same_state_loops,
            "unknown_state_loops": self.state.unknown_state_loops,
            "repeated_action_count": self.state.repeated_action_count,
            "last_progress_loop": self.state.last_progress_loop,
            "step_before_recovery": self.state.current_step,
            "step_after_recovery": "GO_HOME" if level == 3 else self.state.current_step,
            "state": self.state.current_state,
            "screenshot_path": screenshot_path,
            **self.state.as_dict(),
        }
        plan = RecoveryPlan(
            stuck_reason=stuck_reason,
            recovery_level=level,
            recovery_action=action,
            decision=decision,
            event=event,
        )
        if decision is not None:
            self._pending_recovery = plan
        return plan


def _action_key(action: str, marker: str | None, screenshot_path: str) -> tuple[str, str, str]:
    return action, marker or "", screenshot_path

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Mapping

from PIL import Image, ImageChops, ImageStat

from .actions import ActionResult
from .strategy_base import DetectionResult, StrategyDecision


@dataclass(frozen=True)
class RecoveryAction:
    type: str
    seconds: float = 0.0


DEFAULT_RECOVERY_ACTIONS = (
    RecoveryAction("adb_back"),
    RecoveryAction("wait", 1.0),
    RecoveryAction("detect_and_resume"),
)


@dataclass(frozen=True)
class RecoveryConfig:
    same_state_stall_seconds: float = 180.0
    same_wait_reason_limit: int = 60
    no_progress_seconds: float = 240.0
    wait_not_on_target_page_seconds: float = 180.0
    no_known_targets_seconds: float = 120.0
    ad_stage_hard_timeout_seconds: float = 120.0
    click_no_effect_limit: int = 2
    max_recovery_attempts_per_cycle: int = 3
    max_recovery_attempts_per_run: int = 10
    recovery_cooldown_seconds: float = 60.0


@dataclass(frozen=True)
class RecoveryTrigger:
    reason: str
    should_recover: bool
    state: str
    wait_reason: str
    recovery_attempt_cycle: int
    recovery_attempt_run: int
    actions: tuple[RecoveryAction, ...] = DEFAULT_RECOVERY_ACTIONS


@dataclass
class PendingClick:
    decision: str
    target_name: str
    state_before: str
    screenshot_before: Path | None
    detections_before: frozenset[str]


class GlobalStallWatchdog:
    def __init__(
        self,
        config: RecoveryConfig | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config or RecoveryConfig()
        self.clock = clock
        self.run_recovery_attempts = 0
        self.cycle_recovery_attempts = 0
        self._events: list[dict[str, object]] = []
        self._state = ""
        self._state_since = self.clock()
        self._last_progress_at = self._state_since
        self._no_known_targets_since: float | None = None
        self._wait_not_on_target_since: float | None = None
        self._ad_stage_since: float | None = None
        self._last_wait_reason = ""
        self._same_wait_count = 0
        self._last_recovery_at: float | None = None
        self._pending_click: PendingClick | None = None
        self._click_no_effect_count = 0
        self._pending_recovery_state: str | None = None
        self._current_screenshot_path: Path | None = None
        self._current_detection_names: tuple[str, ...] = ()

    def reset_cycle(self) -> None:
        now = self.clock()
        self.cycle_recovery_attempts = 0
        self._state = ""
        self._state_since = now
        self._last_progress_at = now
        self._no_known_targets_since = None
        self._wait_not_on_target_since = None
        self._ad_stage_since = None
        self._last_wait_reason = ""
        self._same_wait_count = 0
        self._pending_click = None
        self._click_no_effect_count = 0
        self._pending_recovery_state = None

    def observe(
        self,
        *,
        state: str,
        decision: StrategyDecision,
        detections: Mapping[str, DetectionResult],
        screenshot_path: Path | None,
    ) -> RecoveryTrigger | None:
        now = self.clock()
        self._current_screenshot_path = screenshot_path
        self._current_detection_names = tuple(sorted(detections))
        state_changed = bool(self._state and state != self._state)
        if not self._state or state_changed:
            self._state = state
            self._state_since = now
            self._mark_progress(now)

        if self._pending_recovery_state is not None:
            if state_changed or detections:
                self._events.append(
                    {
                        "event": "recovery_succeeded",
                        "state": state,
                        "detected_targets": sorted(detections),
                    }
                )
                self._mark_progress(now)
            else:
                self._events.append(
                    {"event": "recovery_failed", "state": state, "reason": "no_target_after_back"}
                )
            self._pending_recovery_state = None

        click_trigger = self._check_pending_click(
            state=state,
            detections=detections,
            screenshot_path=screenshot_path,
        )
        if click_trigger is not None:
            return self._trigger(click_trigger, state, decision.reason, now)

        normal_wait = decision.kind == "wait" and decision.reason in {"cycle_wait", "battle_wait", "ad_wait"}
        if normal_wait:
            self._last_wait_reason = decision.reason
            self._same_wait_count = 0
            return None

        if decision.kind == "wait":
            if decision.reason == self._last_wait_reason:
                self._same_wait_count += 1
            else:
                self._last_wait_reason = decision.reason
                self._same_wait_count = 1
        else:
            self._last_wait_reason = ""
            self._same_wait_count = 0

        if detections:
            self._no_known_targets_since = None
        elif self._no_known_targets_since is None:
            self._no_known_targets_since = now

        if decision.reason == "wait_not_on_target_page":
            if self._wait_not_on_target_since is None:
                self._wait_not_on_target_since = now
        else:
            self._wait_not_on_target_since = None

        ad_stage = self._is_ad_stage(state)
        if ad_stage and not self._has_ad_progress_target(detections):
            if self._ad_stage_since is None:
                self._ad_stage_since = now
        else:
            self._ad_stage_since = None

        checks = (
            (
                self._same_wait_count >= self.config.same_wait_reason_limit,
                "same_wait_reason_limit",
            ),
            (
                now - self._state_since >= self.config.same_state_stall_seconds,
                "same_state_stall_seconds",
            ),
            (
                now - self._last_progress_at >= self.config.no_progress_seconds,
                "no_progress_seconds",
            ),
            (
                self._wait_not_on_target_since is not None
                and now - self._wait_not_on_target_since
                >= self.config.wait_not_on_target_page_seconds,
                "wait_not_on_target_page_seconds",
            ),
            (
                self._no_known_targets_since is not None
                and now - self._no_known_targets_since >= self.config.no_known_targets_seconds,
                "no_known_targets_seconds",
            ),
            (
                self._ad_stage_since is not None
                and now - self._ad_stage_since >= self.config.ad_stage_hard_timeout_seconds,
                "ad_stage_hard_timeout_seconds",
            ),
        )
        for matched, reason in checks:
            if matched:
                return self._trigger(reason, state, decision.reason, now)
        return None

    def register_action(
        self,
        *,
        decision: StrategyDecision,
        action_result: ActionResult,
        state: str,
        screenshot_path: Path | None,
        detections: Mapping[str, DetectionResult],
    ) -> None:
        if action_result.result != "executed":
            return
        now = self.clock()
        if decision.kind in {"click", "tap"}:
            self._pending_click = PendingClick(
                decision=decision.action_name or decision.kind,
                target_name=decision.target_name or "",
                state_before=state,
                screenshot_before=screenshot_path,
                detections_before=frozenset(detections),
            )
        self._mark_progress(now)

    def record_recovery_action_result(
        self,
        *,
        state: str,
        action_result: ActionResult,
    ) -> None:
        self._events.append(
            {
                "event": "recovery_action",
                "action": "adb_back",
                "decision": "problem_recovery_adb_back",
                "result": action_result.result,
                "state": state,
                "attempt_cycle": self.cycle_recovery_attempts,
                "attempt_run": self.run_recovery_attempts,
            }
        )
        if action_result.result == "executed":
            self._pending_recovery_state = state
        else:
            self._events.append(
                {
                    "event": "recovery_failed",
                    "state": state,
                    "reason": action_result.result,
                }
            )

    def drain_events(self) -> list[dict[str, object]]:
        events = self._events
        self._events = []
        return events

    def _trigger(
        self,
        reason: str,
        state: str,
        wait_reason: str,
        now: float,
    ) -> RecoveryTrigger | None:
        if self._last_recovery_at is not None:
            if now - self._last_recovery_at < self.config.recovery_cooldown_seconds:
                return None
        if self.cycle_recovery_attempts >= self.config.max_recovery_attempts_per_cycle:
            self._events.append(
                {
                    "event": "recovery_failed",
                    "state": state,
                    "reason": "max_recovery_attempts_per_cycle_reached",
                }
            )
            return RecoveryTrigger(
                "max_recovery_attempts_per_cycle_reached",
                False,
                state,
                wait_reason,
                self.cycle_recovery_attempts,
                self.run_recovery_attempts,
            )
        if self.run_recovery_attempts >= self.config.max_recovery_attempts_per_run:
            self._events.append(
                {
                    "event": "recovery_failed",
                    "state": state,
                    "reason": "max_recovery_attempts_per_run_reached",
                }
            )
            return RecoveryTrigger(
                "max_recovery_attempts_per_run_reached",
                False,
                state,
                wait_reason,
                self.cycle_recovery_attempts,
                self.run_recovery_attempts,
            )
        self.cycle_recovery_attempts += 1
        self.run_recovery_attempts += 1
        self._last_recovery_at = now
        self._events.append(
            {
                "event": "global_stall_detected",
                "reason": reason,
                "state": state,
                "wait_reason": wait_reason,
                "attempt_cycle": self.cycle_recovery_attempts,
                "attempt_run": self.run_recovery_attempts,
                "screenshot_path": (
                    "" if self._current_screenshot_path is None else str(self._current_screenshot_path)
                ),
                "top_detections": list(self._current_detection_names),
            }
        )
        return RecoveryTrigger(
            reason,
            True,
            state,
            wait_reason,
            self.cycle_recovery_attempts,
            self.run_recovery_attempts,
        )

    def _check_pending_click(
        self,
        *,
        state: str,
        detections: Mapping[str, DetectionResult],
        screenshot_path: Path | None,
    ) -> str | None:
        pending = self._pending_click
        if pending is None:
            return None
        self._pending_click = None
        target_still_present = bool(pending.target_name and pending.target_name in detections)
        state_unchanged = state == pending.state_before
        screen_unchanged = screenshots_similar(pending.screenshot_before, screenshot_path)
        detections_unchanged = pending.detections_before == frozenset(detections)
        if state_unchanged and target_still_present and (screen_unchanged or detections_unchanged):
            self._click_no_effect_count += 1
            self._events.append(
                {
                    "event": "click_no_effect_detected",
                    "decision": pending.decision,
                    "target_name": pending.target_name,
                    "state": state,
                    "count": self._click_no_effect_count,
                    "reason": "click_no_effect_same_screen_or_same_state",
                }
            )
            if self._click_no_effect_count >= self.config.click_no_effect_limit:
                return "click_no_effect_same_screen_or_same_state"
        else:
            self._click_no_effect_count = 0
            self._mark_progress(self.clock())
        return None

    def _mark_progress(self, now: float) -> None:
        self._last_progress_at = now

    @staticmethod
    def _is_ad_stage(state: str) -> bool:
        return state in {"ad_wait", "close_ad", "wait_return_after_ad", "film_ad_reward_phase"}

    @staticmethod
    def _has_ad_progress_target(detections: Mapping[str, DetectionResult]) -> bool:
        return any(
            name.startswith("close_")
            or name in {"ad_entry", "page_marker", "watch_ad_button", "reward_confirm_marker", "confirm_button", "scrap_entry"}
            for name in detections
        )


def screenshot_difference_percent(first: Path | None, second: Path | None) -> float | None:
    if first is None or second is None or not first.exists() or not second.exists():
        return None
    try:
        with Image.open(first) as first_image, Image.open(second) as second_image:
            first_gray = first_image.convert("L").resize((160, 90))
            second_gray = second_image.convert("L").resize((160, 90))
            difference = ImageChops.difference(first_gray, second_gray)
            mean = ImageStat.Stat(difference).mean[0]
            return mean / 255.0 * 100.0
    except (OSError, ValueError):
        return None


def screenshots_similar(first: Path | None, second: Path | None, threshold: float = 1.0) -> bool:
    difference = screenshot_difference_percent(first, second)
    return difference is not None and difference < threshold

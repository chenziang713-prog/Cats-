from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence

from .actions import ActionResult
from .runtime_paths import error_button_templates_dir, error_popup_templates_dir
from .strategy_base import DetectionResult, StrategyContext, StrategyDecision, TargetSpec


ERROR_POPUP_MIN_CONFIDENCE = 0.80
ERROR_BUTTON_MIN_CONFIDENCE = 0.80


@dataclass(frozen=True)
class ErrorPopupRecoveryConfig:
    max_attempts_per_cycle: int = 2
    max_attempts_per_run: int = 5
    cooldown_seconds: float = 60.0


@dataclass(frozen=True)
class RecoveryPathSnapshot:
    previous_state: str
    previous_phase: str
    previous_strategy: str
    previous_cycle_index: int
    previous_pending_goal: str
    last_expected_target: str
    last_stable_state: str
    last_stable_decision: str
    awaiting_watch_ad_in_cycle: bool
    strategy_context: dict[str, object]


class ErrorPopupRecoveryManager:
    def __init__(
        self,
        config: ErrorPopupRecoveryConfig | None = None,
        *,
        popup_dir: Path | None = None,
        button_dir: Path | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config or ErrorPopupRecoveryConfig()
        self.popup_dir = popup_dir or error_popup_templates_dir()
        self.button_dir = button_dir or error_button_templates_dir()
        self.clock = clock
        self.active = False
        self.awaiting_resume = False
        self.attempts_per_cycle = 0
        self.attempts_per_run = 0
        self.successes = 0
        self.failures = 0
        self.last_popup_name = ""
        self.last_button_name = ""
        self.snapshot: RecoveryPathSnapshot | None = None
        self._last_attempt_at: float | None = None
        self._events: list[dict[str, object]] = []

    def reset_cycle(self) -> None:
        self.active = False
        self.awaiting_resume = False
        self.attempts_per_cycle = 0
        self.snapshot = None

    def targets(self) -> Sequence[TargetSpec]:
        self.popup_dir.mkdir(parents=True, exist_ok=True)
        self.button_dir.mkdir(parents=True, exist_ok=True)
        popup_targets = tuple(
            TargetSpec(
                name=f"error_popup_{_safe_name(path.stem)}",
                template=str(path.resolve()),
                threshold=ERROR_POPUP_MIN_CONFIDENCE,
                scale_min=0.4,
                scale_max=1.1,
                scale_step=0.05,
                optional=True,
            )
            for path in sorted(self.popup_dir.glob("*.png"))
        )
        button_targets = tuple(
            TargetSpec(
                name=f"error_button_{_safe_name(path.stem)}",
                template=str(path.resolve()),
                threshold=ERROR_BUTTON_MIN_CONFIDENCE,
                scale_min=0.4,
                scale_max=1.1,
                scale_step=0.05,
                optional=True,
            )
            for path in sorted(self.button_dir.glob("*.png"))
        )
        return (*popup_targets, *button_targets)

    def start(
        self,
        *,
        strategy: object,
        cycle_index: int,
        last_decision: StrategyDecision | None,
    ) -> bool:
        now = self.clock()
        if self._last_attempt_at is not None and now - self._last_attempt_at < self.config.cooldown_seconds:
            return False
        if (
            self.attempts_per_cycle >= self.config.max_attempts_per_cycle
            or self.attempts_per_run >= self.config.max_attempts_per_run
        ):
            self._events.append(
                {
                    "event": "max_error_popup_recovery_attempts_reached",
                    "attempts_cycle": self.attempts_per_cycle,
                    "attempts_run": self.attempts_per_run,
                }
            )
            return False
        self.attempts_per_cycle += 1
        self.attempts_per_run += 1
        self._last_attempt_at = now
        self.active = True
        self.awaiting_resume = False
        self.snapshot = _snapshot(strategy, cycle_index, last_decision)
        self._events.append(
            {
                "event": "error_popup_recovery_started",
                "attempt_cycle": self.attempts_per_cycle,
                "attempt_run": self.attempts_per_run,
                "previous_state": self.snapshot.previous_state,
                "previous_phase": self.snapshot.previous_phase,
                "previous_strategy": self.snapshot.previous_strategy,
            }
        )
        return True

    def decide(self, context: StrategyContext) -> StrategyDecision | None:
        if not self.active:
            return None
        if self.awaiting_resume:
            return self._resume_decision(context.detections)
        workflow_targets = _workflow_targets(context.detections)
        if workflow_targets:
            self.active = False
            self._events.append(
                {
                    "event": "error_popup_recovery_skipped_for_workflow_target",
                    "targets": workflow_targets,
                }
            )
            return None

        popup = _best(context.detections, "error_popup_")
        button = _best(context.detections, "error_button_")
        if popup is None and button is not None:
            self._events.append(
                {
                    "event": "error_button_without_popup_ignored",
                    "button_name": button.name,
                    "confidence": button.confidence,
                }
            )
            return _wait_decision("error_popup_recovery_wait", "error_button_without_popup_ignored", button.name)
        if popup is not None and button is None:
            self.last_popup_name = popup.name
            self._events.extend(
                [
                    _detection_event("error_popup_detected", popup),
                    {
                        "event": "error_popup_detected_but_button_missing",
                        "popup_name": popup.name,
                    },
                ]
            )
            return _wait_decision("error_popup_recovery_wait", "error_popup_detected_but_button_missing", popup.name)
        if popup is None or button is None:
            self.failures += 1
            self.active = False
            self._events.append(
                {"event": "error_popup_recovery_failed", "reason": "error_popup_not_detected"}
            )
            return _wait_decision("error_popup_recovery_failed", "error_popup_not_detected")
        if not _button_near_popup(popup, button):
            self._events.append(
                {
                    "event": "error_button_without_popup_ignored",
                    "button_name": button.name,
                    "popup_name": popup.name,
                    "reason": "error_button_outside_popup_area",
                }
            )
            return _wait_decision("error_popup_recovery_wait", "error_button_outside_popup_area", button.name)

        self.last_popup_name = popup.name
        self.last_button_name = button.name
        self._events.extend(
            [
                _detection_event("error_popup_detected", popup),
                _detection_event("error_popup_button_detected", button),
            ]
        )
        return StrategyDecision.click(
            button.name,
            "error_popup_recovery_click",
            "error_popup_and_button_detected",
            post_action_delay_seconds=1.0,
            min_click_confidence_override=ERROR_BUTTON_MIN_CONFIDENCE,
        )

    def on_action_result(self, decision: StrategyDecision, result: ActionResult) -> None:
        if decision.action_name != "error_popup_recovery_click":
            return
        if result.result == "executed":
            self.awaiting_resume = True
            self._events.append(
                {
                    "event": "error_popup_button_clicked",
                    "popup_name": self.last_popup_name,
                    "button_name": self.last_button_name,
                    "action_type": result.action_type,
                    "result": result.result,
                }
            )
            return
        self.failures += 1
        self.active = False
        self._events.append(
            {"event": "error_popup_recovery_failed", "reason": result.result}
        )

    def drain_events(self) -> list[dict[str, object]]:
        events = self._events
        self._events = []
        return events

    def _resume_decision(
        self,
        detections: Mapping[str, DetectionResult],
    ) -> StrategyDecision | None:
        workflow_targets = _workflow_targets(detections)
        self.active = False
        self.awaiting_resume = False
        if workflow_targets:
            self.successes += 1
            self._events.extend(
                [
                    {
                        "event": "resume_state_detected_after_error_popup",
                        "targets": workflow_targets,
                    },
                    {
                        "event": "error_popup_recovery_succeeded",
                        "targets": workflow_targets,
                    },
                ]
            )
            return None
        self.failures += 1
        previous_state = "" if self.snapshot is None else self.snapshot.previous_state
        self._events.extend(
            [
                {
                    "event": "resume_previous_state_after_error_popup",
                    "previous_state": previous_state,
                },
                {
                    "event": "error_popup_recovery_failed",
                    "reason": "resume_screen_uncertain",
                    "previous_state": previous_state,
                },
            ]
        )
        return _wait_decision(
            "resume_previous_state_after_error_popup",
            "resume_previous_state_after_error_popup_uncertain",
        )


def _snapshot(
    strategy: object,
    cycle_index: int,
    last_decision: StrategyDecision | None,
) -> RecoveryPathSnapshot:
    child = getattr(strategy, "scrap_strategy", strategy)
    context_names = (
        "battle_clicked_in_cycle",
        "battle_wait_finished_in_cycle",
        "battle_result_closed_in_cycle",
        "scrap_watch_ad_clicked_in_cycle",
        "close_ad_executed",
        "scrap_phase_completed_in_cycle",
        "home_detected_after_scrap",
        "film_ad_reward_started_in_cycle",
        "film_ad_reward_completed_in_cycle",
    )
    return RecoveryPathSnapshot(
        previous_state=str(getattr(strategy, "state", getattr(child, "state", "unknown"))),
        previous_phase=str(getattr(strategy, "phase", "")),
        previous_strategy=type(strategy).__name__,
        previous_cycle_index=cycle_index,
        previous_pending_goal=str(getattr(strategy, "current_step_name", getattr(child, "current_step_name", ""))),
        last_expected_target="" if last_decision is None else (last_decision.target_name or ""),
        last_stable_state=str(getattr(strategy, "state", getattr(child, "state", "unknown"))),
        last_stable_decision="" if last_decision is None else (last_decision.action_name or last_decision.kind),
        awaiting_watch_ad_in_cycle=bool(getattr(child, "awaiting_watch_ad_in_cycle", False)),
        strategy_context={
            name: getattr(strategy, name, getattr(child, name, None)) for name in context_names
        },
    )


def _best(
    detections: Mapping[str, DetectionResult],
    prefix: str,
) -> DetectionResult | None:
    candidates = [item for name, item in detections.items() if name.startswith(prefix)]
    return None if not candidates else max(candidates, key=lambda item: item.confidence)


def _button_near_popup(popup: DetectionResult, button: DetectionResult) -> bool:
    popup_x, popup_y = popup.top_left
    popup_width, popup_height = popup.size
    margin_x = max(40, popup_width // 2)
    margin_y = max(40, popup_height // 2)
    button_x, button_y = button.center
    return (
        popup_x - margin_x <= button_x <= popup_x + popup_width + margin_x
        and popup_y - margin_y <= button_y <= popup_y + popup_height + margin_y
    )


def _workflow_targets(detections: Mapping[str, DetectionResult]) -> list[str]:
    known = {
        "battle_result_popup",
        "confirm_button",
        "scrap_watch_ad_button",
        "scrap_entry",
        "ad_entry",
        "page_marker",
        "watch_ad_button",
        "reward_confirm_marker",
        "scrap_next_button",
        "battle_button",
        "skip_button",
    }
    return sorted(
        name
        for name in detections
        if name in known or name.startswith("close_end_") or name.startswith("close_user_")
    )


def _wait_decision(action_name: str, reason: str, target_name: str | None = None) -> StrategyDecision:
    return StrategyDecision(
        kind="wait",
        target_name=target_name,
        action_name=action_name,
        wait_seconds=1.0,
        reason=reason,
    )


def _detection_event(event: str, detection: DetectionResult) -> dict[str, object]:
    return {
        "event": event,
        "target_name": detection.name,
        "confidence": detection.confidence,
        "center": list(detection.center),
    }


def _safe_name(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "_", value).strip("_").lower() or "template"

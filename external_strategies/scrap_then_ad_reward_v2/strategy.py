from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from cats_automatic.actions import ActionResult
from cats_automatic.strategy_base import DetectionResult, StrategyContext, StrategyDecision, TargetSpec

from external_strategies.scrap_then_ad_reward_v2.authoring import action_to_decision
from external_strategies.scrap_then_ad_reward_v2.close_markers import safe_close_marker_names
from external_strategies.scrap_then_ad_reward_v2.film_flow import (
    FILM_CLOSE_AD_MAX_TOTAL_CLICKS,
    FILM_ENTRY_MARKER,
    V2_TAP_MARKER_ALLOW_LIST,
    WATCH_AD_MARKER,
    decide_film_flow_action,
)
from external_strategies.scrap_then_ad_reward_v2.screen_state_detector import (
    detect_current_screen_state_from_detections,
    explain_screen_state_result,
)
from external_strategies.scrap_then_ad_reward_v2.screen_state_templates import SCREEN_STATE_TEMPLATES
from external_strategies.scrap_then_ad_reward_v2.state_action_templates import handle_screen_state
from external_strategies.scrap_then_ad_reward_v2.state_names import normalize_state_name
from external_strategies.scrap_then_ad_reward_v2.template_sources import (
    V2_CANONICAL_TEMPLATE_DIRS,
    collect_canonical_marker_names,
    template_paths_for_marker,
)


DEFAULT_TARGET_THRESHOLD = 0.80


class FilmFlowRuntimeContext:
    def __init__(self) -> None:
        self.current_step = "START"
        self.close_attempt_count = 0
        self.selected_reward: str | None = None
        self.last_state: str | None = None
        self.last_action: str | None = None
        self.pending_transition: str | None = None
        self.entry_click_attempts = 0
        self.watch_ad_click_attempts = 0
        self.reward_click_attempts = 0
        self.last_close_marker: str | None = None
        self.last_close_screenshot_path = ""


class Strategy:
    """Thin runtime adapter for the canonical v2 detector and film flow."""

    handles_reward_cycle_completion = True
    tap_marker_allow_list = frozenset(V2_TAP_MARKER_ALLOW_LIST)

    def __init__(self) -> None:
        self.flow_context = FilmFlowRuntimeContext()
        self.state = self.flow_context.current_step
        self.last_monitor_payload: dict[str, Any] = {}
        self._pending_log: dict[str, Any] | None = None
        self._events: list[dict[str, Any]] = []
        self._targets: tuple[TargetSpec, ...] | None = None

    @property
    def close_ad_attempts(self) -> int:
        return self.flow_context.close_attempt_count

    def configure(self, **_kwargs: Any) -> None:
        return None

    def targets(self) -> tuple[TargetSpec, ...]:
        if self._targets is None:
            self._targets = tuple(_canonical_v2_targets())
        return self._targets

    def decide(self, context: StrategyContext) -> StrategyDecision:
        screen_state_result = detect_current_screen_state_from_detections(
            context.detections,
            screenshot_path=str(context.screen_path),
        )
        _, normalized_state = normalize_state_name(screen_state_result.state_name)
        _apply_pending_transition(self.flow_context, normalized_state)

        before_step = self.flow_context.current_step
        film_decision = decide_film_flow_action(
            step=before_step,
            state=normalized_state,
            detections=context.detections,
            entry_click_attempts=self.flow_context.entry_click_attempts,
            watch_ad_click_attempts=self.flow_context.watch_ad_click_attempts,
            close_ad_attempts=self.flow_context.close_attempt_count,
            reward_click_attempts=self.flow_context.reward_click_attempts,
        )
        film_decision = self._guard_repeated_close_on_same_screenshot(film_decision, context)
        action = film_decision.action
        action_name = str(action.get("name", ""))
        target_marker = _action_marker(action)
        target_confidence = film_decision.selected_confidence
        if target_confidence is None and target_marker in context.detections:
            target_confidence = context.detections[target_marker].confidence

        self._pending_log = {
            "loop": context.loop_index,
            "step": before_step,
            "current_step": before_step,
            "state": normalized_state,
            "raw_state": screen_state_result.state_name,
            "confidence": screen_state_result.confidence,
            "matched_markers": list(screen_state_result.matched_markers),
            "best_marker": screen_state_result.best_marker,
            "reason": screen_state_result.reason,
            "selection_reason": screen_state_result.selection_reason,
            "action": action_name,
            "action_reason": film_decision.reason,
            "target_marker": target_marker,
            "target_confidence": target_confidence,
            "selected_marker": target_marker,
            "selected_confidence": target_confidence,
            "next_step": film_decision.next_step,
            "step_changed": film_decision.next_step != before_step,
            "screenshot_path": str(context.screen_path),
            "dry_run": True,
            "close_ad_attempts": self.flow_context.close_attempt_count,
            "pending_transition": self.flow_context.pending_transition,
            "planned_status": "planned",
        }

        if film_decision.next_step == "FINISH":
            self._finish_pending_log("complete")
            return StrategyDecision.complete(film_decision.reason or "film_reward_flow_finished")
        return action_to_decision(action)

    def on_action_result(self, decision: StrategyDecision, action_result: ActionResult) -> None:
        if self._pending_log is None:
            return
        old_step = str(self._pending_log["step"])
        proposed_next_step = str(self._pending_log["next_step"])
        action = str(self._pending_log["action"])
        marker = self._pending_log.get("target_marker")
        status = _action_status(action_result)

        if action_result.success:
            self.flow_context.current_step = _next_step_after_action(
                current_step=old_step,
                proposed_next_step=proposed_next_step,
                action=action,
            )
            self._update_transition_after_success(action, None if marker is None else str(marker), proposed_next_step)
        else:
            self.flow_context.current_step = old_step

        self.flow_context.last_state = str(self._pending_log["state"])
        self.flow_context.last_action = action
        self.state = self.flow_context.current_step
        self._pending_log["action_result"] = action_result.to_dict()
        self._pending_log["next_step"] = self.flow_context.current_step
        self._pending_log["step_changed"] = self.flow_context.current_step != old_step
        self._pending_log["close_ad_attempts"] = self.flow_context.close_attempt_count
        self._pending_log["pending_transition"] = self.flow_context.pending_transition
        self._pending_log["planned_status"] = status
        self.last_monitor_payload = dict(self._pending_log)
        self._events.append({"event": "scrap_then_ad_reward_v2_loop", **self._pending_log})
        self._pending_log = None

    def reset_cycle(self) -> None:
        self.flow_context = FilmFlowRuntimeContext()
        self.state = self.flow_context.current_step
        self.last_monitor_payload = {}
        self._pending_log = None

    def reset_for_recovery(self, step: str = "GO_HOME") -> None:
        self.flow_context.current_step = step
        self.flow_context.pending_transition = None
        self.flow_context.close_attempt_count = 0
        self.flow_context.last_close_marker = None
        self.flow_context.last_close_screenshot_path = ""
        self.state = self.flow_context.current_step

    def current_phase(self) -> str:
        return self.flow_context.current_step

    def phase_snapshot(
        self,
        *,
        loop_index: int,
        detections: dict[str, DetectionResult],
        decision: StrategyDecision,
    ) -> dict[str, Any]:
        return {
            "loop": loop_index,
            "step": self.flow_context.current_step,
            "current_step": self.flow_context.current_step,
            "pending_transition": self.flow_context.pending_transition,
            "close_ad_attempts": self.flow_context.close_attempt_count,
            "chosen_decision": decision.action_name or decision.kind,
            "detected_targets": sorted(detections),
        }

    def consume_strategy_events(self) -> list[dict[str, Any]]:
        events = self._events
        self._events = []
        return events

    def recovery_stage_lock(self) -> None:
        return None

    def _guard_repeated_close_on_same_screenshot(self, film_decision: Any, context: StrategyContext) -> Any:
        action = film_decision.action
        if str(action.get("name", "")) != "tap_marker":
            return film_decision
        marker = _action_marker(action)
        if marker not in set(safe_close_marker_names()):
            return film_decision
        screenshot_path = str(context.screen_path)
        if (
            marker == self.flow_context.last_close_marker
            and screenshot_path == self.flow_context.last_close_screenshot_path
        ):
            return decide_film_flow_action(
                step=film_decision.step,
                state=film_decision.state,
                detections={},
                close_ad_attempts=FILM_CLOSE_AD_MAX_TOTAL_CLICKS,
            )
        return film_decision

    def _update_transition_after_success(self, action: str, marker: str | None, proposed_next_step: str) -> None:
        if action == "tap_marker":
            if marker == FILM_ENTRY_MARKER:
                self.flow_context.entry_click_attempts += 1
                self.flow_context.pending_transition = "SELECT_REWARD"
            elif marker == WATCH_AD_MARKER:
                self.flow_context.watch_ad_click_attempts += 1
                self.flow_context.pending_transition = "WATCH_AD"
            elif marker in set(safe_close_marker_names()):
                self.flow_context.close_attempt_count += 1
                self.flow_context.pending_transition = "CLOSE_AD_DOING"
                self.flow_context.last_close_marker = marker
                self.flow_context.last_close_screenshot_path = str(self._pending_log.get("screenshot_path", ""))
        elif action == "press_back":
            self.flow_context.pending_transition = proposed_next_step
        elif action == "no_action" and proposed_next_step == "CLAIM_REWARD":
            self.flow_context.close_attempt_count = 0
            self.flow_context.last_close_marker = None
            self.flow_context.last_close_screenshot_path = ""
        if action == "tap_marker" and marker == "select_reward_mode":
            self.flow_context.selected_reward = marker

    def _finish_pending_log(self, status: str) -> None:
        if self._pending_log is None:
            return
        old_step = str(self._pending_log["step"])
        self.flow_context.current_step = "FINISH"
        self.flow_context.last_state = str(self._pending_log["state"])
        self.flow_context.last_action = str(self._pending_log["action"])
        self.state = self.flow_context.current_step
        self._pending_log["next_step"] = "FINISH"
        self._pending_log["step_changed"] = old_step != "FINISH"
        self._pending_log["planned_status"] = status
        self.last_monitor_payload = dict(self._pending_log)
        self._events.append({"event": "scrap_then_ad_reward_v2_loop", **self._pending_log})
        self._pending_log = None


def _canonical_v2_targets() -> list[TargetSpec]:
    targets: list[TargetSpec] = []
    for marker_name in collect_canonical_marker_names():
        threshold = _threshold_for_marker(marker_name)
        for template_path in template_paths_for_marker(marker_name):
            if not _is_under_canonical_template_dirs(template_path):
                continue
            targets.append(
                TargetSpec(
                    name=marker_name,
                    template=str(template_path.resolve()),
                    threshold=threshold,
                    optional=True,
                )
            )
    return targets


def _threshold_for_marker(marker_name: str) -> float:
    thresholds: list[float] = []
    for template in SCREEN_STATE_TEMPLATES.values():
        patterns = [*template.required_any, *template.required_all, *template.exclude_any]
        if any(_marker_matches(pattern, marker_name) for pattern in patterns):
            thresholds.append(template.threshold)
    return min(thresholds, default=DEFAULT_TARGET_THRESHOLD)


def _apply_pending_transition(context: FilmFlowRuntimeContext, detected_state: str) -> None:
    if context.pending_transition is None:
        return
    if context.pending_transition == "WATCH_AD" and detected_state in {"UNKNOWN", "UNKNOWN_PAGE", "AD_CLOSE_PAGE"}:
        context.current_step = "WATCH_AD"
        context.pending_transition = None
    elif context.pending_transition == "SELECT_REWARD" and detected_state == "FILM_WATCH_PAGE":
        context.current_step = "SELECT_REWARD"
        context.pending_transition = None
    elif context.pending_transition == "CLOSE_AD_DOING" and detected_state in {
        "AD_CLOSE_PAGE",
        "RIGHT_AD_REWARD_SUCCESS_PAGE",
        "HOME",
        "HOME_PAGE",
        "UNKNOWN",
        "UNKNOWN_PAGE",
    }:
        context.current_step = "CLOSE_AD_DOING"
        context.pending_transition = None
    elif context.pending_transition == "RETURN_HOME" and detected_state in {"HOME", "HOME_PAGE"}:
        context.current_step = "RETURN_HOME"
        context.pending_transition = None


def _next_step_after_action(*, current_step: str, proposed_next_step: str, action: str) -> str:
    if action == "wait":
        return current_step
    return proposed_next_step


def _action_marker(action: Mapping[str, Any]) -> str | None:
    params = action.get("params", {})
    if not isinstance(params, Mapping):
        return None
    marker = params.get("marker")
    return None if marker is None else str(marker)


def _action_status(action_result: ActionResult) -> str:
    if not action_result.success:
        return "failed"
    if action_result.dry_run:
        return "dry_run"
    return "executed"


def _is_under_canonical_template_dirs(path: Path) -> bool:
    candidate = path.resolve()
    for directory in V2_CANONICAL_TEMPLATE_DIRS:
        try:
            candidate.relative_to(directory.resolve())
        except ValueError:
            continue
        return True
    return False


def _marker_matches(pattern: str, marker_name: str) -> bool:
    if pattern.endswith("*"):
        return marker_name.startswith(pattern[:-1])
    return marker_name == pattern


def debug_detect_screen_state(context: Any = None, detections: Any = None) -> dict[str, Any]:
    current_detections = detections
    if current_detections is None and context is not None:
        current_detections = getattr(context, "detections", {})
    screen_state = detect_current_screen_state_from_detections(current_detections or {})
    action_template = handle_screen_state(context, screen_state)
    return {
        "screen_state": screen_state.state_name,
        "confidence": screen_state.confidence,
        "matched_markers": screen_state.matched_markers,
        "excluded_markers": screen_state.excluded_markers,
        "explanation": explain_screen_state_result(screen_state),
        "action_template": action_template,
    }


def decide_next_action(
    flow_state: str | None,
    screen_state_result: Any,
    context: Any = None,
) -> dict[str, Any]:
    return {
        "decision": "no_action",
        "reason": "flow_controller_not_implemented_yet",
        "flow_state": flow_state,
        "screen_state": screen_state_result.state_name,
    }


def decide_next_action_v2(context: Any, flow_state: str | None = None) -> dict[str, Any]:
    screen_state = detect_current_screen_state_from_detections(getattr(context, "detections", {}))
    return decide_next_action(flow_state, screen_state, context)


def run_strategy_v2(context: Any) -> dict[str, Any]:
    debug_result = debug_detect_screen_state(context)
    debug_result["decision"] = "no_action"
    debug_result["reason"] = "v2_debug_only_no_real_click"
    return debug_result


__all__ = [
    "SCREEN_STATE_TEMPLATES",
    "Strategy",
    "debug_detect_screen_state",
    "decide_next_action",
    "decide_next_action_v2",
    "detect_current_screen_state_from_detections",
    "run_strategy_v2",
]

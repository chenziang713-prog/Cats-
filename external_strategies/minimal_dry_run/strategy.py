from __future__ import annotations

from collections.abc import Mapping
from typing import Any, NamedTuple

from cats_automatic.actions import ActionResult, DEFAULT_TAP_MARKER_ALLOW_LIST
from cats_automatic.strategy_base import (
    DetectionResult,
    RelativeRegion,
    StrategyContext,
    StrategyDecision,
    TargetSpec,
)


STEPS = (
    "START",
    "GO_HOME",
    "ENTER_ACTIVITY",
    "START_TASK",
    "WATCH_AD",
    "CLOSE_AD",
    "CLAIM_REWARD",
    "RETURN_HOME",
    "FINISH",
)

PAGE_STATES = (
    "UNKNOWN_PAGE",
    "HOME_PAGE",
    "ACTIVITY_PAGE",
    "TASK_PAGE",
    "AD_RUNNING_PAGE",
    "AD_CLOSE_PAGE",
    "REWARD_PAGE",
    "POPUP_PAGE",
    "LOADING_PAGE",
)


class FlowRule(NamedTuple):
    action: str
    next_step: str
    reason: str
    action_params: Mapping[str, Any] = {}


class SelectedCloseMarker(NamedTuple):
    name: str
    confidence: float


class FlowAction(NamedTuple):
    step: str
    state: str
    confidence: float | None
    matched_markers: list[str]
    best_marker: str | None
    state_reason: str
    rule: FlowRule


CLOSE_AD_MIN_CONFIDENCE = 0.80
MAX_CLOSE_AD_ATTEMPTS = 3
CLOSE_AD_MARKER_PRIORITY: tuple[tuple[str, ...], ...] = (
    ("close_end_2",),
    ("close_end_1",),
    ("close_end_3",),
    ("close_end_4",),
    ("close_ad",),
    (
        "close_user_2_1",
        "close_user_2_2",
        "close_user_2_3",
        "close_user_2_4",
        "close_user_2_5",
    ),
)
CLOSE_AD_TARGETS = (
    TargetSpec(
        "close_end_2",
        "templates/close-end-2.png",
        CLOSE_AD_MIN_CONFIDENCE,
        region=RelativeRegion(0.80, 0.0, 0.20, 0.20),
        scale_min=0.4,
        scale_max=1.1,
        scale_step=0.05,
        optional=True,
    ),
    TargetSpec(
        "close_end_1",
        "templates/close-end-1.png",
        CLOSE_AD_MIN_CONFIDENCE,
        region=RelativeRegion(0.0, 0.0, 0.25, 0.20),
        scale_min=0.4,
        scale_max=1.1,
        scale_step=0.05,
        optional=True,
    ),
    TargetSpec(
        "close_end_3",
        "templates/close-end-3.png",
        CLOSE_AD_MIN_CONFIDENCE,
        region=RelativeRegion(0.80, 0.0, 0.20, 0.20),
        scale_min=0.4,
        scale_max=1.1,
        scale_step=0.05,
        optional=True,
    ),
    TargetSpec(
        "close_end_4",
        "templates/close-end-4.png",
        CLOSE_AD_MIN_CONFIDENCE,
        region=RelativeRegion(0.80, 0.0, 0.20, 0.20),
        scale_min=0.4,
        scale_max=1.1,
        scale_step=0.05,
        optional=True,
    ),
)


RULES: dict[tuple[str, str], FlowRule] = {
    ("GO_HOME", "HOME_PAGE"): FlowRule("click_activity_entry", "ENTER_ACTIVITY", "home_ready"),
    ("GO_HOME", "UNKNOWN_PAGE"): FlowRule("press_back", "GO_HOME", "find_home_from_unknown"),
    ("GO_HOME", "POPUP_PAGE"): FlowRule("press_back", "GO_HOME", "close_popup_before_home"),
    ("GO_HOME", "LOADING_PAGE"): FlowRule("wait", "GO_HOME", "page_loading"),
    ("ENTER_ACTIVITY", "ACTIVITY_PAGE"): FlowRule("click_start_task", "START_TASK", "activity_ready"),
    ("ENTER_ACTIVITY", "HOME_PAGE"): FlowRule("click_activity_entry", "ENTER_ACTIVITY", "still_home"),
    ("ENTER_ACTIVITY", "UNKNOWN_PAGE"): FlowRule("press_back", "GO_HOME", "lost_activity"),
    ("START_TASK", "TASK_PAGE"): FlowRule("click_start_task", "WATCH_AD", "task_ready"),
    ("START_TASK", "AD_RUNNING_PAGE"): FlowRule("wait", "WATCH_AD", "ad_started"),
    ("START_TASK", "AD_CLOSE_PAGE"): FlowRule("close_ad", "CLOSE_AD", "ad_close_visible"),
    ("WATCH_AD", "AD_RUNNING_PAGE"): FlowRule("wait", "WATCH_AD", "ad_still_running"),
    ("WATCH_AD", "AD_CLOSE_PAGE"): FlowRule("close_ad", "CLOSE_AD", "ad_close_visible"),
    ("WATCH_AD", "UNKNOWN_PAGE"): FlowRule("wait", "WATCH_AD", "watch_ad_unknown"),
    ("CLOSE_AD", "REWARD_PAGE"): FlowRule("claim_reward", "CLAIM_REWARD", "reward_visible"),
    ("CLOSE_AD", "HOME_PAGE"): FlowRule("no_action", "RETURN_HOME", "already_home_after_ad"),
    ("CLOSE_AD", "ACTIVITY_PAGE"): FlowRule("no_action", "RETURN_HOME", "activity_after_ad_close"),
    ("CLOSE_AD", "AD_CLOSE_PAGE"): FlowRule("close_ad", "CLOSE_AD", "ad_close_still_visible"),
    ("CLOSE_AD", "UNKNOWN_PAGE"): FlowRule("wait", "CLOSE_AD", "close_ad_unknown"),
    ("CLAIM_REWARD", "REWARD_PAGE"): FlowRule("claim_reward", "RETURN_HOME", "claim_reward_visible"),
    ("CLAIM_REWARD", "HOME_PAGE"): FlowRule("no_action", "FINISH", "reward_finished_home"),
    ("RETURN_HOME", "HOME_PAGE"): FlowRule("finish", "FINISH", "home_returned"),
    ("RETURN_HOME", "UNKNOWN_PAGE"): FlowRule("press_back", "RETURN_HOME", "return_home_unknown"),
}


STATE_MARKER_TARGETS = (
    ("HOME_PAGE", "home_page.png"),
    ("ACTIVITY_PAGE", "activity_page.png"),
    ("TASK_PAGE", "task_page.png"),
    ("AD_RUNNING_PAGE", "ad_running_page.png"),
    ("AD_CLOSE_PAGE", "ad_close_page.png"),
    ("REWARD_PAGE", "reward_page.png"),
    ("POPUP_PAGE", "popup_page.png"),
    ("LOADING_PAGE", "loading_page.png"),
)


class Strategy:
    handles_reward_cycle_completion = True

    def __init__(self) -> None:
        self.current_step = "START"
        self.state = self.current_step
        self._pending_log: dict[str, Any] | None = None
        self._events: list[dict[str, Any]] = []
        self.close_ad_attempts = 0
        self._last_close_marker: str | None = None
        self._last_close_screenshot_path = ""
        self.last_monitor_payload: dict[str, Any] = {}

    def targets(self):
        state_targets = tuple(
            TargetSpec(
                name=state,
                template=template,
                threshold=0.80,
                optional=True,
            )
            for state, template in STATE_MARKER_TARGETS
        )
        return (*state_targets, *CLOSE_AD_TARGETS)

    def decide(self, context: StrategyContext) -> StrategyDecision:
        flow_action = self.decide_action(context)
        rule = flow_action.rule
        step_changed = rule.next_step != flow_action.step
        self._pending_log = {
            "loop": context.loop_index,
            "step": flow_action.step,
            "current_step": flow_action.step,
            "state": flow_action.state,
            "confidence": flow_action.confidence,
            "matched_markers": flow_action.matched_markers,
            "best_marker": flow_action.best_marker,
            "reason": flow_action.state_reason,
            "action": rule.action,
            "action_reason": rule.reason,
            "next_step": rule.next_step,
            "step_changed": step_changed,
            "screenshot_path": str(context.screen_path),
            "dry_run": True,
        }
        if rule.action in {"close_ad", "tap_marker"} or flow_action.state == "AD_CLOSE_PAGE":
            self._pending_log.update(close_ad_log_fields(context.detections, rule, self.close_ad_attempts))
        return decision_for_rule(rule)

    def decide_action(self, context: StrategyContext) -> FlowAction:
        step = self.current_step
        state, confidence, matched_markers, best_marker, state_reason = detect_page_state(context.detections)
        if step == "START":
            rule = FlowRule("no_action", "GO_HOME", "start_flow")
        elif step == "FINISH":
            rule = FlowRule("finish", "FINISH", "flow_already_finished")
        else:
            rule = RULES.get((step, state), FlowRule("wait", step, "no_matching_rule"))
        if rule.action == "close_ad":
            rule = self._close_ad_rule(context, state, rule)
        return FlowAction(
            step=step,
            state=state,
            confidence=confidence,
            matched_markers=matched_markers,
            best_marker=best_marker,
            state_reason=state_reason,
            rule=rule,
        )

    def _close_ad_rule(
        self,
        context: StrategyContext,
        state: str,
        rule: FlowRule,
    ) -> FlowRule:
        if self.close_ad_attempts >= MAX_CLOSE_AD_ATTEMPTS:
            return FlowRule("wait", self.current_step, "close_ad_attempt_limit_reached")
        selected = select_close_ad_marker(
            context.detections,
            DEFAULT_TAP_MARKER_ALLOW_LIST,
            CLOSE_AD_MIN_CONFIDENCE,
            CLOSE_AD_MARKER_PRIORITY,
        )
        if selected is None:
            return FlowRule("wait", self.current_step, "no_safe_close_ad_marker")
        screenshot_path = str(context.screen_path)
        if selected.name == self._last_close_marker and screenshot_path == self._last_close_screenshot_path:
            return FlowRule("wait", self.current_step, "close_ad_wait_next_screenshot")
        next_step = "CLOSE_AD" if state == "AD_CLOSE_PAGE" else rule.next_step
        return FlowRule(
            "tap_marker",
            next_step,
            "close_ad_marker_selected",
            {
                "marker": selected.name,
                "min_confidence": CLOSE_AD_MIN_CONFIDENCE,
                "fallback_to_best_marker": False,
                "offset_x": 0,
                "offset_y": 0,
            },
        )

    def on_action_result(self, decision: StrategyDecision, action_result: ActionResult) -> None:
        self.update_step(action_result)

    def update_step(self, action_result: ActionResult) -> None:
        if self._pending_log is None:
            return
        old_step = str(self._pending_log["step"])
        proposed_next_step = str(self._pending_log["next_step"])
        observed_state = str(self._pending_log["state"])
        action = str(self._pending_log["action"])
        new_step = resolve_next_step(
            current_step=old_step,
            observed_state=observed_state,
            action=action,
            proposed_next_step=proposed_next_step,
            action_result=action_result,
        )
        self._pending_log["action_result"] = action_result.to_dict()
        self._pending_log["next_step"] = new_step
        self._pending_log["step_changed"] = new_step != old_step
        self.last_monitor_payload = dict(self._pending_log)
        self.current_step = new_step
        self.state = self.current_step
        if action == "tap_marker" and action_result.success:
            selected_marker = self._pending_log.get("selected_marker")
            if selected_marker:
                self.close_ad_attempts += 1
                self._last_close_marker = str(selected_marker)
                self._last_close_screenshot_path = str(self._pending_log.get("screenshot_path", ""))
        elif observed_state in {"REWARD_PAGE", "HOME_PAGE", "ACTIVITY_PAGE"}:
            self.close_ad_attempts = 0
            self._last_close_marker = None
            self._last_close_screenshot_path = ""
        self._events.append({"event": "minimal_dry_run_loop", **self._pending_log})
        self._pending_log = None

    def reset_for_recovery(self, step: str = "GO_HOME") -> None:
        self.current_step = step
        self.state = self.current_step
        self.close_ad_attempts = 0
        self._last_close_marker = None
        self._last_close_screenshot_path = ""

    def consume_strategy_events(self) -> list[dict[str, Any]]:
        events = self._events
        self._events = []
        return events

    def phase_snapshot(
        self,
        *,
        loop_index: int,
        detections: dict[str, DetectionResult],
        decision: StrategyDecision,
    ) -> dict[str, Any]:
        return {
            "loop": loop_index,
            "step": self.current_step,
            "chosen_decision": decision.action_name or decision.kind,
            "detected_targets": sorted(detections),
        }


def detect_page_state(
    detections: dict[str, DetectionResult],
) -> tuple[str, float | None, list[str], str | None, str]:
    if not detections:
        return "UNKNOWN_PAGE", None, [], None, "no_detections"
    scores = {name: detection.confidence for name, detection in detections.items()}
    for state in PAGE_STATES:
        if state in scores:
            return state, scores[state], [state], state, "matched_state_marker"

    mapped = map_detection_names(scores)
    if mapped is None:
        best_name = max(scores, key=scores.get)
        return "UNKNOWN_PAGE", scores[best_name], [best_name], best_name, "unmapped_detection"
    state, marker_names = mapped
    best_marker = max(marker_names, key=lambda name: scores.get(name, 0.0))
    return state, scores[best_marker], marker_names, best_marker, "mapped_detection"


def map_detection_names(scores: dict[str, float]) -> tuple[str, list[str]] | None:
    names = set(scores)
    if {"main-definate", "home_marker", "ad_entry", "scrap_entry"} & names:
        return "HOME_PAGE", sorted({"main-definate", "home_marker", "ad_entry", "scrap_entry"} & names)
    if {"scrap_page_marker", "scrap_next_button"} & names:
        return "ACTIVITY_PAGE", sorted({"scrap_page_marker", "scrap_next_button"} & names)
    if {"battle_button", "scrap_watch_ad_button"} & names:
        return "TASK_PAGE", sorted({"battle_button", "scrap_watch_ad_button"} & names)
    if any(name.startswith("close_user_") or name.startswith("close_end_") for name in names) or "close_ad" in names:
        return "AD_CLOSE_PAGE", sorted(name for name in names if name.startswith(("close_user_", "close_end_")) or name == "close_ad")
    if {"reward_confirm_marker", "confirm_button"} & names:
        return "REWARD_PAGE", sorted({"reward_confirm_marker", "confirm_button"} & names)
    if {"error_popup", "network_error_popup", "retry_button"} & names:
        return "POPUP_PAGE", sorted({"error_popup", "network_error_popup", "retry_button"} & names)
    return None


def select_close_ad_marker(
    detections: Mapping[str, DetectionResult],
    allow_list: set[str] | frozenset[str],
    min_confidence: float,
    priority: tuple[tuple[str, ...], ...],
) -> SelectedCloseMarker | None:
    priority_index: dict[str, int] = {}
    for index, group in enumerate(priority):
        for marker_name in group:
            priority_index[marker_name] = index

    candidates: list[tuple[int, float, str]] = []
    for name, detection in detections.items():
        if name not in allow_list:
            continue
        if name not in priority_index:
            continue
        if detection.confidence < min_confidence:
            continue
        candidates.append((priority_index[name], detection.confidence, name))
    if not candidates:
        return None

    priority_rank, confidence, name = min(candidates, key=lambda item: (item[0], -item[1], item[2]))
    return SelectedCloseMarker(name=name, confidence=confidence)


def close_ad_log_fields(
    detections: Mapping[str, DetectionResult],
    rule: FlowRule,
    close_ad_attempts: int,
) -> dict[str, Any]:
    available = [
        {
            "marker": name,
            "confidence": detection.confidence,
        }
        for name, detection in sorted(detections.items())
        if name in DEFAULT_TAP_MARKER_ALLOW_LIST
    ]
    selected_marker = rule.action_params.get("marker") if rule.action == "tap_marker" else None
    selected_confidence = None
    if selected_marker and selected_marker in detections:
        selected_confidence = detections[str(selected_marker)].confidence
    return {
        "available_close_markers": available,
        "selected_marker": selected_marker,
        "selected_confidence": selected_confidence,
        "close_ad_attempts": close_ad_attempts,
    }


def decision_for_rule(rule: FlowRule) -> StrategyDecision:
    if rule.action == "press_back":
        return StrategyDecision.keyevent("BACK", "press_back", rule.reason)
    if rule.action == "tap_marker":
        return StrategyDecision.action(
            "tap_marker",
            params=rule.action_params,
            reason=rule.reason,
        )
    return StrategyDecision(
        kind="wait",
        action_name=rule.action,
        wait_seconds=0.0,
        reason=rule.reason,
    )


def resolve_next_step(
    *,
    current_step: str,
    observed_state: str,
    action: str,
    proposed_next_step: str,
    action_result: ActionResult,
) -> str:
    if current_step == "START" and action == "no_action":
        return proposed_next_step
    if action == "wait":
        return current_step
    if action == "press_back":
        return proposed_next_step if observed_state == "POPUP_PAGE" else current_step
    if action == "no_action":
        return proposed_next_step
    if action == "finish" and observed_state == "HOME_PAGE":
        return "FINISH"

    confirmed_step = step_confirmed_by_state(observed_state, current_step)
    if confirmed_step == proposed_next_step:
        return proposed_next_step
    return current_step


def step_confirmed_by_state(observed_state: str, current_step: str) -> str:
    if observed_state == "HOME_PAGE":
        return "RETURN_HOME" if current_step in {"CLOSE_AD", "CLAIM_REWARD", "RETURN_HOME"} else "GO_HOME"
    return {
        "ACTIVITY_PAGE": "ENTER_ACTIVITY",
        "TASK_PAGE": "START_TASK",
        "AD_RUNNING_PAGE": "WATCH_AD",
        "AD_CLOSE_PAGE": "CLOSE_AD",
        "REWARD_PAGE": "CLAIM_REWARD",
    }.get(observed_state, current_step)

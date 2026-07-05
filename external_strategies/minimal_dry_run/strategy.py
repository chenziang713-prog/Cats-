from __future__ import annotations

from typing import Any, NamedTuple

from cats_automatic.actions import ActionResult
from cats_automatic.strategy_base import DetectionResult, StrategyContext, StrategyDecision, TargetSpec


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

    def targets(self):
        return tuple(
            TargetSpec(
                name=state,
                template=template,
                threshold=0.80,
                optional=True,
            )
            for state, template in STATE_MARKER_TARGETS
        )

    def decide(self, context: StrategyContext) -> StrategyDecision:
        step = self.current_step
        state, confidence, matched_markers, best_marker, state_reason = detect_page_state(context.detections)
        if step == "START":
            rule = FlowRule("no_action", "GO_HOME", "start_flow")
        elif step == "FINISH":
            rule = FlowRule("finish", "FINISH", "flow_already_finished")
        else:
            rule = RULES.get((step, state), FlowRule("wait", step, "no_matching_rule"))

        step_changed = rule.next_step != step
        self._pending_log = {
            "loop": context.loop_index,
            "step": step,
            "state": state,
            "confidence": confidence,
            "matched_markers": matched_markers,
            "best_marker": best_marker,
            "reason": state_reason,
            "action": rule.action,
            "action_reason": rule.reason,
            "next_step": rule.next_step,
            "step_changed": step_changed,
            "screenshot_path": str(context.screen_path),
            "dry_run": True,
        }
        return decision_for_rule(rule)

    def on_action_result(self, decision: StrategyDecision, action_result: ActionResult) -> None:
        if self._pending_log is None:
            return
        self._pending_log["action_result"] = normalize_action_result(action_result)
        self.current_step = str(self._pending_log["next_step"])
        self.state = self.current_step
        self._events.append({"event": "minimal_dry_run_loop", **self._pending_log})
        self._pending_log = None

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


def decision_for_rule(rule: FlowRule) -> StrategyDecision:
    if rule.action == "press_back":
        return StrategyDecision.keyevent("BACK", "press_back", rule.reason)
    return StrategyDecision(
        kind="wait",
        action_name=rule.action,
        wait_seconds=0.0,
        reason=rule.reason,
    )


def normalize_action_result(action_result: ActionResult) -> str:
    if action_result.action_type in {"adb_tap", "adb_keyevent"}:
        return action_result.result
    return "dry_run_skipped"

from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any, Mapping, NamedTuple

from cats_automatic.actions import ActionResult
from cats_automatic.strategy_base import DetectionResult, StrategyContext, StrategyDecision, TargetSpec

from external_strategies.scrap_then_ad_reward_v2.authoring import action_to_decision
from external_strategies.scrap_then_ad_reward_v2.close_markers import safe_close_marker_names
from external_strategies.scrap_then_ad_reward_v2.film_flow import (
    FILM_CLOSE_AD_MAX_TOTAL_CLICKS,
    FILM_ENTRY_MARKER,
    FilmDecision,
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
STRONG_STATE_CONFIDENCE = 0.90
STABLE_STATE_FRAMES = 2
DEFAULT_EFFECT_CONFIRMATION_SECONDS = 2.5
STEP_RANK = {
    "START": 0,
    "GO_HOME": 1,
    "ENTER_FILM": 2,
    "SELECT_REWARD": 3,
    "START_AD": 4,
    "WATCH_AD": 5,
    "CLOSE_AD_DOING": 6,
    "CLAIM_REWARD": 7,
    "RETURN_HOME": 8,
    "FINISH": 9,
}
RECOVERY_STAGE_LOCKS = {
    "WATCH_AD": "v2_preserve_watch_ad",
    "CLOSE_AD_DOING": "v2_preserve_close_ad",
    "CLAIM_REWARD": "v2_preserve_claim_reward",
    "RETURN_HOME": "v2_preserve_return_home",
}
OVERLAY_STATES = {"ERROR_POPUP_PAGE", "POPUP_PAGE"}
NORMAL_WAIT_REASONS = {
    "pending_effect_waiting_for_confirmation",
    "pending_effect_duplicate_blocked",
    "wait_for_ad_close_marker",
    "wait_after_ad_close",
    "wait_for_home_after_reward",
    "post_ad_network_flashback",
}


class StateAcceptance(NamedTuple):
    accepted: bool
    observed_state: str
    accepted_state: str
    keep_step: bool
    next_step: str | None
    policy: str
    reason: str
    overlay_state: str | None = None


class PendingEffect(NamedTuple):
    decision_id: str
    action_name: str
    target_marker: str | None
    source_state: str
    source_fingerprint: str
    source_center: tuple[int, int] | None
    expected_step: str
    executed_at_monotonic: float
    confirmation_deadline: float
    retry_count: int
    max_retries: int
    reason: str


class FilmFlowRuntimeContext:
    def __init__(self) -> None:
        now = time.monotonic()
        self.current_step = "START"
        self.observed_state: str | None = None
        self.accepted_state: str | None = None
        self.last_stable_state: str | None = None
        self.overlay_state: str | None = None
        self.pending_transition: str | None = None
        self.mismatch_state: str | None = None
        self.mismatch_count = 0
        self.stable_state_count = 0
        self.last_progress_monotonic = now
        self.step_entered_monotonic = now
        self.pending_decision_id: str | None = None
        self.pending_action_name: str | None = None
        self.pending_target_marker: str | None = None
        self.pending_decision_selected = False
        self.pending_effect: PendingEffect | None = None
        self.pending_effect_status = ""
        self.blocked_duplicate_actions = 0
        self.selected_reward: str | None = None
        self.last_state: str | None = None
        self.last_action: str | None = None
        self.entry_click_attempts = 0
        self.watch_ad_click_attempts = 0
        self.reward_click_attempts = 0
        self.close_attempt_count = 0
        self.last_close_marker: str | None = None
        self.last_close_screenshot_path = ""
        self.last_close_fingerprint = ""
        self.last_close_center: tuple[int, int] | None = None


class Strategy:
    """Runtime adapter that keeps v2 detection and film flow state synchronized."""

    handles_reward_cycle_completion = True
    tap_marker_allow_list = frozenset(V2_TAP_MARKER_ALLOW_LIST)

    def __init__(self) -> None:
        self.flow_context = FilmFlowRuntimeContext()
        self.state = self.flow_context.current_step
        self.last_monitor_payload: dict[str, Any] = {}
        self._pending_log: dict[str, Any] | None = None
        self._events: list[dict[str, Any]] = []
        self._targets: tuple[TargetSpec, ...] | None = None
        self._decision_sequence = 0

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
        _, observed_state = normalize_state_name(screen_state_result.state_name)
        fingerprint = image_fingerprint(context.screen_path)
        _apply_pending_transition(self.flow_context, observed_state)

        before_step = self.flow_context.current_step
        acceptance = accept_observed_state(
            current_step=before_step,
            observed_state=observed_state,
            previous_accepted_state=self.flow_context.accepted_state,
            consecutive_count=self.flow_context.stable_state_count,
            detections=context.detections,
            confidence=screen_state_result.confidence,
        )
        self._record_acceptance(acceptance)
        accepted_state = acceptance.accepted_state
        before_step = self.flow_context.current_step

        effect_decision = self._decision_for_pending_effect(
            observed_state=observed_state,
            accepted_state=accepted_state,
            detections=context.detections,
            fingerprint=fingerprint,
        )
        film_decision = effect_decision or decide_film_flow_action(
            step=before_step,
            state=accepted_state,
            detections=context.detections,
            entry_click_attempts=self.flow_context.entry_click_attempts,
            watch_ad_click_attempts=self.flow_context.watch_ad_click_attempts,
            close_ad_attempts=self.flow_context.close_attempt_count,
            reward_click_attempts=self.flow_context.reward_click_attempts,
        )
        film_decision = self._guard_repeated_close_on_same_image(film_decision, context, fingerprint)
        action = self._with_decision_id(film_decision.action, context.loop_index, fingerprint)
        action_name = str(action.get("name", ""))
        target_marker = _action_marker(action)
        target_confidence = film_decision.selected_confidence
        if target_confidence is None and target_marker in context.detections:
            target_confidence = context.detections[target_marker].confidence

        self._pending_log = {
            "decision_id": self.flow_context.pending_decision_id,
            "loop": context.loop_index,
            "step": before_step,
            "current_step": before_step,
            "observed_state": observed_state,
            "accepted_state": accepted_state,
            "state": accepted_state,
            "raw_state": screen_state_result.state_name,
            "overlay_state": self.flow_context.overlay_state,
            "confidence": screen_state_result.confidence,
            "matched_markers": list(screen_state_result.matched_markers),
            "best_marker": screen_state_result.best_marker,
            "reason": screen_state_result.reason,
            "selection_reason": screen_state_result.selection_reason,
            "acceptance_policy": acceptance.policy,
            "acceptance_reason": acceptance.reason,
            "action": action_name,
            "action_reason": film_decision.reason,
            "target_marker": target_marker,
            "target_confidence": target_confidence,
            "selected_marker": target_marker,
            "selected_confidence": target_confidence,
            "next_step": film_decision.next_step,
            "step_changed": film_decision.next_step != before_step,
            "screenshot_path": str(context.screen_path),
            "image_fingerprint": fingerprint,
            "dry_run": True,
            "close_ad_attempts": self.flow_context.close_attempt_count,
            "entry_click_attempts": self.flow_context.entry_click_attempts,
            "watch_ad_click_attempts": self.flow_context.watch_ad_click_attempts,
            "reward_click_attempts": self.flow_context.reward_click_attempts,
            "pending_transition": self.flow_context.pending_transition,
            "pending_effect": self._pending_effect_name(),
            "pending_effect_status": self.flow_context.pending_effect_status,
            "blocked_duplicate_actions": self.flow_context.blocked_duplicate_actions,
            "planned_status": "planned",
        }

        if film_decision.next_step == "FINISH":
            self._finish_pending_log("complete")
            return StrategyDecision.complete("flow_finished")
        return action_to_decision(action)

    def on_decision_selected(self, final_decision: StrategyDecision) -> None:
        if self._pending_log is None:
            return
        if _decision_matches_pending(final_decision, self._pending_log):
            self.flow_context.pending_decision_selected = True
            return
        self._pending_log["planned_status"] = "overridden"
        self._pending_log["override_decision"] = final_decision.action_name or final_decision.kind
        self._events.append({"event": "scrap_then_ad_reward_v2_decision_overridden", **self._pending_log})
        self._clear_pending_decision()
        self._pending_log = None

    def on_action_result(self, decision: StrategyDecision, action_result: ActionResult) -> None:
        if self._pending_log is None:
            return
        if not self.flow_context.pending_decision_selected:
            if _decision_matches_pending(decision, self._pending_log):
                self.flow_context.pending_decision_selected = True
            else:
                self._events.append(
                    {
                        "event": "scrap_then_ad_reward_v2_action_result_ignored",
                        "reason": "decision_not_selected",
                        "decision": decision.action_name or decision.kind,
                        "action_result": action_result.to_dict(),
                        **self._pending_log,
                    }
                )
                return
        if not self.flow_context.pending_decision_selected:
            self._events.append(
                {
                    "event": "scrap_then_ad_reward_v2_action_result_ignored",
                    "reason": "decision_not_selected",
                    "decision": decision.action_name or decision.kind,
                    "action_result": action_result.to_dict(),
                    **self._pending_log,
                }
            )
            return
        decision_id = _decision_id_from_decision(decision)
        if decision_id and decision_id != self.flow_context.pending_decision_id:
            self._events.append(
                {
                    "event": "scrap_then_ad_reward_v2_action_result_ignored",
                    "reason": "decision_id_mismatch",
                    "received_decision_id": decision_id,
                    "action_result": action_result.to_dict(),
                    **self._pending_log,
                }
            )
            return

        old_step = str(self._pending_log["step"])
        proposed_next_step = str(self._pending_log["next_step"])
        action = str(self._pending_log["action"])
        marker = self._pending_log.get("target_marker")
        status = _action_status(action_result)

        if action_result.success:
            self.flow_context.current_step = self._resolve_step_after_action(
                old_step=old_step,
                proposed_next_step=proposed_next_step,
                action=action,
                status=status,
            )
            self._update_transition_after_success(
                action,
                None if marker is None else str(marker),
                proposed_next_step,
                status=status,
                action_result=action_result,
            )
        else:
            self.flow_context.current_step = old_step

        self.flow_context.last_state = str(self._pending_log["accepted_state"])
        self.flow_context.last_action = action
        self.state = self.flow_context.current_step
        self._pending_log["action_result"] = action_result.to_dict()
        self._pending_log["next_step"] = self.flow_context.current_step
        self._pending_log["step_changed"] = self.flow_context.current_step != old_step
        self._pending_log["close_ad_attempts"] = self.flow_context.close_attempt_count
        self._pending_log["entry_click_attempts"] = self.flow_context.entry_click_attempts
        self._pending_log["watch_ad_click_attempts"] = self.flow_context.watch_ad_click_attempts
        self._pending_log["reward_click_attempts"] = self.flow_context.reward_click_attempts
        self._pending_log["pending_transition"] = self.flow_context.pending_transition
        self._pending_log["pending_effect"] = self._pending_effect_name()
        self._pending_log["pending_effect_status"] = self.flow_context.pending_effect_status
        self._pending_log["blocked_duplicate_actions"] = self.flow_context.blocked_duplicate_actions
        self._pending_log["planned_status"] = status
        self.last_monitor_payload = dict(self._pending_log)
        self._events.append({"event": "scrap_then_ad_reward_v2_loop", **self._pending_log})
        self._clear_pending_decision()
        self._pending_log = None

    def reset_cycle(self) -> None:
        self.flow_context = FilmFlowRuntimeContext()
        self.state = self.flow_context.current_step
        self.last_monitor_payload = {}
        self._pending_log = None

    def reset_for_recovery(self, step: str = "GO_HOME") -> None:
        if self.recovery_stage_lock() is not None:
            self._events.append(
                {
                    "event": "scrap_then_ad_reward_v2_recovery_reset_blocked",
                    "current_step": self.flow_context.current_step,
                    "requested_step": step,
                    "reason": self.recovery_stage_lock(),
                }
            )
            return
        self.flow_context.current_step = step
        self.flow_context.pending_transition = None
        self.flow_context.close_attempt_count = 0
        self.flow_context.last_close_marker = None
        self.flow_context.last_close_screenshot_path = ""
        self.flow_context.last_close_fingerprint = ""
        self.flow_context.last_close_center = None
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
            "observed_state": self.flow_context.observed_state,
            "accepted_state": self.flow_context.accepted_state,
            "overlay_state": self.flow_context.overlay_state,
            "pending_transition": self.flow_context.pending_transition,
            "pending_effect": self._pending_effect_name(),
            "pending_effect_status": self.flow_context.pending_effect_status,
            "close_ad_attempts": self.flow_context.close_attempt_count,
            "entry_click_attempts": self.flow_context.entry_click_attempts,
            "watch_ad_click_attempts": self.flow_context.watch_ad_click_attempts,
            "chosen_decision": decision.action_name or decision.kind,
            "detected_targets": sorted(detections),
        }

    def consume_strategy_events(self) -> list[dict[str, Any]]:
        events = self._events
        self._events = []
        return events

    def recovery_stage_lock(self) -> str | None:
        return RECOVERY_STAGE_LOCKS.get(self.flow_context.current_step)

    def _record_acceptance(self, acceptance: StateAcceptance) -> None:
        context = self.flow_context
        context.observed_state = acceptance.observed_state
        context.overlay_state = acceptance.overlay_state
        if acceptance.accepted_state == context.accepted_state:
            context.stable_state_count += 1
        else:
            context.stable_state_count = 1
        context.accepted_state = acceptance.accepted_state
        if acceptance.accepted:
            context.last_stable_state = acceptance.accepted_state
            context.mismatch_state = None
            context.mismatch_count = 0
        else:
            if context.mismatch_state == acceptance.observed_state:
                context.mismatch_count += 1
            else:
                context.mismatch_state = acceptance.observed_state
                context.mismatch_count = 1

    def _guard_repeated_close_on_same_image(
        self,
        film_decision: Any,
        context: StrategyContext,
        fingerprint: str,
    ) -> Any:
        action = film_decision.action
        if str(action.get("name", "")) != "tap_marker":
            return film_decision
        marker = _action_marker(action)
        if marker not in set(safe_close_marker_names()):
            return film_decision
        detection = context.detections.get(marker or "")
        center = None if detection is None else detection.center
        if (
            marker == self.flow_context.last_close_marker
            and fingerprint
            and fingerprint == self.flow_context.last_close_fingerprint
            and center == self.flow_context.last_close_center
        ):
            return decide_film_flow_action(
                step=film_decision.step,
                state=film_decision.state,
                detections={},
                close_ad_attempts=FILM_CLOSE_AD_MAX_TOTAL_CLICKS,
            )
        return film_decision

    def _decision_for_pending_effect(
        self,
        *,
        observed_state: str,
        accepted_state: str,
        detections: Mapping[str, DetectionResult],
        fingerprint: str,
    ) -> Any | None:
        effect = self.flow_context.pending_effect
        if effect is None:
            self.flow_context.pending_effect_status = ""
            return None
        if self._pending_effect_confirmed(effect, observed_state, accepted_state, detections, fingerprint):
            self._events.append(
                {
                    "event": "scrap_then_ad_reward_v2_pending_effect_confirmed",
                    "decision_id": effect.decision_id,
                    "action_name": effect.action_name,
                    "target_marker": effect.target_marker,
                    "observed_state": observed_state,
                    "accepted_state": accepted_state,
                }
            )
            self.flow_context.pending_effect = None
            self.flow_context.pending_effect_status = "confirmed"
            return None
        now = time.monotonic()
        if now < effect.confirmation_deadline or effect.retry_count >= effect.max_retries:
            self.flow_context.blocked_duplicate_actions += 1
            self.flow_context.pending_effect_status = "waiting_for_confirmation"
            return _effect_wait_decision(effect, accepted_state)
        self.flow_context.pending_effect_status = "retry_allowed"
        return None

    def _pending_effect_confirmed(
        self,
        effect: PendingEffect,
        observed_state: str,
        accepted_state: str,
        detections: Mapping[str, DetectionResult],
        fingerprint: str,
    ) -> bool:
        if self.flow_context.current_step == "FINISH":
            return True
        if effect.action_name == "tap_marker" and effect.target_marker == FILM_ENTRY_MARKER:
            return accepted_state == "FILM_WATCH_PAGE" or effect.target_marker not in detections
        if effect.action_name == "tap_marker" and effect.target_marker == WATCH_AD_MARKER:
            return accepted_state in {
                "UNKNOWN",
                "UNKNOWN_PAGE",
                "LOADING_PAGE",
                "AD_CLOSE_PAGE",
                "RIGHT_AD_REWARD_SUCCESS_PAGE",
            } or effect.target_marker not in detections
        if effect.action_name == "tap_marker" and effect.target_marker in set(safe_close_marker_names()):
            return accepted_state in {"RIGHT_AD_REWARD_SUCCESS_PAGE", "HOME", "HOME_PAGE"} or (
                accepted_state in {"UNKNOWN", "UNKNOWN_PAGE", "LOADING_PAGE", "FILM_WATCH_PAGE"}
                and fingerprint
                and fingerprint != effect.source_fingerprint
            )
        if effect.action_name == "press_back":
            return accepted_state in {"HOME", "HOME_PAGE"} or (
                fingerprint and fingerprint != effect.source_fingerprint and accepted_state != "RIGHT_AD_REWARD_SUCCESS_PAGE"
            )
        return fingerprint != "" and fingerprint != effect.source_fingerprint

    def _with_decision_id(self, action: Mapping[str, Any], loop_index: int, fingerprint: str) -> dict[str, Any]:
        self._decision_sequence += 1
        decision_id = f"v2-{loop_index}-{self._decision_sequence}"
        params = dict(action.get("params", {})) if isinstance(action.get("params", {}), Mapping) else {}
        params["decision_id"] = decision_id
        params["source_fingerprint"] = fingerprint
        self.flow_context.pending_decision_id = decision_id
        self.flow_context.pending_action_name = str(action.get("name", ""))
        self.flow_context.pending_target_marker = _action_marker({"params": params})
        self.flow_context.pending_decision_selected = False
        return {"name": str(action.get("name", "")), "params": params, "reason": str(action.get("reason", ""))}

    def _resolve_step_after_action(
        self,
        *,
        old_step: str,
        proposed_next_step: str,
        action: str,
        status: str,
    ) -> str:
        if action == "wait":
            return old_step
        if action in {"tap_marker", "press_back"} and status == "dry_run":
            return old_step
        return _forward_step(old_step, proposed_next_step)

    def _update_transition_after_success(
        self,
        action: str,
        marker: str | None,
        proposed_next_step: str,
        *,
        status: str,
        action_result: ActionResult,
    ) -> None:
        if action == "tap_marker":
            if marker == FILM_ENTRY_MARKER:
                if status == "executed":
                    self.flow_context.entry_click_attempts += 1
                    self._set_pending_effect(action, marker, proposed_next_step, action_result)
                self.flow_context.pending_transition = "SELECT_REWARD"
            elif marker == WATCH_AD_MARKER:
                if status == "executed":
                    self.flow_context.watch_ad_click_attempts += 1
                    self._set_pending_effect(action, marker, proposed_next_step, action_result)
                self.flow_context.pending_transition = "WATCH_AD"
            elif marker in set(safe_close_marker_names()):
                if status == "executed":
                    self.flow_context.close_attempt_count += 1
                    self._set_pending_effect(action, marker, proposed_next_step, action_result)
                self.flow_context.pending_transition = "CLOSE_AD_DOING"
                self.flow_context.last_close_marker = marker
                self.flow_context.last_close_screenshot_path = str(self._pending_log.get("screenshot_path", ""))
                self.flow_context.last_close_fingerprint = str(self._pending_log.get("image_fingerprint", ""))
                self.flow_context.last_close_center = action_result.clicked_pos or _pair_or_none(
                    self._pending_log.get("clicked_pos")
                )
        elif action == "press_back":
            if status == "executed":
                self.flow_context.reward_click_attempts += 1
                self._set_pending_effect(action, marker, proposed_next_step, action_result)
            self.flow_context.pending_transition = proposed_next_step
        elif action == "no_action" and proposed_next_step == "CLAIM_REWARD":
            self.flow_context.close_attempt_count = 0
            self.flow_context.last_close_marker = None
            self.flow_context.last_close_screenshot_path = ""
            self.flow_context.last_close_fingerprint = ""
            self.flow_context.last_close_center = None
        if action == "tap_marker" and marker == "select_reward_mode":
            self.flow_context.selected_reward = marker

    def _set_pending_effect(
        self,
        action: str,
        marker: str | None,
        proposed_next_step: str,
        action_result: ActionResult,
    ) -> None:
        if self._pending_log is None:
            return
        old = self.flow_context.pending_effect
        retry_count = (
            old.retry_count + 1
            if old is not None and old.action_name == action and old.target_marker == marker
            else 0
        )
        max_retries = _max_retries_for_effect(action, marker)
        now = time.monotonic()
        self.flow_context.pending_effect = PendingEffect(
            decision_id=str(self._pending_log.get("decision_id", "")),
            action_name=action,
            target_marker=marker,
            source_state=str(self._pending_log.get("accepted_state", "")),
            source_fingerprint=str(self._pending_log.get("image_fingerprint", "")),
            source_center=action_result.clicked_pos or _pair_or_none(self._pending_log.get("clicked_pos")),
            expected_step=proposed_next_step,
            executed_at_monotonic=now,
            confirmation_deadline=now + _confirmation_seconds_for_effect(action, marker),
            retry_count=retry_count,
            max_retries=max_retries,
            reason=str(self._pending_log.get("action_reason", "")),
        )
        self.flow_context.pending_effect_status = "waiting_for_confirmation"

    def _pending_effect_name(self) -> str | None:
        effect = self.flow_context.pending_effect
        if effect is None:
            return None
        if effect.action_name == "tap_marker":
            return f"waiting_for_{effect.target_marker}_effect"
        if effect.action_name == "press_back":
            return "waiting_for_home_after_reward_back"
        return f"waiting_for_{effect.action_name}_effect"

    def _finish_pending_log(self, status: str) -> None:
        if self._pending_log is None:
            return
        old_step = str(self._pending_log["step"])
        self.flow_context.current_step = "FINISH"
        self.flow_context.last_state = str(self._pending_log["accepted_state"])
        self.flow_context.last_action = str(self._pending_log["action"])
        self.state = self.flow_context.current_step
        self._pending_log["next_step"] = "FINISH"
        self._pending_log["step_changed"] = old_step != "FINISH"
        self._pending_log["planned_status"] = status
        self.last_monitor_payload = dict(self._pending_log)
        self._events.append({"event": "scrap_then_ad_reward_v2_loop", **self._pending_log})
        self._clear_pending_decision()
        self._pending_log = None

    def _clear_pending_decision(self) -> None:
        self.flow_context.pending_decision_id = None
        self.flow_context.pending_action_name = None
        self.flow_context.pending_target_marker = None
        self.flow_context.pending_decision_selected = False


def accept_observed_state(
    *,
    current_step: str,
    observed_state: str,
    previous_accepted_state: str | None,
    consecutive_count: int,
    detections: Mapping[str, DetectionResult],
    confidence: float = 0.0,
) -> StateAcceptance:
    if observed_state in OVERLAY_STATES:
        return StateAcceptance(
            accepted=True,
            observed_state=observed_state,
            accepted_state=previous_accepted_state or "UNKNOWN",
            keep_step=True,
            next_step=None,
            policy="overlay",
            reason="overlay_state_does_not_replace_main_step",
            overlay_state=observed_state,
        )

    state = observed_state
    strong = confidence >= STRONG_STATE_CONFIDENCE
    repeated = consecutive_count + 1 >= STABLE_STATE_FRAMES
    if current_step in {"WATCH_AD", "CLOSE_AD_DOING", "CLAIM_REWARD", "RETURN_HOME"} and state in {"HOME", "HOME_PAGE"}:
        return _accepted(current_step, state, "late_home_fast_path", "home accepted in late flow")
    if current_step in {"CLOSE_AD_DOING", "WATCH_AD"} and state == "RIGHT_AD_REWARD_SUCCESS_PAGE":
        return _accepted(current_step, state, "reward_fast_path", "reward page accepted after ad")
    if current_step == "CLAIM_REWARD" and state == "RIGHT_AD_REWARD_SUCCESS_PAGE":
        return _accepted(current_step, state, "claim_reward_state", "reward page still active")
    if state in {"UNKNOWN", "UNKNOWN_PAGE", "LOADING_PAGE"}:
        return _accepted(current_step, state, "wait_state", "transient or ad playback state")

    allowed = _allowed_states_for_step(current_step)
    if state in allowed["forward"] or state in allowed["wait"] or state in allowed["transient"]:
        if strong or repeated or state in {"HOME", "AD_CLOSE_PAGE", "FILM_WATCH_PAGE"}:
            return _accepted(current_step, state, "step_matrix", "state allowed by current step")
        return StateAcceptance(
            accepted=False,
            observed_state=state,
            accepted_state=previous_accepted_state or state,
            keep_step=True,
            next_step=None,
            policy="needs_confirmation",
            reason="waiting for consecutive frame confirmation",
        )

    if state == "FILM_WATCH_PAGE" and current_step in {"WATCH_AD", "CLOSE_AD_DOING", "CLAIM_REWARD", "RETURN_HOME"}:
        return _accepted(current_step, state, "network_flashback", "film page flashback kept in current step")

    return StateAcceptance(
        accepted=False,
        observed_state=state,
        accepted_state=previous_accepted_state or state,
        keep_step=True,
        next_step=None,
        policy="illegal_state_held",
        reason="observed state is not legal for current step",
    )


def _accepted(current_step: str, state: str, policy: str, reason: str) -> StateAcceptance:
    return StateAcceptance(
        accepted=True,
        observed_state=state,
        accepted_state=state,
        keep_step=True,
        next_step=None,
        policy=policy,
        reason=reason,
    )


def _allowed_states_for_step(step: str) -> dict[str, set[str]]:
    matrix = {
        "START": {"forward": {"UNKNOWN", "UNKNOWN_PAGE", "HOME"}, "wait": set(), "transient": set()},
        "GO_HOME": {"forward": {"HOME", "HOME_PAGE"}, "wait": {"UNKNOWN", "UNKNOWN_PAGE", "LOADING_PAGE"}, "transient": set()},
        "ENTER_FILM": {"forward": {"HOME", "HOME_PAGE", "FILM_WATCH_PAGE"}, "wait": {"UNKNOWN", "UNKNOWN_PAGE", "LOADING_PAGE"}, "transient": set()},
        "SELECT_REWARD": {"forward": {"FILM_WATCH_PAGE"}, "wait": {"UNKNOWN", "UNKNOWN_PAGE", "LOADING_PAGE"}, "transient": set()},
        "START_AD": {"forward": {"FILM_WATCH_PAGE", "AD_CLOSE_PAGE"}, "wait": {"UNKNOWN", "UNKNOWN_PAGE", "LOADING_PAGE"}, "transient": set()},
        "WATCH_AD": {"forward": {"AD_CLOSE_PAGE", "RIGHT_AD_REWARD_SUCCESS_PAGE", "HOME", "HOME_PAGE"}, "wait": {"UNKNOWN", "UNKNOWN_PAGE", "LOADING_PAGE"}, "transient": {"FILM_WATCH_PAGE"}},
        "CLOSE_AD_DOING": {"forward": {"RIGHT_AD_REWARD_SUCCESS_PAGE", "HOME", "HOME_PAGE"}, "wait": {"AD_CLOSE_PAGE", "UNKNOWN", "UNKNOWN_PAGE", "LOADING_PAGE"}, "transient": {"FILM_WATCH_PAGE"}},
        "CLAIM_REWARD": {"forward": {"RIGHT_AD_REWARD_SUCCESS_PAGE", "HOME", "HOME_PAGE"}, "wait": {"UNKNOWN", "UNKNOWN_PAGE", "LOADING_PAGE"}, "transient": {"FILM_WATCH_PAGE"}},
        "RETURN_HOME": {"forward": {"HOME", "HOME_PAGE", "RIGHT_AD_REWARD_SUCCESS_PAGE"}, "wait": {"UNKNOWN", "UNKNOWN_PAGE", "LOADING_PAGE"}, "transient": {"FILM_WATCH_PAGE"}},
        "FINISH": {"forward": {"HOME", "HOME_PAGE"}, "wait": set(), "transient": set()},
    }
    return matrix.get(step, {"forward": set(), "wait": {"UNKNOWN", "UNKNOWN_PAGE"}, "transient": set()})


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
    if context.pending_transition == "WATCH_AD" and detected_state in {"UNKNOWN", "UNKNOWN_PAGE", "AD_CLOSE_PAGE", "RIGHT_AD_REWARD_SUCCESS_PAGE"}:
        _set_step(context, "WATCH_AD")
        context.pending_transition = None
    elif context.pending_transition == "SELECT_REWARD" and detected_state == "FILM_WATCH_PAGE":
        _set_step(context, "SELECT_REWARD")
        context.pending_transition = None
    elif context.pending_transition == "CLOSE_AD_DOING" and detected_state in {
        "AD_CLOSE_PAGE",
        "RIGHT_AD_REWARD_SUCCESS_PAGE",
        "HOME",
        "HOME_PAGE",
        "UNKNOWN",
        "UNKNOWN_PAGE",
        "FILM_WATCH_PAGE",
    }:
        _set_step(context, "CLOSE_AD_DOING")
        context.pending_transition = None
    elif context.pending_transition == "RETURN_HOME" and detected_state in {"HOME", "HOME_PAGE"}:
        _set_step(context, "RETURN_HOME")
        context.pending_transition = None


def _set_step(context: FilmFlowRuntimeContext, next_step: str) -> None:
    current = context.current_step
    context.current_step = _forward_step(current, next_step)
    if context.current_step != current:
        context.step_entered_monotonic = time.monotonic()
        context.last_progress_monotonic = context.step_entered_monotonic


def _forward_step(current_step: str, proposed_step: str) -> str:
    if STEP_RANK.get(proposed_step, -1) < STEP_RANK.get(current_step, -1):
        return current_step
    return proposed_step


def image_fingerprint(path: Path) -> str:
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return ""


def _decision_matches_pending(decision: StrategyDecision, pending: Mapping[str, Any]) -> bool:
    expected_action = str(pending.get("action", ""))
    if expected_action == "press_back":
        actual_action = decision.action_name or decision.kind
        return actual_action == "press_back"
    actual_action = decision.action_name or decision.kind
    if actual_action != expected_action:
        return False
    decision_id = _decision_id_from_decision(decision)
    pending_id = pending.get("decision_id")
    return not decision_id or decision_id == pending_id


def _decision_id_from_decision(decision: StrategyDecision) -> str | None:
    raw = decision.action_params.get("decision_id") if decision.action_params else None
    return None if raw is None else str(raw)


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


def _pair_or_none(value: Any) -> tuple[int, int] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    try:
        return int(value[0]), int(value[1])
    except (TypeError, ValueError):
        return None


def _effect_wait_decision(effect: PendingEffect, state: str) -> FilmDecision:
    reason = (
        "pending_effect_duplicate_blocked"
        if time.monotonic() >= effect.confirmation_deadline and effect.retry_count >= effect.max_retries
        else "pending_effect_waiting_for_confirmation"
    )
    return FilmDecision(
        step=effect.expected_step,
        state=state,
        action={"name": "wait", "params": {"seconds": 1.0}, "reason": reason},
        next_step=effect.expected_step,
        reason=reason,
        selected_marker=effect.target_marker,
        selected_confidence=None,
    )


def _confirmation_seconds_for_effect(action: str, marker: str | None) -> float:
    if action == "tap_marker" and marker == FILM_ENTRY_MARKER:
        return 2.5
    if action == "tap_marker" and marker == WATCH_AD_MARKER:
        return 3.0
    if action == "tap_marker" and marker in set(safe_close_marker_names()):
        return 2.0
    if action == "press_back":
        return 3.0
    return DEFAULT_EFFECT_CONFIRMATION_SECONDS


def _max_retries_for_effect(action: str, marker: str | None) -> int:
    if action == "tap_marker" and marker in {FILM_ENTRY_MARKER, WATCH_AD_MARKER}:
        return 1
    if action == "tap_marker" and marker in set(safe_close_marker_names()):
        return 1
    if action == "press_back":
        return 0
    return 0


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
    "STEP_RANK",
    "StateAcceptance",
    "Strategy",
    "accept_observed_state",
    "debug_detect_screen_state",
    "decide_next_action",
    "decide_next_action_v2",
    "detect_current_screen_state_from_detections",
    "image_fingerprint",
    "run_strategy_v2",
]

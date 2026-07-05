from __future__ import annotations

import time
from collections.abc import Sequence
from pathlib import Path

from cats_automatic.actions import ActionResult
from cats_automatic.games.cats.game import definition
from cats_automatic.strategy_base import RelativeRegion, StrategyContext, StrategyDecision, TargetSpec
from cats_automatic.scrap_watch_cooldown import detect_cooldown, load_cooldown_targets
from cats_automatic.user_close_templates import (
    CLOSE_AD_CANDIDATE_THRESHOLD,
    CLOSE_AD_MIN_CONFIDENCE,
    load_user_close_targets,
)


CLICK_DELAYS = {
    "click_scrap_entry": 3.0,
    "adb_back_scrap_popup": 1.0,
    "adb_back_battle_popup": 1.0,
    "adb_back_battle_result": 1.0,
    "adb_back_watch_popup": 1.0,
    "click_battle_result_confirm": 1.5,
    "click_battle_button": 3.0,
    "click_skip_button": 2.0,
    "click_scrap_watch_ad_button": 3.0,
    "close_ad": 1.5,
}

BATTLE_INITIAL_WAIT_SECONDS = 2.0
SKIP_INTERVAL_SECONDS = 2.0
SCRAP_ENTRY_TRANSITION_TIMEOUT_SECONDS = 5.0
NEXT_TO_BATTLE_TIMEOUT_SECONDS = 5.0
BATTLE_TO_SKIP_TIMEOUT_SECONDS = 8.0
RESULT_POPUP_TIMEOUT_SECONDS = 10.0
RESULT_TO_WATCH_TIMEOUT_SECONDS = 5.0
AD_CLOSE_TIMEOUT_SECONDS = 10.0
MAX_BACK_ATTEMPTS_PER_STEP = 3
MAX_SAME_DECISION_CLICKS_BEFORE_BACK = 2
TARGET_MISS_THRESHOLD = 3
TEMPLATE_ROOT = Path(__file__).resolve().parent / "templates"


class Strategy:
    def __init__(self) -> None:
        self.battle_wait_seconds = 60.0
        self.ad_wait_seconds = 20.0
        self.battle_initial_wait_seconds = BATTLE_INITIAL_WAIT_SECONDS
        self.skip_interval_seconds = SKIP_INTERVAL_SECONDS
        self.state = "home"
        self.skip_click_count = 0
        self.close_streak = 0
        self.battle_clicked_in_cycle = False
        self.battle_wait_finished_in_cycle = False
        self.battle_result_closed_in_cycle = False
        self.battle_result_handled = False
        self.battle_phase_completed = False
        self.awaiting_watch_ad_in_cycle = False
        self.scrap_watch_ad_clicked_in_cycle = False
        self.scrap_ad_in_progress = False
        self.scrap_ad_completed = False
        self.scrap_phase_completed = False
        self.return_home_after_scrap_started = False
        self.current_ad_source = "none"
        self.last_expected_target = "scrap_entry"
        self.last_stable_scrap_state = "home"
        self.ad_wait_finished_in_cycle = False
        self.close_ad_executed = False
        self._pending_state_recovery: dict[str, object] | None = None
        self._pending_state_change_details: dict[str, object] | None = None
        self._pending_strategy_events: list[dict[str, object]] = []
        self._early_watch_blocked_states: set[str] = set()
        self._clock = time.monotonic
        self.scrap_entry_transition_timeout_seconds = SCRAP_ENTRY_TRANSITION_TIMEOUT_SECONDS
        self.next_to_battle_timeout_seconds = NEXT_TO_BATTLE_TIMEOUT_SECONDS
        self.battle_to_skip_timeout_seconds = BATTLE_TO_SKIP_TIMEOUT_SECONDS
        self.result_popup_timeout_seconds = RESULT_POPUP_TIMEOUT_SECONDS
        self.result_to_watch_timeout_seconds = RESULT_TO_WATCH_TIMEOUT_SECONDS
        self.ad_close_timeout_seconds = AD_CLOSE_TIMEOUT_SECONDS
        self.max_back_attempts_per_step = MAX_BACK_ATTEMPTS_PER_STEP
        self.max_same_decision_clicks_before_back = MAX_SAME_DECISION_CLICKS_BEFORE_BACK
        self.target_miss_threshold = TARGET_MISS_THRESHOLD
        self.current_step_name = "home"
        self.step_started_at = self._clock()
        self.last_progress_at = self.step_started_at
        self.last_clicked_decision = ""
        self.last_clicked_at: float | None = None
        self.repeated_click_count_by_decision: dict[str, int] = {}
        self.back_attempt_count_by_step: dict[str, int] = {}
        self.miss_count_by_step: dict[str, int] = {}
        self.last_screen_progress_signature: tuple[str, ...] = ()
        self.max_close_attempts_per_ad = 8
        self.scrap_ad_closed_once = False
        self.scrap_ad_finished_by_return_to_scrap_page = False
        self.scrap_watch_cooldown_enabled = True
        self.scrap_watch_cooldown_template_threshold = 0.80
        self.scrap_watch_cooldown_white_text_threshold = 0.02
        self.scrap_watch_cooldown_min_white_components = 2
        self.scrap_watch_ad_cooldown_detected = False
        self.scrap_ad_skipped_by_cooldown = False
        self.scrap_watch_cooldown_score = 0.0
        self.scrap_watch_cooldown_method = ""
        self.scrap_watch_cooldown_template_name = ""
        self.scrap_watch_button_roi = None
        self.white_text_pixel_ratio = 0.0
        self.white_text_component_count = 0

    def configure(self, *, battle_wait_seconds: float = 60.0, ad_wait_seconds: float = 20.0) -> None:
        if battle_wait_seconds < 0 or ad_wait_seconds < 0:
            raise ValueError("battle_wait_seconds and ad_wait_seconds must not be negative")
        self.battle_wait_seconds = battle_wait_seconds
        self.ad_wait_seconds = ad_wait_seconds

    def reset_cycle(self) -> None:
        self.state = "home"
        self.skip_click_count = 0
        self.close_streak = 0
        self.battle_clicked_in_cycle = False
        self.battle_wait_finished_in_cycle = False
        self.battle_result_closed_in_cycle = False
        self.battle_result_handled = False
        self.battle_phase_completed = False
        self.awaiting_watch_ad_in_cycle = False
        self.scrap_watch_ad_clicked_in_cycle = False
        self.scrap_ad_in_progress = False
        self.scrap_ad_completed = False
        self.scrap_phase_completed = False
        self.return_home_after_scrap_started = False
        self.current_ad_source = "none"
        self.last_expected_target = "scrap_entry"
        self.last_stable_scrap_state = "home"
        self.ad_wait_finished_in_cycle = False
        self.close_ad_executed = False
        self._pending_state_recovery = None
        self._pending_state_change_details = None
        self._pending_strategy_events = []
        self._early_watch_blocked_states = set()
        self.repeated_click_count_by_decision = {}
        self.back_attempt_count_by_step = {}
        self.miss_count_by_step = {}
        self.last_clicked_decision = ""
        self.last_clicked_at = None
        self.last_screen_progress_signature = ()
        self.scrap_ad_closed_once = False
        self.scrap_ad_finished_by_return_to_scrap_page = False
        self.scrap_watch_ad_cooldown_detected = False
        self.scrap_ad_skipped_by_cooldown = False
        self.scrap_watch_cooldown_score = 0.0
        self.scrap_watch_cooldown_method = ""
        self.scrap_watch_cooldown_template_name = ""
        self.scrap_watch_button_roi = None
        self.white_text_pixel_ratio = 0.0
        self.white_text_component_count = 0
        self._start_step("home")

    @property
    def current_phase(self) -> str:
        return self.state

    @property
    def scrap_watch_ad_clicked(self) -> bool:
        return self.scrap_watch_ad_clicked_in_cycle

    def recovery_stage_lock(self) -> str | None:
        if self.scrap_phase_completed or self.return_home_after_scrap_started:
            return "recovery_preserved_return_home_after_scrap"
        if self.awaiting_watch_ad_in_cycle:
            return "recovery_preserved_wait_scrap_watch_ad_button"
        return None

    def phase_snapshot(self, *, loop_index: int, detections, decision: StrategyDecision) -> dict[str, object]:
        ignored_targets: list[str] = []
        ignore_reasons: list[str] = []
        if self.current_phase == "wait_scrap_watch_ad_button" and "battle_button" in detections:
            ignored_targets.append("battle_button")
            ignore_reasons.append("battle_finished_awaiting_scrap_watch_ad")
        if self.current_phase == "return_home_after_scrap":
            for target in ("battle_button", "scrap_watch_ad_button"):
                if target in detections:
                    ignored_targets.append(target)
                    ignore_reasons.append("return_home_after_scrap_stage_lock")
        return {
            "loop": loop_index,
            "current_phase": self.current_phase,
            "state": self.state,
            "current_ad_source": self.current_ad_source,
            "battle_result_handled": self.battle_result_handled,
            "battle_phase_completed": self.battle_phase_completed,
            "awaiting_watch_ad_in_cycle": self.awaiting_watch_ad_in_cycle,
            "scrap_watch_ad_clicked": self.scrap_watch_ad_clicked,
            "scrap_ad_in_progress": self.scrap_ad_in_progress,
            "scrap_ad_completed": self.scrap_ad_completed,
            "scrap_phase_completed": self.scrap_phase_completed,
            "return_home_after_scrap_started": self.return_home_after_scrap_started,
            "home_detected_after_scrap": False,
            "film_ad_reward_started": False,
            "film_ad_entry_clicked": False,
            "scrap_watch_ad_cooldown_detected": self.scrap_watch_ad_cooldown_detected,
            "scrap_ad_skipped_by_cooldown": self.scrap_ad_skipped_by_cooldown,
            "scrap_watch_cooldown_score": self.scrap_watch_cooldown_score,
            "scrap_watch_cooldown_method": self.scrap_watch_cooldown_method,
            "scrap_watch_cooldown_template_name": self.scrap_watch_cooldown_template_name,
            "scrap_watch_button_roi": self.scrap_watch_button_roi,
            "white_text_pixel_ratio": self.white_text_pixel_ratio,
            "white_text_component_count": self.white_text_component_count,
            "last_expected_target": self.last_expected_target,
            "detected_targets": sorted(detections),
            "chosen_decision": decision.action_name or decision.kind,
            "ignored_targets": ignored_targets,
            "ignore_reasons": ignore_reasons,
            "transition_from": "",
            "transition_to": self.current_phase,
            "transition_reason": decision.reason,
        }

    def targets(self) -> Sequence[TargetSpec]:
        return (
            *self._close_targets(),
            TargetSpec("scrap_entry", "scrap_entry.png", 0.80, scale_min=0.4, scale_max=1.1, scale_step=0.05),
            TargetSpec("scrap_page_marker", "scrap_page_marker.png", 0.80, scale_min=0.4, scale_max=1.1, scale_step=0.05, optional=True),
            TargetSpec("scrap_next_button", "scrap_next_button.png", 0.80, scale_min=0.4, scale_max=1.1, scale_step=0.05),
            TargetSpec("battle_button", "battle_button.png", 0.80, scale_min=0.4, scale_max=1.1, scale_step=0.05),
            TargetSpec("skip_button", "skip_button.png", 0.80, scale_min=0.4, scale_max=1.1, scale_step=0.05),
            TargetSpec("battle_result_popup", "battle_result_popup.png", 0.80, scale_min=0.4, scale_max=1.1, scale_step=0.05),
            TargetSpec("confirm_button", str(definition().templates_dir / "confirm-button.png"), 0.80, scale_min=0.4, scale_max=1.1, scale_step=0.05),
            TargetSpec("scrap_watch_ad_button", "scrap_watch_ad_button.png", 0.80, scale_min=0.4, scale_max=1.1, scale_step=0.05),
            *load_cooldown_targets(threshold=self.scrap_watch_cooldown_template_threshold),
        )

    def decide(self, context: StrategyContext) -> StrategyDecision:
        self.recover_state_from_screen(context)
        self.last_screen_progress_signature = tuple(sorted(context.detections))
        self._ensure_watchdog_step()

        close_detection = self._best_close_detection(context)

        if self.scrap_phase_completed or self.state == "return_home_after_scrap":
            for target_name in ("battle_button", "scrap_watch_ad_button"):
                if target_name in context.detections:
                    self._pending_strategy_events.append(
                        {
                            "event": f"{target_name}_ignored_returning_home_after_scrap",
                            "reason": "return_home_after_scrap_stage_lock",
                            "target_name": target_name,
                        }
                    )
            return StrategyDecision.complete("scrap_return_after_watch_ad")
        if close_detection is not None:
            if self._ad_stage_active():
                will_click = close_detection.confidence >= CLOSE_AD_MIN_CONFIDENCE
                self._pending_strategy_events.append(
                    {
                        "event": "close_ad_candidate",
                        "target_name": close_detection.name,
                        "confidence": close_detection.confidence,
                        "center": list(close_detection.center),
                        "threshold": CLOSE_AD_MIN_CONFIDENCE,
                        "ad_stage_active": True,
                        "will_click": will_click,
                        "reason": (
                            "close_ad_candidate_above_threshold"
                            if will_click
                            else "close_ad_candidate_below_threshold"
                        ),
                    }
                )
                if not will_click:
                    return StrategyDecision.wait(
                        1.0,
                        "close_ad_candidate_below_threshold_after_ad_wait",
                        target_name=close_detection.name,
                    )
            else:
                self._pending_strategy_events.append(
                    {
                        "event": "close_ad_candidate_ignored",
                        "target_name": close_detection.name,
                        "confidence": close_detection.confidence,
                        "center": list(close_detection.center),
                        "threshold": CLOSE_AD_MIN_CONFIDENCE,
                        "ad_stage_active": False,
                        "will_click": False,
                        "reason": "close_ad_detected_before_ad_stage_ignored",
                        "record_in_click_records": True,
                    }
                )

        watch_ad_detected = "scrap_watch_ad_button" in context.detections
        if (
            watch_ad_detected
            and self.scrap_watch_ad_clicked_in_cycle
            and not self.close_ad_executed
        ):
            click_count = self.repeated_click_count_by_decision.get(
                "click_scrap_watch_ad_button",
                0,
            )
            if click_count < self.max_same_decision_clicks_before_back:
                return StrategyDecision.click(
                    "scrap_watch_ad_button",
                    "click_scrap_watch_ad_button",
                    "click_scrap_watch_ad_button",
                    post_action_delay_seconds=CLICK_DELAYS["click_scrap_watch_ad_button"],
                )
            return StrategyDecision.wait(
                1.0,
                "repeated_watch_ad_click_without_ad_transition",
                target_name="scrap_watch_ad_button",
            )
        watch_ad_ready = self._watch_ad_ready()
        if watch_ad_detected and not watch_ad_ready:
            self._pending_strategy_events.append(
                {
                    "event": "decision_blocked",
                    "blocked_decision": "click_scrap_watch_ad_button",
                    "reason": "watch_ad_detected_before_battle_complete",
                    "current_state": self.state,
                    "battle_clicked_in_cycle": self.battle_clicked_in_cycle,
                    "skip_count": self.skip_click_count,
                    "battle_wait_finished_in_cycle": self.battle_wait_finished_in_cycle,
                    "battle_result_closed_in_cycle": self.battle_result_closed_in_cycle,
                    "awaiting_watch_ad_in_cycle": self.awaiting_watch_ad_in_cycle,
                }
            )
            stage_target_visible = (
                (not self.battle_clicked_in_cycle and "battle_button" in context.detections)
                or (self.battle_clicked_in_cycle and self.skip_click_count < 2 and "skip_button" in context.detections)
                or (self.battle_wait_finished_in_cycle and "battle_result_popup" in context.detections)
            )
            if not stage_target_visible and self.state not in self._early_watch_blocked_states:
                self._early_watch_blocked_states.add(self.state)
                return StrategyDecision.wait(
                    1.0,
                    "watch_ad_detected_before_battle_complete_ignored",
                    target_name="scrap_watch_ad_button",
                )

        if watch_ad_ready:
            if "scrap_watch_ad_button" in context.detections:
                if self.scrap_watch_cooldown_enabled:
                    button = context.detections["scrap_watch_ad_button"]
                    cooldown = detect_cooldown(
                        context.screen_path,
                        button,
                        context.detections,
                        white_ratio_threshold=self.scrap_watch_cooldown_white_text_threshold,
                        min_white_components=self.scrap_watch_cooldown_min_white_components,
                    )
                    self.scrap_watch_cooldown_score = cooldown.score
                    self.scrap_watch_cooldown_method = cooldown.method
                    self.scrap_watch_cooldown_template_name = cooldown.template_name
                    self.scrap_watch_button_roi = cooldown.roi
                    self.white_text_pixel_ratio = cooldown.white_text_pixel_ratio
                    self.white_text_component_count = cooldown.white_text_component_count
                    if cooldown.detected:
                        self.scrap_watch_ad_cooldown_detected = True
                        self.scrap_ad_skipped_by_cooldown = True
                        self.scrap_ad_in_progress = False
                        self.scrap_ad_completed = False
                        self.scrap_phase_completed = True
                        self.current_ad_source = "none"
                        self.return_home_after_scrap_started = True
                        self.state = "return_home_after_scrap"
                        self.last_expected_target = "home_marker"
                        self._pending_strategy_events.append(
                            {
                                "event": "scrap_watch_ad_cooldown_detected",
                                "target_name": "scrap_watch_ad_button",
                                "confidence": button.confidence,
                                "cooldown_score": cooldown.score,
                                "cooldown_method": cooldown.method,
                                "reason": "scrap_watch_ad_button_cooldown_detected",
                            }
                        )
                        return StrategyDecision(
                            kind="wait",
                            target_name="scrap_watch_ad_button",
                            action_name="skip_scrap_ad_due_to_cooldown",
                            wait_seconds=0.0,
                            reason="scrap_watch_ad_button_cooldown_detected",
                        )
                return self._click_or_wait(
                    context,
                    "scrap_watch_ad_button",
                    "click_scrap_watch_ad_button",
                    "wait_scrap_watch_ad_button_not_found",
                )
            if "battle_button" in context.detections:
                self._pending_strategy_events.append(
                    {
                        "event": "battle_button_ignored_awaiting_scrap_watch_ad",
                        "blocked_decision": "click_battle_button",
                        "reason": "battle_finished_awaiting_scrap_watch_ad",
                    }
                )
                return StrategyDecision.wait(1.0, "battle_button_ignored_awaiting_scrap_watch_ad")
            watchdog_decision = self._transition_watchdog_decision(context)
            if watchdog_decision is not None:
                return watchdog_decision
            return StrategyDecision.wait(1.0, "wait_scrap_watch_ad_button_not_found")

        if (
            self.battle_clicked_in_cycle
            and self.state == "wait_battle_button"
            and "battle_button" in context.detections
        ):
            self._pending_strategy_events.append(
                {
                    "event": "decision_blocked",
                    "blocked_decision": "click_battle_button",
                    "reason": "battle_already_clicked_in_cycle",
                }
            )
            return StrategyDecision.wait(1.0, "battle_already_clicked_in_cycle")

        if (
            self.skip_click_count >= 2
            and "skip_button" in context.detections
            and self.state == "wait_battle_result_popup"
        ):
            return StrategyDecision.wait(1.0, "skip_limit_reached")

        watchdog_decision = self._transition_watchdog_decision(context)
        if watchdog_decision is not None:
            return watchdog_decision

        if self.state in {"close_ad", "wait_return_after_ad"}:
            close_detection = self._best_close_detection(context)
            if close_detection is not None and self._ad_stage_active():
                if self.close_streak >= self.max_close_attempts_per_ad:
                    return StrategyDecision.wait(1.0, "wait_close_limit_reached")
                return StrategyDecision.click(
                    close_detection.name,
                    "close_ad",
                    "close_ad_detected_ad_stage",
                    post_action_delay_seconds=CLICK_DELAYS["close_ad"],
                    min_click_confidence_override=CLOSE_AD_MIN_CONFIDENCE,
                )

        if self.state == "home":
            return self._click_or_wait(context, "scrap_entry", "click_scrap_entry", "wait_scrap_entry_not_found")
        if self.state == "wait_scrap_next_button":
            if "scrap_next_button" in context.detections:
                return StrategyDecision.click(
                    "scrap_next_button",
                    "click_scrap_next_button",
                    "click_scrap_next_button",
                    post_action_delay_seconds=self.battle_initial_wait_seconds,
                )
            if not self._template_exists("scrap_next_button"):
                return StrategyDecision.wait(1.0, "template_missing_scrap_next_button")
            return StrategyDecision.wait(1.0, "wait_scrap_next_button_not_found_after_back")
        if self.state == "wait_battle_button":
            if "battle_button" in context.detections and "scrap_next_button" not in context.detections:
                return StrategyDecision.click(
                    "battle_button",
                    "click_battle_button",
                    "click_battle_button",
                    post_action_delay_seconds=CLICK_DELAYS["click_battle_button"],
                )
            if "battle_button" in context.detections and "scrap_next_button" in context.detections:
                return StrategyDecision.wait(1.0, "battle_button_conflict_with_scrap_next_button")
            if not self._template_exists("battle_button"):
                return StrategyDecision.wait(1.0, "template_missing_battle_button")
            return StrategyDecision.wait(1.0, "wait_battle_button_not_found_after_back")
        if self.state in {"skip_1", "skip_2"}:
            if "skip_button" not in context.detections:
                return StrategyDecision.wait(1.0, "wait_skip_button_not_found")
            delay = self.skip_interval_seconds if self.state == "skip_1" else 0.0
            return StrategyDecision.click(
                "skip_button",
                "click_skip_button",
                "click_skip_button",
                post_action_delay_seconds=delay,
            )
        if self.state == "battle_wait":
            return StrategyDecision.wait(self.battle_wait_seconds, "battle_wait")
        if self.state == "wait_battle_result_popup":
            if "battle_result_popup" not in context.detections:
                return self._wait_or_missing(
                    "battle_result_popup",
                    "wait_battle_result_popup_not_found",
                )
            confirm_detection = context.detections.get("confirm_button")
            action_name = (
                "click_battle_result_confirm"
                if confirm_detection is not None
                else "adb_back_battle_result"
            )
            self._pending_strategy_events.append(
                {
                    "event": "battle_result_popup_detected",
                    "battle_result_popup_confidence": context.detections[
                        "battle_result_popup"
                    ].confidence,
                    "confirm_button_confidence": (
                        confirm_detection.confidence if confirm_detection is not None else None
                    ),
                    "action": action_name,
                }
            )
            if confirm_detection is not None:
                return StrategyDecision.click(
                    "confirm_button",
                    "click_battle_result_confirm",
                    "battle_result_popup_confirm_button_detected",
                    post_action_delay_seconds=CLICK_DELAYS["click_battle_result_confirm"],
                )
            return StrategyDecision.keyevent(
                "BACK",
                "adb_back_battle_result",
                "battle_result_popup_detected_confirm_missing",
                post_action_delay_seconds=CLICK_DELAYS["adb_back_battle_result"],
            )
        if self.state == "wait_scrap_watch_ad_button":
            return self._click_or_wait(
                context,
                "scrap_watch_ad_button",
                "click_scrap_watch_ad_button",
                "wait_scrap_watch_ad_button_not_found",
            )
        if self.state == "ad_wait":
            return StrategyDecision.wait(self.ad_wait_seconds, "ad_wait")
        if self.state == "close_ad":
            ad_close_timed_out = (
                self.current_step_name == "waiting_ad_close"
                and self._clock() - self.step_started_at >= self.ad_close_timeout_seconds
            )
            reason = "wait_close_ad_not_found_after_ad_wait" if ad_close_timed_out else "wait_close_ad_not_found"
            return StrategyDecision.wait(1.0, reason)
        if self.state == "wait_return_after_ad":
            return_targets = {"scrap_watch_ad_button", "scrap_next_button", "scrap_entry"}
            if return_targets.intersection(context.detections):
                return StrategyDecision.complete("scrap_return_after_watch_ad")
            return StrategyDecision.wait(1.0, "wait_return_after_ad_not_found")
        return StrategyDecision.wait(1.0, "wait_unknown_screen")

    def recover_state_from_screen(self, context: StrategyContext) -> str:
        detections = context.detections
        return_targets = {
            "scrap_page_marker",
            "scrap_watch_ad_button",
            "scrap_next_button",
            "scrap_entry",
            "battle_button",
            "skip_button",
        }
        return_hits = return_targets.intersection(detections)
        close_target = self._best_close_target(context)

        if (
            not self.battle_result_handled
            and self.battle_clicked_in_cycle
            and self.battle_wait_finished_in_cycle
            and "scrap_watch_ad_button" in detections
        ):
            self.battle_result_closed_in_cycle = True
            self.battle_result_handled = True
            self.battle_phase_completed = True
            self.awaiting_watch_ad_in_cycle = True
            self.last_expected_target = "scrap_watch_ad_button"
            self._pending_strategy_events.append(
                {
                    "event": "battle_phase_completed_from_scrap_page_evidence",
                    "reason": "battle_result_disappeared_and_watch_ad_detected",
                }
            )

        if self.scrap_phase_completed or self.return_home_after_scrap_started:
            if "battle_button" in detections:
                self._pending_strategy_events.append(
                    {"event": "recovery_ignored_battle_button_due_to_scrap_context"}
                )
            return self._recover_to(
                "return_home_after_scrap",
                None,
                detections,
                reason="recovery_preserved_return_home_after_scrap",
            )

        if self.awaiting_watch_ad_in_cycle:
            return self._recover_to(
                "wait_scrap_watch_ad_button",
                "scrap_watch_ad_button" if "scrap_watch_ad_button" in detections else None,
                detections,
                reason="recovery_preserved_wait_scrap_watch_ad_button",
            )

        if "battle_result_popup" in detections and not self.battle_result_closed_in_cycle:
            recovery_reason = (
                "battle_result_popup_priority_override"
                if self.state in {"ad_wait", "close_ad"}
                else None
            )
            return self._recover_to(
                "wait_battle_result_popup",
                "battle_result_popup",
                detections,
                reason=recovery_reason,
            )

        if (
            self.scrap_watch_ad_clicked_in_cycle
            and self.close_ad_executed
            and return_hits
        ):
            detection_name = max(
                return_hits,
                key=lambda name: detections[name].confidence,
            )
            self._complete_scrap_ad_from_return(detection_name)
            return self._recover_to(
                "return_home_after_scrap",
                detection_name,
                detections,
                reason="scrap_ad_finished_by_return_to_scrap_page",
            )

        if self._ad_stage_active() and not self.close_ad_executed:
            if close_target is not None:
                return self._recover_to("close_ad", close_target, detections)
            if "scrap_watch_ad_button" in detections:
                return self._recover_to(
                    "wait_scrap_watch_ad_button",
                    "scrap_watch_ad_button",
                    detections,
                )
            return self.state

        if self._watch_ad_ready():
            if "scrap_watch_ad_button" in detections:
                return self._recover_to(
                    "wait_scrap_watch_ad_button",
                    "scrap_watch_ad_button",
                    detections,
                )
            return self._recover_to(
                "wait_scrap_watch_ad_button",
                None,
                detections,
                reason="awaiting_watch_ad_stage_lock",
            )

        if "skip_button" in detections:
            inferred_state = (
                "skip_1"
                if self.skip_click_count == 0
                else "skip_2"
                if self.skip_click_count == 1
                else "wait_battle_result_popup"
            )
            return self._recover_to(inferred_state, "skip_button", detections)
        if not self.battle_clicked_in_cycle and "battle_button" in detections:
            return self._recover_to("wait_battle_button", "battle_button", detections)
        if not self.battle_clicked_in_cycle and "scrap_next_button" in detections:
            return self._recover_to(
                "wait_scrap_next_button",
                "scrap_next_button",
                detections,
            )
        if not self.battle_clicked_in_cycle and "scrap_entry" in detections:
            return self._recover_to("home", "scrap_entry", detections)
        if "scrap_watch_ad_button" in detections:
            return self._recover_to(
                self._expected_pre_watch_state(),
                None,
                detections,
                reason="watch_ad_detected_before_battle_complete",
            )
        if self.battle_clicked_in_cycle:
            return self.state
        return self.state

    def _watch_ad_ready(self) -> bool:
        return self.awaiting_watch_ad_in_cycle and (
            self.battle_phase_completed or self.battle_result_closed_in_cycle
        )

    def _ad_stage_active(self) -> bool:
        scrap_ad_context = (
            self.scrap_ad_in_progress and self.current_ad_source == "scrap_ad"
        ) or (
            self.scrap_watch_ad_clicked_in_cycle
            and self.current_ad_source == "none"
        )
        return scrap_ad_context and (
            self.state in {"ad_wait", "close_ad", "wait_return_after_ad"}
            or self.ad_wait_finished_in_cycle
        )

    def _expected_pre_watch_state(self) -> str:
        if not self.battle_clicked_in_cycle:
            return "wait_battle_button"
        if self.skip_click_count < 2:
            return "skip_1" if self.skip_click_count == 0 else "skip_2"
        if not self.battle_wait_finished_in_cycle:
            return "battle_wait"
        return "wait_battle_result_popup"

    def _ensure_watchdog_step(self) -> None:
        if self.current_step_name != "home":
            return
        step_by_state = {
            "wait_scrap_next_button": "waiting_scrap_next_button",
            "wait_battle_button": "waiting_battle_button",
            "skip_1": "waiting_skip_button",
            "skip_2": "waiting_skip_button",
            "wait_battle_result_popup": "waiting_battle_result_popup",
            "wait_scrap_watch_ad_button": "waiting_scrap_watch_ad_button",
            "close_ad": "waiting_ad_close",
        }
        step = step_by_state.get(self.state)
        if step is not None:
            self._start_step(step)

    def _transition_watchdog_decision(
        self,
        context: StrategyContext,
    ) -> StrategyDecision | None:
        specs = {
            "waiting_scrap_next_button": (
                "scrap_next_button",
                self.scrap_entry_transition_timeout_seconds,
                "adb_back_scrap_popup",
                "transition_timeout_waiting_scrap_next_button",
            ),
            "waiting_battle_button": (
                "battle_button",
                self.next_to_battle_timeout_seconds,
                "adb_back_battle_popup",
                "transition_timeout_waiting_battle_button",
            ),
            "waiting_skip_button": (
                "skip_button",
                self.battle_to_skip_timeout_seconds,
                "adb_back_battle_popup",
                "transition_timeout_waiting_skip_button",
            ),
            "waiting_battle_result_popup": (
                "battle_result_popup",
                self.result_popup_timeout_seconds,
                "adb_back_battle_result",
                "transition_timeout_waiting_battle_result_popup",
            ),
            "waiting_scrap_watch_ad_button": (
                "scrap_watch_ad_button",
                self.result_to_watch_timeout_seconds,
                "adb_back_watch_popup",
                "transition_timeout_waiting_scrap_watch_ad_button",
            ),
        }
        spec = specs.get(self.current_step_name)
        if spec is None:
            return None
        expected_target, timeout_seconds, action_name, timeout_reason = spec
        if not self._template_exists(expected_target):
            return None
        if expected_target in context.detections:
            self.last_progress_at = self._clock()
            self.miss_count_by_step[self.current_step_name] = 0
            return None

        miss_count = min(
            self.miss_count_by_step.get(self.current_step_name, 0) + 1,
            self.target_miss_threshold,
        )
        self.miss_count_by_step[self.current_step_name] = miss_count
        self._pending_strategy_events.append(
            {
                "event": "target_miss_count",
                "step": expected_target,
                "current_state": self.state,
                "miss_count": miss_count,
                "threshold": self.target_miss_threshold,
            }
        )
        if miss_count < self.target_miss_threshold:
            return StrategyDecision.wait(
                1.0,
                f"miss_count_{miss_count}_waiting_{expected_target}",
                target_name=expected_target,
            )

        repeated_count = self.repeated_click_count_by_decision.get(
            "click_scrap_next_button",
            0,
        )
        repeated = (
            self.current_step_name == "waiting_battle_button"
            and repeated_count >= self.max_same_decision_clicks_before_back
        )
        elapsed_seconds = self._clock() - self.step_started_at
        return self._watchdog_back_decision(
            action_name=action_name,
            reason=f"miss_count_{self.target_miss_threshold}_waiting_{expected_target}",
            expected_target=expected_target,
            elapsed_seconds=elapsed_seconds,
            repeated_click_count=repeated_count,
            repeated=repeated,
        )

    def _watchdog_back_decision(
        self,
        *,
        action_name: str,
        reason: str,
        expected_target: str,
        elapsed_seconds: float | None = None,
        repeated_click_count: int = 0,
        repeated: bool = False,
    ) -> StrategyDecision:
        step = self.current_step_name
        back_attempt_count = self.back_attempt_count_by_step.get(step, 0)
        event_fields = {
            "step": step,
            "current_state": self.state,
            "expected_next_target": expected_target,
            "elapsed_seconds": elapsed_seconds,
            "repeated_click_count": repeated_click_count,
            "back_attempt_count": back_attempt_count,
            "reason": reason,
        }
        if back_attempt_count >= self.max_back_attempts_per_step:
            self._pending_strategy_events.append(
                {
                    "event": "max_back_attempts_reached",
                    **event_fields,
                }
            )
            return StrategyDecision.wait(1.0, "max_back_attempts_reached_for_step")

        self._pending_strategy_events.extend(
            [
                {"event": "transition_watchdog_triggered", **event_fields},
                {"event": "no_progress_detected", **event_fields},
                {
                    "event": "miss_threshold_triggered_back",
                    **event_fields,
                    "decision": action_name,
                    "miss_count": self.target_miss_threshold,
                    "threshold": self.target_miss_threshold,
                },
            ]
        )
        if repeated:
            self._pending_strategy_events.append(
                {"event": "repeated_click_without_progress", **event_fields}
            )
        return StrategyDecision.keyevent(
            "BACK",
            action_name,
            reason,
            post_action_delay_seconds=CLICK_DELAYS[action_name],
        )

    def _start_step(self, step_name: str) -> None:
        now = self._clock()
        if hasattr(self, "current_step_name"):
            self.miss_count_by_step[self.current_step_name] = 0
        self.current_step_name = step_name
        self.step_started_at = now
        self.last_progress_at = now
        self.back_attempt_count_by_step[step_name] = 0
        self.miss_count_by_step[step_name] = 0

    def _recover_to(
        self,
        inferred_state: str,
        detection_name: str | None,
        detections,
        *,
        reason: str | None = None,
    ) -> str:
        if inferred_state != self.state:
            detection = detections.get(detection_name) if detection_name is not None else None
            self._pending_state_recovery = {
                "from_state": self.state,
                "to_state": inferred_state,
                "reason": reason or f"detected_{detection_name}",
                "confidence": detection.confidence if detection is not None else None,
                "center": list(detection.center) if detection is not None else None,
            }
            self.state = inferred_state
        return self.state

    def consume_state_recovery_event(self) -> dict[str, object] | None:
        event = self._pending_state_recovery
        self._pending_state_recovery = None
        return event

    def consume_state_change_details(self) -> dict[str, object] | None:
        details = self._pending_state_change_details
        self._pending_state_change_details = None
        return details

    def consume_strategy_events(self) -> list[dict[str, object]]:
        events = self._pending_strategy_events
        self._pending_strategy_events = []
        return events

    def on_action_result(self, decision: StrategyDecision, action_result: ActionResult) -> None:
        if decision.kind == "wait" and decision.reason == "battle_wait":
            self.battle_wait_finished_in_cycle = True
            self.state = "wait_battle_result_popup"
            self._start_step("waiting_battle_result_popup")
            return
        if decision.kind == "wait" and decision.reason == "ad_wait":
            self.ad_wait_finished_in_cycle = True
            self.state = "close_ad"
            self._start_step("waiting_ad_close")
            return
        if action_result.result != "executed":
            return
        now = self._clock()
        if decision.kind in {"click", "tap"}:
            self.last_clicked_decision = decision.action_name
            self.last_clicked_at = now
            self.repeated_click_count_by_decision[decision.action_name] = (
                self.repeated_click_count_by_decision.get(decision.action_name, 0) + 1
            )
        if decision.kind == "keyevent":
            step = self.current_step_name
            self.back_attempt_count_by_step[step] = (
                self.back_attempt_count_by_step.get(step, 0) + 1
            )
            self.step_started_at = now
            self.last_progress_at = now
            self.miss_count_by_step[step] = 0
            if decision.reason == "repeated_scrap_next_click_without_battle_button":
                self.repeated_click_count_by_decision["click_scrap_next_button"] = 0
        transitions = {
            "click_scrap_entry": "wait_scrap_next_button",
            "click_scrap_next_button": "wait_battle_button",
            "click_battle_button": "skip_1",
            "click_scrap_watch_ad_button": "ad_wait",
        }
        if decision.action_name in {
            "adb_back_scrap_popup",
            "adb_back_battle_popup",
            "adb_back_watch_popup",
        }:
            return
        if decision.action_name in {
            "adb_back_battle_result",
            "click_battle_result_confirm",
        }:
            self.battle_result_closed_in_cycle = True
            self.battle_result_handled = True
            self.battle_phase_completed = True
            self.awaiting_watch_ad_in_cycle = True
            self.last_expected_target = "scrap_watch_ad_button"
            self.last_stable_scrap_state = "wait_scrap_watch_ad_button"
            self._pending_state_change_details = {
                "reason": "battle_result_closed_awaiting_watch_ad",
                "awaiting_watch_ad_in_cycle": True,
            }
            self.state = "wait_scrap_watch_ad_button"
            self._start_step("waiting_scrap_watch_ad_button")
        elif decision.action_name == "click_skip_button":
            self.skip_click_count += 1
            self.state = "skip_2" if self.skip_click_count == 1 else "battle_wait"
            if self.skip_click_count >= 2:
                self.current_step_name = "battle_wait"
        elif decision.action_name == "close_ad":
            self.close_streak += 1
            self.close_ad_executed = True
            if (
                self.current_ad_source == "scrap_ad"
                or self.scrap_ad_in_progress
                or self.scrap_watch_ad_clicked_in_cycle
            ):
                self.scrap_ad_closed_once = True
                self.state = "wait_return_after_ad"
                self.last_expected_target = "scrap_page_marker"
                self.last_stable_scrap_state = "wait_return_after_ad"
                self._start_step("waiting_return_after_ad")
            else:
                self.state = "wait_return_after_ad"
                self._start_step("waiting_return_after_ad")
        elif decision.action_name == "click_scrap_watch_ad_button":
            self.scrap_watch_ad_clicked_in_cycle = True
            self.awaiting_watch_ad_in_cycle = False
            self.scrap_ad_in_progress = True
            self.current_ad_source = "scrap_ad"
            self.state = "ad_wait"
            self.last_expected_target = "close_ad"
            self.last_stable_scrap_state = "ad_wait"
            self._start_step("ad_wait")
        elif decision.action_name == "click_battle_button":
            self.battle_clicked_in_cycle = True
            self.state = "skip_1"
            self._start_step("waiting_skip_button")
        elif decision.action_name == "click_scrap_entry":
            self.state = "wait_scrap_next_button"
            self._start_step("waiting_scrap_next_button")
        elif decision.action_name == "click_scrap_next_button":
            self.state = "wait_battle_button"
            if self.current_step_name != "waiting_battle_button":
                self._start_step("waiting_battle_button")
        elif decision.action_name in transitions:
            self.state = transitions[decision.action_name]

    @property
    def skip_count(self) -> int:
        return self.skip_click_count

    def _complete_scrap_ad_from_return(self, detection_name: str) -> None:
        self.scrap_ad_in_progress = False
        self.scrap_ad_completed = True
        self.scrap_ad_finished_by_return_to_scrap_page = True
        self.scrap_phase_completed = True
        self.current_ad_source = "none"
        self.close_streak = 0
        self.return_home_after_scrap_started = True
        self.state = "return_home_after_scrap"
        self.last_expected_target = "home_marker"
        self.last_stable_scrap_state = "return_home_after_scrap"
        self._pending_strategy_events.append(
            {
                "event": "scrap_ad_closed_returned_to_scrap_page",
                "reason": "detected_scrap_page_after_close_ad",
                "target_name": detection_name,
            }
        )
        self._start_step("returning_home_after_scrap")

    def _click_or_wait(
        self,
        context: StrategyContext,
        target_name: str,
        action_name: str,
        wait_reason: str,
    ) -> StrategyDecision:
        if target_name not in context.detections:
            return self._wait_or_missing(target_name, wait_reason)
        return StrategyDecision.click(
            target_name,
            action_name,
            action_name,
            post_action_delay_seconds=CLICK_DELAYS[action_name],
        )

    def _wait_or_missing(self, target_name: str, wait_reason: str) -> StrategyDecision:
        if not self._template_exists(target_name):
            return StrategyDecision.wait(1.0, f"template_missing_{target_name}")
        return StrategyDecision.wait(1.0, wait_reason)

    def _template_exists(self, target_name: str) -> bool:
        return (TEMPLATE_ROOT / f"{target_name}.png").exists()

    def _close_targets(self) -> Sequence[TargetSpec]:
        templates_dir = definition().templates_dir
        builtins = (
            TargetSpec("close_end_2", str(templates_dir / "close-end-2.png"), CLOSE_AD_CANDIDATE_THRESHOLD, region=RelativeRegion(0.80, 0.0, 0.20, 0.20), scale_min=0.4, scale_max=1.1, scale_step=0.05),
            TargetSpec("close_end_1", str(templates_dir / "close-end-1.png"), CLOSE_AD_CANDIDATE_THRESHOLD, region=RelativeRegion(0.0, 0.0, 0.25, 0.20), scale_min=0.4, scale_max=1.1, scale_step=0.05),
            TargetSpec("close_end_3", str(templates_dir / "close-end-3.png"), CLOSE_AD_CANDIDATE_THRESHOLD, region=RelativeRegion(0.80, 0.0, 0.20, 0.20), scale_min=0.4, scale_max=1.1, scale_step=0.05),
            TargetSpec("close_end_4", str(templates_dir / "close-end-4.png"), CLOSE_AD_CANDIDATE_THRESHOLD, region=RelativeRegion(0.80, 0.0, 0.20, 0.20), scale_min=0.4, scale_max=1.1, scale_step=0.05),
        )
        return (
            *builtins,
            *load_user_close_targets(log=print, threshold=CLOSE_AD_CANDIDATE_THRESHOLD),
        )

    def _best_close_detection(self, context: StrategyContext):
        candidates = [
            detection
            for name, detection in context.detections.items()
            if name.startswith("close_end_") or name.startswith("close_user_")
        ]
        return None if not candidates else max(candidates, key=lambda item: item.confidence)

    def _best_close_target(self, context: StrategyContext) -> str | None:
        detection = self._best_close_detection(context)
        return None if detection is None else detection.name

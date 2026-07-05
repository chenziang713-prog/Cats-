from __future__ import annotations

# 旧版策略逻辑，已废弃。
# 保留原因：方便对比、回退和查看旧行为。
# 新逻辑请使用 external_strategies/scrap_then_ad_reward_v2 下的
# screen_state_detector / state_action_templates / strategy。

import importlib.util
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from cats_automatic.actions import ActionResult
from cats_automatic.games.cats.game import definition
from cats_automatic.games.cats.strategies.ad_reward import Strategy as AdRewardStrategy
from cats_automatic.strategy_base import DetectionResult, StrategyContext, StrategyDecision, TargetSpec


PACKAGE_ROOT = Path(__file__).resolve().parent
EXTERNAL_ROOT = PACKAGE_ROOT.parent
SCRAP_PACKAGE_ROOT = EXTERNAL_ROOT / "scrap_ad_battle"
SCRAP_TEMPLATE_ROOT = SCRAP_PACKAGE_ROOT / "templates"
HOME_CONFIDENCE_THRESHOLD = 0.80
MAX_BACK_TO_HOME_ATTEMPTS = 5
TARGET_MISS_THRESHOLD = 3
SCRAP_INTERNAL_TARGETS = {
    "scrap_next_button",
    "battle_button",
    "skip_button",
    "battle_result_popup",
    "scrap_watch_ad_button",
}


def _load_scrap_strategy_class():
    strategy_path = SCRAP_PACKAGE_ROOT / "strategy.py"
    spec = importlib.util.spec_from_file_location(
        "cats_automatic_combined_scrap_ad_battle",
        strategy_path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load scrap strategy: {strategy_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.Strategy


ScrapStrategy = _load_scrap_strategy_class()


class Strategy:
    handles_reward_cycle_completion = True

    def __init__(self) -> None:
        self.scrap_strategy = ScrapStrategy()
        self.film_strategy = AdRewardStrategy()
        self.max_back_to_home_attempts = MAX_BACK_TO_HOME_ATTEMPTS
        self.target_miss_threshold = TARGET_MISS_THRESHOLD
        self.state = "home"
        self.phase = "scrap_phase"
        self.scrap_phase_completed_in_cycle = False
        self.returning_home_after_scrap = False
        self.back_to_home_attempt_count = 0
        self.home_detected_after_scrap = False
        self.film_ad_reward_started_in_cycle = False
        self.film_ad_reward_completed_in_cycle = False
        self.film_watch_ad_clicked_in_cycle = False
        self.film_close_ad_executed_in_cycle = False
        self.film_ad_entry_clicked = False
        self.film_ad_in_progress = False
        self.current_ad_source = "none"
        self.last_expected_target = "scrap_entry"
        self.last_successful_decision = ""
        self.last_successful_click_before_ad_wait = ""
        self._pending_strategy_events: list[dict[str, object]] = []
        self.miss_count_by_step: dict[str, int] = {"home_after_scrap": 0}

    def configure(
        self,
        *,
        battle_wait_seconds: float = 60.0,
        ad_wait_seconds: float = 20.0,
    ) -> None:
        self.scrap_strategy.configure(
            battle_wait_seconds=battle_wait_seconds,
            ad_wait_seconds=ad_wait_seconds,
        )

    def reset_cycle(self) -> None:
        self.scrap_strategy.reset_cycle()
        self.film_strategy.reset_cycle()
        self.state = self.scrap_strategy.state
        self.phase = "scrap_phase"
        self.scrap_phase_completed_in_cycle = False
        self.returning_home_after_scrap = False
        self.back_to_home_attempt_count = 0
        self.home_detected_after_scrap = False
        self.film_ad_reward_started_in_cycle = False
        self.film_ad_reward_completed_in_cycle = False
        self.film_watch_ad_clicked_in_cycle = False
        self.film_close_ad_executed_in_cycle = False
        self.film_ad_entry_clicked = False
        self.film_ad_in_progress = False
        self.current_ad_source = "none"
        self.last_expected_target = "scrap_entry"
        self.last_successful_decision = ""
        self.last_successful_click_before_ad_wait = ""
        self._pending_strategy_events = []
        self.miss_count_by_step = {"home_after_scrap": 0}

    def targets(self) -> Sequence[TargetSpec]:
        targets: dict[str, TargetSpec] = {}
        for target in self.scrap_strategy.targets():
            targets[target.name] = self._resolve_scrap_target(target)
        for target in self.film_strategy.targets():
            targets.setdefault(target.name, self._resolve_film_target(target))
        return tuple(targets.values())

    @property
    def current_phase(self) -> str:
        return self.phase

    def recovery_stage_lock(self) -> str | None:
        if self.phase in {"film_ad_reward_phase", "wait_film_watch_button", "film_ad_closing"} or self.film_ad_reward_started_in_cycle:
            return "recovery_preserved_film_ad_reward_phase"
        if self.phase == "return_home_after_scrap" or self.scrap_phase_completed_in_cycle:
            return "recovery_preserved_return_home_after_scrap"
        return self.scrap_strategy.recovery_stage_lock()

    def phase_snapshot(self, *, loop_index: int, detections, decision: StrategyDecision) -> dict[str, object]:
        ad_entry = detections.get("ad_entry")
        close_candidates = [
            item for name, item in detections.items()
            if name.startswith("close_user_") or name.startswith("close_end_")
        ]
        close_allowed = self._film_close_candidate_allowed()
        snapshot = self.scrap_strategy.phase_snapshot(
            loop_index=loop_index,
            detections=detections,
            decision=decision,
        )
        snapshot.update(
            {
                "current_phase": self.phase,
                "state": self.state,
                "current_ad_source": (
                    self.current_ad_source
                    if self.phase in {"film_ad_reward_phase", "wait_film_watch_button", "film_ad_closing"}
                    else self.scrap_strategy.current_ad_source
                ),
                "scrap_phase_completed": self.scrap_phase_completed_in_cycle,
                "return_home_after_scrap_started": self.returning_home_after_scrap,
                "home_detected_after_scrap": self.home_detected_after_scrap,
                "film_ad_reward_started": self.film_ad_reward_started_in_cycle,
                "film_ad_entry_clicked": self.film_ad_entry_clicked,
                "last_expected_target": self.last_expected_target,
                "film_ad_entry_detected": ad_entry is not None,
                "film_ad_entry_confidence": None if ad_entry is None else ad_entry.confidence,
                "film_ad_entry_center": None if ad_entry is None else list(ad_entry.center),
                "film_ad_entry_click_allowed": ad_entry is not None and self.phase == "film_ad_reward_phase",
                "film_ad_entry_blocked_by": "" if ad_entry is not None else "film_ad_entry_missing",
                "close_candidate_seen": bool(close_candidates),
                "close_candidate_allowed": close_allowed,
                "close_candidate_ignored_reason": (
                    "close_candidate_ignored_not_in_ad_stage"
                    if close_candidates and not close_allowed else ""
                ),
                "close_candidate_ignored_in_film_phase": bool(close_candidates) and not close_allowed,
                "ad_wait_enter_reason": (
                    "click_watch_ad_button" if self.film_ad_in_progress else ""
                ),
                "ad_wait_allowed_by_decision": self.last_successful_click_before_ad_wait,
                "last_successful_decision": self.last_successful_decision,
                "last_successful_click_before_ad_wait": self.last_successful_click_before_ad_wait,
                "transition_to": self.phase,
            }
        )
        return snapshot

    def decide(self, context: StrategyContext) -> StrategyDecision:
        # DEPRECATED: 旧版执行逻辑，不再作为新策略主入口。
        # 后续新策略应通过“状态识别 -> 状态动作 -> 流程控制”的方式执行。
        if (
            "battle_result_popup" in context.detections
            and not self.film_ad_reward_started_in_cycle
            and not self.scrap_strategy.battle_result_closed_in_cycle
            and self.phase != "scrap_phase"
        ):
            previous_state = self.state
            self.phase = "scrap_phase"
            self.scrap_phase_completed_in_cycle = False
            self.returning_home_after_scrap = False
            self.scrap_strategy.state = "wait_battle_result_popup"
            self.state = "wait_battle_result_popup"
            self._pending_strategy_events.append(
                {
                    "event": "state_recovered",
                    "from_state": previous_state,
                    "to_state": "wait_battle_result_popup",
                    "reason": "battle_result_popup_priority_override",
                }
            )

        if self.phase == "scrap_phase":
            decision = self.scrap_strategy.decide(context)
            self.state = self.scrap_strategy.state
            if decision.kind != "complete":
                return decision
            self.scrap_phase_completed_in_cycle = True
            self.returning_home_after_scrap = True
            self.phase = "return_home_after_scrap"
            self.state = "return_home_after_scrap"
            self._pending_strategy_events.extend(
                [
                    {"event": "scrap_phase_completed", "reason": decision.reason},
                    {"event": "return_home_after_scrap_started"},
                ]
            )
            return StrategyDecision.wait(0.0, "scrap_phase_completed_returning_home")

        if self.phase == "return_home_after_scrap":
            return self._decide_return_home(context)

        if self.phase in {"film_ad_reward_phase", "wait_film_watch_button", "film_ad_closing"}:
            return self._decide_film_ad_reward(context)

        if self.phase == "cycle_completed":
            return StrategyDecision.complete("scrap_then_ad_reward_completed")

        return StrategyDecision.wait(1.0, "wait_unknown_combined_phase")

    def on_action_result(self, decision: StrategyDecision, action_result: ActionResult) -> None:
        if self.phase == "scrap_phase":
            self.scrap_strategy.on_action_result(decision, action_result)
            self.state = self.scrap_strategy.state
            if self.scrap_strategy.scrap_phase_completed:
                self.scrap_phase_completed_in_cycle = True
                self.returning_home_after_scrap = True
                self.phase = "return_home_after_scrap"
                self.state = "return_home_after_scrap"
                self._pending_strategy_events.extend(
                    [
                        {"event": "scrap_phase_completed", "reason": "scrap_ad_closed"},
                        {"event": "return_home_after_scrap_started"},
                    ]
                )
            return

        if self.phase == "return_home_after_scrap":
            if (
                decision.action_name == "adb_back_to_home_after_scrap"
                and action_result.result == "executed"
            ):
                self.back_to_home_attempt_count += 1
                self.miss_count_by_step["home_after_scrap"] = 0
                self._pending_strategy_events.append(
                    {
                        "event": "adb_back_to_home_after_scrap",
                        "back_to_home_attempt_count": self.back_to_home_attempt_count,
                    }
                )
            return

        if self.phase not in {"film_ad_reward_phase", "wait_film_watch_button", "film_ad_closing"}:
            return
        self.film_strategy.on_action_result(decision, action_result)
        if action_result.result != "executed":
            return
        self.last_successful_decision = decision.action_name
        if decision.action_name == "click_watch_ad_button":
            self.film_watch_ad_clicked_in_cycle = True
            self.film_ad_in_progress = True
            self.current_ad_source = "film_ad"
            self.phase = "film_ad_closing"
            self.state = "film_ad_closing"
            self.last_successful_click_before_ad_wait = decision.action_name
            self.last_expected_target = "close_ad"
        elif decision.action_name == "close_ad":
            self.film_close_ad_executed_in_cycle = True
            self.film_ad_in_progress = False
            self.current_ad_source = "none"
        elif decision.action_name == "click_ad_entry":
            self.film_ad_entry_clicked = True
            self.phase = "wait_film_watch_button"
            self.state = "wait_film_watch_button"
            self.last_expected_target = "watch_ad_button"
        elif decision.action_name == "confirm_reward":
            self._complete_film_ad_reward("confirm_reward")

    def consume_state_recovery_event(self) -> dict[str, object] | None:
        if self.phase != "scrap_phase":
            return None
        return self.scrap_strategy.consume_state_recovery_event()

    def consume_state_change_details(self) -> dict[str, object] | None:
        if self.phase != "scrap_phase":
            return None
        return self.scrap_strategy.consume_state_change_details()

    def consume_strategy_events(self) -> list[dict[str, object]]:
        events = self._pending_strategy_events
        self._pending_strategy_events = []
        if self.phase == "scrap_phase":
            events.extend(self.scrap_strategy.consume_strategy_events())
        return events

    def _decide_return_home(self, context: StrategyContext) -> StrategyDecision:
        for target_name in ("battle_button", "scrap_watch_ad_button"):
            if target_name in context.detections:
                self._pending_strategy_events.append(
                    {
                        "event": f"{target_name}_ignored_returning_home_after_scrap",
                        "reason": "return_home_after_scrap_stage_lock",
                    }
                )
        home_detection = self.is_home_screen(context.detections)
        self._pending_strategy_events.append(
            {
                "event": "home_detection",
                "is_home": home_detection is not None,
                "matched_target": home_detection.name if home_detection is not None else "none",
                "confidence": home_detection.confidence if home_detection is not None else None,
            }
        )
        if home_detection is not None:
            self.miss_count_by_step["home_after_scrap"] = 0
            self.home_detected_after_scrap = True
            self.returning_home_after_scrap = False
            self.film_ad_reward_started_in_cycle = True
            self.phase = "film_ad_reward_phase"
            self.state = "film_ad_reward_phase"
            self.film_strategy.reset_cycle()
            self.last_expected_target = "ad_entry"
            self._pending_strategy_events.extend(
                [
                    {
                        "event": "home_detected_after_scrap",
                        "matched_target": home_detection.name,
                        "confidence": home_detection.confidence,
                    },
                    {"event": "film_ad_reward_started"},
                ]
            )
            return StrategyDecision.wait(0.0, "home_detected_after_scrap")
        miss_count = min(
            self.miss_count_by_step.get("home_after_scrap", 0) + 1,
            self.target_miss_threshold,
        )
        self.miss_count_by_step["home_after_scrap"] = miss_count
        self._pending_strategy_events.append(
            {
                "event": "target_miss_count",
                "step": "home_after_scrap",
                "miss_count": miss_count,
                "threshold": self.target_miss_threshold,
            }
        )
        if miss_count < self.target_miss_threshold:
            return StrategyDecision.wait(
                1.0,
                f"miss_count_{miss_count}_waiting_home_after_scrap",
                target_name="home_after_scrap",
            )
        if self.back_to_home_attempt_count >= self.max_back_to_home_attempts:
            self._pending_strategy_events.append(
                {
                    "event": "return_home_after_scrap_home_not_detected_after_max_back",
                    "detected_targets": sorted(context.detections),
                    "internal_scrap_targets": sorted(
                        SCRAP_INTERNAL_TARGETS.intersection(context.detections)
                    ),
                }
            )
            return StrategyDecision.wait(1.0, "final_home_probe_not_detected")
        self._pending_strategy_events.append(
            {
                "event": "miss_threshold_triggered_back",
                "step": "home_after_scrap",
                "miss_count": miss_count,
                "threshold": self.target_miss_threshold,
                "decision": "adb_back_to_home_after_scrap",
            }
        )
        return StrategyDecision.keyevent(
            "BACK",
            "adb_back_to_home_after_scrap",
            "miss_count_3_waiting_home_after_scrap",
            post_action_delay_seconds=1.0,
        )

    def _decide_film_ad_reward(self, context: StrategyContext) -> StrategyDecision:
        if self.film_ad_reward_completed_in_cycle:
            self.phase = "cycle_completed"
            self.state = "cycle_completed"
            return StrategyDecision.complete("scrap_then_ad_reward_completed")
        if (
            self.film_watch_ad_clicked_in_cycle
            and self.film_close_ad_executed_in_cycle
            and "reward_confirm_marker" not in context.detections
            and "confirm_button" not in context.detections
        ):
            home_detection = self.is_home_screen(context.detections)
            if home_detection is not None:
                return self._complete_film_ad_reward("home_return_after_ad")
        close_candidates = {
            name: detection for name, detection in context.detections.items()
            if name.startswith("close_user_") or name.startswith("close_end_")
        }
        if close_candidates and not self._film_close_candidate_allowed():
            self._pending_strategy_events.append(
                {
                    "event": "close_candidate_ignored_not_in_ad_stage",
                    "target_names": sorted(close_candidates),
                    "current_phase": self.phase,
                    "current_ad_source": self.current_ad_source,
                    "reason": "close_candidate_ignored_not_in_ad_stage",
                }
            )
        filtered = {
            name: detection for name, detection in context.detections.items()
            if self._film_close_candidate_allowed()
            or not (name.startswith("close_user_") or name.startswith("close_end_"))
        }
        filtered_context = replace(context, detections=filtered)
        if "reward_confirm_marker" in filtered and "confirm_button" in filtered:
            return self.film_strategy.decide(filtered_context)
        if self.phase == "film_ad_reward_phase" and not self.film_ad_entry_clicked:
            if "ad_entry" not in filtered:
                return StrategyDecision.wait(1.0, "film_ad_entry_missing", target_name="ad_entry")
            return StrategyDecision.click(
                "ad_entry",
                "click_ad_entry",
                "click_ad_entry",
                post_action_delay_seconds=5.0,
            )
        if self.phase == "wait_film_watch_button":
            watch_names = [name for name in filtered if name == "watch_ad_button" or name.startswith("watch_user_")]
            if not watch_names:
                return StrategyDecision.wait(1.0, "film_watch_button_missing", target_name="watch_ad_button")
            watch_target = max(watch_names, key=lambda name: filtered[name].confidence)
            return StrategyDecision.click(
                watch_target,
                "click_watch_ad_button",
                "click_watch_ad_button",
                post_action_delay_seconds=15.0,
            )
        return self.film_strategy.decide(filtered_context)

    def _film_close_candidate_allowed(self) -> bool:
        return (
            self.current_ad_source == "film_ad"
            and self.film_watch_ad_clicked_in_cycle
            and self.film_ad_in_progress
            and self.phase == "film_ad_closing"
        )

    def _complete_film_ad_reward(self, reason: str) -> StrategyDecision:
        self.film_ad_reward_completed_in_cycle = True
        self.phase = "cycle_completed"
        self.state = "cycle_completed"
        self._pending_strategy_events.append(
            {"event": "film_ad_reward_completed", "reason": reason}
        )
        return StrategyDecision.complete("scrap_then_ad_reward_completed")

    def is_home_screen(
        self,
        detections,
    ) -> DetectionResult | None:
        if SCRAP_INTERNAL_TARGETS.intersection(detections):
            return None
        candidates = [
            detection
            for name, detection in detections.items()
            if name in {"ad_entry", "scrap_entry"}
            and detection.confidence >= HOME_CONFIDENCE_THRESHOLD
        ]
        return None if not candidates else max(candidates, key=lambda item: item.confidence)

    def _resolve_scrap_target(self, target: TargetSpec) -> TargetSpec:
        path = Path(target.template)
        if path.is_absolute():
            return target
        return replace(target, template=str((SCRAP_TEMPLATE_ROOT / path).resolve()))

    def _resolve_film_target(self, target: TargetSpec) -> TargetSpec:
        path = Path(target.template)
        if path.is_absolute():
            return target
        if path.parts and path.parts[0] == "templates":
            path = definition().templates_dir / path.name
        return replace(target, template=str(path.resolve()))

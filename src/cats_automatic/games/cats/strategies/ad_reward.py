from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from ....actions import ActionResult
from ....user_ad_reward_templates import (
    load_pre_watch_optional_target,
    load_user_watch_targets,
)
from ....user_close_templates import load_user_close_targets
from ....strategy_base import RelativeRegion, StrategyContext, StrategyDecision, TargetSpec


BUILTIN_CLOSE_TARGET_NAMES = ("close_end_2", "close_end_1", "close_end_3", "close_end_4")

POST_ACTION_DELAYS = {
    "click_ad_entry": 5.0,
    "click_pre_watch_optional": 1.0,
    "click_watch_ad_button": 15.0,
    "close_ad": 1.5,
    "confirm_reward": 1.5,
}


class Strategy:
    def __init__(
        self,
        max_consecutive_close_actions: int = 3,
        user_close_template_dir: Path | None = None,
        pre_watch_optional_template_dir: Path | None = None,
        user_watch_template_dir: Path | None = None,
    ) -> None:
        self.max_consecutive_close_actions = max_consecutive_close_actions
        self._consecutive_close_actions = 0
        self.user_close_template_dir = user_close_template_dir
        self.pre_watch_optional_template_dir = pre_watch_optional_template_dir
        self.user_watch_template_dir = user_watch_template_dir
        self._pre_watch_optional_clicked = False

    def targets(self) -> Sequence[TargetSpec]:
        return (
            *self._close_targets(),
            TargetSpec(
                name="page_marker",
                template="templates/page-marker.png",
                threshold=0.80,
                match_mode="color",
                scale_min=0.4,
                scale_max=1.1,
                scale_step=0.05,
            ),
            TargetSpec(
                name="reward_confirm_marker",
                template="templates/reward-confirm-marker.png",
                threshold=0.80,
                match_mode="color",
                scale_min=0.4,
                scale_max=1.1,
                scale_step=0.05,
            ),
            TargetSpec(
                name="confirm_button",
                template="templates/confirm-button.png",
                threshold=0.80,
                match_mode="color",
                scale_min=0.4,
                scale_max=1.1,
                scale_step=0.05,
            ),
            *self._optional_targets(),
            TargetSpec(
                name="watch_ad_button",
                template="templates/watch-ad-button.png",
                threshold=0.80,
                match_mode="color",
                scale_min=0.4,
                scale_max=1.1,
                scale_step=0.05,
            ),
            *load_user_watch_targets(self.user_watch_template_dir, log=print),
            TargetSpec(
                name="ad_entry",
                template="templates/ad-entry.png",
                threshold=0.55,
                match_mode="color",
                scale_min=0.4,
                scale_max=1.1,
                scale_step=0.05,
            ),
        )

    def _optional_targets(self) -> Sequence[TargetSpec]:
        target = load_pre_watch_optional_target(self.pre_watch_optional_template_dir, log=print)
        return () if target is None else (target,)

    def _close_targets(self) -> Sequence[TargetSpec]:
        return (
            TargetSpec(
                name="close_end_2",
                template="templates/close-end-2.png",
                threshold=0.75,
                match_mode="color",
                region=RelativeRegion(x=0.80, y=0.0, width=0.20, height=0.20),
                scale_min=0.4,
                scale_max=1.1,
                scale_step=0.05,
            ),
            TargetSpec(
                name="close_end_1",
                template="templates/close-end-1.png",
                threshold=0.90,
                match_mode="color",
                region=RelativeRegion(x=0.0, y=0.0, width=0.25, height=0.20),
                scale_min=0.4,
                scale_max=1.1,
                scale_step=0.05,
            ),
            TargetSpec(
                name="close_end_3",
                template="templates/close-end-3.png",
                threshold=0.75,
                match_mode="color",
                region=RelativeRegion(x=0.80, y=0.0, width=0.20, height=0.20),
                scale_min=0.4,
                scale_max=1.1,
                scale_step=0.05,
            ),
            TargetSpec(
                name="close_end_4",
                template="templates/close-end-4.png",
                threshold=0.75,
                match_mode="color",
                region=RelativeRegion(x=0.80, y=0.0, width=0.20, height=0.20),
                scale_min=0.4,
                scale_max=1.1,
                scale_step=0.05,
            ),
            *load_user_close_targets(self.user_close_template_dir, log=print),
        )

    def decide(self, context: StrategyContext) -> StrategyDecision:
        close_target_name = self._best_close_target(context)
        if close_target_name is not None:
            return self._close_or_wait(close_target_name)

        self._reset_close_limit()
        if "reward_confirm_marker" in context.detections:
            if "confirm_button" not in context.detections:
                return StrategyDecision.wait(1.0, "wait_reward_confirm_no_button")
            return StrategyDecision.click(
                "confirm_button",
                "confirm_reward",
                "confirm_reward",
                post_action_delay_seconds=POST_ACTION_DELAYS["confirm_reward"],
            )
        if "page_marker" not in context.detections:
            if "ad_entry" in context.detections:
                return StrategyDecision.click(
                    "ad_entry",
                    "click_ad_entry",
                    "click_ad_entry",
                    post_action_delay_seconds=POST_ACTION_DELAYS["click_ad_entry"],
                )
            return StrategyDecision.wait(1.0, "wait_not_on_target_page")
        if not self._pre_watch_optional_clicked and "pre_watch_optional" in context.detections:
            return StrategyDecision.click(
                "pre_watch_optional",
                "click_pre_watch_optional",
                "click_pre_watch_optional",
                post_action_delay_seconds=POST_ACTION_DELAYS["click_pre_watch_optional"],
            )
        watch_target_name = self._best_watch_target(context)
        if watch_target_name is None:
            return StrategyDecision.wait(1.0, "wait_no_ad_button")
        return StrategyDecision.click(
            watch_target_name,
            "click_watch_ad_button",
            "click_watch_ad_button",
            post_action_delay_seconds=POST_ACTION_DELAYS["click_watch_ad_button"],
        )

    def _close_or_wait(self, target_name: str) -> StrategyDecision:
        if self._consecutive_close_actions >= self.max_consecutive_close_actions:
            return StrategyDecision.wait(1.0, "wait_close_limit_reached")
        self._consecutive_close_actions += 1
        return StrategyDecision.click(
            target_name,
            "close_ad",
            "close_ad",
            post_action_delay_seconds=POST_ACTION_DELAYS["close_ad"],
        )

    def _reset_close_limit(self) -> None:
        self._consecutive_close_actions = 0

    def reset_cycle(self) -> None:
        self._reset_close_limit()
        self._pre_watch_optional_clicked = False

    def on_action_result(self, decision: StrategyDecision, action_result: ActionResult) -> None:
        if (
            decision.action_name == "click_pre_watch_optional"
            and action_result.result == "executed"
        ):
            self._pre_watch_optional_clicked = True

    def _best_close_target(self, context: StrategyContext) -> str | None:
        close_detections = [
            detection
            for name, detection in context.detections.items()
            if name in BUILTIN_CLOSE_TARGET_NAMES or name.startswith("close_user_")
        ]
        if not close_detections:
            return None
        return max(close_detections, key=lambda detection: detection.confidence).name

    def _best_watch_target(self, context: StrategyContext) -> str | None:
        watch_detections = [
            detection
            for name, detection in context.detections.items()
            if name == "watch_ad_button" or name.startswith("watch_user_")
        ]
        if not watch_detections:
            return None
        return max(watch_detections, key=lambda detection: detection.confidence).name

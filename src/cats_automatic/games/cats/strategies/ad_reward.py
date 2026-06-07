from __future__ import annotations

from collections.abc import Sequence

from ....strategy_base import RelativeRegion, StrategyContext, StrategyDecision, TargetSpec


class Strategy:
    def __init__(self, max_consecutive_close_actions: int = 3) -> None:
        self.max_consecutive_close_actions = max_consecutive_close_actions
        self._consecutive_close_actions = 0

    def targets(self) -> Sequence[TargetSpec]:
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
            TargetSpec(
                name="watch_ad_button",
                template="templates/watch-ad-button.png",
                threshold=0.80,
                match_mode="color",
                scale_min=0.4,
                scale_max=1.1,
                scale_step=0.05,
            ),
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

    def decide(self, context: StrategyContext) -> StrategyDecision:
        if "close_end_2" in context.detections:
            return self._close_or_wait("close_end_2")
        if "close_end_1" in context.detections:
            return self._close_or_wait("close_end_1")
        if "close_end_3" in context.detections:
            return self._close_or_wait("close_end_3")
        if "close_end_4" in context.detections:
            return self._close_or_wait("close_end_4")

        self._reset_close_limit()
        if "reward_confirm_marker" in context.detections:
            if "confirm_button" not in context.detections:
                return StrategyDecision.wait(1.0, "wait_reward_confirm_no_button")
            return StrategyDecision.click(
                "confirm_button",
                "confirm_reward",
                "confirm_reward",
            )
        if "page_marker" not in context.detections:
            if "ad_entry" in context.detections:
                return StrategyDecision.click("ad_entry", "click_ad_entry", "click_ad_entry")
            return StrategyDecision.wait(1.0, "wait_not_on_target_page")
        if "watch_ad_button" not in context.detections:
            return StrategyDecision.wait(1.0, "wait_no_ad_button")
        return StrategyDecision.click(
            "watch_ad_button",
            "click_watch_ad_button",
            "click_watch_ad_button",
        )

    def _close_or_wait(self, target_name: str) -> StrategyDecision:
        if self._consecutive_close_actions >= self.max_consecutive_close_actions:
            return StrategyDecision.wait(1.0, "wait_close_limit_reached")
        self._consecutive_close_actions += 1
        return StrategyDecision.click(target_name, "close_ad", "close_ad")

    def _reset_close_limit(self) -> None:
        self._consecutive_close_actions = 0

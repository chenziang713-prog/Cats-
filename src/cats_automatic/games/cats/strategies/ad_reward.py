from __future__ import annotations

from collections.abc import Sequence

from ....strategy_base import StrategyContext, StrategyDecision, TargetSpec


class Strategy:
    def targets(self) -> Sequence[TargetSpec]:
        return (
            TargetSpec(
                name="close_button",
                template="templates/ad-close-x.png",
                threshold=0.60,
                match_mode="edge",
                scale_min=0.4,
                scale_max=1.1,
                scale_step=0.05,
            ),
            TargetSpec(
                name="reward_button",
                template="templates/ad-confirm-claim.png",
                threshold=0.70,
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
        if "close_button" in context.detections:
            return StrategyDecision.click("close_button", "close_ad")
        if "reward_button" in context.detections:
            return StrategyDecision.click("reward_button", "click_reward_button")
        if "ad_entry" in context.detections:
            return StrategyDecision.click("ad_entry", "click_ad_entry")
        return StrategyDecision.wait(1.0, "no_target_detected")

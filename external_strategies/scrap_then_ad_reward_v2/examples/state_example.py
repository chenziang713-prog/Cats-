from __future__ import annotations

from external_strategies.scrap_then_ad_reward_v2.authoring import define_state
from external_strategies.scrap_then_ad_reward_v2.marker_groups import AD_CLOSE_MARKERS


EXAMPLE_SCRAP_REWARD_PAGE = define_state(
    "EXAMPLE_SCRAP_REWARD_PAGE",
    require_all=("reward_confirm_marker",),
    require_any=("confirm_button",),
    exclude=AD_CLOSE_MARKERS,
    priority=80,
    action="no_action",
    reason="example reward page definition",
)

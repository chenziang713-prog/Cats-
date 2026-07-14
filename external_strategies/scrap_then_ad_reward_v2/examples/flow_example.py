from __future__ import annotations

from external_strategies.scrap_then_ad_reward_v2.authoring import (
    define_flow,
    tap_marker_action,
    wait_action,
)


EXAMPLE_CLOSE_AD_FLOW = define_flow(
    step="WATCH_AD",
    state="AD_CLOSE_PAGE",
    action=tap_marker_action(
        "close_end_2",
        min_confidence=0.80,
        reason="example_close_ad",
    ),
    next_step="CLOSE_AD",
    description="example only: close an ad using a safe marker action after a close marker is visible",
)

EXAMPLE_WAIT_FLOW = define_flow(
    step="WATCH_AD",
    state="UNKNOWN",
    action=wait_action(seconds=1.0, reason="example_wait_unknown"),
    next_step="WATCH_AD",
    description="example only: wait when the page is unclear",
)

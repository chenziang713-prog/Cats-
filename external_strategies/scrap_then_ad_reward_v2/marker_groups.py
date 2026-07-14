from __future__ import annotations

from cats_automatic.actions import DEFAULT_TAP_MARKER_ALLOW_LIST


AD_CLOSE_MARKERS = tuple(sorted(DEFAULT_TAP_MARKER_ALLOW_LIST))

HOME_MARKERS = (
    "main-definate",
)

SCRAP_ACTIVITY_MARKERS = (
    "scrap_page_marker",
    "scrap_next_button",
    "battle_button",
    "scrap_watch_ad_button",
)

REWARD_MARKERS = (
    "reward_confirm_marker",
    "confirm_button",
    "get_reward",
)

POPUP_MARKERS = (
    "error_popup",
    "network_error_popup",
    "retry_button",
)

FILM_MARKERS = (
    "ad_entry",
    "watch_ad_button",
    "watch_ad_film",
    "select_reward_mode",
    "pre_watch_optional",
)

REGISTERED_MARKERS = tuple(
    dict.fromkeys(
        (
            *AD_CLOSE_MARKERS,
            *HOME_MARKERS,
            *SCRAP_ACTIVITY_MARKERS,
            "skip_button",
            "battle_running_marker",
            "battle_result_popup",
            "chest_open_button",
            "special_chest_page",
            *REWARD_MARKERS,
            *POPUP_MARKERS,
            *FILM_MARKERS,
            "watch_user_*",
            "close_user_*",
            "close_end_*",
        )
    )
)

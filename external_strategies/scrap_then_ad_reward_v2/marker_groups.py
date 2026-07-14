from __future__ import annotations

from cats_automatic.actions import DEFAULT_TAP_MARKER_ALLOW_LIST


AD_CLOSE_MARKERS = tuple(sorted(DEFAULT_TAP_MARKER_ALLOW_LIST))

HOME_MARKERS = (
    "main-definate",
    "home_marker",
    "underground_park_entrance_buttons",
)

SCRAP_ACTIVITY_MARKERS = (
    "scrap_page_marker",
    "scrap_next_button",
    "battle_button",
    "scrap_watch_ad_button",
    "scrap_iron_route_marker",
    "scrap_iron_route_start_buttons",
    "scrap_iron_tournament_marker",
    "ad_bolt_accelerator_marker",
)

REWARD_MARKERS = (
    "reward_confirm_marker",
    "confirm_button",
    "get_reward",
    "claim_buttons",
    "confirm_buttons",
    "right_ad_reward_success_buttons",
    "right_ad_reward_success_marker",
)

POPUP_MARKERS = (
    "error_popup",
    "network_error_popup",
    "retry_button",
    "error_popups",
    "error_buttons",
    "retry_buttons",
    "reconnect_buttons",
)

FILM_MARKERS = (
    "ad_entry",
    "watch_ad_button",
    "watch_ad_film",
    "select_reward_mode",
    "pre_watch_optional",
    "watch_buttons",
    "home_right_ad_buttons",
    "home_right_ad_marker",
)

TOURNAMENT_MARKERS = (
    "tournament_watch_battle_marker",
    "tournament_skip_buttons",
    "tournament_exit_buttons",
    "tank_attack_marke",
    "tank_hp_marker",
    "tournament_battle_result_buttons",
    "tournament_battle_result_marker",
    "tournament_rank_marker1",
    "tournament_rank_marker2",
    "tournament_advance_success_buttons",
    "sticker_select_buttons",
    "sticker_select_marker",
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
            *TOURNAMENT_MARKERS,
            "close_buttons",
            "watch_user_*",
            "close_user_*",
            "close_end_*",
        )
    )
)

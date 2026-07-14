from __future__ import annotations

from .screen_state_types import ScreenStateTemplate


# Paths are resolved relative to this package by screen_state_detector.py.
# The teammate delivery directory is kept as an original asset package.
DEFAULT_TEMPLATE_DIRS = [
    "templates",
    "../scrap_then_ad_reward/templates",
    "../scrap_ad_battle/templates",
    "../../user_templates",
    "../../状态判断文件及状态图片/user_templates",
    "../../状态判断文件及状态图片/page_status_judge_page",
]


def _state(
    state_name: str,
    *,
    required_any: list[str] | None = None,
    required_all: list[str] | None = None,
    exclude_any: list[str] | None = None,
    threshold: float = 0.80,
    priority: int = 0,
    description: str,
) -> ScreenStateTemplate:
    return ScreenStateTemplate(
        state_name=state_name,
        required_any=required_any or [],
        required_all=required_all or [],
        exclude_any=exclude_any or [],
        threshold=threshold,
        priority=priority,
        description=description,
        template_dirs=list(DEFAULT_TEMPLATE_DIRS),
    )


HOME = _state(
    "HOME",
    required_any=["main-definate", "home_marker", "underground_park_entrance_buttons"],
    exclude_any=["error_popup", "error_popups"],
    threshold=0.80,
    priority=40,
    description="home page markers",
)

SCRAP_ENTRY_PAGE = _state(
    "SCRAP_ENTRY_PAGE",
    required_any=[
        "scrap_page_marker",
        "scrap_next_button",
        "scrap_iron_route_marker",
        "scrap_iron_route_start_buttons",
    ],
    exclude_any=[
        "battle_result_popup",
        "skip_button",
        "close_ad",
        "close_user_*",
        "close_end_*",
        "close_buttons",
        "error_popups",
        "error_buttons",
    ],
    threshold=0.80,
    priority=30,
    description="scrap entry page markers",
)

SCRAP_BATTLE_PAGE = _state(
    "SCRAP_BATTLE_PAGE",
    required_any=["battle_button", "scrap_watch_ad_button"],
    exclude_any=["battle_result_popup", "skip_button", "close_ad", "close_user_*", "close_end_*", "close_buttons"],
    threshold=0.80,
    priority=50,
    description="scrap battle page markers",
)

SCRAP_IRON_TOURNAMENT_PAGE = _state(
    "SCRAP_IRON_TOURNAMENT_PAGE",
    required_any=["scrap_iron_tournament_marker"],
    exclude_any=["battle_result_popup", "skip_button", "close_ad", "close_user_*", "close_end_*", "close_buttons"],
    threshold=0.80,
    priority=49,
    description="teammate scrap iron tournament page marker",
)

BATTLE_RUNNING_PAGE = _state(
    "BATTLE_RUNNING_PAGE",
    required_all=["tournament_watch_battle_marker", "tournament_skip_buttons", "tournament_exit_buttons"],
    threshold=0.80,
    priority=48,
    description="teammate battle preparation page; state name preserved",
)

TOURNAMENT_RUNNING_PAGE = _state(
    "TOURNAMENT_RUNNING_PAGE",
    required_all=["tank_attack_marke", "tank_hp_marker"],
    threshold=0.80,
    priority=60,
    description="teammate tournament running page markers",
)

BATTLE_RESULT_PAGE = _state(
    "BATTLE_RESULT_PAGE",
    required_any=["battle_result_popup", "confirm_button"],
    threshold=0.80,
    priority=80,
    description="legacy battle result popup markers",
)

TOURNAMENT_BATTLE_RESULT_PAGE = _state(
    "TOURNAMENT_BATTLE_RESULT_PAGE",
    required_all=["tournament_battle_result_buttons", "tournament_battle_result_marker"],
    threshold=0.80,
    priority=82,
    description="teammate tournament battle result markers",
)

SCRAP_WATCH_AD_PAGE = _state(
    "SCRAP_WATCH_AD_PAGE",
    required_any=["scrap_watch_ad_button"],
    exclude_any=["battle_result_popup", "close_ad", "close_user_*", "close_end_*", "close_buttons"],
    threshold=0.80,
    priority=55,
    description="legacy scrap watch ad button marker",
)

AD_BOLT_ACCELERATOR_PAGE = _state(
    "AD_BOLT_ACCELERATOR_PAGE",
    required_any=["ad_bolt_accelerator_marker"],
    exclude_any=["close_buttons"],
    threshold=0.80,
    priority=55,
    description="teammate ad bolt accelerator page marker; button marker was not delivered",
)

GET_THREE_BOLTS_MARKER = _state(
    "GET_THREE_BOLTS_MARKER",
    required_all=["get_three_bolts_buttons", "get_three_bolts_marker"],
    exclude_any=["close_buttons"],
    threshold=0.80,
    priority=54,
    description="disabled: teammate name preserved, but marker images were not delivered",
)

# This name is preserved even though close_buttons currently means
# the ad close button is visible, not that video playback is still running.
AD_RUNNING_PAGE = _state(
    "AD_RUNNING_PAGE",
    required_any=["close_ad", "close_user_*", "close_end_*", "close_buttons"],
    threshold=0.80,
    priority=90,
    description="ad close controls visible; semantic name kept for compatibility",
)

SPECIAL_CHEST_PAGE = _state(
    "SPECIAL_CHEST_PAGE",
    required_any=["chest_open_button", "special_chest_page", "claim_buttons", "confirm_buttons"],
    threshold=0.80,
    priority=85,
    description="special chest or claim/confirm page markers",
)

FILM_ENTRY_PAGE = _state(
    "FILM_ENTRY_PAGE",
    required_any=["ad_entry"],
    exclude_any=["battle_button", "scrap_watch_ad_button", "battle_result_popup", "close_user_*", "close_end_*"],
    threshold=0.80,
    priority=35,
    description="legacy film entry marker",
)

HOME_RIGHT_AD_PAGE = _state(
    "HOME_RIGHT_AD_PAGE",
    required_all=["home_right_ad_buttons", "home_right_ad_marker"],
    threshold=0.80,
    priority=35,
    description="disabled: overlaps FILM_WATCH_PAGE and should not steal HOME",
)

FILM_WATCH_PAGE = _state(
    "FILM_WATCH_PAGE",
    required_any=[
        "watch_ad_button",
        "watch_user_*",
        "pre_watch_optional",
        "watch_buttons",
        "home_right_ad_buttons",
        "home_right_ad_marker",
    ],
    exclude_any=["close_user_*", "close_end_*", "close_buttons"],
    threshold=0.80,
    priority=65,
    description="film watch/select page markers",
)

REWARD_CONFIRM_PAGE = _state(
    "REWARD_CONFIRM_PAGE",
    required_all=["reward_confirm_marker", "confirm_button"],
    threshold=0.80,
    priority=88,
    description="legacy reward confirmation markers",
)

RIGHT_AD_REWARD_SUCCESS_PAGE = _state(
    "RIGHT_AD_REWARD_SUCCESS_PAGE",
    required_all=["right_ad_reward_success_buttons", "right_ad_reward_success_marker"],
    exclude_any=["close_buttons"],
    threshold=0.80,
    priority=88,
    description="teammate right ad reward success page markers",
)

ERROR_POPUP_PAGE = _state(
    "ERROR_POPUP_PAGE",
    required_any=[
        "error_popup",
        "network_error_popup",
        "retry_button",
        "error_popups",
        "retry_buttons",
        "reconnect_buttons",
        "error_buttons",
    ],
    threshold=0.80,
    priority=95,
    description="error popup or recovery entry markers",
)

TOURNAMENT_PAGE = _state(
    "TOURNAMENT_PAGE",
    required_any=["confirm_buttons", "claim_buttons"],
    exclude_any=["tournament_advance_success_marker", "tournament_advance_success_buttons"],
    threshold=0.80,
    priority=33,
    description="disabled: teammate tournament failed/settlement name preserved, overlaps claim pages",
)

STICKER_SELECT_PAGE = _state(
    "STICKER_SELECT_PAGE",
    required_all=["sticker_select_buttons", "sticker_select_marker"],
    threshold=0.80,
    priority=32,
    description="teammate sticker selection page markers",
)

TOURNAMENT_ADVANCE_SUCCESS_PAGE = _state(
    "TOURNAMENT_ADVANCE_SUCCESS_PAGE",
    required_any=["tournament_advance_success_buttons"],
    threshold=0.80,
    priority=35,
    description="teammate tournament advance success page marker",
)

UNKNOWN = _state(
    "UNKNOWN",
    required_any=[],
    threshold=0.0,
    priority=-1,
    description="fallback unknown page",
)


ENABLED_SCREEN_STATE_TEMPLATES = [
    HOME,
    SCRAP_ENTRY_PAGE,
    SCRAP_BATTLE_PAGE,
    SCRAP_IRON_TOURNAMENT_PAGE,
    BATTLE_RUNNING_PAGE,
    TOURNAMENT_RUNNING_PAGE,
    BATTLE_RESULT_PAGE,
    TOURNAMENT_BATTLE_RESULT_PAGE,
    SCRAP_WATCH_AD_PAGE,
    AD_BOLT_ACCELERATOR_PAGE,
    AD_RUNNING_PAGE,
    SPECIAL_CHEST_PAGE,
    FILM_ENTRY_PAGE,
    FILM_WATCH_PAGE,
    REWARD_CONFIRM_PAGE,
    RIGHT_AD_REWARD_SUCCESS_PAGE,
    ERROR_POPUP_PAGE,
    STICKER_SELECT_PAGE,
    TOURNAMENT_ADVANCE_SUCCESS_PAGE,
    UNKNOWN,
]

DISABLED_SCREEN_STATE_TEMPLATES = {
    GET_THREE_BOLTS_MARKER.state_name: GET_THREE_BOLTS_MARKER,
    HOME_RIGHT_AD_PAGE.state_name: HOME_RIGHT_AD_PAGE,
    TOURNAMENT_PAGE.state_name: TOURNAMENT_PAGE,
}

SCREEN_STATE_TEMPLATES = {
    template.state_name: template
    for template in ENABLED_SCREEN_STATE_TEMPLATES
}

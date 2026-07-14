from __future__ import annotations

from .close_markers import SAFE_CLOSE_MARKER_PATTERNS
from .screen_state_types import ScreenStateTemplate
from .template_sources import (
    ACTION_ONLY_MARKERS,
    V2_CANONICAL_TEMPLATE_DIR_NAMES,
)


DEFAULT_TEMPLATE_DIRS = list(V2_CANONICAL_TEMPLATE_DIR_NAMES)

ACTIVE_STATE_NAMES = frozenset(
    {
        "HOME",
        "FILM_WATCH_PAGE",
        "AD_CLOSE_PAGE",
        "RIGHT_AD_REWARD_SUCCESS_PAGE",
        "ERROR_POPUP_PAGE",
        "UNKNOWN",
    }
)

DISABLED_STATE_NAMES = frozenset(
    {
        "FILM_ENTRY_PAGE",
        "AD_RUNNING_PAGE",
        "REWARD_CONFIRM_PAGE",
        "SCRAP_ENTRY_PAGE",
        "SCRAP_BATTLE_PAGE",
        "SCRAP_IRON_TOURNAMENT_PAGE",
        "BATTLE_RUNNING_PAGE",
        "TOURNAMENT_RUNNING_PAGE",
        "BATTLE_RESULT_PAGE",
        "TOURNAMENT_BATTLE_RESULT_PAGE",
        "SCRAP_WATCH_AD_PAGE",
        "AD_BOLT_ACCELERATOR_PAGE",
        "GET_THREE_BOLTS_MARKER",
        "SPECIAL_CHEST_PAGE",
        "HOME_RIGHT_AD_PAGE",
        "TOURNAMENT_PAGE",
        "STICKER_SELECT_PAGE",
        "TOURNAMENT_ADVANCE_SUCCESS_PAGE",
    }
)


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
    exclude_any=["error_popup", "error_popups", "error_buttons"],
    threshold=0.80,
    priority=40,
    description="home page markers",
)

FILM_WATCH_PAGE = _state(
    "FILM_WATCH_PAGE",
    required_any=[
        "watch_ad_film",
        "watch_ad_button",
        "watch_buttons",
        "watch_user_*",
        "pre_watch_optional",
        "home_right_ad_buttons",
        "home_right_ad_marker",
    ],
    exclude_any=[
        *SAFE_CLOSE_MARKER_PATTERNS,
        "right_ad_reward_success_buttons",
        "right_ad_reward_success_marker",
    ],
    threshold=0.80,
    priority=65,
    description="film watch/select page markers",
)

AD_CLOSE_PAGE = _state(
    "AD_CLOSE_PAGE",
    required_any=list(SAFE_CLOSE_MARKER_PATTERNS),
    exclude_any=[
        "right_ad_reward_success_buttons",
        "right_ad_reward_success_marker",
        "error_popup",
        "error_popups",
    ],
    threshold=0.80,
    priority=90,
    description="ad close controls visible; safe close decision may run",
)

RIGHT_AD_REWARD_SUCCESS_PAGE = _state(
    "RIGHT_AD_REWARD_SUCCESS_PAGE",
    required_any=["get_reward", "right_ad_reward_success_buttons", "right_ad_reward_success_marker"],
    threshold=0.78,
    priority=88,
    description="right-side ad reward success page markers",
)

ERROR_POPUP_PAGE = _state(
    "ERROR_POPUP_PAGE",
    required_any=[
        "error_popup",
        "network_error_popup",
        "error_popups",
    ],
    threshold=0.80,
    priority=95,
    description="error popup or recovery entry markers",
)

UNKNOWN = _state(
    "UNKNOWN",
    required_any=[],
    threshold=0.0,
    priority=-1,
    description="fallback unknown page",
)

_ALL_STATE_TEMPLATES = {
    template.state_name: template
    for template in (
        HOME,
        FILM_WATCH_PAGE,
        AD_CLOSE_PAGE,
        RIGHT_AD_REWARD_SUCCESS_PAGE,
        ERROR_POPUP_PAGE,
        UNKNOWN,
    )
}

SCREEN_STATE_TEMPLATES = {
    name: template
    for name, template in _ALL_STATE_TEMPLATES.items()
    if name in ACTIVE_STATE_NAMES
}

DISABLED_SCREEN_STATE_TEMPLATES = {
    name: _state(
        name,
        required_any=[],
        threshold=0.0,
        priority=-100,
        description="disabled legacy v2 state; retained only for migration notes",
    )
    for name in sorted(DISABLED_STATE_NAMES)
}


def validate_active_state_templates() -> None:
    unknown_active = set(SCREEN_STATE_TEMPLATES) - set(ACTIVE_STATE_NAMES)
    if unknown_active:
        raise ValueError(f"SCREEN_STATE_TEMPLATES contains inactive states: {sorted(unknown_active)}")

    for template in SCREEN_STATE_TEMPLATES.values():
        required = set(template.required_any) | set(template.required_all)
        illegal = sorted(required & set(ACTION_ONLY_MARKERS))
        if illegal:
            raise ValueError(
                f"State {template.state_name} uses action-only marker(s): {illegal}"
            )


validate_active_state_templates()

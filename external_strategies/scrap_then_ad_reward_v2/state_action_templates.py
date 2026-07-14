from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .screen_state_types import ScreenStateResult


def _no_action(screen_state_result: ScreenStateResult, message: str) -> dict[str, Any]:
    return {
        "decision": "no_action",
        "reason": "state_action_template_only",
        "screen_state": screen_state_result.state_name,
        "message": message,
    }


def handle_home_state(context: Any, screen_state_result: ScreenStateResult) -> dict[str, Any]:
    return _no_action(screen_state_result, "home is recognized; flow layer decides whether to enter film")


def handle_film_watch_page_state(context: Any, screen_state_result: ScreenStateResult) -> dict[str, Any]:
    return _no_action(screen_state_result, "film watch page is recognized; flow layer chooses watch action")


def handle_ad_close_page_state(context: Any, screen_state_result: ScreenStateResult) -> dict[str, Any]:
    return _no_action(screen_state_result, "ad close marker observed; flow layer must choose safe close marker")


def handle_reward_success_page_state(context: Any, screen_state_result: ScreenStateResult) -> dict[str, Any]:
    return _no_action(screen_state_result, "reward success page is recognized; flow layer returns home")


def handle_error_popup_page_state(context: Any, screen_state_result: ScreenStateResult) -> dict[str, Any]:
    return _no_action(screen_state_result, "error popup is recognized; recovery layer decides next action")


def handle_unknown_state(context: Any, screen_state_result: ScreenStateResult) -> dict[str, Any]:
    return _no_action(screen_state_result, "unknown page; wait or recovery should be decided by flow layer")


STATE_ACTION_HANDLERS: dict[str, Callable[[Any, ScreenStateResult], dict[str, Any]]] = {
    "HOME": handle_home_state,
    "FILM_WATCH_PAGE": handle_film_watch_page_state,
    "AD_CLOSE_PAGE": handle_ad_close_page_state,
    "RIGHT_AD_REWARD_SUCCESS_PAGE": handle_reward_success_page_state,
    "ERROR_POPUP_PAGE": handle_error_popup_page_state,
    "UNKNOWN": handle_unknown_state,
}


def handle_screen_state(context: Any, screen_state_result: ScreenStateResult) -> dict[str, Any]:
    handler = STATE_ACTION_HANDLERS.get(screen_state_result.state_name, handle_unknown_state)
    return handler(context, screen_state_result)

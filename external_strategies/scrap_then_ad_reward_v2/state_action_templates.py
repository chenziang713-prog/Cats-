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
    """主页动作模板。

    后续可以根据 flow_state 选择进入废铁或胶卷入口；禁止仅凭主页识别结果直接点击。
    例如同样是 HOME，可能是准备开始废铁，也可能是废铁结束后准备进入胶卷。
    """

    return _no_action(screen_state_result, "当前只是主页动作模板，尚未接管真实点击")


def handle_scrap_entry_page_state(context: Any, screen_state_result: ScreenStateResult) -> dict[str, Any]:
    """废铁入口页动作模板。

    后续允许在正确 flow_state 下点击废铁下一步；禁止在返回主页阶段继续深入废铁页。
    """

    return _no_action(screen_state_result, "当前只是废铁入口页动作模板，尚未接管真实点击")


def handle_scrap_battle_page_state(context: Any, screen_state_result: ScreenStateResult) -> dict[str, Any]:
    """废铁对战页动作模板。

    如果 flow_state 是 WAIT_BATTLE_BUTTON，可以点击 battle_button。
    如果 flow_state 是 RETURN_HOME_AFTER_SCRAP，不能点击 battle_button，应该小退回主页。
    所以单靠 screen_state 不能决定动作，后面必须结合 flow_state。
    """

    return _no_action(screen_state_result, "当前只是废铁对战页动作模板，尚未接管真实点击")


def handle_battle_running_page_state(context: Any, screen_state_result: ScreenStateResult) -> dict[str, Any]:
    """战斗运行页动作模板。

    后续可能允许等待或点击跳过；是否跳过必须由流程状态和安全策略共同决定。
    """

    return _no_action(screen_state_result, "当前只是战斗运行页动作模板，尚未接管真实点击")


def handle_battle_result_page_state(context: Any, screen_state_result: ScreenStateResult) -> dict[str, Any]:
    """战斗结果页动作模板。

    后续可以在等待战斗结果的 flow_state 下点击确认；禁止在广告关闭阶段误点确认。
    """

    return _no_action(screen_state_result, "当前只是战斗结果页动作模板，尚未接管真实点击")


def handle_scrap_watch_ad_page_state(context: Any, screen_state_result: ScreenStateResult) -> dict[str, Any]:
    """废铁看广告页动作模板。

    后续只有在废铁奖励流程允许时才可点击 scrap_watch_ad_button；其他阶段应等待或返回。
    """

    return _no_action(screen_state_result, "当前只是废铁看广告页动作模板，尚未接管真实点击")


def handle_ad_running_page_state(context: Any, screen_state_result: ScreenStateResult) -> dict[str, Any]:
    """广告播放页动作模板。

    后续允许在广告阶段点击 close_ad/close_user/close_end；禁止非广告阶段误关页面。
    连续关闭次数限制仍应由流程控制层或动作执行层维护。
    """

    return _no_action(screen_state_result, "当前只是广告播放页动作模板，尚未接管真实点击")


def handle_ad_close_page_state(context: Any, screen_state_result: ScreenStateResult) -> dict[str, Any]:
    return _no_action(screen_state_result, "ad close marker observed; flow layer must choose any safe close action")


def handle_special_chest_page_state(context: Any, screen_state_result: ScreenStateResult) -> dict[str, Any]:
    """特殊宝箱页动作模板。

    后续可能允许打开或关闭宝箱；具体动作必须结合 flow_state 判断是否来自废铁广告结束。
    """

    return _no_action(screen_state_result, "当前只是特殊宝箱页动作模板，尚未接管真实点击")


def handle_film_entry_page_state(context: Any, screen_state_result: ScreenStateResult) -> dict[str, Any]:
    """胶卷入口页动作模板。

    后续可以在胶卷阶段点击 ad_entry；如果当前流程仍在废铁回主页阶段，则禁止进入胶卷。
    """

    return _no_action(screen_state_result, "当前只是胶卷入口页动作模板，尚未接管真实点击")


def handle_film_watch_page_state(context: Any, screen_state_result: ScreenStateResult) -> dict[str, Any]:
    """胶卷观看页动作模板。

    后续可以点击 watch_ad_button 或用户自定义 watch_user_*；是否允许要结合 flow_state。
    """

    return _no_action(screen_state_result, "当前只是胶卷观看页动作模板，尚未接管真实点击")


def handle_reward_confirm_page_state(context: Any, screen_state_result: ScreenStateResult) -> dict[str, Any]:
    """奖励确认页动作模板。

    后续可在奖励确认阶段点击 confirm_button；禁止把普通确认按钮当作任意状态通用动作。
    """

    return _no_action(screen_state_result, "当前只是奖励确认页动作模板，尚未接管真实点击")


def handle_error_popup_page_state(context: Any, screen_state_result: ScreenStateResult) -> dict[str, Any]:
    """错误弹窗页动作模板。

    后续应交给恢复层处理重试、关闭或暂停；第一阶段不做真实恢复动作。
    """

    return _no_action(screen_state_result, "当前只是错误弹窗页动作模板，尚未接管真实点击")


def handle_unknown_state(context: Any, screen_state_result: ScreenStateResult) -> dict[str, Any]:
    """未知页动作模板。

    后续通常只能等待、截图记录或进入恢复层；禁止在 UNKNOWN 状态下盲点。
    """

    return _no_action(screen_state_result, "当前只是未知页动作模板，尚未接管真实点击")


STATE_ACTION_HANDLERS: dict[str, Callable[[Any, ScreenStateResult], dict[str, Any]]] = {
    "HOME": handle_home_state,
    "SCRAP_ENTRY_PAGE": handle_scrap_entry_page_state,
    "SCRAP_BATTLE_PAGE": handle_scrap_battle_page_state,
    "BATTLE_RUNNING_PAGE": handle_battle_running_page_state,
    "BATTLE_RESULT_PAGE": handle_battle_result_page_state,
    "SCRAP_WATCH_AD_PAGE": handle_scrap_watch_ad_page_state,
    "AD_RUNNING_PAGE": handle_ad_running_page_state,
    "AD_CLOSE_PAGE": handle_ad_close_page_state,
    "SPECIAL_CHEST_PAGE": handle_special_chest_page_state,
    "FILM_ENTRY_PAGE": handle_film_entry_page_state,
    "FILM_WATCH_PAGE": handle_film_watch_page_state,
    "REWARD_CONFIRM_PAGE": handle_reward_confirm_page_state,
    "ERROR_POPUP_PAGE": handle_error_popup_page_state,
    "UNKNOWN": handle_unknown_state,
}


def handle_screen_state(context: Any, screen_state_result: ScreenStateResult) -> dict[str, Any]:
    handler = STATE_ACTION_HANDLERS.get(screen_state_result.state_name, handle_unknown_state)
    return handler(context, screen_state_result)

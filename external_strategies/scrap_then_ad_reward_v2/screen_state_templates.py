from __future__ import annotations

from .screen_state_types import ScreenStateTemplate


DEFAULT_TEMPLATE_DIRS = [
    "templates",
    "../scrap_then_ad_reward/templates",
    "../scrap_ad_battle/templates",
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


# 主页：通常能看到废铁入口或胶卷广告入口，不能同时出现废铁页内部按钮。
HOME = _state(
    "HOME",
    required_any=["main-definate"],
    exclude_any=[
        "error_popup",
    ],
    threshold=0.80,
    priority=40,
    description="主页，通常能看到废铁入口和胶卷入口",
)

# 废铁入口页：从主页进入废铁流程后的第一页，通常能看到废铁页标志或下一步按钮。
SCRAP_ENTRY_PAGE = _state(
    "SCRAP_ENTRY_PAGE",
    required_any=["scrap_page_marker", "scrap_next_button"],
    exclude_any=["battle_result_popup", "skip_button", "close_ad", "close_user_*", "close_end_*"],
    threshold=0.80,
    priority=30,
    description="废铁入口页，通常能看到废铁页面标志或下一步按钮",
)

# 废铁对战页：能看到对战按钮或废铁看广告按钮。
SCRAP_BATTLE_PAGE = _state(
    "SCRAP_BATTLE_PAGE",
    required_any=["battle_button", "scrap_watch_ad_button"],
    exclude_any=["battle_result_popup", "skip_button", "close_ad", "close_user_*", "close_end_*"],
    threshold=0.80,
    priority=50,
    description="废铁对战页，能看到对战按钮或废铁看广告按钮",
)

# 战斗运行页：废铁战斗进行中，可能出现跳过按钮或战斗中标志。
BATTLE_RUNNING_PAGE = _state(
    "BATTLE_RUNNING_PAGE",
    required_any=["skip_button", "battle_running_marker"],
    exclude_any=["battle_result_popup", "close_ad", "close_user_*", "close_end_*"],
    threshold=0.80,
    priority=60,
    description="战斗运行页，通常能看到跳过按钮或战斗中标志",
)

# 战斗结果页：战斗结束后的结果弹窗，优先级高于普通废铁页面。
BATTLE_RESULT_PAGE = _state(
    "BATTLE_RESULT_PAGE",
    required_any=["battle_result_popup", "confirm_button"],
    threshold=0.80,
    priority=80,
    description="战斗结果弹窗页面",
)

# 废铁看广告页：废铁流程里等待点击看广告的页面。
SCRAP_WATCH_AD_PAGE = _state(
    "SCRAP_WATCH_AD_PAGE",
    required_any=["scrap_watch_ad_button"],
    exclude_any=["battle_result_popup", "close_ad", "close_user_*", "close_end_*"],
    threshold=0.80,
    priority=55,
    description="废铁看广告入口页，能看到废铁看广告按钮",
)

# 广告播放页：广告播放或可关闭广告页面，任何关闭标志都应优先识别。
AD_RUNNING_PAGE = _state(
    "AD_RUNNING_PAGE",
    required_any=["close_ad", "close_user_*", "close_end_*"],
    threshold=0.80,
    priority=90,
    description="广告播放或广告关闭页面",
)

# 特殊宝箱页：废铁广告结束后可能出现的特殊货箱或宝箱页面。
SPECIAL_CHEST_PAGE = _state(
    "SPECIAL_CHEST_PAGE",
    required_any=["chest_open_button", "special_chest_page"],
    threshold=0.80,
    priority=85,
    description="废铁广告结束后可能出现的特殊货箱/宝箱页面",
)

# 胶卷入口页：主页或胶卷区域里可进入胶卷广告奖励的页面。
FILM_ENTRY_PAGE = _state(
    "FILM_ENTRY_PAGE",
    required_any=["ad_entry"],
    exclude_any=["battle_button", "scrap_watch_ad_button", "battle_result_popup", "close_user_*", "close_end_*"],
    threshold=0.80,
    priority=35,
    description="胶卷入口页，通常能看到胶卷广告入口",
)

# 胶卷观看页：进入胶卷奖励后等待点击观看广告的页面。
FILM_WATCH_PAGE = _state(
    "FILM_WATCH_PAGE",
    required_any=["watch_ad_button", "watch_user_*", "pre_watch_optional"],
    exclude_any=["close_user_*", "close_end_*"],
    threshold=0.80,
    priority=65,
    description="胶卷观看页，通常能看到观看广告按钮或观看前可选按钮",
)

# 奖励确认页：广告奖励已到达确认弹窗。
REWARD_CONFIRM_PAGE = _state(
    "REWARD_CONFIRM_PAGE",
    required_all=["reward_confirm_marker", "confirm_button"],
    threshold=0.80,
    priority=88,
    description="奖励确认页面，通常能看到奖励确认标志或确认按钮",
)

# 错误弹窗页：识别到错误弹窗或异常恢复入口。
ERROR_POPUP_PAGE = _state(
    "ERROR_POPUP_PAGE",
    required_any=["error_popup", "network_error_popup", "retry_button"],
    threshold=0.80,
    priority=95,
    description="错误弹窗页面，需要后续恢复层处理",
)

# 未知页：兜底状态，不依赖模板命中。
UNKNOWN = _state(
    "UNKNOWN",
    required_any=[],
    threshold=0.0,
    priority=-1,
    description="未知页面，当前模板无法可信判断",
)


SCREEN_STATE_TEMPLATES = {
    template.state_name: template
    for template in [
        HOME,
        SCRAP_ENTRY_PAGE,
        SCRAP_BATTLE_PAGE,
        BATTLE_RUNNING_PAGE,
        BATTLE_RESULT_PAGE,
        SCRAP_WATCH_AD_PAGE,
        AD_RUNNING_PAGE,
        SPECIAL_CHEST_PAGE,
        FILM_ENTRY_PAGE,
        FILM_WATCH_PAGE,
        REWARD_CONFIRM_PAGE,
        ERROR_POPUP_PAGE,
        UNKNOWN,
    ]
}

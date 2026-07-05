"""废铁 + 胶卷广告 v2 状态识别入口。

第一阶段只提供界面状态识别和动作模板，不接管真实点击流程。
"""

from .screen_state_detector import (
    detect_current_screen_state,
    detect_current_screen_state_from_detections,
    explain_screen_state_result,
)
from .screen_state_templates import SCREEN_STATE_TEMPLATES

__all__ = [
    "SCREEN_STATE_TEMPLATES",
    "detect_current_screen_state",
    "detect_current_screen_state_from_detections",
    "explain_screen_state_result",
]

from __future__ import annotations

from typing import Any

from .screen_state_detector import (
    detect_current_screen_state,
    detect_current_screen_state_from_detections,
    explain_screen_state_result,
)
from .screen_state_templates import SCREEN_STATE_TEMPLATES
from .screen_state_types import ScreenStateResult
from .state_action_templates import handle_screen_state


def debug_detect_screen_state(context: Any = None, detections: Any = None) -> dict[str, Any]:
    """调试入口：识别当前界面并返回动作模板建议。

    第一阶段只读 context/detections，不真实点击、不改变旧 runner 的执行流程。
    """

    current_detections = detections
    if current_detections is None and context is not None:
        current_detections = getattr(context, "detections", {})
    screen_state = detect_current_screen_state_from_detections(current_detections or {})
    action_template = handle_screen_state(context, screen_state)
    return {
        "screen_state": screen_state.state_name,
        "confidence": screen_state.confidence,
        "matched_markers": screen_state.matched_markers,
        "excluded_markers": screen_state.excluded_markers,
        "explanation": explain_screen_state_result(screen_state),
        "action_template": action_template,
    }


def decide_next_action(
    flow_state: str | None,
    screen_state_result: ScreenStateResult,
    context: Any = None,
) -> dict[str, Any]:
    """预留接口：后续组合 flow_state 和 screen_state 决定下一步动作。

    screen_state 是“眼睛”，负责判断画面。
    flow_state 是“流程记忆”，负责判断当前允许做什么。
    同一个 screen_state 在不同 flow_state 下动作可能完全不同。
    第一阶段暂不实现真实点击，只返回 no_action。
    """

    return {
        "decision": "no_action",
        "reason": "flow_controller_not_implemented_yet",
        "flow_state": flow_state,
        "screen_state": screen_state_result.state_name,
    }


def decide_next_action_v2(context: Any, flow_state: str | None = None) -> dict[str, Any]:
    """薄入口：从 context.detections 识别界面，再交给预留流程控制接口。"""

    screen_state = detect_current_screen_state_from_detections(getattr(context, "detections", {}))
    return decide_next_action(flow_state, screen_state, context)


def run_strategy_v2(context: Any) -> dict[str, Any]:
    """显式 v2 调试入口。

    该入口只返回 no_action 调试结构，避免第一阶段替换现有正式执行流程。
    """

    debug_result = debug_detect_screen_state(context)
    debug_result["decision"] = "no_action"
    debug_result["reason"] = "v2_debug_only_no_real_click"
    return debug_result


__all__ = [
    "SCREEN_STATE_TEMPLATES",
    "debug_detect_screen_state",
    "decide_next_action",
    "decide_next_action_v2",
    "detect_current_screen_state",
    "detect_current_screen_state_from_detections",
    "run_strategy_v2",
]

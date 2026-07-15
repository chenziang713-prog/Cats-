from __future__ import annotations

from collections.abc import Mapping

from .strategy_base import DetectionResult, StrategyDecision


TARGET_NAMES = {
    "scrap_entry": "废铁入口",
    "scrap_next_button": "废铁下一步按钮",
    "battle_button": "对战按钮",
    "skip_button": "跳过按钮",
    "battle_result_popup": "战斗结果弹窗",
    "confirm_button": "确认按钮",
    "scrap_watch_ad_button": "废铁看广告按钮",
    "ad_entry": "胶卷广告入口",
    "page_marker": "胶卷页面标记",
    "watch_ad_button": "胶卷看广告按钮",
    "reward_confirm_marker": "奖励确认标记",
}

DECISION_NAMES = {
    "click_battle_result_confirm": "点击战斗结果确认按钮",
    "adb_back_battle_result": "小退关闭战斗结果弹窗",
    "adb_back_to_home_after_scrap": "小退返回主页",
    "problem_recovery_adb_back": "异常恢复小退",
    "close_ad": "点击广告关闭按钮",
    "click_ad_entry": "点击胶卷广告入口",
    "click_watch_ad_button": "点击胶卷看广告按钮",
    "click_scrap_watch_ad_button": "点击废铁看广告按钮",
    "confirm_reward": "点击奖励确认",
    "wait": "等待",
    "stop": "停止",
}

REASON_NAMES = {
    "wait_not_on_target_page": "不在目标页面",
    "wait_close_ad_not_found_after_ad_wait": "广告关闭按钮未出现",
    "wait_close_ad_not_found": "广告关闭按钮未出现",
    "close_ad_candidate_below_threshold_after_ad_wait": "检测到关闭按钮候选但置信度不足",
    "close_ad_detected_before_ad_stage_ignored": "非广告阶段检测到关闭按钮，已忽略",
    "max_back_to_home_attempts_reached": "返回主页小退次数已达上限",
    "global_stall_detected": "检测到长期无进展",
}

DECISION_NAMES.update({
    "tap_marker": "点击目标",
    "press_back": "按返回键",
})

REASON_NAMES.update({
    "pending_effect_waiting_for_confirmation": "已发送动作，等待页面确认",
    "pending_effect_duplicate_blocked": "已拦截重复动作",
    "post_ad_network_flashback": "广告结束后页面网络回闪，保持当前阶段等待奖励页",
})


def target_name_cn(name: str) -> str:
    if name.startswith("close_user_") or name.startswith("close_end_") or name == "close_ad":
        return "广告关闭按钮"
    return TARGET_NAMES.get(name, name)


def detection_summary(loop_index: int, detections: Mapping[str, DetectionResult]) -> str | None:
    important = []
    for name, detection in detections.items():
        if name in TARGET_NAMES or name.startswith("close_"):
            important.append(f"{target_name_cn(name)} {detection.confidence:.3f}")
    if not important:
        return None
    return f"[循环 {loop_index}] 检测到：" + "，".join(important)


def decision_summary(loop_index: int, decision: StrategyDecision) -> str:
    name = decision.action_name or decision.kind
    if decision.kind == "wait":
        reason = REASON_NAMES.get(decision.reason, decision.reason or "等待下一轮识别")
        return f"[循环 {loop_index}] 等待：{reason}"
    if decision.kind == "stop":
        return f"[循环 {loop_index}] 停止：{REASON_NAMES.get(decision.reason, decision.reason)}"
    return f"[循环 {loop_index}] 执行：{DECISION_NAMES.get(name, name)}"


def state_change_summary(loop_index: int, old_state: object, new_state: object) -> str:
    return f"[循环 {loop_index}] 阶段：{old_state or '开始'} → {new_state}"


def ignored_close_summary(loop_index: int, confidence: object) -> str:
    suffix = "" if confidence is None else f" {float(confidence):.3f}"
    return f"[循环 {loop_index}] 忽略：非广告阶段检测到关闭按钮候选{suffix}，未点击"


def recovery_summary(loop_index: int, reason: str) -> str:
    return f"[循环 {loop_index}] 可疑：{REASON_NAMES.get(reason, reason)}，启动异常恢复"

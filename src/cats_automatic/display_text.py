from __future__ import annotations

DECISION_LABELS = {
    "wait": "等待", "stop": "停止", "click_scrap_entry": "点击废铁入口",
    "click_scrap_next_button": "点击废铁下一步", "click_battle_button": "点击对战按钮",
    "click_skip_button": "点击跳过按钮", "click_battle_result_confirm": "点击战斗结果确认",
    "click_scrap_watch_ad_button": "点击废铁看广告按钮",
    "skip_scrap_ad_due_to_cooldown": "废铁广告冷却，跳过废铁广告",
    "close_ad": "点击广告关闭按钮", "adb_back_to_home_after_scrap": "小退返回主页",
    "problem_recovery_adb_back": "异常恢复小退", "error_popup_recovery_click": "点击错误弹窗按钮",
    "error_popup_recovery_wait": "等待错误弹窗恢复", "error_popup_recovery_failed": "错误弹窗恢复失败",
    "click_ad_entry": "点击胶卷广告入口", "click_film_ad_entry": "点击胶卷广告入口",
    "click_watch": "点击胶卷看广告按钮", "click_watch_ad_button": "点击看广告按钮",
    "confirm_reward": "点击奖励确认", "click_reward_confirm": "点击奖励确认",
    "cycle_completed": "本轮完成", "scrap_then_ad_reward_completed": "废铁+胶卷流程完成",
    "dry_run_click": "模拟点击", "adb_back_battle_popup": "小退关闭战斗弹窗",
    "adb_back_battle_result": "小退关闭战斗结果", "wait_close_limit_reached": "广告关闭等待达到限制",
    "max_actions_limit_reached": "达到最大动作限制", "license_failed_stop": "授权失败，停止运行",
}

TARGET_LABELS = {
    "scrap_entry": "废铁入口", "scrap_page_marker": "废铁页面标记",
    "scrap_next_button": "废铁下一步按钮", "battle_button": "对战按钮",
    "skip_button": "跳过按钮", "battle_result_popup": "战斗结果弹窗",
    "confirm_button": "确认按钮", "scrap_watch_ad_button": "废铁看广告按钮",
    "scrap_watch_cooldown": "废铁广告冷却提示", "ad_entry": "胶卷广告入口",
    "page_marker": "胶卷广告页面标记", "watch_ad_button": "看广告按钮",
    "close_ad": "广告关闭按钮", "close_end_1": "广告关闭按钮",
    "close_end_2": "广告关闭按钮", "close_end_3": "广告关闭按钮",
    "close_end_4": "广告关闭按钮", "reward_confirm_marker": "奖励确认页面",
    "error_popup": "错误弹窗", "error_button": "错误弹窗按钮", "home_marker": "主页标记",
}

PHASE_LABELS = {
    "home": "主页", "enter_scrap_page": "进入废铁页面",
    "wait_scrap_next_button": "等待废铁下一步按钮", "wait_battle_button": "等待对战按钮",
    "battle_button_clicked": "已点击对战按钮", "skip_1": "第一次跳过", "skip_2": "第二次跳过",
    "battle_wait": "等待战斗结果", "wait_battle_result_popup": "等待战斗结果弹窗",
    "battle_result_handled": "战斗结果已处理", "wait_scrap_watch_ad_button": "等待废铁看广告按钮",
    "scrap_watch_ad_clicked": "已点击废铁看广告", "ad_wait": "等待广告播放",
    "scrap_ad_running": "废铁广告播放中", "scrap_ad_closing": "关闭废铁广告",
    "return_home_after_scrap": "废铁后返回主页", "home_detected_after_scrap": "废铁后已回到主页",
    "film_ad_reward_phase": "胶卷广告流程", "film_ad_entry_clicked": "已点击胶卷广告入口",
    "film_ad_running": "胶卷广告播放中", "film_ad_closing": "关闭胶卷广告",
    "film_reward_confirm": "胶卷奖励确认", "cycle_completed": "本轮完成",
}

REASON_LABELS = {
    "click_scrap_entry": "点击废铁入口", "click_scrap_next_button": "点击废铁下一步",
    "click_battle_button": "点击对战按钮", "click_skip_button": "点击跳过按钮",
    "battle_result_popup_confirm_button_detected": "检测到战斗结果确认按钮",
    "click_scrap_watch_ad_button": "点击废铁看广告按钮",
    "scrap_watch_ad_button_cooldown_detected": "废铁看广告按钮处于冷却状态",
    "close_ad_detected_ad_stage": "广告阶段检测到关闭按钮",
    "close_ad_candidate_below_threshold_after_ad_wait": "检测到关闭按钮候选，但置信度不足",
    "close_ad_detected_before_ad_stage_ignored": "非广告阶段检测到关闭按钮候选，已忽略",
    "home_detected_after_scrap": "已检测到主页，准备进入胶卷广告流程",
    "same_state_stall_seconds": "同一阶段停留过久，触发异常恢复",
    "max_recovery_attempts_per_cycle_reached": "本轮异常恢复次数已达上限",
    "error_popup_not_detected": "未检测到错误弹窗", "stop_file": "检测到停止文件，停止运行",
    "license_cache_missing": "未找到本地授权缓存", "dev_bypass_env_missing": "未开启开发测试卡密环境变量",
}
for index in (1, 2, 3):
    REASON_LABELS[f"miss_count_{index}_waiting_scrap_watch_ad_button"] = (
        f"第 {index} 次未识别到废铁看广告按钮，继续等待" if index < 3 else "多次未识别到废铁看广告按钮，准备恢复"
    )
    REASON_LABELS[f"miss_count_{index}_waiting_home_after_scrap"] = (
        f"第 {index} 次未识别到主页，继续等待" if index < 3 else "多次未识别到主页，执行小退返回主页"
    )

ACTION_TYPE_LABELS = {"dry_run_click": "模拟点击", "adb_tap": "真实点击", "wait": "等待", "stop": "停止", "state_transition": "状态转换"}

DECISION_LABELS.update({
    "no_action": "无需操作",
    "tap_marker": "模拟点击目标",
    "press_back": "返回",
    "cycle_completed": "流程完成",
})

TARGET_LABELS.update({
    "main-definate": "主页标记",
    "watch_ad_film": "胶卷看广告按钮",
    "watch_buttons": "看广告按钮",
    "close_buttons": "广告关闭按钮",
    "get_reward": "领取奖励按钮",
    "right_ad_reward_success_buttons": "奖励成功按钮",
    "right_ad_reward_success_marker": "奖励成功页面",
    "error_buttons": "错误弹窗按钮",
    "retry_buttons": "重试按钮",
    "reconnect_buttons": "重新连接按钮",
    "home_right_ad_buttons": "主页右侧广告按钮",
    "home_right_ad_marker": "主页右侧广告页面",
    "pre_watch_optional": "观看前可选按钮",
})

PHASE_LABELS.update({
    "START": "开始",
    "GO_HOME": "确认主页",
    "ENTER_FILM": "进入胶卷活动",
    "SELECT_REWARD": "选择奖励",
    "START_AD": "开始广告",
    "WATCH_AD": "等待广告播放",
    "CLOSE_AD_DOING": "关闭广告中",
    "CLAIM_REWARD": "领取奖励",
    "RETURN_HOME": "返回主页",
    "FINISH": "流程完成",
    "HOME": "主页",
    "HOME_PAGE": "主页",
    "FILM_WATCH_PAGE": "胶卷广告页面",
    "AD_CLOSE_PAGE": "广告关闭页面",
    "RIGHT_AD_REWARD_SUCCESS_PAGE": "奖励成功页面",
    "UNKNOWN": "未知页面",
    "UNKNOWN_PAGE": "未知页面",
    "LOADING_PAGE": "加载中",
    "ERROR_POPUP_PAGE": "错误弹窗",
})

REASON_LABELS.update({
    "film_flow_start": "初始化胶卷流程",
    "home_ready_for_film_entry": "主页已确认，准备进入胶卷",
    "film_entry_marker_selected": "选择胶卷入口",
    "film_entry_marker_not_found": "未找到胶卷入口，继续等待",
    "film_watch_page_confirmed": "已进入胶卷广告页面",
    "optional_reward_marker_not_found": "未找到可选奖励，继续看广告",
    "watch_ad_film_marker_selected": "选择看广告按钮",
    "watch_ad_film_marker_not_found": "未找到看广告按钮，继续等待",
    "wait_for_ad_close_marker": "等待广告播放或关闭按钮出现",
    "close_ad_marker_selected": "选择安全关闭按钮",
    "no_safe_close_ad_marker": "未找到安全关闭按钮",
    "close_ad_attempt_limit": "关闭广告尝试达到上限",
    "reward_page_confirmed_after_ad_close": "关闭广告后已确认奖励页",
    "reward_success_press_back": "奖励页受控返回",
    "reward_success_press_back_retry": "奖励页再次受控返回",
    "reward_already_returned_home": "奖励后已回到主页",
    "already_home_after_ad_close": "关闭广告后已在主页",
    "wait_after_ad_close": "等待关闭广告后的页面变化",
    "wait_for_home_after_reward": "等待回到主页",
    "film_reward_flow_finished_home": "主页确认，流程完成",
    "flow_finished": "流程完成",
    "recovery_level_1_wait": "恢复等待",
    "recovery_level_2_press_back": "恢复返回",
})


def to_display_decision(value: str) -> str:
    return DECISION_LABELS.get(value, f"未翻译决策：{value}" if value else "等待下一次识别结果")

def to_display_target(value: str) -> str:
    if value.startswith("close_user_"):
        return "广告关闭按钮"
    if value.startswith("error_popup_screenshot_"):
        return "错误弹窗"
    if value.startswith("error_button_screenshot_"):
        return "错误弹窗按钮"
    return TARGET_LABELS.get(value, f"未翻译目标：{value}" if value else "暂无目标")

def to_display_reason(value: str) -> str:
    return REASON_LABELS.get(value, f"其他原因：{value}" if value else "等待下一次识别结果")

def to_display_phase(value: str) -> str:
    return PHASE_LABELS.get(value, f"未翻译阶段：{value}" if value else "等待阶段信息")

def to_display_action_type(value: str) -> str:
    return ACTION_TYPE_LABELS.get(value, f"其他动作：{value}" if value else "等待")

def format_decision_panel_row(record: dict[str, object]) -> dict[str, str]:
    return {
        "decision": to_display_decision(str(record.get("decision") or record.get("chosen_decision") or "")),
        "target": to_display_target(str(record.get("target_name") or "")),
        "reason": to_display_reason(str(record.get("reason") or "")),
        "phase": to_display_phase(str(record.get("current_phase") or record.get("state") or "")),
        "action_type": to_display_action_type(str(record.get("action_type") or "")),
    }

from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

from .runtime_paths import watch_button_templates_dir
from .runtime_paths import error_button_templates_dir, error_popup_templates_dir


def generate_diagnosis(
    *,
    strategy_name: str,
    click_records_path: Path,
    events_path: Path,
    phase_journal_path: Path | None = None,
    total_loops: int,
    total_clicks: int,
    total_cycles_completed: int,
    stop_reason: str,
) -> str:
    rows = _read_csv(click_records_path)
    events = _read_events(events_path)
    phase_rows = _read_events(phase_journal_path) if phase_journal_path is not None else []
    reasons = Counter(str(row.get("reason", "")) for row in rows)
    event_names = Counter(str(event.get("event", "")) for event in events)
    decisions = Counter(str(row.get("decision", "")) for row in rows)
    problems: list[str] = []
    suggestions: list[str] = []

    battle_confirmed = decisions["click_battle_result_confirm"] > 0 or decisions["adb_back_battle_result"] > 0
    watch_blocked_after_battle = reasons["watch_ad_detected_before_battle_complete_ignored"] > 0
    scrap_watch_clicked = decisions["click_scrap_watch_ad_button"] > 0
    close_executed = any(
        row.get("decision") == "close_ad" and row.get("result") == "executed"
        for row in rows
    )
    returned_home = event_names["return_home_after_scrap_started"] > 0
    film_started = event_names["film_ad_reward_started"] > 0
    cooldown_skipped = event_names["scrap_watch_ad_cooldown_detected"] > 0
    film_phase_without_source = any(
        row.get("current_phase") == "film_ad_reward_phase"
        and row.get("film_ad_reward_started") is True
        and row.get("current_ad_source") in {None, "", "none"}
        for row in phase_rows
    )
    close_waits = [
        row for row in rows
        if row.get("reason") == "close_ad_candidate_below_threshold_after_ad_wait"
        and str(row.get("target_name", "")).startswith(("close_user_", "close_end_"))
    ]
    film_entry_clicked = decisions["click_ad_entry"] > 0 or decisions["click_film_ad_entry"] > 0

    if film_phase_without_source and close_waits and not film_entry_clicked:
        problems.append(
            "已进入胶卷广告阶段，但被广告关闭按钮候选阻塞，未点击胶卷广告入口。"
            "这是阶段机优先级错误：current_ad_source=none 时不应处理 close_ad 候选，应优先点击 ad_entry。"
        )
    if film_phase_without_source and close_waits:
        problems.append(
            "检测到无广告来源时处理关闭按钮候选。close_ad 候选只能在广告播放后处理。"
        )

    if cooldown_skipped:
        problems.append("废铁看广告按钮处于冷却状态，已跳过废铁广告并进入回主页流程。")
        if not film_started:
            problems.append(
                "废铁广告因冷却被跳过，但没有进入胶卷广告阶段。请检查 return_home_after_scrap 和主页 ad_entry 检测。"
            )

    if battle_confirmed and watch_blocked_after_battle:
        problems.append(
            "废铁看广告按钮已被识别，但被错误的 battle_complete 条件阻止点击；这是状态机问题，不是模板问题。"
        )
        suggestions.append(
            "检查 battle_result_confirm 后是否设置 battle_phase_completed、awaiting_watch_ad_in_cycle，并避免重新进入 battle_wait。"
        )
    if scrap_watch_clicked and close_executed and not returned_home:
        problems.append(
            "废铁广告已关闭，但状态机仍停留在广告关闭阶段；应在 close_ad 成功后进入 return_home_after_scrap。"
        )
        suggestions.append(
            "检查废铁 close_ad 后的状态切换，并确认 recovery 没有错误恢复到 battle_wait。"
        )
    if scrap_watch_clicked and close_executed and returned_home and not film_started:
        problems.append(
            "废铁广告已关闭，但没有成功返回主页并进入胶卷广告流程。"
        )
        suggestions.append(
            "重点检查 return_home_after_scrap 的主页检测以及 recovery 阶段保持逻辑。"
        )
    if decisions["adb_back_to_home_after_scrap"] and not film_started:
        problems.append("已执行返回主页，但没有进入胶卷广告流程；主页检测或胶卷阶段启动失败。")
    if event_names["return_home_after_scrap_home_not_detected_after_max_back"]:
        problems.append("返回主页达到小退上限后仍未识别主页，最终主页探测失败。")
    if event_names["recovery_ignored_battle_wait_due_to_completed_scrap_phase"]:
        problems.append("废铁阶段已完成后仍尝试进入 battle_wait，这是状态恢复错误。")

    if strategy_name in {"ad_reward", "scrap_then_ad_reward"}:
        watch_directory = watch_button_templates_dir()
        if not any(watch_directory.glob("*.png")):
            problems.append("胶卷看广告按钮模板目录为空。")
            suggestions.append("通过 GUI 添加当前设备上的胶卷看广告按钮模板，再进行 Dry-run。")

    if total_clicks == 0 and reasons["wait_not_on_target_page"] >= 3:
        problems.append("本次运行没有进入目标流程，程序长期认为不在目标页面。")
        suggestions.append("确认当前页面和所选策略，并检查入口模板、watch_buttons 与模拟器画面是否匹配。")
    elif reasons["wait_not_on_target_page"] >= 5:
        problems.append("程序多次判断不在目标页面。")
        suggestions.append("打开最后截图，确认游戏是否位于主页、胶卷页或废铁页。")
    if reasons["wait_close_ad_not_found_after_ad_wait"] and not close_executed:
        problems.append(
            f"广告关闭阶段有 {reasons['wait_close_ad_not_found_after_ad_wait']} 次未识别到关闭按钮。"
        )
        suggestions.append("检查或补充 user_templates\\close_buttons 中的关闭按钮模板。")
    if reasons["close_ad_candidate_below_threshold_after_ad_wait"] and not close_executed:
        problems.append("检测到广告关闭按钮候选，但置信度低于 0.72，未点击。")
        suggestions.append("重新裁剪更准确的关闭按钮模板，再进行 Dry-run 验证。")
    if event_names["close_ad_candidate_ignored"] or reasons["close_ad_detected_before_ad_stage_ignored"]:
        problems.append("非广告阶段出现关闭按钮候选，已被阶段锁安全忽略。")
        suggestions.append("可能存在 close_buttons 模板误匹配，请检查对应 close_user 模板。")
    if event_names["miss_threshold_triggered_back"] >= 2:
        problems.append("多个阶段连续三次未识别目标并触发小退。")
        suggestions.append("检查弹窗、模板稳定性和页面跳转速度。")
    home_back_count = decisions["adb_back_to_home_after_scrap"]
    if home_back_count:
        problems.append(f"废铁结束后为返回主页执行了 {home_back_count} 次小退。")
        suggestions.append("检查主页上的 ad_entry / scrap_entry 是否能稳定识别。")
    if strategy_name == "scrap_then_ad_reward" and not event_names["film_ad_reward_started"]:
        problems.append("废铁结束后没有进入胶卷广告阶段。")
        suggestions.append("重点检查 return_home_after_scrap、主页检测和 ad_entry 置信度。")
    if strategy_name == "scrap_then_ad_reward" and not any(
        event.get("reason") == "scrap_then_ad_reward_completed" for event in events
    ):
        problems.append("完整组合流程没有自然完成。")
    if stop_reason == "stop_file":
        problems.append("本次由 stop_file 手动停止，不是程序自然完成。")
    if "max_actions" in stop_reason or any(row.get("result") == "skipped_max_actions_reached" for row in rows):
        problems.append("达到最大动作数限制，可能是 max-actions 较小或流程重复。")
    if event_names["global_stall_detected"]:
        problems.append(f"本次触发全局异常恢复 {event_names['global_stall_detected']} 次。")
    if event_names["click_no_effect_detected"]:
        problems.append("检测到点击后页面没有明显变化。")
        suggestions.append("检查点击坐标、按钮遮挡、模拟器响应和页面是否卡住。")
    license_failures = [
        event for event in events
        if event.get("event") in {"license_activate_failed", "license_heartbeat_failed", "license_feature_denied"}
    ]
    if license_failures:
        last_error = str(license_failures[-1].get("error", "license_failed"))
        license_messages = {
            "license_expired": "卡密已过期",
            "license_disabled": "卡密已被禁用",
            "device_limit_reached": "设备数量已达到上限",
            "feature_denied": "当前功能未开通",
            "license_cache_missing": "本地没有授权缓存",
        }
        problems.append(f"授权失败：{license_messages.get(last_error, last_error)}。")
        suggestions.append("检查卡密状态、联网情况和授权服务器地址，然后重新激活或检查授权。")
    popup_template_count = len(tuple(error_popup_templates_dir().glob("*.png")))
    button_template_count = len(tuple(error_button_templates_dir().glob("*.png")))
    if popup_template_count == 0 or button_template_count == 0:
        problems.append(
            "错误弹窗恢复未启用：user_templates/error_popups 或 user_templates/error_buttons 为空。"
        )
        suggestions.append("添加错误弹窗标记模板和对应按钮模板后重新 Dry-run。")
    if event_names["error_popup_recovery_started"]:
        problems.append(
            f"错误弹窗恢复触发 {event_names['error_popup_recovery_started']} 次，"
            f"成功 {event_names['error_popup_recovery_succeeded']} 次，"
            f"失败 {event_names['error_popup_recovery_failed']} 次。"
        )
    clicked_buttons = [
        str(event.get("button_name", ""))
        for event in events
        if event.get("event") == "error_popup_button_clicked"
    ]
    if clicked_buttons:
        problems.append(f"最近处理的错误弹窗按钮：{clicked_buttons[-1]}。")
    if event_names["error_button_without_popup_ignored"]:
        problems.append("曾只识别到错误按钮而没有弹窗，已安全忽略，可能存在模板误匹配。")
    if event_names["error_popup_detected_but_button_missing"]:
        problems.append("检测到错误弹窗但没有找到按钮，需要补充 error_buttons 模板。")
    if event_names["max_error_popup_recovery_attempts_reached"]:
        problems.append("错误弹窗恢复次数达到上限，请检查最后截图和模板。")

    if not problems:
        problems.append("未发现明显异常。")
        automatic = "本次流程基本正常，可以继续进行循环测试。"
    else:
        automatic = suggestions[0] if suggestions else "建议查看最后截图、最后状态和最后一条点击记录。"

    lines = [
        "========== 本次运行总结 ==========",
        f"策略：{strategy_name or 'unknown'}",
        f"循环次数：{total_loops}",
        f"有效点击：{total_clicks}",
        f"完成轮数：{total_cycles_completed}",
        f"停止原因：{stop_reason}",
        "",
        "========== 可疑问题 ==========",
    ]
    lines.extend(f"{index}. {problem}" for index, problem in enumerate(problems, 1))
    lines.extend(["", "========== 自动判断 ==========", automatic])
    if suggestions:
        lines.extend(["", "建议："])
        lines.extend(f"- {item}" for item in dict.fromkeys(suggestions))
    return "\n".join(lines) + "\n"


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _read_events(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events

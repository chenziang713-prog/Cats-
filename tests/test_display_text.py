from __future__ import annotations

import csv
import json

from cats_automatic.display_text import (
    to_display_decision, to_display_phase, to_display_reason, to_display_target,
)
from tools.catsautomatic_gui import load_latest_decision_record


def test_display_mappings_and_fallbacks() -> None:
    assert to_display_decision("click_scrap_entry") == "点击废铁入口"
    assert to_display_decision("click_scrap_watch_ad_button") == "点击废铁看广告按钮"
    assert to_display_decision("skip_scrap_ad_due_to_cooldown") == "废铁广告冷却，跳过废铁广告"
    assert to_display_decision("close_ad") == "点击广告关闭按钮"
    assert to_display_phase("return_home_after_scrap") == "废铁后返回主页"
    assert to_display_phase("film_ad_reward_phase") == "胶卷广告流程"
    assert to_display_target("close_user_123_5") == "广告关闭按钮"
    assert to_display_target("error_popup_screenshot_xxx") == "错误弹窗"
    assert to_display_decision("unknown") == "未翻译决策：unknown"
    assert to_display_reason("unknown") == "其他原因：unknown"


def test_gui_decision_fallback_prefers_click_records(tmp_path) -> None:
    with (tmp_path / "click_records.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["decision"])
        writer.writeheader()
        writer.writerow({"decision": "close_ad"})
    (tmp_path / "phase_journal.jsonl").write_text(json.dumps({"chosen_decision": "wait"}), encoding="utf-8")
    assert load_latest_decision_record(tmp_path) == "close_ad"


def test_gui_decision_fallback_uses_phase_journal(tmp_path) -> None:
    (tmp_path / "phase_journal.jsonl").write_text(json.dumps({"chosen_decision": "click_ad_entry"}), encoding="utf-8")
    assert load_latest_decision_record(tmp_path) == "click_ad_entry"

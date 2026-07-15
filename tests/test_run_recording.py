from __future__ import annotations

import csv
from pathlib import Path

from cats_automatic.actions import ActionResult
from cats_automatic.run_recording import RunRecorder
from cats_automatic.strategy_base import DetectionResult, StrategyDecision


def test_run_recorder_records_v2_action_fields_and_execution_counts(tmp_path: Path) -> None:
    recorder = RunRecorder(
        output_root=tmp_path / "runs",
        capture_backend="adb",
        adb_serial="emulator-5556",
        max_actions_limit=8,
        strategy_name="scrap_then_ad_reward_v2",
        run_id="run-1",
    )
    recorder.last_screenshot = "output/runs/run-1/screenshots/loop-001.png"
    decision = StrategyDecision.action(
        "tap_marker",
        params={
            "marker": "watch_ad_film",
            "min_confidence": 0.85,
            "decision_id": "v2-1-1",
            "source_fingerprint": "abc123",
        },
        reason="watch_ad_film_marker_selected",
    )
    detection = DetectionResult(
        name="watch_ad_film",
        template=Path("watch_ad_film.png"),
        confidence=0.93,
        center=(100, 120),
        top_left=(90, 110),
        size=(20, 20),
        scale=1.0,
        threshold=0.8,
    )

    recorder.record_action(
        loop_index=1,
        decision=decision,
        action_result=ActionResult(
            "adb_tap",
            "executed",
            "watch_ad_film_marker_selected",
            success=True,
            action="tap_marker",
            dry_run=False,
            clicked_pos=(101, 121),
        ),
        detection=detection,
        max_actions_used=1,
    )
    recorder.write_summary()

    rows = list(csv.DictReader(recorder.click_records_path.open(encoding="utf-8")))
    summary = recorder.summary_path.read_text(encoding="utf-8")

    assert rows[0]["decision_id"] == "v2-1-1"
    assert rows[0]["marker"] == "watch_ad_film"
    assert rows[0]["source_fingerprint"] == "abc123"
    assert rows[0]["click_x"] == "101"
    assert rows[0]["click_y"] == "121"
    assert "adb_tap_count: 1" in summary
    assert "total_executed_actions: 1" in summary
    assert "planned_actions: 1" in summary
    assert recorder.last_adb_tap["decision"] == "tap_marker"


def test_run_recorder_counts_keyevent_and_blocked_duplicate_actions(tmp_path: Path) -> None:
    recorder = RunRecorder(
        output_root=tmp_path / "runs",
        capture_backend="adb",
        strategy_name="scrap_then_ad_reward_v2",
        run_id="run-2",
    )
    recorder.record_action(
        loop_index=1,
        decision=StrategyDecision.keyevent("BACK", "press_back", "reward_success_press_back"),
        action_result=ActionResult(
            "adb_keyevent",
            "executed",
            "reward_success_press_back",
            success=True,
            action="press_back",
            dry_run=False,
        ),
        detection=None,
        max_actions_used=2,
    )
    recorder.record_action(
        loop_index=2,
        decision=StrategyDecision.action(
            "wait",
            reason="pending_effect_duplicate_blocked",
        ),
        action_result=ActionResult(
            "wait",
            "skipped_wait",
            "pending_effect_duplicate_blocked",
            success=True,
            action="wait",
            dry_run=True,
        ),
        detection=None,
        max_actions_used=2,
    )
    recorder.write_summary()

    summary = recorder.summary_path.read_text(encoding="utf-8")

    assert "adb_keyevent_count: 1" in summary
    assert "total_executed_actions: 1" in summary
    assert "planned_actions: 2" in summary
    assert "dry_run_actions: 1" in summary
    assert "blocked_duplicate_actions: 1" in summary

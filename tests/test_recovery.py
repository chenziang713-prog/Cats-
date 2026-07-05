from __future__ import annotations

import csv
import subprocess
from dataclasses import replace
from pathlib import Path

from PIL import Image

from cats_automatic.actions import ActionResult, AdbActionBackend, DryRunBackend
from cats_automatic.console_output import decision_summary, detection_summary, ignored_close_summary
from cats_automatic.diagnosis import generate_diagnosis
from cats_automatic.error_popup_recovery import ErrorPopupRecoveryManager
from cats_automatic.game_base import GameDefinition
from cats_automatic.license_client import LicenseResult
from cats_automatic.recovery import GlobalStallWatchdog, RecoveryConfig
from cats_automatic.run_recording import RunRecorder
from cats_automatic.strategy_base import DetectionResult, StrategyContext, StrategyDecision
from cats_automatic.strategy_runner import StrategyRunner
from cats_automatic.window_capture import WindowFrame


class Clock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value


def test_same_state_timeout_triggers_recovery() -> None:
    clock = Clock()
    watchdog = _watchdog(clock, same_state_stall_seconds=10)
    watchdog.observe(state="stuck", decision=_wait("other"), detections={}, screenshot_path=None)
    clock.value = 10

    trigger = watchdog.observe(
        state="stuck", decision=_wait("another"), detections={}, screenshot_path=None
    )

    assert trigger is not None
    assert trigger.reason == "same_state_stall_seconds"
    assert trigger.should_recover is True


def test_same_wait_reason_limit_triggers_recovery() -> None:
    watchdog = _watchdog(Clock(), same_wait_reason_limit=2)

    assert watchdog.observe(state="stuck", decision=_wait("same"), detections={}, screenshot_path=None) is None
    trigger = watchdog.observe(state="stuck", decision=_wait("same"), detections={}, screenshot_path=None)

    assert trigger is not None
    assert trigger.reason == "same_wait_reason_limit"


def test_no_progress_timeout_triggers_recovery() -> None:
    clock = Clock()
    watchdog = _watchdog(clock, no_progress_seconds=12)
    watchdog.observe(state="stuck", decision=_wait("one"), detections={}, screenshot_path=None)
    clock.value = 12

    trigger = watchdog.observe(
        state="stuck", decision=_wait("two"), detections={}, screenshot_path=None
    )

    assert trigger is not None
    assert trigger.reason == "no_progress_seconds"


def test_wait_not_on_target_page_timeout_triggers_recovery() -> None:
    clock = Clock()
    watchdog = _watchdog(clock, wait_not_on_target_page_seconds=8)
    decision = _wait("wait_not_on_target_page")
    watchdog.observe(state="home", decision=decision, detections={}, screenshot_path=None)
    clock.value = 8

    trigger = watchdog.observe(state="home", decision=decision, detections={}, screenshot_path=None)

    assert trigger is not None
    assert trigger.reason == "wait_not_on_target_page_seconds"


def test_no_known_targets_timeout_triggers_recovery() -> None:
    clock = Clock()
    watchdog = _watchdog(clock, no_known_targets_seconds=6)
    watchdog.observe(state="unknown", decision=_wait("first"), detections={}, screenshot_path=None)
    clock.value = 6

    trigger = watchdog.observe(
        state="unknown", decision=_wait("second"), detections={}, screenshot_path=None
    )

    assert trigger is not None
    assert trigger.reason == "no_known_targets_seconds"


def test_ad_stage_hard_timeout_requires_no_progress_target() -> None:
    clock = Clock()
    watchdog = _watchdog(clock, ad_stage_hard_timeout_seconds=9)
    watchdog.observe(state="close_ad", decision=_wait("first"), detections={}, screenshot_path=None)
    clock.value = 9

    trigger = watchdog.observe(
        state="close_ad", decision=_wait("second"), detections={}, screenshot_path=None
    )

    assert trigger is not None
    assert trigger.reason == "ad_stage_hard_timeout_seconds"


def test_normal_battle_and_ad_wait_do_not_trigger() -> None:
    clock = Clock()
    watchdog = _watchdog(
        clock,
        same_state_stall_seconds=1,
        no_progress_seconds=1,
        no_known_targets_seconds=1,
    )
    watchdog.observe(state="battle_wait", decision=_wait("battle_wait"), detections={}, screenshot_path=None)
    clock.value = 100
    assert watchdog.observe(
        state="battle_wait", decision=_wait("battle_wait"), detections={}, screenshot_path=None
    ) is None
    assert watchdog.observe(
        state="ad_wait", decision=_wait("ad_wait"), detections={}, screenshot_path=None
    ) is None


def test_recovery_limits_and_cooldown() -> None:
    clock = Clock()
    watchdog = _watchdog(
        clock,
        same_wait_reason_limit=1,
        recovery_cooldown_seconds=10,
        max_recovery_attempts_per_cycle=1,
    )
    first = watchdog.observe(state="x", decision=_wait("same"), detections={}, screenshot_path=None)
    clock.value = 5
    cooldown = watchdog.observe(state="x", decision=_wait("same"), detections={}, screenshot_path=None)
    clock.value = 11
    limited = watchdog.observe(state="x", decision=_wait("same"), detections={}, screenshot_path=None)

    assert first is not None and first.should_recover
    assert cooldown is None
    assert limited is not None and not limited.should_recover
    assert limited.reason == "max_recovery_attempts_per_cycle_reached"


def test_run_recovery_limit_survives_cycle_reset() -> None:
    watchdog = _watchdog(
        Clock(),
        same_wait_reason_limit=1,
        max_recovery_attempts_per_cycle=3,
        max_recovery_attempts_per_run=1,
    )
    assert watchdog.observe(
        state="x", decision=_wait("same"), detections={}, screenshot_path=None
    ).should_recover
    watchdog.reset_cycle()

    limited = watchdog.observe(
        state="x", decision=_wait("same"), detections={}, screenshot_path=None
    )

    assert limited is not None and not limited.should_recover
    assert limited.reason == "max_recovery_attempts_per_run_reached"


def test_click_no_effect_triggers_after_two_repeated_clicks(tmp_path: Path) -> None:
    screen = tmp_path / "same.png"
    Image.new("RGB", (100, 100), "black").save(screen)
    watchdog = _watchdog(Clock(), click_no_effect_limit=2)
    detection = _detection("button")
    decision = StrategyDecision.click("button", "click_button")
    for _ in range(2):
        watchdog.register_action(
            decision=decision,
            action_result=ActionResult("dry_run_click", "executed"),
            state="same",
            screenshot_path=screen,
            detections={"button": detection},
        )
        trigger = watchdog.observe(
            state="same",
            decision=decision,
            detections={"button": detection},
            screenshot_path=screen,
        )

    assert trigger is not None
    assert trigger.reason == "click_no_effect_same_screen_or_same_state"
    assert any(event["event"] == "click_no_effect_detected" for event in watchdog.drain_events())


def test_changed_target_after_click_is_progress(tmp_path: Path) -> None:
    screen = tmp_path / "screen.png"
    Image.new("RGB", (100, 100), "black").save(screen)
    watchdog = _watchdog(Clock(), click_no_effect_limit=1)
    watchdog.register_action(
        decision=StrategyDecision.click("button", "click_button"),
        action_result=ActionResult("dry_run_click", "executed"),
        state="before",
        screenshot_path=screen,
        detections={"button": _detection("button")},
    )

    trigger = watchdog.observe(
        state="after",
        decision=_wait("next"),
        detections={"next": _detection("next")},
        screenshot_path=screen,
    )

    assert trigger is None
    assert not any(event["event"] == "click_no_effect_detected" for event in watchdog.drain_events())


def test_runner_dry_run_records_recovery_back(tmp_path: Path) -> None:
    runner, recorder = _runner(
        tmp_path,
        DryRunBackend(max_actions=3),
        GlobalStallWatchdog(RecoveryConfig(same_wait_reason_limit=1, recovery_cooldown_seconds=0)),
    )

    runner.run()

    rows = _rows(recorder.click_records_path)
    assert rows[0]["decision"] == "problem_recovery_adb_back"
    assert rows[0]["action_type"] == "dry_run_keyevent"
    assert "global_stall_detected" in recorder.events_path.read_text(encoding="utf-8")
    assert "total_recovery_attempts: 1" in recorder.summary_path.read_text(encoding="utf-8")


def test_runner_adb_recovery_uses_guarded_back(tmp_path: Path) -> None:
    adb = tmp_path / "adb.exe"
    adb.touch()
    commands: list[list[str]] = []

    def subprocess_runner(command: list[str], **_: object) -> subprocess.CompletedProcess[bytes]:
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, stdout=b"", stderr=b"")

    backend = AdbActionBackend(
        adb_path=adb,
        adb_serial="emulator-5556",
        max_actions=3,
        click_cooldown=0,
        runner=subprocess_runner,
        sleep=lambda _: None,
    )
    runner, _ = _runner(
        tmp_path,
        backend,
        GlobalStallWatchdog(RecoveryConfig(same_wait_reason_limit=1, recovery_cooldown_seconds=0)),
    )

    runner.run()

    assert commands == [
        [str(adb), "-s", "emulator-5556", "shell", "input", "keyevent", "BACK"]
    ]


def test_stop_file_prevents_recovery(tmp_path: Path) -> None:
    stop_file = tmp_path / "STOP"
    stop_file.touch()
    backend = DryRunBackend(max_actions=3)
    runner, recorder = _runner(
        tmp_path,
        backend,
        GlobalStallWatchdog(RecoveryConfig(same_wait_reason_limit=1)),
        stop_file=stop_file,
    )

    runner.run()

    assert backend.action_count == 0
    assert "global_stall_detected" not in recorder.events_path.read_text(encoding="utf-8")


def test_license_heartbeat_failure_stops_before_actions(tmp_path: Path) -> None:
    backend = DryRunBackend(max_actions=3)
    runner, recorder = _runner(
        tmp_path,
        backend,
        GlobalStallWatchdog(RecoveryConfig(same_wait_reason_limit=100)),
    )
    runner.license_heartbeat = lambda: LicenseResult(
        False,
        "heartbeat_failed",
        "卡密已被禁用",
        "license_disabled",
        event="license_heartbeat_failed",
    )
    runner.heartbeat_interval_seconds = 0
    runner._next_license_heartbeat_at = 0

    runner.run()

    assert backend.action_count == 0
    assert "license_heartbeat_failed" in recorder.events_path.read_text(encoding="utf-8")
    summary = recorder.summary_path.read_text(encoding="utf-8")
    assert "stop_reason: license_heartbeat_failed" in summary
    assert "last_license_error: license_disabled" in summary


def test_diagnosis_reports_common_template_problems(tmp_path: Path) -> None:
    records = tmp_path / "click_records.csv"
    records.write_text(
        "decision,reason,result\nwait,wait_not_on_target_page,skipped_wait\n"
        "wait,wait_not_on_target_page,skipped_wait\n"
        "wait,wait_not_on_target_page,skipped_wait\n"
        "wait,close_ad_candidate_below_threshold_after_ad_wait,waiting_close_ad\n",
        encoding="utf-8",
    )
    events = tmp_path / "events.jsonl"
    events.write_text('{"event":"close_ad_candidate_ignored"}\n', encoding="utf-8")

    report = generate_diagnosis(
        strategy_name="ad_reward",
        click_records_path=records,
        events_path=events,
        total_loops=4,
        total_clicks=0,
        total_cycles_completed=0,
        stop_reason="stop_file",
    )

    assert "本次运行总结" in report
    assert "目标流程" in report
    assert "置信度低于 0.72" in report
    assert "阶段锁安全忽略" in report
    assert "手动停止" in report


def test_chinese_console_summaries_cover_detection_action_wait_and_ignore() -> None:
    detections = {
        "battle_result_popup": _detection("battle_result_popup"),
        "confirm_button": _detection("confirm_button"),
    }

    detected = detection_summary(16, detections)
    action = decision_summary(
        16,
        StrategyDecision.click("confirm_button", "click_battle_result_confirm"),
    )
    waiting = decision_summary(
        17,
        StrategyDecision.wait(1, "wait_close_ad_not_found_after_ad_wait"),
    )
    ignored = ignored_close_summary(12, 0.759)

    assert detected is not None and "检测到：战斗结果弹窗" in detected and "确认按钮" in detected
    assert "执行：点击战斗结果确认按钮" in action
    assert "等待：广告关闭按钮未出现" in waiting
    assert "忽略：非广告阶段检测到关闭按钮" in ignored


def _watchdog(clock: Clock, **changes: object) -> GlobalStallWatchdog:
    base = RecoveryConfig(
        same_state_stall_seconds=10_000,
        same_wait_reason_limit=10_000,
        no_progress_seconds=10_000,
        wait_not_on_target_page_seconds=10_000,
        no_known_targets_seconds=10_000,
        ad_stage_hard_timeout_seconds=10_000,
        click_no_effect_limit=10_000,
        recovery_cooldown_seconds=0,
    )
    return GlobalStallWatchdog(replace(base, **changes), clock=clock)


def _wait(reason: str) -> StrategyDecision:
    return StrategyDecision.wait(0, reason)


def _detection(name: str) -> DetectionResult:
    return DetectionResult(name, Path(f"{name}.png"), 0.95, (10, 10), (5, 5), (10, 10), 1.0, 0.8)


class WaitStrategy:
    state = "stuck"

    def targets(self):
        return ()

    def decide(self, _context: StrategyContext) -> StrategyDecision:
        return StrategyDecision.wait(0, "repeated_wait")


class Capture:
    name = "fake"

    def __init__(self, source: Path) -> None:
        self.source = source

    def capture(self, output_path: Path) -> WindowFrame:
        return WindowFrame(self.source, "fake", (0, 0), (100, 100))


def _runner(
    tmp_path: Path,
    backend,
    watchdog: GlobalStallWatchdog,
    *,
    stop_file: Path | None = None,
):
    screen = tmp_path / "screen.png"
    Image.new("RGB", (100, 100), "black").save(screen)
    recorder = RunRecorder(
        output_root=tmp_path / "runs",
        capture_backend="fake",
        strategy_name="test",
        run_id="recovery-test",
    )
    runner = StrategyRunner(
        game=GameDefinition("test", tmp_path / "config.json", tmp_path),
        strategy=WaitStrategy(),
        capture_backend=Capture(screen),
        action_backend=backend,
        root=tmp_path,
        output_dir=tmp_path / "output",
        max_loops=1,
        run_recorder=recorder,
        stop_file=stop_file,
        matcher=lambda *_, **__: None,
        sleep=lambda _: None,
        recovery_watchdog=watchdog,
        error_popup_recovery=ErrorPopupRecoveryManager(
            popup_dir=tmp_path / "empty-error-popups",
            button_dir=tmp_path / "empty-error-buttons",
        ),
    )
    return runner, recorder


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))

from __future__ import annotations

import csv
import subprocess
from pathlib import Path

from PIL import Image

from cats_automatic.actions import AdbActionBackend, DryRunBackend
from cats_automatic.error_popup_recovery import (
    ERROR_BUTTON_MIN_CONFIDENCE,
    ERROR_POPUP_MIN_CONFIDENCE,
    ErrorPopupRecoveryConfig,
    ErrorPopupRecoveryManager,
)
from cats_automatic.game_base import GameDefinition
from cats_automatic.license_client import LicenseResult
from cats_automatic.recovery import GlobalStallWatchdog, RecoveryConfig
from cats_automatic.run_recording import RunRecorder
from cats_automatic.strategy_base import DetectionResult, StrategyContext, StrategyDecision
from cats_automatic.strategy_runner import StrategyRunner
from cats_automatic.vision import MatchResult
from cats_automatic.window_capture import WindowFrame


def test_error_template_directories_and_thresholds(tmp_path: Path) -> None:
    popup_dir = tmp_path / "error_popups"
    button_dir = tmp_path / "error_buttons"
    Image.new("RGB", (20, 20), "red").save(popup_dir.mkdir(parents=True) or popup_dir / "network.png")
    Image.new("RGB", (10, 10), "green").save(button_dir.mkdir(parents=True) or button_dir / "ok.png")

    manager = ErrorPopupRecoveryManager(popup_dir=popup_dir, button_dir=button_dir)
    targets = {target.name: target for target in manager.targets()}

    assert targets["error_popup_network"].threshold == ERROR_POPUP_MIN_CONFIDENCE == 0.80
    assert targets["error_button_ok"].threshold == ERROR_BUTTON_MIN_CONFIDENCE == 0.80


def test_popup_and_button_produce_recovery_click(tmp_path: Path) -> None:
    manager = _active_manager(tmp_path)

    decision = manager.decide(
        _context(
            {
                "error_popup_network": _detection("error_popup_network", top_left=(10, 10), size=(200, 100)),
                "error_button_ok": _detection("error_button_ok", center=(100, 80)),
            }
        )
    )

    assert decision is not None
    assert decision.action_name == "error_popup_recovery_click"
    assert decision.target_name == "error_button_ok"
    assert decision.post_action_delay_seconds == 1.0
    assert decision.min_click_confidence_override == 0.80


def test_button_without_popup_is_ignored(tmp_path: Path) -> None:
    manager = _active_manager(tmp_path)

    decision = manager.decide(
        _context({"error_button_ok": _detection("error_button_ok")})
    )

    assert decision.action_name == "error_popup_recovery_wait"
    assert decision.reason == "error_button_without_popup_ignored"
    assert any(event["event"] == "error_button_without_popup_ignored" for event in manager.drain_events())


def test_popup_without_button_waits(tmp_path: Path) -> None:
    manager = _active_manager(tmp_path)

    decision = manager.decide(
        _context({"error_popup_network": _detection("error_popup_network")})
    )

    assert decision.action_name == "error_popup_recovery_wait"
    assert decision.reason == "error_popup_detected_but_button_missing"


def test_resume_with_scrap_watch_returns_control_to_strategy(tmp_path: Path) -> None:
    manager = _active_manager(tmp_path)
    manager.awaiting_resume = True

    decision = manager.decide(
        _context({"scrap_watch_ad_button": _detection("scrap_watch_ad_button")})
    )

    assert decision is None
    events = manager.drain_events()
    assert any(event["event"] == "resume_state_detected_after_error_popup" for event in events)
    assert any(event["event"] == "error_popup_recovery_succeeded" for event in events)


def test_resume_battle_result_keeps_original_priority(tmp_path: Path) -> None:
    manager = _active_manager(tmp_path)
    manager.awaiting_resume = True
    context = _context(
        {
            "battle_result_popup": _detection("battle_result_popup"),
            "confirm_button": _detection("confirm_button"),
        }
    )

    assert manager.decide(context) is None
    decision = PriorityStrategy().decide(context)

    assert decision.action_name == "click_battle_result_confirm"


def test_resume_unknown_screen_waits_in_previous_state(tmp_path: Path) -> None:
    manager = _active_manager(tmp_path)
    manager.awaiting_resume = True

    decision = manager.decide(_context({}))

    assert decision.action_name == "resume_previous_state_after_error_popup"
    assert decision.reason == "resume_previous_state_after_error_popup_uncertain"
    assert manager.snapshot.previous_state == "wait_scrap_watch_ad_button"


def test_error_popup_recovery_limits(tmp_path: Path) -> None:
    manager = ErrorPopupRecoveryManager(
        ErrorPopupRecoveryConfig(max_attempts_per_cycle=1, max_attempts_per_run=1, cooldown_seconds=0),
        popup_dir=tmp_path / "popups",
        button_dir=tmp_path / "buttons",
    )
    strategy = FakeStrategy()

    assert manager.start(strategy=strategy, cycle_index=1, last_decision=None)
    manager.active = False
    assert not manager.start(strategy=strategy, cycle_index=1, last_decision=None)
    assert any(
        event["event"] == "max_error_popup_recovery_attempts_reached"
        for event in manager.drain_events()
    )


def test_runner_dry_run_records_error_popup_click(tmp_path: Path) -> None:
    runner, recorder, backend = _runner(tmp_path, DryRunBackend(max_actions=3))

    runner.run()

    rows = _rows(recorder.click_records_path)
    assert rows[-1]["decision"] == "error_popup_recovery_click"
    assert rows[-1]["action_type"] == "dry_run_click"
    assert backend.action_count == 1
    events = recorder.events_path.read_text(encoding="utf-8")
    assert "error_popup_recovery_started" in events
    assert "error_popup_button_clicked" in events
    summary = recorder.summary_path.read_text(encoding="utf-8")
    diagnosis = recorder.diagnosis_path.read_text(encoding="utf-8")
    assert "error_popup_recovery_attempts: 1" in summary
    assert "错误弹窗恢复触发 1 次" in diagnosis


def test_runner_adb_executes_error_popup_click(tmp_path: Path) -> None:
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
        min_click_confidence=0.85,
        runner=subprocess_runner,
        sleep=lambda _: None,
    )
    runner, _, _ = _runner(tmp_path, backend)

    runner.run()

    assert commands == [
        [str(adb), "-s", "emulator-5556", "shell", "input", "tap", "100", "80"]
    ]


def test_stop_file_and_license_failure_prevent_error_popup_recovery(tmp_path: Path) -> None:
    stop_file = tmp_path / "STOP"
    stop_file.touch()
    runner, recorder, backend = _runner(
        tmp_path,
        DryRunBackend(max_actions=3),
        stop_file=stop_file,
    )
    runner.run()
    assert backend.action_count == 0
    assert "error_popup_recovery_started" not in recorder.events_path.read_text(encoding="utf-8")

    stop_file.unlink()
    runner, recorder, backend = _runner(tmp_path / "license", DryRunBackend(max_actions=3))
    runner.license_heartbeat = lambda: LicenseResult(
        False,
        "heartbeat_failed",
        "disabled",
        "license_disabled",
        event="license_heartbeat_failed",
    )
    runner._next_license_heartbeat_at = 0
    runner.run()
    assert backend.action_count == 0
    assert "error_popup_recovery_started" not in recorder.events_path.read_text(encoding="utf-8")


def test_max_actions_prevents_error_popup_recovery(tmp_path: Path) -> None:
    backend = DryRunBackend(max_actions=1)
    backend.action_count = 1
    backend.reset_cycle = lambda: None  # type: ignore[method-assign]
    runner, recorder, _ = _runner(tmp_path, backend)

    runner.run()

    assert "error_popup_recovery_started" not in recorder.events_path.read_text(encoding="utf-8")


class FakeStrategy:
    state = "wait_scrap_watch_ad_button"
    phase = "scrap_phase"
    awaiting_watch_ad_in_cycle = True

    def targets(self):
        return ()

    def decide(self, _context: StrategyContext) -> StrategyDecision:
        return StrategyDecision.wait(0, "stalled")


class PriorityStrategy:
    def decide(self, context: StrategyContext) -> StrategyDecision:
        if "battle_result_popup" in context.detections and "confirm_button" in context.detections:
            return StrategyDecision.click(
                "confirm_button",
                "click_battle_result_confirm",
                "battle_result_popup_confirm_button_detected",
            )
        return StrategyDecision.wait(1, "unknown")


class Capture:
    name = "fake"

    def __init__(self, source: Path) -> None:
        self.source = source

    def capture(self, _output_path: Path) -> WindowFrame:
        return WindowFrame(self.source, "fake", (0, 0), (300, 200))


def _active_manager(tmp_path: Path) -> ErrorPopupRecoveryManager:
    manager = ErrorPopupRecoveryManager(
        ErrorPopupRecoveryConfig(cooldown_seconds=0),
        popup_dir=tmp_path / "popups",
        button_dir=tmp_path / "buttons",
    )
    assert manager.start(strategy=FakeStrategy(), cycle_index=1, last_decision=None)
    manager.drain_events()
    return manager


def _runner(tmp_path: Path, backend, *, stop_file: Path | None = None):
    tmp_path.mkdir(parents=True, exist_ok=True)
    screen = tmp_path / "screen.png"
    Image.new("RGB", (300, 200), "black").save(screen)
    popup_dir = tmp_path / "popups"
    button_dir = tmp_path / "buttons"
    popup_dir.mkdir()
    button_dir.mkdir()
    Image.new("RGB", (200, 100), "red").save(popup_dir / "network.png")
    Image.new("RGB", (20, 20), "green").save(button_dir / "ok.png")
    manager = ErrorPopupRecoveryManager(
        ErrorPopupRecoveryConfig(cooldown_seconds=0),
        popup_dir=popup_dir,
        button_dir=button_dir,
    )
    watchdog = GlobalStallWatchdog(
        RecoveryConfig(
            same_wait_reason_limit=1,
            max_recovery_attempts_per_cycle=0,
            recovery_cooldown_seconds=0,
        )
    )
    recorder = RunRecorder(
        output_root=tmp_path / "runs",
        capture_backend="fake",
        strategy_name="test",
        run_id="popup-test",
    )

    def matcher(_screen: Path, template: Path, **_: object) -> MatchResult:
        if template.name == "network.png":
            return MatchResult(0.95, (10, 10), (200, 100))
        return MatchResult(0.95, (90, 70), (20, 20))

    runner = StrategyRunner(
        game=GameDefinition("test", tmp_path / "config.json", tmp_path),
        strategy=FakeStrategy(),
        capture_backend=Capture(screen),
        action_backend=backend,
        root=tmp_path,
        output_dir=tmp_path / "output",
        max_loops=1,
        run_recorder=recorder,
        stop_file=stop_file,
        matcher=matcher,
        sleep=lambda _: None,
        recovery_watchdog=watchdog,
        error_popup_recovery=manager,
    )
    return runner, recorder, backend


def _context(detections: dict[str, DetectionResult]) -> StrategyContext:
    return StrategyContext(
        1,
        Path("screen.png"),
        GameDefinition("test", Path("config.json"), Path("templates")),
        detections,
        lambda value: Path(value),
    )


def _detection(
    name: str,
    *,
    confidence: float = 0.95,
    center: tuple[int, int] = (100, 80),
    top_left: tuple[int, int] = (10, 10),
    size: tuple[int, int] = (100, 80),
) -> DetectionResult:
    return DetectionResult(name, Path(f"{name}.png"), confidence, center, top_left, size, 1.0, 0.8)


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))

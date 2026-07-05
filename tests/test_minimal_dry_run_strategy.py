from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from cats_automatic.actions import DryRunBackend
from cats_automatic.backends.static_image_capture import StaticImageCaptureBackend
from cats_automatic.game_base import GameDefinition
from cats_automatic.run_recording import RunRecorder
from cats_automatic.strategy_base import DetectionResult, StrategyContext
from cats_automatic.strategy_runner import StrategyRunner
from external_strategies.minimal_dry_run.strategy import Strategy


def test_minimal_dry_run_initial_step_is_start() -> None:
    strategy = Strategy()

    assert strategy.current_step == "START"


def test_start_jumps_to_go_home() -> None:
    strategy = Strategy()

    decision = strategy.decide(_context({}))
    strategy.on_action_result(decision, DryRunBackend().wait(0.0, decision.reason))

    assert decision.action_name == "no_action"
    assert strategy.current_step == "GO_HOME"


def test_go_home_home_clicks_activity_entry() -> None:
    strategy = Strategy()
    strategy.current_step = "GO_HOME"

    decision = strategy.decide(_context({"HOME_PAGE": _detection("HOME_PAGE")}))
    strategy.on_action_result(decision, DryRunBackend().wait(0.0, decision.reason))

    assert decision.action_name == "click_activity_entry"
    assert strategy.current_step == "ENTER_ACTIVITY"


def test_watch_ad_running_waits_and_stays_watch_ad() -> None:
    strategy = Strategy()
    strategy.current_step = "WATCH_AD"

    decision = strategy.decide(_context({"AD_RUNNING_PAGE": _detection("AD_RUNNING_PAGE")}))
    strategy.on_action_result(decision, DryRunBackend().wait(0.0, decision.reason))

    assert decision.action_name == "wait"
    assert strategy.current_step == "WATCH_AD"


def test_watch_ad_close_visible_moves_to_close_ad() -> None:
    strategy = Strategy()
    strategy.current_step = "WATCH_AD"

    decision = strategy.decide(_context({"AD_CLOSE_PAGE": _detection("AD_CLOSE_PAGE")}))
    strategy.on_action_result(decision, DryRunBackend().wait(0.0, decision.reason))

    assert decision.action_name == "close_ad"
    assert strategy.current_step == "CLOSE_AD"


def test_unknown_combination_defaults_to_wait() -> None:
    strategy = Strategy()
    strategy.current_step = "ENTER_ACTIVITY"

    decision = strategy.decide(_context({"TASK_PAGE": _detection("TASK_PAGE")}))
    strategy.on_action_result(decision, DryRunBackend().wait(0.0, decision.reason))

    assert decision.action_name == "wait"
    assert decision.reason == "no_matching_rule"
    assert strategy.current_step == "ENTER_ACTIVITY"


def test_dry_run_runner_does_not_execute_adb_and_records_loop_fields(tmp_path: Path) -> None:
    screen = tmp_path / "screen.png"
    Image.new("RGB", (80, 60), "white").save(screen)
    recorder = RunRecorder(
        output_root=tmp_path / "output" / "runs",
        capture_backend="static",
        strategy_name="minimal_dry_run",
    )
    backend = DryRunBackend(max_actions=5)

    runner = StrategyRunner(
        game=_game(tmp_path),
        strategy=Strategy(),
        capture_backend=StaticImageCaptureBackend(screen),
        action_backend=backend,
        root=tmp_path,
        output_dir=tmp_path / "output" / "strategy",
        max_loops=1,
        run_recorder=recorder,
        sleep=lambda _seconds: None,
    )

    runner.run()
    recorder.finish("test_done")

    assert backend.action_count == 0
    event = _minimal_loop_event(recorder.events_path)
    assert event["loop"] == 1
    assert event["step"] == "START"
    assert event["state"] == "UNKNOWN_PAGE"
    assert event["action"] == "no_action"
    assert event["action_result"] == "dry_run_skipped"
    assert event["next_step"] == "GO_HOME"
    assert event["step_changed"] is True
    assert event["run_id"] == recorder.run_id
    assert event["dry_run"] is True
    assert event["matched_markers"] == []
    assert event["screenshot_path"].endswith("loop-001.png")


def _context(detections: dict[str, DetectionResult]) -> StrategyContext:
    return StrategyContext(
        loop_index=1,
        screen_path=Path("screen.png"),
        game=_game(Path(".")),
        detections=detections,
        resolve_template=lambda template: Path(template),
    )


def _game(root: Path) -> GameDefinition:
    return GameDefinition("test", root / "config.json", root / "templates")


def _detection(name: str, confidence: float = 0.95) -> DetectionResult:
    return DetectionResult(
        name=name,
        template=Path(f"{name}.png"),
        confidence=confidence,
        center=(10, 20),
        top_left=(5, 15),
        size=(10, 10),
        scale=1.0,
        threshold=0.8,
    )


def _minimal_loop_event(events_path: Path) -> dict[str, object]:
    for line in events_path.read_text(encoding="utf-8").splitlines():
        event = json.loads(line)
        if event.get("event") == "minimal_dry_run_loop":
            return event
    raise AssertionError("minimal_dry_run_loop event not found")

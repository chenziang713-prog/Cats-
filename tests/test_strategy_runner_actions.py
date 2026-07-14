from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from cats_automatic.actions import ActionResult
from cats_automatic.backends.static_image_capture import StaticImageCaptureBackend
from cats_automatic.game_base import GameDefinition
from cats_automatic.run_recording import RunRecorder
from cats_automatic.strategy_base import DetectionResult, StrategyContext, StrategyDecision
from cats_automatic.strategy_runner import StrategyRunner
from external_strategies.minimal_dry_run.strategy import Strategy as MinimalDryRunStrategy


def test_strategy_runner_records_action_result_from_actions_layer(tmp_path: Path) -> None:
    screen = tmp_path / "screen.png"
    Image.new("RGB", (80, 60), "white").save(screen)
    strategy = WaitOnceStrategy()
    action_backend = RecordingWaitBackend()
    recorder = RunRecorder(
        output_root=tmp_path / "output" / "runs",
        capture_backend="static",
        strategy_name="wait_once",
    )
    runner = StrategyRunner(
        game=_game(tmp_path),
        strategy=strategy,
        capture_backend=StaticImageCaptureBackend(screen),
        action_backend=action_backend,
        root=tmp_path,
        output_dir=tmp_path / "output" / "strategy",
        max_loops=1,
        run_recorder=recorder,
        sleep=lambda _seconds: None,
    )

    runner.run()
    recorder.finish("test_done")

    assert strategy.action_result is not None
    assert strategy.action_result.message == "backend_wait_result"
    action_event = _event(recorder.events_path, "action")
    assert action_event["action_result"]["message"] == "backend_wait_result"
    assert action_event["action_result"]["action"] == "wait"


def test_page_state_without_change_does_not_advance_click_step() -> None:
    strategy = MinimalDryRunStrategy()
    strategy.current_step = "GO_HOME"

    decision = strategy.decide(_context({"HOME_PAGE": _detection("HOME_PAGE")}))
    strategy.on_action_result(
        decision,
        ActionResult(
            "click_activity_entry",
            "unknown_action",
            "home_ready",
            success=False,
            action="click_activity_entry",
            dry_run=True,
            message="unsupported_action",
            error="unknown_action",
        ),
    )

    assert decision.action_name == "click_activity_entry"
    assert strategy.current_step == "GO_HOME"
    event = strategy.consume_strategy_events()[0]
    assert event["step"] == "GO_HOME"
    assert event["next_step"] == "GO_HOME"
    assert event["step_changed"] is False
    assert event["action_result"]["error"] == "unknown_action"


def test_strategy_runner_can_use_strategy_tap_marker_allow_list(tmp_path: Path) -> None:
    screen = tmp_path / "screen.png"
    Image.new("RGB", (80, 60), "white").save(screen)
    strategy = TapMarkerAllowListStrategy()
    runner = StrategyRunner(
        game=_game(tmp_path),
        strategy=strategy,
        capture_backend=StaticImageCaptureBackend(screen),
        action_backend=RecordingWaitBackend(),
        root=tmp_path,
        output_dir=tmp_path / "output" / "strategy",
        max_loops=1,
        sleep=lambda _seconds: None,
    )
    runner._current_image_size = (100, 100)
    runner._current_screen_path = screen
    decision = StrategyDecision.action(
        "tap_marker",
        params={"marker": "close_buttons", "min_confidence": 0.8},
        reason="v2_close_buttons_allowed",
    )

    executed = runner._execute_decision(
        decision,
        {"close_buttons": _detection("close_buttons", center=(30, 40))},
    )

    assert executed is True
    assert strategy.action_result is not None
    assert strategy.action_result.success is True
    assert strategy.action_result.action == "tap_marker"
    assert strategy.action_result.clicked_pos == (30, 40)


class RecordingWaitBackend:
    dry_run = True

    def __init__(self) -> None:
        self.action_count = 0

    def click(self, action):  # pragma: no cover - must not be called here
        raise AssertionError("click should not be called")

    def tap(self, action):  # pragma: no cover - must not be called here
        raise AssertionError("tap should not be called")

    def wait(self, seconds: float, reason: str = "") -> ActionResult:
        return ActionResult(
            "wait",
            "skipped_wait",
            reason,
            success=True,
            action="wait",
            dry_run=True,
            message="backend_wait_result",
            duration=0.0,
        )

    def keyevent(self, keycode: str, reason: str = "") -> ActionResult:
        raise AssertionError("keyevent should not be called")

    def reset_cycle(self) -> None:
        self.action_count = 0


class WaitOnceStrategy:
    state = "WAIT"

    def __init__(self) -> None:
        self.action_result: ActionResult | None = None

    def targets(self):
        return ()

    def decide(self, context: StrategyContext) -> StrategyDecision:
        return StrategyDecision.wait(0.0, "runner_wait")

    def on_action_result(self, decision: StrategyDecision, action_result: ActionResult) -> None:
        self.action_result = action_result


class TapMarkerAllowListStrategy:
    state = "WATCH_AD"
    tap_marker_allow_list = frozenset({"close_buttons"})

    def __init__(self) -> None:
        self.action_result: ActionResult | None = None

    def targets(self):
        return ()

    def decide(self, context: StrategyContext) -> StrategyDecision:
        return StrategyDecision.wait(0.0, "unused")

    def on_action_result(self, decision: StrategyDecision, action_result: ActionResult) -> None:
        self.action_result = action_result


def _game(root: Path) -> GameDefinition:
    return GameDefinition("test", root / "config.json", root / "templates")


def _context(detections: dict[str, DetectionResult]) -> StrategyContext:
    return StrategyContext(
        loop_index=1,
        screen_path=Path("screen.png"),
        game=_game(Path(".")),
        detections=detections,
        resolve_template=lambda template: Path(template),
    )


def _detection(
    name: str,
    confidence: float = 0.95,
    *,
    center: tuple[int, int] = (10, 20),
) -> DetectionResult:
    return DetectionResult(
        name=name,
        template=Path(f"{name}.png"),
        confidence=confidence,
        center=center,
        top_left=(center[0] - 5, center[1] - 5),
        size=(10, 10),
        scale=1.0,
        threshold=0.8,
    )


def _event(events_path: Path, event_name: str) -> dict[str, object]:
    for line in events_path.read_text(encoding="utf-8").splitlines():
        event = json.loads(line)
        if event.get("event") == event_name:
            return event
    raise AssertionError(f"{event_name} event not found")

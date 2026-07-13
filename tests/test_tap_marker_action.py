from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from cats_automatic.actions import ActionResult, DryRunBackend, TapAction, execute_action
from cats_automatic.backends.static_image_capture import StaticImageCaptureBackend
from cats_automatic.game_base import GameDefinition
from cats_automatic.run_recording import RunRecorder
from cats_automatic.strategy_base import DetectionResult, StrategyContext, StrategyDecision, TargetSpec
from cats_automatic.strategy_runner import StrategyRunner
from cats_automatic.vision import MatchResult


def test_allow_list_marker_dry_run_success() -> None:
    backend = NoTapDryRunBackend()

    result = execute_action(
        _tap_marker_action("close_end_2"),
        backend,
        state_result=_state({"close_end_2": _detection("close_end_2", center=(30, 40))}),
        allowed_markers=frozenset({"close_end_2"}),
        dry_run=True,
    )

    assert result.success is True
    assert result.action == "tap_marker"
    assert result.dry_run is True
    assert result.clicked_pos == (30, 40)
    assert result.error == ""
    assert backend.taps == []


def test_non_allow_list_marker_is_rejected() -> None:
    result = execute_action(
        _tap_marker_action("ad_entry"),
        DryRunBackend(),
        state_result=_state({"ad_entry": _detection("ad_entry")}),
        allowed_markers=frozenset({"close_end_2"}),
        dry_run=True,
    )

    assert result.success is False
    assert result.error == "marker_not_allowed"


def test_marker_not_found() -> None:
    result = execute_action(
        _tap_marker_action("close_end_2"),
        DryRunBackend(),
        state_result=_state({}),
        allowed_markers=frozenset({"close_end_2"}),
        dry_run=True,
    )

    assert result.error == "marker_not_found"


def test_confidence_below_threshold() -> None:
    result = execute_action(
        _tap_marker_action("close_end_2", min_confidence=0.9),
        DryRunBackend(),
        state_result=_state({"close_end_2": _detection("close_end_2", confidence=0.5)}),
        allowed_markers=frozenset({"close_end_2"}),
        dry_run=True,
    )

    assert result.error == "confidence_too_low"


def test_marker_has_no_coordinates() -> None:
    result = execute_action(
        _tap_marker_action("close_end_2"),
        DryRunBackend(),
        state_result=_state({"close_end_2": {"confidence": 0.95}}),
        allowed_markers=frozenset({"close_end_2"}),
        dry_run=True,
    )

    assert result.error == "marker_has_no_coordinates"


def test_coordinates_out_of_bounds() -> None:
    result = execute_action(
        _tap_marker_action("close_end_2"),
        DryRunBackend(),
        state_result=_state(
            {"close_end_2": _detection("close_end_2", center=(120, 40))},
            image_size=(100, 100),
        ),
        allowed_markers=frozenset({"close_end_2"}),
        dry_run=True,
    )

    assert result.error == "coordinates_out_of_bounds"
    assert result.clicked_pos == (120, 40)


def test_offset_after_coordinates_out_of_bounds() -> None:
    result = execute_action(
        _tap_marker_action("close_end_2", offset_x=20),
        DryRunBackend(),
        state_result=_state(
            {"close_end_2": _detection("close_end_2", center=(90, 40))},
            image_size=(100, 100),
        ),
        allowed_markers=frozenset({"close_end_2"}),
        dry_run=True,
    )

    assert result.error == "coordinates_out_of_bounds"
    assert result.clicked_pos == (110, 40)


def test_dry_run_records_clicked_pos_without_adb() -> None:
    backend = NoTapDryRunBackend()

    result = execute_action(
        _tap_marker_action("close_end_2", offset_x=2, offset_y=-3),
        backend,
        state_result=_state({"close_end_2": _detection("close_end_2", center=(30, 40))}),
        allowed_markers=frozenset({"close_end_2"}),
        dry_run=True,
    )

    assert result.clicked_pos == (32, 37)
    assert "dry_run_skipped_adb_tap" in result.message
    assert backend.taps == []


def test_fallback_to_best_marker_false_does_not_fallback() -> None:
    result = execute_action(
        _tap_marker_action("close_end_2", fallback_to_best_marker=False),
        DryRunBackend(),
        state_result=_state(
            {"close_end_3": _detection("close_end_3", center=(22, 33))},
            best_marker="close_end_3",
        ),
        allowed_markers=frozenset({"close_end_2", "close_end_3"}),
        dry_run=True,
    )

    assert result.error == "marker_not_found"


def test_fallback_true_with_allowed_best_marker_succeeds() -> None:
    result = execute_action(
        _tap_marker_action("close_end_2", fallback_to_best_marker=True),
        DryRunBackend(),
        state_result=_state(
            {"close_end_3": _detection("close_end_3", center=(22, 33))},
            best_marker="close_end_3",
        ),
        allowed_markers=frozenset({"close_end_2", "close_end_3"}),
        dry_run=True,
    )

    assert result.success is True
    assert result.clicked_pos == (22, 33)


def test_fallback_true_with_disallowed_best_marker_is_rejected() -> None:
    result = execute_action(
        _tap_marker_action("close_end_2", fallback_to_best_marker=True),
        DryRunBackend(),
        state_result=_state(
            {"ad_entry": _detection("ad_entry", center=(22, 33))},
            best_marker="ad_entry",
        ),
        allowed_markers=frozenset({"close_end_2"}),
        dry_run=True,
    )

    assert result.error == "marker_not_allowed"


def test_non_dry_run_uses_existing_tap_backend() -> None:
    backend = RecordingTapBackend(dry_run=False)

    result = execute_action(
        _tap_marker_action("close_end_2"),
        backend,
        state_result=_state({"close_end_2": _detection("close_end_2", center=(30, 40))}),
        allowed_markers=frozenset({"close_end_2"}),
        dry_run=False,
    )

    assert result.success is True
    assert result.dry_run is False
    assert result.clicked_pos == (30, 40)
    assert [(tap.x, tap.y, tap.confidence) for tap in backend.taps] == [(30, 40, 0.95)]


def test_non_dry_run_without_real_backend_is_rejected() -> None:
    result = execute_action(
        _tap_marker_action("close_end_2"),
        DryRunBackend(),
        state_result=_state({"close_end_2": _detection("close_end_2", center=(30, 40))}),
        allowed_markers=frozenset({"close_end_2"}),
        dry_run=False,
    )

    assert result.success is False
    assert result.error == "adb_backend_unavailable"


def test_failed_backend_tap_maps_to_adb_tap_failed() -> None:
    backend = RecordingTapBackend(dry_run=False, result=ActionResult("adb_tap", "adb_tap_failed", "boom"))

    result = execute_action(
        _tap_marker_action("close_end_2"),
        backend,
        state_result=_state({"close_end_2": _detection("close_end_2", center=(30, 40))}),
        allowed_markers=frozenset({"close_end_2"}),
        dry_run=False,
    )

    assert result.success is False
    assert result.error == "adb_tap_failed"


def test_strategy_runner_records_tap_marker_action_result(tmp_path: Path) -> None:
    screen = tmp_path / "screen.png"
    template = tmp_path / "templates" / "close_end_2.png"
    template.parent.mkdir()
    Image.new("RGB", (100, 80), "white").save(screen)
    Image.new("RGB", (10, 8), "black").save(template)
    recorder = RunRecorder(
        output_root=tmp_path / "output" / "runs",
        capture_backend="static",
        strategy_name="tap_marker_once",
    )
    strategy = TapMarkerOnceStrategy()
    backend = NoTapDryRunBackend()
    runner = StrategyRunner(
        game=_game(tmp_path),
        strategy=strategy,
        capture_backend=StaticImageCaptureBackend(screen),
        action_backend=backend,
        root=tmp_path,
        output_dir=tmp_path / "output" / "strategy",
        max_loops=1,
        run_recorder=recorder,
        matcher=lambda *_, **__: MatchResult(confidence=0.96, top_left=(20, 30), size=(10, 8)),
        sleep=lambda _seconds: None,
    )

    runner.run()
    recorder.finish("test_done")

    assert backend.taps == []
    assert strategy.action_result is not None
    assert strategy.action_result.clicked_pos == (25, 34)
    event = _event(recorder.events_path, "action")
    assert event["decision"] == "tap_marker"
    assert event["action_result"]["clicked_pos"] == [25, 34]
    assert event["action_result"]["message"].startswith("dry_run_skipped_adb_tap")


class NoTapDryRunBackend(DryRunBackend):
    def __init__(self) -> None:
        super().__init__()
        self.taps: list[TapAction] = []

    def tap(self, action: TapAction) -> ActionResult:
        self.taps.append(action)
        raise AssertionError("dry-run tap_marker must not call backend.tap")


class RecordingTapBackend:
    def __init__(self, *, dry_run: bool, result: ActionResult | None = None) -> None:
        self.dry_run = dry_run
        self.result = result
        self.action_count = 0
        self.taps: list[TapAction] = []

    def click(self, action):
        raise AssertionError("tap_marker should use tap backend")

    def tap(self, action: TapAction) -> ActionResult:
        self.action_count += 1
        self.taps.append(action)
        if self.result is not None:
            return self.result
        return ActionResult("adb_tap", "executed", action.reason)

    def wait(self, seconds: float, reason: str = "") -> ActionResult:
        raise AssertionError("wait should not be called")

    def keyevent(self, keycode: str, reason: str = "") -> ActionResult:
        raise AssertionError("keyevent should not be called")

    def reset_cycle(self) -> None:
        self.action_count = 0


class TapMarkerOnceStrategy:
    state = "START"

    def __init__(self) -> None:
        self.action_result: ActionResult | None = None

    def targets(self):
        return (TargetSpec("close_end_2", "close_end_2.png", 0.8),)

    def decide(self, context: StrategyContext) -> StrategyDecision:
        return StrategyDecision.action(
            "tap_marker",
            params={"marker": "close_end_2", "min_confidence": 0.8},
            reason="close_ad_marker_detected",
        )

    def on_action_result(self, decision: StrategyDecision, action_result: ActionResult) -> None:
        self.action_result = action_result


def _tap_marker_action(
    marker: str,
    *,
    min_confidence: float = 0.8,
    fallback_to_best_marker: bool = False,
    offset_x: int = 0,
    offset_y: int = 0,
) -> dict[str, object]:
    return {
        "name": "tap_marker",
        "params": {
            "marker": marker,
            "min_confidence": min_confidence,
            "fallback_to_best_marker": fallback_to_best_marker,
            "offset_x": offset_x,
            "offset_y": offset_y,
        },
        "reason": "close_ad_marker_detected",
    }


def _state(
    detections: dict[str, object],
    *,
    best_marker: str | None = None,
    image_size: tuple[int, int] = (100, 100),
) -> dict[str, object]:
    return {
        "detections": detections,
        "best_marker": best_marker,
        "image_size": image_size,
    }


def _detection(
    name: str,
    *,
    confidence: float = 0.95,
    center: tuple[int, int] = (30, 40),
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


def _game(root: Path) -> GameDefinition:
    return GameDefinition("test", root / "config.json", root / "templates")


def _event(events_path: Path, event_name: str) -> dict[str, object]:
    for line in events_path.read_text(encoding="utf-8").splitlines():
        event = json.loads(line)
        if event.get("event") == event_name:
            return event
    raise AssertionError(f"{event_name} event not found")

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from cats_automatic.actions import ActionResult, DEFAULT_TAP_MARKER_ALLOW_LIST, DryRunBackend, TapAction
from cats_automatic.backends.static_image_capture import StaticImageCaptureBackend
from cats_automatic.game_base import GameDefinition
from cats_automatic.run_recording import RunRecorder
from cats_automatic.strategy_base import DetectionResult, StrategyContext
from cats_automatic.strategy_runner import StrategyRunner
from external_strategies.minimal_dry_run.strategy import (
    CLOSE_AD_MARKER_PRIORITY,
    CLOSE_AD_MIN_CONFIDENCE,
    MAX_CLOSE_AD_ATTEMPTS,
    Strategy,
    select_close_ad_marker,
)


def test_single_qualified_close_marker_outputs_tap_marker() -> None:
    strategy = Strategy()
    strategy.current_step = "WATCH_AD"

    decision = strategy.decide(_context({"close_end_2": _detection("close_end_2")}))

    assert decision.action_name == "tap_marker"
    assert decision.action_params["marker"] == "close_end_2"
    assert decision.action_params["fallback_to_best_marker"] is False
    assert decision.reason == "close_ad_marker_selected"


def test_multiple_close_markers_use_explicit_priority() -> None:
    selected = select_close_ad_marker(
        {
            "close_end_1": _detection("close_end_1", confidence=0.99),
            "close_end_2": _detection("close_end_2", confidence=0.81),
        },
        DEFAULT_TAP_MARKER_ALLOW_LIST,
        CLOSE_AD_MIN_CONFIDENCE,
        CLOSE_AD_MARKER_PRIORITY,
    )

    assert selected is not None
    assert selected.name == "close_end_2"


def test_same_priority_uses_higher_confidence() -> None:
    selected = select_close_ad_marker(
        {
            "close_user_2_1": _detection("close_user_2_1", confidence=0.82),
            "close_user_2_2": _detection("close_user_2_2", confidence=0.96),
        },
        DEFAULT_TAP_MARKER_ALLOW_LIST,
        CLOSE_AD_MIN_CONFIDENCE,
        CLOSE_AD_MARKER_PRIORITY,
    )

    assert selected is not None
    assert selected.name == "close_user_2_2"


def test_non_allow_list_marker_is_ignored() -> None:
    selected = select_close_ad_marker(
        {"ad_entry": _detection("ad_entry", confidence=0.99)},
        DEFAULT_TAP_MARKER_ALLOW_LIST,
        CLOSE_AD_MIN_CONFIDENCE,
        CLOSE_AD_MARKER_PRIORITY,
    )

    assert selected is None


def test_below_threshold_marker_is_ignored() -> None:
    selected = select_close_ad_marker(
        {"close_end_2": _detection("close_end_2", confidence=0.79)},
        DEFAULT_TAP_MARKER_ALLOW_LIST,
        CLOSE_AD_MIN_CONFIDENCE,
        CLOSE_AD_MARKER_PRIORITY,
    )

    assert selected is None


def test_no_qualified_marker_returns_wait() -> None:
    strategy = Strategy()
    strategy.current_step = "WATCH_AD"

    decision = strategy.decide(_context({"AD_CLOSE_PAGE": _detection("AD_CLOSE_PAGE")}))

    assert decision.action_name == "wait"
    assert decision.reason == "no_safe_close_ad_marker"


def test_does_not_use_arbitrary_best_marker() -> None:
    strategy = Strategy()
    strategy.current_step = "WATCH_AD"

    decision = strategy.decide(
        _context(
            {
                "AD_CLOSE_PAGE": _detection("AD_CLOSE_PAGE", confidence=0.9),
                "ad_entry": _detection("ad_entry", confidence=0.99),
            }
        )
    )

    assert decision.action_name == "wait"
    assert decision.reason == "no_safe_close_ad_marker"


def test_dry_run_close_ad_does_not_call_adb_and_records_clicked_pos(tmp_path: Path) -> None:
    screen = tmp_path / "screen.png"
    Image.new("RGB", (100, 80), "white").save(screen)
    strategy = Strategy()
    strategy.current_step = "WATCH_AD"
    backend = NoTapDryRunBackend()
    recorder = RunRecorder(
        output_root=tmp_path / "output" / "runs",
        capture_backend="static",
        strategy_name="minimal_dry_run",
    )
    runner = StrategyRunner(
        game=_game(tmp_path),
        strategy=strategy,
        capture_backend=StaticImageCaptureBackend(screen),
        action_backend=backend,
        root=tmp_path,
        output_dir=tmp_path / "output" / "strategy",
        max_loops=1,
        run_recorder=recorder,
        matcher=lambda *_, **__: None,
        sleep=lambda _seconds: None,
    )
    runner._current_screen_path = screen
    runner._current_image_size = (100, 80)

    decision = strategy.decide(_context({"close_end_2": _detection("close_end_2", center=(25, 30))}, screen))
    runner._execute_decision(decision, {"close_end_2": _detection("close_end_2", center=(25, 30))})

    assert backend.taps == []
    assert strategy.current_step == "CLOSE_AD"
    event = _event(recorder.events_path, "minimal_dry_run_loop")
    assert event["action"] == "tap_marker"
    assert event["action_result"]["clicked_pos"] == [25, 30]
    assert event["action_result"]["message"].startswith("dry_run_skipped_adb_tap")


def test_tap_success_does_not_jump_to_claim_reward() -> None:
    strategy = Strategy()
    strategy.current_step = "WATCH_AD"
    decision = strategy.decide(_context({"close_end_2": _detection("close_end_2")}))

    strategy.on_action_result(
        decision,
        ActionResult(
            "tap_marker",
            "skipped_dry_run",
            "close_ad_marker_selected",
            success=True,
            action="tap_marker",
            dry_run=True,
            clicked_pos=(30, 40),
        ),
    )

    assert strategy.current_step == "CLOSE_AD"
    assert strategy.current_step != "CLAIM_REWARD"


def test_next_reward_page_updates_to_claim_reward() -> None:
    strategy = Strategy()
    strategy.current_step = "WATCH_AD"
    close = strategy.decide(_context({"close_end_2": _detection("close_end_2")}))
    strategy.on_action_result(
        close,
        ActionResult("tap_marker", "skipped_dry_run", success=True, action="tap_marker", dry_run=True),
    )
    strategy.consume_strategy_events()

    reward = strategy.decide(_context({"REWARD_PAGE": _detection("REWARD_PAGE")}))
    strategy.on_action_result(
        reward,
        ActionResult("claim_reward", "unknown_action", success=False, action="claim_reward", dry_run=True),
    )

    assert strategy.current_step == "CLAIM_REWARD"
    event = strategy.consume_strategy_events()[0]
    assert event["step"] == "CLOSE_AD"
    assert event["state"] == "REWARD_PAGE"
    assert event["next_step"] == "CLAIM_REWARD"


def test_ad_close_page_is_limited_by_max_attempts() -> None:
    strategy = Strategy()
    strategy.current_step = "CLOSE_AD"
    strategy.close_ad_attempts = MAX_CLOSE_AD_ATTEMPTS

    decision = strategy.decide(_context({"close_end_2": _detection("close_end_2")}))

    assert decision.action_name == "wait"
    assert decision.reason == "close_ad_attempt_limit_reached"


def test_same_marker_same_screenshot_waits_for_next_capture() -> None:
    strategy = Strategy()
    strategy.current_step = "CLOSE_AD"
    screen_path = Path("same-screen.png")
    first = strategy.decide(_context({"close_end_2": _detection("close_end_2")}, screen_path))
    strategy.on_action_result(
        first,
        ActionResult("tap_marker", "skipped_dry_run", success=True, action="tap_marker", dry_run=True),
    )
    strategy.consume_strategy_events()

    second = strategy.decide(_context({"close_end_2": _detection("close_end_2")}, screen_path))

    assert second.action_name == "wait"
    assert second.reason == "close_ad_wait_next_screenshot"


def test_runner_records_close_ad_decision_fields(tmp_path: Path) -> None:
    screen = tmp_path / "screen.png"
    template = tmp_path / "templates" / "close-end-2.png"
    template.parent.mkdir()
    Image.new("RGB", (100, 80), "white").save(screen)
    Image.new("RGB", (10, 8), "black").save(template)
    strategy = Strategy()
    strategy.current_step = "WATCH_AD"
    backend = NoTapDryRunBackend()
    recorder = RunRecorder(
        output_root=tmp_path / "output" / "runs",
        capture_backend="static",
        strategy_name="minimal_dry_run",
    )
    runner = StrategyRunner(
        game=_game(tmp_path),
        strategy=strategy,
        capture_backend=StaticImageCaptureBackend(screen),
        action_backend=backend,
        root=tmp_path,
        output_dir=tmp_path / "output" / "strategy",
        max_loops=1,
        run_recorder=recorder,
        matcher=lambda *_, **__: _match(),
        sleep=lambda _seconds: None,
    )

    runner.run()
    recorder.finish("test_done")

    loop_event = _event(recorder.events_path, "minimal_dry_run_loop")
    assert loop_event["current_step"] == "WATCH_AD"
    assert loop_event["state"] == "AD_CLOSE_PAGE"
    assert loop_event["selected_marker"] == "close_end_2"
    assert loop_event["selected_confidence"] == 0.96
    assert loop_event["action"] == "tap_marker"
    assert loop_event["action_reason"] == "close_ad_marker_selected"
    assert loop_event["close_ad_attempts"] == 0
    assert loop_event["next_step"] == "CLOSE_AD"
    assert loop_event["step_changed"] is True
    assert loop_event["screenshot_path"].endswith("loop-001.png")
    assert loop_event["action_result"]["clicked_pos"] == [25, 34]


class NoTapDryRunBackend(DryRunBackend):
    def __init__(self) -> None:
        super().__init__()
        self.taps: list[TapAction] = []

    def tap(self, action: TapAction) -> ActionResult:
        self.taps.append(action)
        raise AssertionError("dry-run close_ad must not call backend.tap")


def _context(
    detections: dict[str, DetectionResult],
    screen_path: Path = Path("screen.png"),
) -> StrategyContext:
    return StrategyContext(
        loop_index=1,
        screen_path=screen_path,
        game=_game(Path(".")),
        detections=detections,
        resolve_template=lambda template: Path(template),
    )


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


def _match():
    from cats_automatic.vision import MatchResult

    return MatchResult(confidence=0.96, top_left=(20, 30), size=(10, 8))


def _event(events_path: Path, event_name: str) -> dict[str, object]:
    for line in events_path.read_text(encoding="utf-8").splitlines():
        event = json.loads(line)
        if event.get("event") == event_name:
            return event
    raise AssertionError(f"{event_name} event not found")

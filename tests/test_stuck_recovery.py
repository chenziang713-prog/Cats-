from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from cats_automatic.actions import ActionResult, DryRunBackend
from cats_automatic.backends.static_image_capture import StaticImageCaptureBackend
from cats_automatic.game_base import GameDefinition
from cats_automatic.run_recording import RunRecorder
from cats_automatic.strategy_base import StrategyContext, StrategyDecision
from cats_automatic.strategy_runner import StrategyRunner
from cats_automatic.stuck_recovery import StuckRecoveryConfig, StuckRecoveryTracker


def test_step_change_resets_counts() -> None:
    tracker = _tracker()
    tracker.observe(**_obs(loop_index=1, current_step="START", step_changed=False))

    tracker.observe(**_obs(loop_index=2, current_step="GO_HOME", step_changed=True))

    assert tracker.state.same_step_loops == 1
    assert tracker.state.last_progress_loop == 2


def test_state_change_counts_as_progress() -> None:
    tracker = _tracker()
    tracker.observe(**_obs(loop_index=1, current_state="WATCH_AD"))

    tracker.observe(**_obs(loop_index=2, current_state="AD_CLOSE_PAGE"))

    assert tracker.state.same_state_loops == 1
    assert tracker.state.last_progress_loop == 2


def test_wait_success_is_not_progress() -> None:
    tracker = _tracker()

    tracker.observe(**_obs(loop_index=1, action="wait", action_result=_result("wait")))
    tracker.observe(**_obs(loop_index=2, action="wait", action_result=_result("wait")))

    assert tracker.state.same_step_loops == 2
    assert tracker.state.last_progress_loop == 0


def test_tap_marker_success_without_state_change_is_not_page_progress() -> None:
    tracker = _tracker()

    tracker.observe(**_obs(loop_index=1, action="tap_marker", action_result=_result("tap_marker")))
    tracker.observe(**_obs(loop_index=2, action="tap_marker", action_result=_result("tap_marker")))

    assert tracker.state.same_state_loops == 2
    assert tracker.state.last_progress_loop == 0


def test_same_step_threshold_triggers_step_stuck() -> None:
    tracker = StuckRecoveryTracker(StuckRecoveryConfig(same_step_threshold=2))
    tracker.observe(**_obs(loop_index=1))

    plan = tracker.observe(**_obs(loop_index=2, screenshot_path="screen-2.png"))

    assert plan is not None
    assert plan.stuck_reason == "step_stuck"


def test_same_state_threshold_triggers_state_stuck() -> None:
    tracker = StuckRecoveryTracker(StuckRecoveryConfig(same_state_threshold=2, same_step_threshold=99))
    tracker.observe(**_obs(loop_index=1))

    plan = tracker.observe(**_obs(loop_index=2, screenshot_path="screen-2.png"))

    assert plan is not None
    assert plan.stuck_reason == "state_stuck"


def test_unknown_page_short_stuck_uses_level_1_wait() -> None:
    tracker = StuckRecoveryTracker(
        StuckRecoveryConfig(unknown_level_1_threshold=2, unknown_level_2_threshold=5)
    )
    tracker.observe(**_obs(loop_index=1, current_state="UNKNOWN_PAGE"))

    plan = tracker.observe(**_obs(loop_index=2, current_state="UNKNOWN_PAGE", screenshot_path="screen-2.png"))

    assert plan is not None
    assert plan.recovery_level == 1
    assert plan.recovery_action == "wait"
    assert plan.decision is not None
    assert plan.decision.reason == "recovery_level_1_wait"


def test_unknown_page_higher_threshold_uses_press_back() -> None:
    tracker = StuckRecoveryTracker(
        StuckRecoveryConfig(
            unknown_level_1_threshold=2,
            unknown_level_2_threshold=3,
            recovery_cooldown_loops=0,
        )
    )
    tracker.observe(**_obs(loop_index=1, current_state="UNKNOWN_PAGE", screenshot_path="screen-1.png"))
    tracker.observe(**_obs(loop_index=2, current_state="UNKNOWN_PAGE", screenshot_path="screen-2.png"))

    plan = tracker.observe(**_obs(loop_index=3, current_state="UNKNOWN_PAGE", screenshot_path="screen-3.png"))

    assert plan is not None
    assert plan.recovery_level == 2
    assert plan.recovery_action == "press_back"
    assert plan.decision is not None
    assert plan.decision.action_name == "press_back"


def test_close_ad_attempt_limit_maps_to_stuck_reason() -> None:
    tracker = StuckRecoveryTracker(StuckRecoveryConfig(close_ad_attempt_limit=3))

    plan = tracker.observe(**_obs(loop_index=1, close_ad_attempts=3))

    assert plan is not None
    assert plan.stuck_reason == "close_ad_attempt_limit"


def test_repeated_action_reaches_limit() -> None:
    tracker = StuckRecoveryTracker(
        StuckRecoveryConfig(repeated_action_threshold=2, same_step_threshold=99, same_state_threshold=99)
    )
    tracker.observe(**_obs(loop_index=1, action="tap_marker", clicked_marker="close_end_2"))

    plan = tracker.observe(
        **_obs(
            loop_index=2,
            action="tap_marker",
            clicked_marker="close_end_2",
            screenshot_path="screen-1.png",
        )
    )

    assert plan is not None
    assert plan.stuck_reason == "repeated_action"


def test_same_screenshot_does_not_repeat_recovery() -> None:
    tracker = StuckRecoveryTracker(
        StuckRecoveryConfig(unknown_level_1_threshold=1, recovery_cooldown_loops=2)
    )
    first = tracker.observe(**_obs(loop_index=1, current_state="UNKNOWN_PAGE", screenshot_path="same.png"))

    second = tracker.observe(**_obs(loop_index=2, current_state="UNKNOWN_PAGE", screenshot_path="same.png"))

    assert first is not None
    assert second is None


def test_level_3_resets_step_to_go_home_without_faking_state() -> None:
    tracker = StuckRecoveryTracker(
        StuckRecoveryConfig(
            unknown_level_1_threshold=1,
            max_same_recovery_reason=0,
        )
    )

    plan = tracker.observe(
        **_obs(loop_index=1, current_step="CLOSE_AD", current_state="UNKNOWN_PAGE")
    )

    assert plan is not None
    assert plan.recovery_level == 3
    assert plan.event["step_after_recovery"] == "GO_HOME"
    assert plan.event["state"] == "UNKNOWN_PAGE"


def test_runner_writes_recovery_event_and_dry_run_press_back_does_not_call_adb(tmp_path: Path) -> None:
    screen = tmp_path / "screen.png"
    Image.new("RGB", (80, 60), "white").save(screen)
    strategy = UnknownWaitStrategy()
    backend = NoAdbDryRunBackend()
    recorder = RunRecorder(
        output_root=tmp_path / "output" / "runs",
        capture_backend="static",
        strategy_name="unknown_wait",
    )
    runner = StrategyRunner(
        game=_game(tmp_path),
        strategy=strategy,
        capture_backend=StaticImageCaptureBackend(screen),
        action_backend=backend,
        root=tmp_path,
        output_dir=tmp_path / "output" / "strategy",
        max_loops=4,
        run_recorder=recorder,
        sleep=lambda _seconds: None,
    )
    runner.stuck_recovery = StuckRecoveryTracker(
        StuckRecoveryConfig(
            unknown_level_1_threshold=1,
            unknown_level_2_threshold=2,
            recovery_cooldown_loops=0,
            same_step_threshold=99,
            same_state_threshold=99,
        )
    )

    runner.run()
    recorder.finish("test_done")

    events = _events(recorder.events_path)
    stuck_events = [event for event in events if event.get("event") == "stuck_detected"]
    recovery_events = [event for event in events if event.get("event") == "recovery_action"]
    assert stuck_events
    assert any(event["recovery_level"] == 2 for event in stuck_events)
    assert any(event["recovery_action"] == "press_back" for event in recovery_events)
    assert backend.keyevents == []


class UnknownWaitStrategy:
    state = "WATCH_AD"

    def __init__(self) -> None:
        self.last_monitor_payload: dict[str, object] = {}

    def targets(self):
        return ()

    def decide(self, context: StrategyContext) -> StrategyDecision:
        return StrategyDecision.action("wait", params={"seconds": 0.0}, reason="unknown_wait")

    def on_action_result(self, decision: StrategyDecision, action_result: ActionResult) -> None:
        self.last_monitor_payload = {
            "current_step": "WATCH_AD",
            "step": "WATCH_AD",
            "state": "UNKNOWN_PAGE",
            "action": decision.action_name or decision.kind,
            "step_changed": False,
            "screenshot_path": "screen.png",
            "action_result": action_result.to_dict(),
        }


class NoAdbDryRunBackend(DryRunBackend):
    def __init__(self) -> None:
        super().__init__()
        self.keyevents: list[tuple[str, str]] = []

    def keyevent(self, keycode: str, reason: str = "") -> ActionResult:
        self.keyevents.append((keycode, reason))
        raise AssertionError("dry-run recovery must not call keyevent")


def _tracker() -> StuckRecoveryTracker:
    return StuckRecoveryTracker(
        StuckRecoveryConfig(
            same_step_threshold=99,
            same_state_threshold=99,
            unknown_level_1_threshold=99,
            repeated_action_threshold=99,
        )
    )


def _obs(
    *,
    loop_index: int,
    current_step: str = "WATCH_AD",
    current_state: str = "AD_RUNNING_PAGE",
    action: str = "wait",
    action_result: ActionResult | None = None,
    screenshot_path: str = "screen-1.png",
    step_changed: bool = False,
    clicked_marker: str | None = None,
    close_ad_attempts: int = 0,
) -> dict[str, object]:
    return {
        "loop_index": loop_index,
        "current_step": current_step,
        "current_state": current_state,
        "action": action,
        "action_result": action_result or _result(action),
        "screenshot_path": screenshot_path,
        "step_changed": step_changed,
        "clicked_marker": clicked_marker,
        "close_ad_attempts": close_ad_attempts,
    }


def _result(action: str) -> ActionResult:
    return ActionResult(
        action,
        "skipped_dry_run" if action == "tap_marker" else "skipped_wait",
        success=True,
        action=action,
        dry_run=True,
        clicked_pos=(30, 40) if action == "tap_marker" else None,
    )


def _game(root: Path) -> GameDefinition:
    return GameDefinition("test", root / "config.json", root / "templates")


def _events(events_path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]

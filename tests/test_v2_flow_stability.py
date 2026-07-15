from __future__ import annotations

from pathlib import Path

from PIL import Image

from cats_automatic.actions import ActionResult, DryRunBackend
from cats_automatic.backends import StaticImageCaptureBackend
from cats_automatic.game_base import GameDefinition
from cats_automatic.run_recording import RunRecorder
from cats_automatic.strategy_base import DetectionResult, StrategyContext, StrategyDecision
from cats_automatic.strategy_runner import StrategyRunner
from cats_automatic.display_text import to_display_decision, to_display_phase, to_display_reason, to_display_target
from external_strategies.scrap_then_ad_reward_v2.screen_state_detector import _template_paths_for_marker
from external_strategies.scrap_then_ad_reward_v2.strategy import (
    Strategy,
    accept_observed_state,
    image_fingerprint,
)


def test_observed_state_does_not_directly_modify_current_step() -> None:
    strategy = Strategy()
    strategy.flow_context.current_step = "WATCH_AD"

    strategy.decide(_context({"main-definate": _detection("main-definate", 0.99)}))

    assert strategy.flow_context.observed_state == "HOME"
    assert strategy.flow_context.current_step == "WATCH_AD"


def test_illegal_old_page_keeps_current_step_and_does_not_click_watch_again() -> None:
    strategy = Strategy()
    strategy.flow_context.current_step = "WATCH_AD"

    decision = strategy.decide(_context({"watch_ad_film": _detection("watch_ad_film", 0.93)}))

    assert strategy.flow_context.current_step == "WATCH_AD"
    assert decision.action_name == "wait"
    assert decision.reason == "no_matching_film_flow_rule"


def test_dry_run_taps_do_not_increment_real_attempt_counters() -> None:
    strategy = Strategy()
    strategy.flow_context.current_step = "START_AD"
    decision = strategy.decide(_context({"watch_ad_film": _detection("watch_ad_film", 0.93)}))

    strategy.on_action_result(decision, _result("tap_marker", dry_run=True))

    assert strategy.flow_context.watch_ad_click_attempts == 0
    assert strategy.flow_context.pending_transition == "WATCH_AD"


def test_real_entry_tap_blocks_immediate_duplicate() -> None:
    strategy = Strategy()
    strategy.flow_context.current_step = "ENTER_FILM"
    detections = {
        "main-definate": _detection("main-definate", 0.99),
        "ad_entry": _detection("ad_entry", 0.93),
    }

    first = strategy.decide(_context(detections))
    strategy.on_action_result(first, _result("tap_marker", dry_run=False))
    second = strategy.decide(_context(detections))

    assert first.action_name == "tap_marker"
    assert second.action_name == "wait"
    assert second.reason == "pending_effect_waiting_for_confirmation"
    assert strategy.flow_context.entry_click_attempts == 1


def test_real_entry_tap_retries_once_after_confirmation_timeout() -> None:
    strategy = Strategy()
    strategy.flow_context.current_step = "ENTER_FILM"
    detections = {
        "main-definate": _detection("main-definate", 0.99),
        "ad_entry": _detection("ad_entry", 0.93),
    }

    first = strategy.decide(_context(detections))
    strategy.on_action_result(first, _result("tap_marker", dry_run=False))
    assert strategy.flow_context.pending_effect is not None
    strategy.flow_context.pending_effect = strategy.flow_context.pending_effect._replace(
        confirmation_deadline=0.0
    )
    retry = strategy.decide(_context(detections))
    strategy.on_action_result(retry, _result("tap_marker", dry_run=False))
    assert strategy.flow_context.pending_effect is not None
    strategy.flow_context.pending_effect = strategy.flow_context.pending_effect._replace(
        confirmation_deadline=0.0
    )
    blocked = strategy.decide(_context(detections))

    assert retry.action_name == "tap_marker"
    assert blocked.action_name == "wait"
    assert blocked.reason == "pending_effect_duplicate_blocked"
    assert strategy.flow_context.entry_click_attempts == 2


def test_real_watch_tap_blocks_network_flashback_duplicate() -> None:
    strategy = Strategy()
    strategy.flow_context.current_step = "START_AD"
    detections = {"watch_ad_film": _detection("watch_ad_film", 0.93)}

    first = strategy.decide(_context(detections))
    strategy.on_action_result(first, _result("tap_marker", dry_run=False))
    second = strategy.decide(_context(detections))

    assert first.action_name == "tap_marker"
    assert second.action_name == "wait"
    assert strategy.flow_context.watch_ad_click_attempts == 1


def test_reward_back_blocks_immediate_second_back() -> None:
    strategy = Strategy()
    strategy.flow_context.current_step = "CLAIM_REWARD"
    detections = {"get_reward": _detection("get_reward", 0.91)}

    first = strategy.decide(_context(detections))
    strategy.on_action_result(first, _result("press_back", dry_run=False))
    second = strategy.decide(_context(detections))

    assert first.action_name == "press_back"
    assert second.action_name == "wait"
    assert second.reason == "pending_effect_waiting_for_confirmation"
    assert strategy.flow_context.reward_click_attempts == 1


def test_executed_tap_increments_attempt_counter() -> None:
    strategy = Strategy()
    strategy.flow_context.current_step = "START_AD"
    decision = strategy.decide(_context({"watch_ad_film": _detection("watch_ad_film", 0.93)}))

    strategy.on_action_result(decision, _result("tap_marker", dry_run=False))

    assert strategy.flow_context.watch_ad_click_attempts == 1


def test_recovery_override_cancels_pending_close_action() -> None:
    strategy = Strategy()
    strategy.flow_context.current_step = "WATCH_AD"
    close = _close_detection(0.96)
    decision = strategy.decide(_context({"close_buttons": close}))

    strategy.on_decision_selected(StrategyDecision.action("wait", reason="recovery_level_1_wait"))
    strategy.on_action_result(decision, _result("tap_marker", dry_run=True))

    assert strategy.flow_context.close_attempt_count == 0
    assert strategy.flow_context.pending_decision_id is None
    assert any(event["event"] == "scrap_then_ad_reward_v2_decision_overridden" for event in strategy.consume_strategy_events())


def test_decision_id_mismatch_does_not_advance_state() -> None:
    strategy = Strategy()
    decision = strategy.decide(_context({}))
    strategy.on_decision_selected(decision)
    mismatched = StrategyDecision.action(
        "no_action",
        params={"decision_id": "wrong"},
        reason=decision.reason,
    )

    strategy.on_action_result(mismatched, _result("no_action", dry_run=True))

    assert strategy.flow_context.current_step == "START"
    assert strategy.flow_context.pending_decision_id is not None


def test_late_stage_recovery_locks_are_active() -> None:
    strategy = Strategy()
    for step, expected in {
        "WATCH_AD": "v2_preserve_watch_ad",
        "CLOSE_AD_DOING": "v2_preserve_close_ad",
        "CLAIM_REWARD": "v2_preserve_claim_reward",
        "RETURN_HOME": "v2_preserve_return_home",
    }.items():
        strategy.flow_context.current_step = step
        assert strategy.recovery_stage_lock() == expected


def test_level3_reset_is_blocked_in_late_stage() -> None:
    strategy = Strategy()
    strategy.flow_context.current_step = "CLAIM_REWARD"

    strategy.reset_for_recovery("GO_HOME")

    assert strategy.flow_context.current_step == "CLAIM_REWARD"


def test_error_popup_is_overlay_not_main_step() -> None:
    acceptance = accept_observed_state(
        current_step="CLAIM_REWARD",
        observed_state="ERROR_POPUP_PAGE",
        previous_accepted_state="RIGHT_AD_REWARD_SUCCESS_PAGE",
        consecutive_count=1,
        detections={},
        confidence=0.95,
    )

    assert acceptance.overlay_state == "ERROR_POPUP_PAGE"
    assert acceptance.accepted_state == "RIGHT_AD_REWARD_SUCCESS_PAGE"


def test_home_at_claim_reward_does_not_press_back() -> None:
    strategy = Strategy()
    strategy.flow_context.current_step = "CLAIM_REWARD"

    decision = strategy.decide(_context({"main-definate": _detection("main-definate", 0.99)}))

    assert decision.action_name == "no_action"
    assert decision.reason == "reward_already_returned_home"


def test_home_at_return_home_completes() -> None:
    strategy = Strategy()
    strategy.flow_context.current_step = "RETURN_HOME"

    decision = strategy.decide(_context({"main-definate": _detection("main-definate", 0.99)}))

    assert decision.kind == "complete"
    assert strategy.flow_context.current_step == "FINISH"


def test_same_image_different_paths_have_same_fingerprint(tmp_path: Path) -> None:
    first = tmp_path / "a.png"
    second = tmp_path / "b.png"
    Image.new("RGB", (8, 8), "red").save(first)
    Image.new("RGB", (8, 8), "red").save(second)

    assert image_fingerprint(first) == image_fingerprint(second)


def test_network_flashback_overlay_sequence_finishes_without_rewatch_or_home_back() -> None:
    strategy = Strategy()
    actions: list[str] = []
    reasons: list[str] = []

    def step(detections: dict[str, DetectionResult]) -> StrategyDecision:
        decision = strategy.decide(_context(detections))
        actions.append(decision.action_name or decision.kind)
        reasons.append(decision.reason)
        if decision.kind != "complete":
            strategy.on_action_result(decision, _result(decision.action_name or decision.kind, dry_run=True))
        return decision

    step({})
    step({"main-definate": _detection("main-definate", 0.99), "ad_entry": _detection("ad_entry", 0.93)})
    step({"main-definate": _detection("main-definate", 0.99), "ad_entry": _detection("ad_entry", 0.93)})
    step({"watch_ad_film": _detection("watch_ad_film", 0.93)})
    step({"watch_ad_film": _detection("watch_ad_film", 0.93)})
    step({})
    step({"close_buttons": _close_detection(0.96)})
    step({"watch_ad_film": _detection("watch_ad_film", 0.93)})
    step({"error_popups": _detection("error_popups", 0.95), "error_buttons": _detection("error_buttons", 0.96)})
    step({"get_reward": _detection("get_reward", 0.91)})
    step({"main-definate": _detection("main-definate", 0.99)})
    final = step({"main-definate": _detection("main-definate", 0.99)})

    assert final.kind == "complete"
    assert strategy.flow_context.current_step == "FINISH"
    assert "watch_ad_film_marker_selected" in reasons
    assert reasons.count("watch_ad_film_marker_selected") == 1
    assert "reward_success_press_back" not in reasons[-2:]


def test_max_loops_unfinished_is_not_completed(tmp_path: Path) -> None:
    screen = tmp_path / "screen.png"
    Image.new("RGB", (20, 20), "black").save(screen)
    recorder = RunRecorder(
        output_root=tmp_path / "runs",
        capture_backend="static",
        strategy_name="never_finish",
        run_id="never-finish",
    )
    runner = StrategyRunner(
        game=GameDefinition("test", tmp_path / "config.json", tmp_path),
        strategy=NeverFinishStrategy(),
        capture_backend=StaticImageCaptureBackend(screen),
        action_backend=DryRunBackend(),
        root=tmp_path,
        output_dir=tmp_path / "output",
        max_loops=1,
        run_recorder=recorder,
        stop_file=None,
        sleep=lambda _: None,
    )

    runner.run()

    assert "stop_reason: max_loops_reached" in recorder.summary_path.read_text(encoding="utf-8")


def test_v2_display_text_has_no_untranslated_fallbacks() -> None:
    values = [
        to_display_target("main-definate"),
        to_display_target("watch_ad_film"),
        to_display_target("close_buttons"),
        to_display_target("get_reward"),
        to_display_decision("tap_marker"),
        to_display_decision("press_back"),
        to_display_phase("WATCH_AD"),
        to_display_reason("wait_for_ad_close_marker"),
    ]

    assert all("未翻译" not in value for value in values)


class NeverFinishStrategy:
    handles_reward_cycle_completion = True
    state = "START"

    def targets(self):
        return []

    def decide(self, _context):
        return StrategyDecision.action("wait", reason="never_finish", wait_seconds=0.0)


def _context(detections: dict[str, DetectionResult]) -> StrategyContext:
    return StrategyContext(
        loop_index=1,
        screen_path=Path("screen.png"),
        game=GameDefinition("cats", Path("config.json"), Path("templates")),
        detections=detections,
        resolve_template=lambda value: Path(value),
    )


def _detection(name: str, confidence: float) -> DetectionResult:
    return DetectionResult(
        name=name,
        template=_template_path(name),
        confidence=confidence,
        center=(100, 120),
        top_left=(90, 110),
        size=(20, 20),
        scale=1.0,
        threshold=0.8,
    )


def _close_detection(confidence: float) -> DetectionResult:
    return DetectionResult(
        name="close_buttons",
        template=_template_path("close_buttons"),
        confidence=confidence,
        center=(1232, 49),
        top_left=(1222, 39),
        size=(20, 20),
        scale=1.0,
        threshold=0.8,
    )


def _template_path(name: str) -> Path:
    paths = _template_paths_for_marker(name)
    return paths[0] if paths else Path(f"{name}.png")


def _result(action: str, *, dry_run: bool = True) -> ActionResult:
    return ActionResult(
        action,
        "skipped_dry_run" if dry_run else "executed",
        success=True,
        action=action,
        dry_run=dry_run,
        clicked_pos=(1232, 49) if action == "tap_marker" else None,
    )

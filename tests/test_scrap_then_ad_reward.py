from __future__ import annotations

from pathlib import Path

from cats_automatic.actions import ActionResult
from cats_automatic.external_strategy_loader import find_external_strategy, load_external_strategy
from cats_automatic.game_base import GameDefinition
from cats_automatic.run_recording import RunRecorder
from cats_automatic.strategy_base import DetectionResult, StrategyContext, StrategyDecision
from cats_automatic.strategy_runner import StrategyRunner
from cats_automatic.vision import MatchResult
from cats_automatic.window_capture import WindowFrame
from cats_automatic.actions import DryRunBackend


ROOT = Path(__file__).resolve().parents[1]


def test_combined_strategy_manifest_is_discoverable() -> None:
    manifest = find_external_strategy(
        "scrap_then_ad_reward",
        "cats",
        base_dir=ROOT / "external_strategies",
    )

    assert manifest is not None
    assert manifest.display_name == "废铁 + 胶卷广告"


def test_scrap_completion_enters_return_home_instead_of_completing_cycle() -> None:
    strategy = _load_strategy()
    strategy.strategy.scrap_strategy.decide = lambda _context: StrategyDecision.complete(
        "scrap_return_after_watch_ad"
    )

    decision = strategy.decide(_context({}))

    assert decision == StrategyDecision.wait(0.0, "scrap_phase_completed_returning_home")
    assert strategy.phase == "return_home_after_scrap"
    assert strategy.scrap_phase_completed_in_cycle is True
    assert strategy.returning_home_after_scrap is True


def test_return_home_uses_back_and_checks_home_again() -> None:
    strategy = _return_home_strategy()

    first = strategy.decide(_context({}))
    second = strategy.decide(_context({}))
    third = strategy.decide(_context({}))
    strategy.on_action_result(third, ActionResult("dry_run_keyevent", "executed"))
    after_back = strategy.decide(_context({}))

    assert first == StrategyDecision.wait(
        1.0,
        "miss_count_1_waiting_home_after_scrap",
        target_name="home_after_scrap",
    )
    assert second.reason == "miss_count_2_waiting_home_after_scrap"
    assert third.action_name == "adb_back_to_home_after_scrap"
    assert third.reason == "miss_count_3_waiting_home_after_scrap"
    assert after_back.reason == "miss_count_1_waiting_home_after_scrap"
    assert strategy.back_to_home_attempt_count == 1
    events = strategy.consume_strategy_events()
    home_events = [event for event in events if event["event"] == "home_detection"]
    assert len(home_events) == 4
    assert all(event["is_home"] is False for event in home_events)
    assert len([event for event in events if event["event"] == "target_miss_count"]) == 4
    assert any(event["event"] == "miss_threshold_triggered_back" for event in events)
    assert strategy.miss_count_by_step["home_after_scrap"] == 1


def test_return_home_detects_ad_entry_and_starts_film_reward() -> None:
    strategy = _return_home_strategy()

    decision = strategy.decide(_context({"ad_entry": _detection("ad_entry", 0.91)}))

    assert decision == StrategyDecision.wait(0.0, "home_detected_after_scrap")
    assert strategy.phase == "film_ad_reward_phase"
    assert strategy.home_detected_after_scrap is True
    assert strategy.film_ad_reward_started_in_cycle is True
    assert strategy.miss_count_by_step["home_after_scrap"] == 0


def test_return_home_detects_scrap_entry_but_rejects_internal_scrap_page() -> None:
    strategy = _return_home_strategy()

    assert strategy.is_home_screen({"scrap_entry": _detection("scrap_entry")}) is not None
    assert strategy.is_home_screen(
        {
            "scrap_entry": _detection("scrap_entry"),
            "scrap_next_button": _detection("scrap_next_button"),
        }
    ) is None


def test_low_confidence_ad_entry_is_not_home() -> None:
    strategy = _return_home_strategy()

    assert strategy.is_home_screen({"ad_entry": _detection("ad_entry", 0.605)}) is None


def test_combined_scrap_phase_prioritizes_battle_result_confirm() -> None:
    strategy = _load_strategy()
    strategy.strategy.scrap_strategy.state = "close_ad"
    strategy.strategy.state = "close_ad"

    decision = strategy.decide(
        _context(
            {
                "battle_result_popup": _detection("battle_result_popup", 0.984),
                "confirm_button": _detection("confirm_button", 0.932),
                "ad_entry": _detection("ad_entry", 0.95),
            }
        )
    )

    assert decision.action_name == "click_battle_result_confirm"
    assert decision.target_name == "confirm_button"
    assert strategy.phase == "scrap_phase"
    assert strategy.film_ad_reward_started_in_cycle is False


def test_combined_scrap_phase_uses_close_threshold_only_after_ad_wait() -> None:
    strategy = _load_strategy()
    scrap = strategy.strategy.scrap_strategy
    scrap.state = "close_ad"
    scrap.scrap_watch_ad_clicked_in_cycle = True
    scrap.ad_wait_finished_in_cycle = True

    decision = strategy.decide(
        _context({"close_user_5_1": _detection("close_user_5_1", 0.759)})
    )

    assert decision.action_name == "close_ad"
    assert decision.min_click_confidence_override == 0.72


def test_combined_close_success_waits_for_scrap_page_then_enters_return_home() -> None:
    strategy = _load_strategy()
    scrap = strategy.strategy.scrap_strategy
    scrap.state = "close_ad"
    scrap.scrap_watch_ad_clicked_in_cycle = True
    scrap.scrap_ad_in_progress = True
    scrap.current_ad_source = "scrap_ad"

    strategy.on_action_result(
        StrategyDecision.click("close_user_001", "close_ad", "close_ad_detected_ad_stage"),
        ActionResult("dry_run_click", "executed"),
    )

    assert strategy.phase == "scrap_phase"
    assert strategy.state == "wait_return_after_ad"

    decision = strategy.decide(
        _context({"battle_button": _detection("battle_button")})
    )

    assert decision.reason == "scrap_phase_completed_returning_home"
    assert strategy.phase == "return_home_after_scrap"
    assert strategy.scrap_phase_completed_in_cycle is True


def test_return_home_ignores_scrap_page_action_targets() -> None:
    strategy = _return_home_strategy()

    decision = strategy.decide(
        _context(
            {
                "battle_button": _detection("battle_button"),
                "scrap_watch_ad_button": _detection("scrap_watch_ad_button"),
            }
        )
    )
    events = strategy.consume_strategy_events()

    assert decision.action_name not in {"click_battle_button", "click_scrap_watch_ad_button"}
    assert strategy.phase == "return_home_after_scrap"
    assert any(event["event"] == "battle_button_ignored_returning_home_after_scrap" for event in events)
    assert any(event["event"] == "scrap_watch_ad_button_ignored_returning_home_after_scrap" for event in events)


def test_combined_recovers_return_home_phase_to_battle_result() -> None:
    strategy = _return_home_strategy()

    decision = strategy.decide(
        _context(
            {
                "battle_result_popup": _detection("battle_result_popup"),
                "confirm_button": _detection("confirm_button"),
            }
        )
    )

    assert decision.action_name == "click_battle_result_confirm"
    assert strategy.phase == "scrap_phase"
    assert strategy.state == "wait_battle_result_popup"
    assert strategy.home_detected_after_scrap is False


def test_film_phase_keeps_ad_reward_confirm_semantics() -> None:
    strategy = _load_strategy()
    strategy.strategy.phase = "film_ad_reward_phase"
    strategy.strategy.state = "film_ad_reward_phase"
    strategy.strategy.film_ad_reward_started_in_cycle = True

    decision = strategy.decide(
        _context(
            {
                "reward_confirm_marker": _detection("reward_confirm_marker"),
                "confirm_button": _detection("confirm_button"),
            }
        )
    )

    assert decision.action_name == "confirm_reward"
    assert decision.reason == "confirm_reward"


def test_return_home_stops_backing_after_five_attempts() -> None:
    strategy = _return_home_strategy()

    for _attempt in range(5):
        strategy.decide(_context({}))
        strategy.decide(_context({}))
        decision = strategy.decide(_context({}))
        strategy.on_action_result(decision, ActionResult("dry_run_keyevent", "executed"))

    strategy.decide(_context({}))
    strategy.decide(_context({}))
    blocked = strategy.decide(_context({}))

    assert blocked == StrategyDecision.wait(1.0, "final_home_probe_not_detected")
    assert strategy.back_to_home_attempt_count == 5
    assert any(
        event["event"] == "return_home_after_scrap_home_not_detected_after_max_back"
        for event in strategy.consume_strategy_events()
    )


def test_film_phase_reuses_ad_reward_decisions() -> None:
    strategy = _load_strategy()
    strategy.strategy.phase = "film_ad_reward_phase"
    strategy.strategy.state = "film_ad_reward_phase"
    strategy.strategy.film_ad_reward_started_in_cycle = True

    decision = strategy.decide(_context({"ad_entry": _detection("ad_entry", 0.91)}))

    assert decision.action_name == "click_ad_entry"
    assert decision.target_name == "ad_entry"


def test_film_phase_prioritizes_ad_entry_over_close_candidate() -> None:
    strategy = _load_strategy()
    combined = strategy.strategy
    combined.phase = "film_ad_reward_phase"
    combined.state = "film_ad_reward_phase"
    combined.film_ad_reward_started_in_cycle = True
    combined.current_ad_source = "none"

    decision = strategy.decide(
        _context(
            {
                "ad_entry": _detection("ad_entry", 0.91),
                "close_user_2_5": _detection("close_user_2_5", 0.70),
            }
        )
    )
    events = strategy.consume_strategy_events()

    assert decision.action_name == "click_ad_entry"
    assert decision.reason != "close_ad_candidate_below_threshold_after_ad_wait"
    assert any(event["event"] == "close_candidate_ignored_not_in_ad_stage" for event in events)


def test_click_ad_entry_waits_for_watch_before_entering_film_ad() -> None:
    strategy = _load_strategy()
    combined = strategy.strategy
    combined.phase = "film_ad_reward_phase"
    combined.state = "film_ad_reward_phase"
    combined.film_ad_reward_started_in_cycle = True
    combined.current_ad_source = "none"
    entry = StrategyDecision.click("ad_entry", "click_ad_entry", "click_ad_entry")

    strategy.on_action_result(entry, ActionResult("dry_run_click", "executed"))

    assert strategy.phase == "wait_film_watch_button"
    assert strategy.current_ad_source == "none"
    assert combined.film_ad_in_progress is False

    watch = strategy.decide(_context({"watch_ad_button": _detection("watch_ad_button")}))
    strategy.on_action_result(watch, ActionResult("dry_run_click", "executed"))
    assert watch.action_name == "click_watch_ad_button"
    assert strategy.phase == "film_ad_closing"
    assert strategy.current_ad_source == "film_ad"
    assert combined.film_ad_in_progress is True


def test_film_close_candidate_allowed_only_after_watch_click() -> None:
    strategy = _load_strategy()
    combined = strategy.strategy
    combined.phase = "film_ad_closing"
    combined.state = "film_ad_closing"
    combined.film_ad_reward_started_in_cycle = True
    combined.film_watch_ad_clicked_in_cycle = True
    combined.film_ad_in_progress = True
    combined.current_ad_source = "film_ad"

    decision = strategy.decide(
        _context({"close_user_2_5": _detection("close_user_2_5", 0.90)})
    )

    assert decision.action_name == "close_ad"


def test_phase_snapshot_records_film_close_gate() -> None:
    strategy = _load_strategy()
    combined = strategy.strategy
    combined.phase = "film_ad_reward_phase"
    combined.state = "film_ad_reward_phase"
    combined.film_ad_reward_started_in_cycle = True
    decision = strategy.decide(
        _context({"ad_entry": _detection("ad_entry"), "close_user_1": _detection("close_user_1")})
    )
    snapshot = combined.phase_snapshot(
        loop_index=1,
        detections={"ad_entry": _detection("ad_entry"), "close_user_1": _detection("close_user_1")},
        decision=decision,
    )

    assert snapshot["close_candidate_seen"] is True
    assert snapshot["close_candidate_allowed"] is False
    assert snapshot["close_candidate_ignored_in_film_phase"] is True


def test_confirm_reward_completes_combined_cycle() -> None:
    strategy = _load_strategy()
    strategy.strategy.phase = "film_ad_reward_phase"
    strategy.strategy.state = "film_ad_reward_phase"
    confirm = StrategyDecision.click("confirm_button", "confirm_reward", "confirm_reward")

    strategy.on_action_result(confirm, ActionResult("dry_run_click", "executed"))
    completed = strategy.decide(_context({}))

    assert completed == StrategyDecision.complete("scrap_then_ad_reward_completed")
    assert strategy.film_ad_reward_completed_in_cycle is True


def test_film_home_return_completes_combined_cycle() -> None:
    strategy = _load_strategy()
    strategy.strategy.phase = "film_ad_reward_phase"
    strategy.strategy.state = "film_ad_reward_phase"
    strategy.strategy.film_watch_ad_clicked_in_cycle = True
    strategy.strategy.film_close_ad_executed_in_cycle = True

    completed = strategy.decide(_context({"ad_entry": _detection("ad_entry", 0.92)}))

    assert completed == StrategyDecision.complete("scrap_then_ad_reward_completed")


def test_new_cycle_resets_combined_phase_context() -> None:
    strategy = _return_home_strategy()
    strategy.strategy.back_to_home_attempt_count = 4
    strategy.strategy.home_detected_after_scrap = True
    strategy.strategy.film_ad_reward_started_in_cycle = True
    strategy.strategy.film_ad_reward_completed_in_cycle = True

    strategy.reset_cycle()

    assert strategy.phase == "scrap_phase"
    assert strategy.back_to_home_attempt_count == 0
    assert strategy.home_detected_after_scrap is False
    assert strategy.film_ad_reward_started_in_cycle is False
    assert strategy.film_ad_reward_completed_in_cycle is False
    assert strategy.miss_count_by_step == {"home_after_scrap": 0}


def test_runner_summary_uses_combined_completion_reason(tmp_path: Path) -> None:
    strategy = _load_strategy()

    def reset_completed_cycle() -> None:
        strategy.strategy.phase = "cycle_completed"
        strategy.strategy.state = "cycle_completed"

    strategy.strategy.reset_cycle = reset_completed_cycle
    strategy.strategy.targets = lambda: []
    screen = tmp_path / "screen.png"
    screen.write_text("screen", encoding="utf-8")
    recorder = RunRecorder(
        output_root=tmp_path / "runs",
        capture_backend="fake",
        strategy_name="scrap_then_ad_reward",
        run_id="combined-complete",
    )
    runner = StrategyRunner(
        game=GameDefinition("cats", tmp_path / "config.json", tmp_path),
        strategy=strategy,
        capture_backend=_FakeCapture(screen),
        action_backend=DryRunBackend(max_actions=8),
        root=tmp_path,
        output_dir=tmp_path / "output",
        max_loops=1,
        run_recorder=recorder,
        matcher=lambda *_, **__: MatchResult(0.0, (0, 0), (1, 1)),
        sleep=lambda _: None,
    )

    runner.run()

    summary = recorder.summary_path.read_text(encoding="utf-8")
    assert "last_cycle_completed_reason: scrap_then_ad_reward_completed" in summary
    assert "stop_reason: scrap_then_ad_reward_completed" in summary


def _load_strategy():
    manifest = find_external_strategy(
        "scrap_then_ad_reward",
        "cats",
        base_dir=ROOT / "external_strategies",
    )
    assert manifest is not None
    strategy = load_external_strategy(manifest)
    strategy.strategy.scrap_strategy._template_exists = lambda _name: True
    return strategy


def _return_home_strategy():
    strategy = _load_strategy()
    strategy.strategy.phase = "return_home_after_scrap"
    strategy.strategy.state = "return_home_after_scrap"
    strategy.strategy.scrap_phase_completed_in_cycle = True
    strategy.strategy.returning_home_after_scrap = True
    return strategy


def _context(detections: dict[str, DetectionResult]) -> StrategyContext:
    return StrategyContext(
        loop_index=1,
        screen_path=Path("screen.png"),
        game=GameDefinition("cats", Path("config.json"), Path("templates")),
        detections=detections,
        resolve_template=lambda value: Path(value),
    )


def _detection(name: str, confidence: float = 0.95) -> DetectionResult:
    return DetectionResult(
        name=name,
        template=Path(f"{name}.png"),
        confidence=confidence,
        center=(100, 200),
        top_left=(90, 190),
        size=(20, 20),
        scale=1.0,
        threshold=0.8,
    )


class _FakeCapture:
    name = "fake"

    def __init__(self, path: Path) -> None:
        self.path = path

    def capture(self, _output_path: Path) -> WindowFrame:
        return WindowFrame(self.path, "fake", (0, 0), (100, 100))

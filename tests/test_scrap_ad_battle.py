from __future__ import annotations

import csv
import json
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from cats_automatic.actions import ActionResult, AdbActionBackend, DryRunBackend
from cats_automatic.external_strategy_loader import find_external_strategy, load_external_strategy
from cats_automatic.game_base import GameDefinition
from cats_automatic.main import build_parser
from cats_automatic.run_recording import RunRecorder
from cats_automatic.strategy_base import DetectionResult, StrategyContext, StrategyDecision, TargetSpec
from cats_automatic.strategy_runner import StrategyRunner
from cats_automatic.vision import MatchResult
from cats_automatic.window_capture import WindowFrame
from tools.catsautomatic_gui import gui_strategy_names


ROOT = Path(__file__).resolve().parents[1]


def test_scrap_strategy_manifest_is_discoverable() -> None:
    manifest = find_external_strategy(
        "scrap_ad_battle",
        "cats",
        base_dir=ROOT / "external_strategies",
    )

    assert manifest is not None
    assert manifest.display_name == "废铁看广告"
    assert manifest.template_root.name == "templates"
    assert "scrap_ad_battle" in gui_strategy_names(ROOT / "external_strategies")


def test_scrap_strategy_targets_and_defaults() -> None:
    strategy = _load_strategy()
    names = {target.name for target in strategy.targets()}

    assert {
        "scrap_entry",
        "scrap_page_marker",
        "scrap_next_button",
        "battle_button",
        "skip_button",
        "battle_result_popup",
        "scrap_watch_ad_button",
        "close_end_1",
        "close_end_2",
        "close_end_3",
        "close_end_4",
    }.issubset(names)
    assert "battle_confirm_button" not in names
    assert strategy.battle_wait_seconds == 60.0
    assert strategy.ad_wait_seconds == 20.0
    strategy.configure(battle_wait_seconds=12.0, ad_wait_seconds=8.0)
    assert strategy.battle_wait_seconds == 12.0
    assert strategy.ad_wait_seconds == 8.0


def test_scrap_cli_wait_arguments_override_defaults() -> None:
    args = build_parser().parse_args(
        ["--battle-wait-seconds", "12", "--ad-wait-seconds", "8"]
    )

    assert args.battle_wait_seconds == 12.0
    assert args.ad_wait_seconds == 8.0


def test_scrap_home_and_popup_decisions() -> None:
    strategy = _load_strategy()
    entry = strategy.decide(_context({"scrap_entry": _detection("scrap_entry")}))
    strategy.on_action_result(entry, ActionResult("dry_run_click", "executed"))

    waiting = strategy.decide(_context({}))
    next_button = strategy.decide(_context({"scrap_next_button": _detection("scrap_next_button")}))

    assert entry.action_name == "click_scrap_entry"
    assert entry.post_action_delay_seconds == 3.0
    assert waiting == StrategyDecision.wait(
        1.0,
        "miss_count_1_waiting_scrap_next_button",
        target_name="scrap_next_button",
    )
    assert next_button.action_name == "click_scrap_next_button"
    assert next_button.post_action_delay_seconds == 2.0


def test_scrap_battle_skip_wait_confirm_and_ad_states() -> None:
    strategy = _load_strategy()
    strategy.state = "wait_battle_button"
    battle_back = strategy.decide(_context({}))
    stale_page = strategy.decide(
        _context(
            {
                "battle_button": _detection("battle_button"),
                "scrap_next_button": _detection("scrap_next_button"),
            }
        )
    )
    battle = strategy.decide(_context({"battle_button": _detection("battle_button")}))
    strategy.on_action_result(battle, ActionResult("dry_run_click", "executed"))
    first_skip = strategy.decide(_context({"skip_button": _detection("skip_button")}))
    strategy.on_action_result(first_skip, ActionResult("dry_run_click", "executed"))
    second_skip = strategy.decide(_context({"skip_button": _detection("skip_button")}))
    strategy.on_action_result(second_skip, ActionResult("dry_run_click", "executed"))
    battle_wait = strategy.decide(_context({}))
    strategy.on_action_result(battle_wait, ActionResult("wait", "skipped_wait"))
    result_popup = strategy.decide(
        _context({"battle_result_popup": _detection("battle_result_popup")})
    )
    strategy.on_action_result(result_popup, ActionResult("dry_run_keyevent", "executed"))
    watch = strategy.decide(
        _context({"scrap_watch_ad_button": _detection("scrap_watch_ad_button")})
    )
    strategy.on_action_result(watch, ActionResult("dry_run_click", "executed"))
    ad_wait = strategy.decide(_context({}))

    assert battle_back == StrategyDecision.wait(
        1.0,
        "miss_count_1_waiting_battle_button",
        target_name="battle_button",
    )
    assert stale_page == StrategyDecision.wait(1.0, "battle_button_conflict_with_scrap_next_button")
    assert battle.action_name == "click_battle_button"
    assert battle.post_action_delay_seconds == 3.0
    assert first_skip.post_action_delay_seconds == 2.0
    assert second_skip.post_action_delay_seconds == 0.0
    assert strategy.skip_click_count == 2
    assert battle_wait == StrategyDecision.wait(60.0, "battle_wait")
    assert result_popup.action_name == "adb_back_battle_result"
    assert watch.action_name == "click_scrap_watch_ad_button"
    assert ad_wait == StrategyDecision.wait(20.0, "ad_wait")
    assert strategy.battle_clicked_in_cycle is True
    assert strategy.battle_wait_finished_in_cycle is True
    assert strategy.battle_result_closed_in_cycle is True
    assert strategy.scrap_watch_ad_clicked_in_cycle is True
    assert strategy.awaiting_watch_ad_in_cycle is False


@pytest.mark.parametrize(
    ("target_name", "skip_count", "expected_state", "expected_action"),
    [
        ("scrap_next_button", 0, "wait_scrap_next_button", "click_scrap_next_button"),
        ("battle_button", 0, "wait_battle_button", "click_battle_button"),
        ("skip_button", 0, "skip_1", "click_skip_button"),
        ("skip_button", 1, "skip_2", "click_skip_button"),
        ("battle_result_popup", 0, "wait_battle_result_popup", "adb_back_battle_result"),
    ],
)
def test_scrap_recovers_progress_from_current_screen(
    target_name: str,
    skip_count: int,
    expected_state: str,
    expected_action: str,
) -> None:
    strategy = _load_strategy()
    strategy.state = "home"
    strategy.strategy.skip_click_count = skip_count

    decision = strategy.decide(_context({target_name: _detection(target_name)}))

    assert strategy.state == expected_state
    assert decision.action_name == expected_action


def test_scrap_next_button_recovery_replaces_home_wait() -> None:
    strategy = _load_strategy()
    strategy.state = "home"

    decision = strategy.decide(
        _context(
            {
                "scrap_page_marker": _detection("scrap_page_marker", 0.983),
                "scrap_next_button": _detection("scrap_next_button", 0.968),
            }
        )
    )
    recovery = strategy.consume_state_recovery_event()

    assert decision.action_name == "click_scrap_next_button"
    assert recovery == {
        "from_state": "home",
        "to_state": "wait_scrap_next_button",
        "reason": "detected_scrap_next_button",
        "confidence": 0.968,
        "center": [100, 200],
    }


def test_scrap_skip_limit_prevents_third_click() -> None:
    strategy = _load_strategy()
    strategy.state = "home"
    strategy.strategy.skip_click_count = 2

    decision = strategy.decide(_context({"skip_button": _detection("skip_button")}))

    assert strategy.state == "wait_battle_result_popup"
    assert decision == StrategyDecision.wait(1.0, "skip_limit_reached")


def test_scrap_battle_conflict_does_not_click() -> None:
    strategy = _load_strategy()
    strategy.state = "home"

    decision = strategy.decide(
        _context(
            {
                "battle_button": _detection("battle_button"),
                "scrap_next_button": _detection("scrap_next_button"),
            }
        )
    )

    assert decision == StrategyDecision.wait(
        1.0,
        "battle_button_conflict_with_scrap_next_button",
    )


def test_battle_result_back_locks_cycle_to_watch_ad() -> None:
    strategy = _load_strategy()
    strategy.state = "wait_battle_result_popup"
    strategy.strategy.battle_clicked_in_cycle = True
    strategy.strategy.skip_click_count = 2
    strategy.strategy.battle_wait_finished_in_cycle = True
    decision = strategy.decide(
        _context({"battle_result_popup": _detection("battle_result_popup")})
    )

    strategy.on_action_result(decision, ActionResult("dry_run_keyevent", "executed"))

    assert decision.action_name == "adb_back_battle_result"
    assert strategy.state == "wait_scrap_watch_ad_button"
    assert strategy.awaiting_watch_ad_in_cycle is True
    assert strategy.battle_result_closed_in_cycle is True
    assert strategy.battle_result_handled is True
    assert strategy.battle_phase_completed is True

    watch_decision = strategy.decide(
        _context({"scrap_watch_ad_button": _detection("scrap_watch_ad_button")})
    )
    assert watch_decision.action_name == "click_scrap_watch_ad_button"


def test_battle_result_confirm_overrides_close_ad_state() -> None:
    strategy = _load_strategy()
    strategy.state = "close_ad"
    detections = {
        "battle_result_popup": _detection("battle_result_popup", 0.984),
        "confirm_button": _detection("confirm_button", 0.932),
        "ad_entry": _detection("ad_entry", 0.605),
    }

    decision = strategy.decide(_context(detections))
    recovery = strategy.consume_state_recovery_event()
    events = strategy.consume_strategy_events()

    assert decision == StrategyDecision.click(
        "confirm_button",
        "click_battle_result_confirm",
        "battle_result_popup_confirm_button_detected",
        post_action_delay_seconds=1.5,
    )
    assert decision.reason != "wait_close_ad_not_found"
    assert strategy.state == "wait_battle_result_popup"
    assert recovery is not None
    assert recovery["reason"] == "battle_result_popup_priority_override"
    assert events[-1]["event"] == "battle_result_popup_detected"
    assert events[-1]["action"] == "click_battle_result_confirm"

    strategy.on_action_result(decision, ActionResult("dry_run_click", "executed"))

    assert strategy.state == "wait_scrap_watch_ad_button"
    assert strategy.awaiting_watch_ad_in_cycle is True
    assert strategy.battle_result_closed_in_cycle is True


def test_close_candidate_is_ignored_before_ad_stage() -> None:
    strategy = _load_strategy()
    strategy.state = "wait_battle_result_popup"

    decision = strategy.decide(
        _context({"close_user_5_1": _detection("close_user_5_1", 0.759)})
    )
    events = strategy.consume_strategy_events()

    assert strategy.state == "wait_battle_result_popup"
    assert decision.action_name != "close_ad"
    ignored = [event for event in events if event["event"] == "close_ad_candidate_ignored"]
    assert ignored[-1]["target_name"] == "close_user_5_1"
    assert ignored[-1]["ad_stage_active"] is False
    assert ignored[-1]["reason"] == "close_ad_detected_before_ad_stage_ignored"


def test_close_candidate_uses_independent_threshold_in_ad_stage() -> None:
    strategy = _load_strategy()
    strategy.state = "close_ad"
    strategy.strategy.scrap_watch_ad_clicked_in_cycle = True
    strategy.strategy.ad_wait_finished_in_cycle = True

    decision = strategy.decide(
        _context({"close_user_5_1": _detection("close_user_5_1", 0.759)})
    )

    assert decision.action_name == "close_ad"
    assert decision.target_name == "close_user_5_1"
    assert decision.reason == "close_ad_detected_ad_stage"
    assert decision.min_click_confidence_override == 0.72
    assert decision.post_action_delay_seconds == 1.5


def test_close_candidate_below_independent_threshold_waits() -> None:
    strategy = _load_strategy()
    strategy.state = "close_ad"
    strategy.strategy.scrap_watch_ad_clicked_in_cycle = True
    strategy.strategy.ad_wait_finished_in_cycle = True

    decision = strategy.decide(
        _context({"close_user_5_1": _detection("close_user_5_1", 0.70)})
    )

    assert decision == StrategyDecision.wait(
        1.0,
        "close_ad_candidate_below_threshold_after_ad_wait",
        target_name="close_user_5_1",
    )
    event = strategy.consume_strategy_events()[-1]
    assert event["event"] == "close_ad_candidate"
    assert event["will_click"] is False
    assert event["threshold"] == 0.72


def test_battle_result_without_confirm_uses_back_fallback() -> None:
    strategy = _load_strategy()
    strategy.state = "ad_wait"

    decision = strategy.decide(
        _context({"battle_result_popup": _detection("battle_result_popup")})
    )

    assert decision == StrategyDecision.keyevent(
        "BACK",
        "adb_back_battle_result",
        "battle_result_popup_detected_confirm_missing",
        post_action_delay_seconds=1.0,
    )


def test_battle_result_confirm_is_recorded_in_run_files(tmp_path: Path) -> None:
    strategy = _load_strategy()
    result_template = tmp_path / "battle_result_popup.png"
    confirm_template = tmp_path / "confirm_button.png"
    result_template.touch()
    confirm_template.touch()
    strategy.strategy.targets = lambda: [
        TargetSpec("battle_result_popup", str(result_template), 0.80),
        TargetSpec("confirm_button", str(confirm_template), 0.80),
    ]

    def reset_close_state() -> None:
        strategy.strategy.state = "close_ad"
        strategy.strategy.battle_result_closed_in_cycle = False

    strategy.strategy.reset_cycle = reset_close_state
    runner, recorder = _single_loop_runner(tmp_path, strategy, run_id="result-confirm")

    def matcher(_screen: Path, template: Path, **_: object) -> MatchResult:
        if template.name == "confirm_button.png":
            return MatchResult(0.932, (632, 632), (20, 20))
        return MatchResult(0.984, (633, 169), (20, 20))

    runner.matcher = matcher
    runner.run()

    rows = _read_records(recorder.click_records_path)
    events = recorder.events_path.read_text(encoding="utf-8")
    assert rows[0]["decision"] == "click_battle_result_confirm"
    assert rows[0]["target_name"] == "confirm_button"
    assert rows[0]["confidence"] == "0.932"
    assert rows[0]["click_x"] == "642"
    assert rows[0]["click_y"] == "642"
    assert rows[0]["reason"] == "battle_result_popup_confirm_button_detected"
    assert '"event": "battle_result_popup_detected"' in events
    assert '"action": "click_battle_result_confirm"' in events


def test_battle_button_wins_when_watch_ad_is_also_detected() -> None:
    strategy = _load_strategy()
    strategy.state = "wait_battle_button"

    decision = strategy.decide(
        _context(
            {
                "battle_button": _detection("battle_button"),
                "scrap_watch_ad_button": _detection("scrap_watch_ad_button"),
            }
        )
    )

    assert decision.action_name == "click_battle_button"


@pytest.mark.parametrize(
    (
        "battle_clicked",
        "skip_count",
        "battle_wait_finished",
        "expected_state",
    ),
    [
        (False, 0, False, "wait_battle_button"),
        (True, 0, False, "skip_1"),
        (True, 2, False, "battle_wait"),
        (True, 2, True, "wait_scrap_watch_ad_button"),
    ],
)
def test_watch_ad_is_blocked_until_battle_result_is_closed(
    battle_clicked: bool,
    skip_count: int,
    battle_wait_finished: bool,
    expected_state: str,
) -> None:
    strategy = _load_strategy()
    strategy.state = "home"
    strategy.strategy.battle_clicked_in_cycle = battle_clicked
    strategy.strategy.skip_click_count = skip_count
    strategy.strategy.battle_wait_finished_in_cycle = battle_wait_finished

    decision = strategy.decide(
        _context({"scrap_watch_ad_button": _detection("scrap_watch_ad_button")})
    )

    assert strategy.state == expected_state
    if battle_clicked and battle_wait_finished:
        assert decision.action_name == "click_scrap_watch_ad_button"
    else:
        assert decision.action_name != "click_scrap_watch_ad_button"
        assert decision == StrategyDecision.wait(
            1.0,
            "watch_ad_detected_before_battle_complete_ignored",
            target_name="scrap_watch_ad_button",
        )


def test_early_watch_ad_is_recorded_as_stage_not_ready(tmp_path: Path) -> None:
    strategy = _load_strategy()
    watch_template = tmp_path / "scrap_watch_ad_button.png"
    watch_template.touch()
    strategy.strategy.targets = lambda: [
        TargetSpec("scrap_watch_ad_button", str(watch_template), 0.80)
    ]
    runner, recorder = _single_loop_runner(tmp_path, strategy, run_id="early-watch")
    runner.matcher = lambda *_, **__: MatchResult(0.97, (10, 20), (30, 40))

    runner.run()

    events = recorder.events_path.read_text(encoding="utf-8")
    rows = _read_records(recorder.click_records_path)
    rows = _read_records(recorder.click_records_path)
    assert '"event": "decision_blocked"' in events
    assert '"blocked_decision": "click_scrap_watch_ad_button"' in events
    assert '"reason": "watch_ad_detected_before_battle_complete"' in events
    assert rows[0]["decision"] == "wait"
    assert rows[0]["target_name"] == "scrap_watch_ad_button"
    assert rows[0]["reason"] == "watch_ad_detected_before_battle_complete_ignored"
    assert rows[0]["result"] == "skipped_stage_not_ready"


def test_awaiting_watch_ad_ignores_battle_button() -> None:
    strategy = _load_strategy()
    strategy.state = "wait_scrap_watch_ad_button"
    strategy.strategy.battle_clicked_in_cycle = True
    strategy.strategy.skip_click_count = 2
    strategy.strategy.battle_wait_finished_in_cycle = True
    strategy.strategy.battle_result_closed_in_cycle = True
    strategy.strategy.awaiting_watch_ad_in_cycle = True

    decision = strategy.decide(_context({"battle_button": _detection("battle_button")}))
    events = strategy.consume_strategy_events()

    assert strategy.state == "wait_scrap_watch_ad_button"
    assert decision == StrategyDecision.wait(1.0, "battle_button_ignored_awaiting_scrap_watch_ad")
    assert events == [
        {
            "event": "battle_button_ignored_awaiting_scrap_watch_ad",
            "blocked_decision": "click_battle_button",
            "reason": "battle_finished_awaiting_scrap_watch_ad",
        }
    ]


def test_battle_confirm_locks_high_confidence_watch_button_as_next_action() -> None:
    strategy = _load_strategy()
    strategy.state = "wait_battle_result_popup"
    decision = StrategyDecision.click(
        "confirm_button", "click_battle_result_confirm", "battle_result_popup_confirm_button_detected"
    )
    strategy.on_action_result(decision, ActionResult("dry_run_click", "executed"))

    next_decision = strategy.decide(
        _context(
            {
                "battle_button": _detection("battle_button", 0.99),
                "scrap_watch_ad_button": _detection("scrap_watch_ad_button", 0.982),
            }
        )
    )

    assert next_decision.action_name == "click_scrap_watch_ad_button"
    assert next_decision.target_name == "scrap_watch_ad_button"
    assert next_decision.reason != "watch_ad_detected_before_battle_complete_ignored"


def test_scrap_ad_close_enters_return_home_after_scrap_page_evidence() -> None:
    strategy = _load_strategy()
    scrap = strategy.strategy
    scrap.state = "close_ad"
    scrap.scrap_watch_ad_clicked_in_cycle = True
    scrap.scrap_ad_in_progress = True
    scrap.current_ad_source = "scrap_ad"

    strategy.on_action_result(
        StrategyDecision.click("close_user_001", "close_ad", "close_ad_detected_ad_stage"),
        ActionResult("dry_run_click", "executed"),
    )

    assert strategy.state == "wait_return_after_ad"
    assert strategy.scrap_ad_closed_once is True
    follow_up = strategy.decide(
        _context({"scrap_watch_ad_button": _detection("scrap_watch_ad_button")})
    )
    assert strategy.state == "return_home_after_scrap"
    assert strategy.scrap_ad_completed is True
    assert strategy.scrap_phase_completed is True
    assert strategy.scrap_ad_in_progress is False
    assert strategy.current_ad_source == "none"
    assert follow_up.kind == "complete"
    assert follow_up.action_name != "click_scrap_watch_ad_button"


def test_scrap_close_third_attempt_is_allowed_and_limit_is_eight() -> None:
    strategy = _load_strategy()
    scrap = strategy.strategy
    scrap.state = "close_ad"
    scrap.scrap_watch_ad_clicked_in_cycle = True
    scrap.scrap_ad_in_progress = True
    scrap.current_ad_source = "scrap_ad"

    decisions = []
    for _ in range(9):
        scrap.state = "close_ad"
        decision = strategy.decide(_context({"close_user_001": _detection("close_user_001")}))
        decisions.append(decision)
        strategy.on_action_result(decision, ActionResult("dry_run_click", "executed"))

    assert decisions[2].action_name == "close_ad"
    assert decisions[7].action_name == "close_ad"
    assert decisions[8].reason == "wait_close_limit_reached"


def test_runner_writes_phase_journal_snapshot(tmp_path: Path) -> None:
    strategy = _load_strategy()
    strategy.strategy.targets = lambda: []
    runner, recorder = _single_loop_runner(tmp_path, strategy, run_id="phase-journal")

    runner.run()

    payload = json.loads(recorder.phase_journal_path.read_text(encoding="utf-8").splitlines()[0])
    assert payload["run_id"] == "phase-journal"
    assert payload["current_phase"] == "home"
    assert payload["chosen_decision"] == "wait"
    assert payload["detected_targets"] == []
    assert "scrap_watch_ad_cooldown_detected" in payload
    assert "white_text_pixel_ratio" in payload


def test_cooldown_template_skips_scrap_ad_and_returns_home() -> None:
    strategy = _load_strategy()
    scrap = strategy.strategy
    scrap.state = "wait_scrap_watch_ad_button"
    scrap.battle_result_handled = True
    scrap.battle_phase_completed = True
    scrap.awaiting_watch_ad_in_cycle = True

    decision = strategy.decide(
        _context(
            {
                "scrap_watch_ad_button": _detection("scrap_watch_ad_button", 0.982),
                "scrap_watch_cooldown_001": _detection("scrap_watch_cooldown_001", 0.91),
            }
        )
    )

    assert decision.action_name == "skip_scrap_ad_due_to_cooldown"
    assert decision.reason == "scrap_watch_ad_button_cooldown_detected"
    assert strategy.current_phase == "return_home_after_scrap"
    assert strategy.scrap_ad_skipped_by_cooldown is True
    assert strategy.scrap_phase_completed is True
    assert strategy.current_ad_source == "none"


def test_white_text_roi_detects_cooldown(tmp_path: Path) -> None:
    screen = tmp_path / "cooldown.png"
    image = Image.new("RGB", (120, 80), "black")
    for box in ((15, 25, 25, 30), (35, 25, 45, 30)):
        for x in range(box[0], box[2]):
            for y in range(box[1], box[3]):
                image.putpixel((x, y), (255, 255, 255))
    image.save(screen)
    strategy = _load_strategy()
    scrap = strategy.strategy
    scrap.state = "wait_scrap_watch_ad_button"
    scrap.battle_result_handled = True
    scrap.battle_phase_completed = True
    scrap.awaiting_watch_ad_in_cycle = True
    button = DetectionResult(
        name="scrap_watch_ad_button", template=Path("button.png"), confidence=0.98,
        center=(30, 30), top_left=(10, 20), size=(50, 20), scale=1.0, threshold=0.8,
    )
    context = StrategyContext(1, screen, GameDefinition("cats", Path("config.json"), Path("templates")), {"scrap_watch_ad_button": button}, lambda value: Path(value))

    decision = strategy.decide(context)

    assert decision.action_name == "skip_scrap_ad_due_to_cooldown"
    assert strategy.scrap_watch_cooldown_method == "white_text_roi"
    assert strategy.white_text_component_count >= 2


def test_same_cycle_cannot_click_battle_twice() -> None:
    strategy = _load_strategy()
    strategy.state = "wait_battle_button"
    strategy.strategy.battle_clicked_in_cycle = True

    decision = strategy.decide(_context({"battle_button": _detection("battle_button")}))

    assert decision == StrategyDecision.wait(1.0, "battle_already_clicked_in_cycle")


def test_new_cycle_resets_battle_stage_lock() -> None:
    strategy = _load_strategy()
    strategy.strategy.battle_clicked_in_cycle = True
    strategy.strategy.awaiting_watch_ad_in_cycle = True
    strategy.strategy.battle_wait_finished_in_cycle = True
    strategy.strategy.battle_result_closed_in_cycle = True
    strategy.strategy.scrap_watch_ad_clicked_in_cycle = True

    strategy.reset_cycle()
    decision = strategy.decide(_context({"battle_button": _detection("battle_button")}))

    assert strategy.battle_clicked_in_cycle is False
    assert strategy.awaiting_watch_ad_in_cycle is False
    assert strategy.battle_wait_finished_in_cycle is False
    assert strategy.battle_result_closed_in_cycle is False
    assert strategy.scrap_watch_ad_clicked_in_cycle is False
    assert decision.action_name == "click_battle_button"


def test_battle_result_transition_reason_is_recorded(tmp_path: Path) -> None:
    strategy = _load_strategy()
    result_template = tmp_path / "battle_result_popup.png"
    result_template.touch()
    strategy.strategy.targets = lambda: [
        TargetSpec("battle_result_popup", str(result_template), 0.80)
    ]

    def reset_to_result() -> None:
        strategy.strategy.state = "wait_battle_result_popup"
        strategy.strategy.battle_clicked_in_cycle = True

    strategy.strategy.reset_cycle = reset_to_result
    runner, recorder = _single_loop_runner(tmp_path, strategy, run_id="result-lock")
    runner.matcher = lambda *_, **__: MatchResult(0.97, (10, 20), (30, 40))

    runner.run()

    events = recorder.events_path.read_text(encoding="utf-8")
    assert '"reason": "battle_result_closed_awaiting_watch_ad"' in events
    assert '"awaiting_watch_ad_in_cycle": true' in events


def test_ignored_battle_is_recorded_in_events_and_click_records(tmp_path: Path) -> None:
    strategy = _load_strategy()
    battle_template = tmp_path / "battle_button.png"
    battle_template.touch()
    strategy.strategy.targets = lambda: [
        TargetSpec("battle_button", str(battle_template), 0.80)
    ]

    def reset_to_watch_lock() -> None:
        strategy.strategy.state = "wait_scrap_watch_ad_button"
        strategy.strategy.battle_clicked_in_cycle = True
        strategy.strategy.skip_click_count = 2
        strategy.strategy.battle_wait_finished_in_cycle = True
        strategy.strategy.battle_result_closed_in_cycle = True
        strategy.strategy.awaiting_watch_ad_in_cycle = True

    strategy.strategy.reset_cycle = reset_to_watch_lock
    runner, recorder = _single_loop_runner(tmp_path, strategy, run_id="blocked-battle")
    runner.matcher = lambda *_, **__: MatchResult(0.97, (10, 20), (30, 40))

    runner.run()

    events = recorder.events_path.read_text(encoding="utf-8")
    rows = _read_records(recorder.click_records_path)
    assert '"event": "battle_button_ignored_awaiting_scrap_watch_ad"' in events
    assert '"blocked_decision": "click_battle_button"' in events
    assert '"reason": "battle_finished_awaiting_scrap_watch_ad"' in events
    assert rows[0]["action_type"] == "wait"
    assert rows[0]["reason"] == "battle_button_ignored_awaiting_scrap_watch_ad"


def test_watchdog_events_are_written_to_jsonl(tmp_path: Path) -> None:
    timeout_dir = tmp_path / "timeout"
    timeout_dir.mkdir()
    strategy = _load_strategy()
    strategy.strategy._clock = lambda: 6.0
    strategy.strategy.targets = lambda: []

    def reset_timeout_step() -> None:
        strategy.strategy.state = "wait_scrap_next_button"
        strategy.strategy.current_step_name = "waiting_scrap_next_button"
        strategy.strategy.step_started_at = 0.0
        strategy.strategy.last_progress_at = 0.0
        strategy.strategy.back_attempt_count_by_step = {
            "waiting_scrap_next_button": 0
        }

    strategy.strategy.reset_cycle = reset_timeout_step
    runner, recorder = _single_loop_runner(timeout_dir, strategy, run_id="watchdog-timeout")
    runner.max_loops = 3
    runner.run()

    events = recorder.events_path.read_text(encoding="utf-8")
    rows = _read_records(recorder.click_records_path)
    assert '"event": "transition_watchdog_triggered"' in events
    assert '"event": "no_progress_detected"' in events
    assert '"event": "target_miss_count"' in events
    assert '"event": "miss_threshold_triggered_back"' in events
    assert '"reason": "miss_count_3_waiting_scrap_next_button"' in events
    assert rows[0]["reason"] == "miss_count_1_waiting_scrap_next_button"
    assert rows[0]["result"] == "waiting_for_miss_threshold"
    assert rows[1]["reason"] == "miss_count_2_waiting_scrap_next_button"
    assert rows[1]["result"] == "waiting_for_miss_threshold"

    repeated_dir = tmp_path / "repeated"
    repeated_dir.mkdir()
    repeated_strategy = _load_strategy()
    repeated_strategy.strategy._clock = lambda: 0.0
    repeated_strategy.strategy.targets = lambda: []

    def reset_repeated_step() -> None:
        repeated_strategy.strategy.state = "wait_battle_button"
        repeated_strategy.strategy.current_step_name = "waiting_battle_button"
        repeated_strategy.strategy.step_started_at = 0.0
        repeated_strategy.strategy.repeated_click_count_by_decision = {
            "click_scrap_next_button": 2
        }
        repeated_strategy.strategy.back_attempt_count_by_step = {
            "waiting_battle_button": 0
        }

    repeated_strategy.strategy.reset_cycle = reset_repeated_step
    runner, recorder = _single_loop_runner(
        repeated_dir,
        repeated_strategy,
        run_id="watchdog-repeated",
    )
    runner.max_loops = 3
    runner.run()

    repeated_events = recorder.events_path.read_text(encoding="utf-8")
    assert '"event": "repeated_click_without_progress"' in repeated_events
    assert '"reason": "miss_count_3_waiting_battle_button"' in repeated_events


def test_scrap_state_recovery_is_recorded_in_events(tmp_path: Path) -> None:
    strategy = _load_strategy()
    next_template = tmp_path / "scrap_next_button.png"
    next_template.touch()
    strategy.strategy.targets = lambda: [
        TargetSpec("scrap_next_button", str(next_template), 0.80)
    ]
    runner, recorder = _single_loop_runner(tmp_path, strategy, run_id="state-recovery")
    runner.matcher = lambda *_, **__: MatchResult(0.968, (10, 20), (30, 40))

    runner.run()

    events = recorder.events_path.read_text(encoding="utf-8")
    assert '"event": "state_recovered"' in events
    assert '"from_state": "home"' in events
    assert '"to_state": "wait_scrap_next_button"' in events
    assert '"reason": "detected_scrap_next_button"' in events


def test_optional_and_legacy_templates_do_not_log_missing(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    strategy = _load_strategy()
    runner, _ = _single_loop_runner(tmp_path, strategy, run_id="optional-templates")

    runner.run()

    output = capsys.readouterr().out
    assert "Template missing: scrap_page_marker" not in output
    assert "Template missing: battle_confirm_button" not in output


def test_scrap_missing_template_waits_without_crashing() -> None:
    strategy = _load_strategy()
    strategy.strategy._template_exists = lambda _name: False

    decision = strategy.decide(_context({}))

    assert decision == StrategyDecision.wait(1.0, "template_missing_scrap_entry")


def test_scrap_missing_battle_result_popup_waits() -> None:
    strategy = _load_strategy()
    strategy.state = "wait_battle_result_popup"

    decision = strategy.decide(_context({}))

    assert decision == StrategyDecision.wait(
        1.0,
        "miss_count_1_waiting_battle_result_popup",
        target_name="battle_result_popup",
    )


def test_watchdog_backs_when_scrap_next_does_not_appear() -> None:
    strategy, now = _clocked_strategy()
    entry = strategy.decide(_context({"scrap_entry": _detection("scrap_entry")}))
    strategy.on_action_result(entry, ActionResult("dry_run_click", "executed"))

    now[0] = 5.1
    decision = _third_miss(strategy)

    assert decision.action_name == "adb_back_scrap_popup"
    assert decision.reason == "miss_count_3_waiting_scrap_next_button"


def test_watchdog_backs_when_battle_button_does_not_appear() -> None:
    strategy, now = _clocked_strategy()
    strategy.state = "wait_scrap_next_button"
    next_button = strategy.decide(
        _context({"scrap_next_button": _detection("scrap_next_button")})
    )
    strategy.on_action_result(next_button, ActionResult("dry_run_click", "executed"))

    now[0] = 5.1
    decision = _third_miss(strategy)

    assert decision.action_name == "adb_back_battle_popup"
    assert decision.reason == "miss_count_3_waiting_battle_button"


def test_watchdog_backs_after_two_scrap_next_clicks_without_battle() -> None:
    strategy, _ = _clocked_strategy()
    strategy.state = "wait_battle_button"
    strategy.strategy._start_step("waiting_battle_button")
    strategy.strategy.repeated_click_count_by_decision["click_scrap_next_button"] = 2

    decision = _third_miss(strategy)
    events = strategy.consume_strategy_events()

    assert decision.action_name == "adb_back_battle_popup"
    assert decision.reason == "miss_count_3_waiting_battle_button"
    assert any(event["event"] == "repeated_click_without_progress" for event in events)


def test_watchdog_backs_when_skip_button_does_not_appear() -> None:
    strategy, now = _clocked_strategy()
    battle = strategy.decide(_context({"battle_button": _detection("battle_button")}))
    strategy.on_action_result(battle, ActionResult("dry_run_click", "executed"))

    now[0] = 8.1
    decision = _third_miss(strategy)

    assert decision.action_name == "adb_back_battle_popup"
    assert decision.reason == "miss_count_3_waiting_skip_button"


def test_watchdog_backs_when_battle_result_does_not_appear() -> None:
    strategy, now = _clocked_strategy()
    strategy.strategy.battle_clicked_in_cycle = True
    strategy.strategy.skip_click_count = 2
    strategy.state = "battle_wait"
    strategy.strategy.current_step_name = "battle_wait"
    battle_wait = strategy.decide(_context({}))
    strategy.on_action_result(battle_wait, ActionResult("wait", "skipped_wait"))

    now[0] = 10.1
    decision = _third_miss(strategy)

    assert decision.action_name == "adb_back_battle_result"
    assert decision.reason == "miss_count_3_waiting_battle_result_popup"


def test_watchdog_backs_when_watch_button_does_not_appear() -> None:
    strategy, now = _clocked_strategy()
    strategy.strategy.battle_clicked_in_cycle = True
    strategy.strategy.skip_click_count = 2
    strategy.strategy.battle_wait_finished_in_cycle = True
    strategy.state = "wait_battle_result_popup"
    result = strategy.decide(
        _context({"battle_result_popup": _detection("battle_result_popup")})
    )
    strategy.on_action_result(result, ActionResult("dry_run_keyevent", "executed"))

    now[0] = 5.1
    decision = _third_miss(strategy)

    assert decision.action_name == "adb_back_watch_popup"
    assert decision.reason == "miss_count_3_waiting_scrap_watch_ad_button"


def test_watchdog_limits_each_step_to_three_back_attempts() -> None:
    strategy, now = _clocked_strategy()
    strategy.state = "wait_scrap_next_button"
    strategy.strategy._start_step("waiting_scrap_next_button")

    for attempt in range(3):
        now[0] = (attempt + 1) * 5.1
        decision = _third_miss(strategy)
        assert decision.action_name == "adb_back_scrap_popup"
        strategy.on_action_result(decision, ActionResult("dry_run_keyevent", "executed"))

    now[0] += 5.1
    blocked = _third_miss(strategy)

    assert blocked == StrategyDecision.wait(1.0, "max_back_attempts_reached_for_step")


def test_miss_count_resets_when_target_is_detected() -> None:
    strategy, _ = _clocked_strategy()
    strategy.state = "wait_battle_button"
    strategy.strategy._start_step("waiting_battle_button")
    strategy.decide(_context({}))
    strategy.decide(_context({}))

    decision = strategy.decide(_context({"battle_button": _detection("battle_button")}))

    assert decision.action_name == "click_battle_button"
    assert strategy.miss_count_by_step["waiting_battle_button"] == 0


def test_miss_count_resets_when_step_changes_and_after_back() -> None:
    strategy, _ = _clocked_strategy()
    entry = strategy.decide(_context({"scrap_entry": _detection("scrap_entry")}))
    strategy.on_action_result(entry, ActionResult("dry_run_click", "executed"))
    strategy.decide(_context({}))
    assert strategy.miss_count_by_step["waiting_scrap_next_button"] == 1

    next_button = strategy.decide(
        _context({"scrap_next_button": _detection("scrap_next_button")})
    )
    strategy.on_action_result(next_button, ActionResult("dry_run_click", "executed"))
    assert strategy.miss_count_by_step["waiting_scrap_next_button"] == 0
    assert strategy.miss_count_by_step["waiting_battle_button"] == 0

    back = _third_miss(strategy)
    strategy.on_action_result(back, ActionResult("dry_run_keyevent", "executed"))
    assert strategy.miss_count_by_step["waiting_battle_button"] == 0


def test_cycle_reset_clears_all_miss_counts() -> None:
    strategy, _ = _clocked_strategy()
    strategy.strategy.miss_count_by_step["waiting_battle_button"] = 2

    strategy.reset_cycle()

    assert strategy.miss_count_by_step == {"home": 0}


def test_watch_ad_click_is_limited_to_two_without_transition() -> None:
    strategy, _ = _clocked_strategy()
    strategy.strategy.battle_clicked_in_cycle = True
    strategy.strategy.skip_click_count = 2
    strategy.strategy.battle_wait_finished_in_cycle = True
    strategy.strategy.battle_result_closed_in_cycle = True
    strategy.strategy.awaiting_watch_ad_in_cycle = True
    strategy.state = "wait_scrap_watch_ad_button"

    first = strategy.decide(
        _context({"scrap_watch_ad_button": _detection("scrap_watch_ad_button")})
    )
    strategy.on_action_result(first, ActionResult("dry_run_click", "executed"))
    second = strategy.decide(
        _context({"scrap_watch_ad_button": _detection("scrap_watch_ad_button")})
    )
    strategy.on_action_result(second, ActionResult("dry_run_click", "executed"))
    blocked = strategy.decide(
        _context({"scrap_watch_ad_button": _detection("scrap_watch_ad_button")})
    )

    assert first.action_name == "click_scrap_watch_ad_button"
    assert second.action_name == "click_scrap_watch_ad_button"
    assert blocked == StrategyDecision.wait(
        1.0,
        "repeated_watch_ad_click_without_ad_transition",
        target_name="scrap_watch_ad_button",
    )


def test_ad_close_timeout_waits_without_back() -> None:
    strategy, now = _clocked_strategy()
    strategy.state = "close_ad"
    strategy.strategy._start_step("waiting_ad_close")

    now[0] = 9.9
    waiting = strategy.decide(_context({}))
    now[0] = 10.1
    timed_out = strategy.decide(_context({}))

    assert waiting == StrategyDecision.wait(1.0, "wait_close_ad_not_found")
    assert timed_out == StrategyDecision.wait(1.0, "wait_close_ad_not_found_after_ad_wait")


def test_scrap_close_reuses_existing_targets_and_completes_on_home() -> None:
    strategy = _load_strategy()
    strategy.state = "close_ad"
    strategy.strategy.scrap_watch_ad_clicked_in_cycle = True
    strategy.strategy.ad_wait_finished_in_cycle = True
    close = strategy.decide(
        _context(
            {
                "close_end_2": _detection("close_end_2", 0.90),
                "close_user_001": _detection("close_user_001", 0.97),
            }
        )
    )
    strategy.on_action_result(close, ActionResult("dry_run_click", "executed"))
    complete = strategy.decide(_context({"scrap_entry": _detection("scrap_entry")}))

    assert close.target_name == "close_user_001"
    assert close.action_name == "close_ad"
    assert close.post_action_delay_seconds == 1.5
    assert complete == StrategyDecision.complete("scrap_return_after_watch_ad")


@pytest.mark.parametrize(
    ("action_name", "reason"),
    [
        ("adb_back_scrap_popup", "close_scrap_popup_until_next_button_visible"),
        ("adb_back_battle_popup", "close_popup_until_battle_button_visible"),
        ("adb_back_battle_result", "close_battle_result_popup"),
        ("adb_back_watch_popup", "transition_timeout_waiting_scrap_watch_ad_button"),
    ],
)
def test_dry_run_keyevent_is_recorded_without_subprocess(
    tmp_path: Path,
    action_name: str,
    reason: str,
) -> None:
    runner, recorder = _keyevent_runner(
        tmp_path,
        DryRunBackend(max_actions=2),
        action_name,
        reason,
    )

    runner.run()

    rows = _read_records(recorder.click_records_path)
    assert rows[0]["decision"] == action_name
    assert rows[0]["target_name"] == "adb_back"
    assert rows[0]["action_type"] == "dry_run_keyevent"
    assert rows[0]["result"] == "executed"
    assert action_name in recorder.events_path.read_text(encoding="utf-8")


def test_adb_keyevent_runs_guarded_back_command(tmp_path: Path) -> None:
    adb = tmp_path / "adb.exe"
    adb.touch()
    commands: list[list[str]] = []

    def command_runner(command: list[str], **_: object) -> subprocess.CompletedProcess[bytes]:
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, b"", b"")

    backend = AdbActionBackend(
        adb_path=adb,
        adb_serial="emulator-5560",
        max_actions=2,
        click_cooldown=0,
        runner=command_runner,
    )

    result = backend.keyevent("BACK", "close_possible_popup")

    assert result == ActionResult("adb_keyevent", "executed", "close_possible_popup")
    assert commands == [
        [str(adb), "-s", "emulator-5560", "shell", "input", "keyevent", "BACK"]
    ]


def test_adb_keyevent_is_written_to_click_records_and_summary(tmp_path: Path) -> None:
    adb = tmp_path / "adb.exe"
    adb.touch()

    def command_runner(command: list[str], **_: object) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(command, 0, b"", b"")

    backend = AdbActionBackend(
        adb_path=adb,
        adb_serial="emulator-5560",
        max_actions=2,
        click_cooldown=0,
        runner=command_runner,
    )
    runner, recorder = _keyevent_runner(
        tmp_path,
        backend,
        "adb_back_scrap_popup",
        "close_scrap_popup_until_next_button_visible",
    )

    runner.run()

    rows = _read_records(recorder.click_records_path)
    summary = recorder.summary_path.read_text(encoding="utf-8")
    assert rows[0]["action_type"] == "adb_keyevent"
    assert rows[0]["target_name"] == "adb_back"
    assert "last_adb_keyevent: loop=1 decision=adb_back_scrap_popup result=executed" in summary


def test_scrap_wait_events_and_summary_are_recorded(tmp_path: Path) -> None:
    strategy = _load_strategy()
    strategy.configure(battle_wait_seconds=1.0, ad_wait_seconds=2.0)
    strategy.strategy.reset_cycle = lambda: setattr(strategy.strategy, "state", "battle_wait")
    screen = tmp_path / "screen.png"
    screen.write_text("screen", encoding="utf-8")
    recorder = RunRecorder(
        output_root=tmp_path / "runs",
        capture_backend="fake",
        strategy_name="scrap_ad_battle",
        battle_wait_seconds=1.0,
        ad_wait_seconds=2.0,
        run_id="scrap-wait",
    )
    runner = StrategyRunner(
        game=GameDefinition("test", tmp_path / "config.json", tmp_path),
        strategy=strategy,
        capture_backend=FakeCaptureBackend(screen),
        action_backend=DryRunBackend(max_actions=8),
        root=tmp_path,
        output_dir=tmp_path / "output",
        max_loops=1,
        run_recorder=recorder,
        matcher=lambda *_, **__: MatchResult(0.0, (0, 0), (1, 1)),
        sleep=lambda _: None,
    )

    runner.run()

    events = recorder.events_path.read_text(encoding="utf-8")
    summary = recorder.summary_path.read_text(encoding="utf-8")
    assert "battle_wait_started" in events
    assert "battle_wait_finished" in events
    assert "strategy: scrap_ad_battle" in summary
    assert "battle_wait_seconds: 1" in summary
    assert "ad_wait_seconds: 2" in summary


def test_scrap_ad_wait_events_are_recorded(tmp_path: Path) -> None:
    strategy = _load_strategy()
    strategy.configure(battle_wait_seconds=1.0, ad_wait_seconds=1.0)
    strategy.strategy.reset_cycle = lambda: setattr(strategy.strategy, "state", "ad_wait")
    runner, recorder = _single_loop_runner(tmp_path, strategy, run_id="ad-wait")

    runner.run()

    events = recorder.events_path.read_text(encoding="utf-8")
    assert "ad_wait_started" in events
    assert "ad_wait_finished" in events


def test_scrap_home_return_completes_non_repeat_cycle(tmp_path: Path) -> None:
    strategy = _load_strategy()
    strategy.strategy.reset_cycle = lambda: _set_scrap_return_state(strategy.strategy)
    runner, recorder = _scrap_completion_runner(tmp_path, strategy, repeat_after_reward=False)

    runner.run()

    summary = recorder.summary_path.read_text(encoding="utf-8")
    events = recorder.events_path.read_text(encoding="utf-8")
    assert "total_cycles_completed: 1" in summary
    assert "last_cycle_completed_reason: scrap_return_after_watch_ad" in summary
    assert "stop_reason: reward_flow_completed" in summary
    assert '"reason": "scrap_return_after_watch_ad"' in events


def test_scrap_home_return_enters_cycle_wait_in_repeat_mode(tmp_path: Path) -> None:
    strategy = _load_strategy()
    strategy.strategy.reset_cycle = lambda: _set_scrap_return_state(strategy.strategy)
    stop_file = tmp_path / "STOP"

    def sleep(_: float) -> None:
        stop_file.touch()

    runner, recorder = _scrap_completion_runner(
        tmp_path,
        strategy,
        repeat_after_reward=True,
        stop_file=stop_file,
        sleep=sleep,
    )

    runner.run()

    events = recorder.events_path.read_text(encoding="utf-8")
    assert "cycle_wait_started" in events
    assert "cycle_wait_interrupted_by_stop_file" in events


def _load_strategy():
    manifest = find_external_strategy(
        "scrap_ad_battle",
        "cats",
        base_dir=ROOT / "external_strategies",
    )
    assert manifest is not None
    strategy = load_external_strategy(manifest)
    strategy.strategy._template_exists = lambda _name: True
    return strategy


def _clocked_strategy():
    strategy = _load_strategy()
    now = [0.0]
    strategy.strategy._clock = lambda: now[0]
    strategy.reset_cycle()
    return strategy, now


def _third_miss(strategy):
    first = strategy.decide(_context({}))
    second = strategy.decide(_context({}))
    third = strategy.decide(_context({}))
    assert first.reason.startswith("miss_count_1_waiting_")
    assert second.reason.startswith("miss_count_2_waiting_")
    return third


def _set_scrap_return_state(strategy) -> None:
    strategy.state = "wait_return_after_ad"
    strategy.scrap_watch_ad_clicked_in_cycle = True
    strategy.close_ad_executed = True


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


class KeyeventStrategy:
    def __init__(self, action_name: str, reason: str) -> None:
        self.action_name = action_name
        self.reason = reason

    def targets(self):
        return []

    def decide(self, context):
        return StrategyDecision.keyevent("BACK", self.action_name, self.reason)


class FakeCaptureBackend:
    name = "fake"

    def __init__(self, path: Path) -> None:
        self.path = path

    def capture(self, output_path: Path) -> WindowFrame:
        return WindowFrame(self.path, "fake", (0, 0), (100, 100))


def _keyevent_runner(tmp_path: Path, backend, action_name: str, reason: str):
    screen = tmp_path / "screen.png"
    screen.write_text("screen", encoding="utf-8")
    recorder = RunRecorder(
        output_root=tmp_path / "runs",
        capture_backend="fake",
        strategy_name="scrap_ad_battle",
        run_id="keyevent",
    )
    runner = StrategyRunner(
        game=GameDefinition("test", tmp_path / "config.json", tmp_path),
        strategy=KeyeventStrategy(action_name, reason),
        capture_backend=FakeCaptureBackend(screen),
        action_backend=backend,
        root=tmp_path,
        output_dir=tmp_path / "output",
        max_loops=1,
        run_recorder=recorder,
        matcher=lambda *_, **__: MatchResult(0.0, (0, 0), (1, 1)),
        sleep=lambda _: None,
    )
    return runner, recorder


def _single_loop_runner(tmp_path: Path, strategy, *, run_id: str):
    screen = tmp_path / f"{run_id}.png"
    screen.write_text("screen", encoding="utf-8")
    recorder = RunRecorder(
        output_root=tmp_path / "runs",
        capture_backend="fake",
        strategy_name="scrap_ad_battle",
        battle_wait_seconds=strategy.battle_wait_seconds,
        ad_wait_seconds=strategy.ad_wait_seconds,
        run_id=run_id,
    )
    runner = StrategyRunner(
        game=GameDefinition("test", tmp_path / "config.json", tmp_path),
        strategy=strategy,
        capture_backend=FakeCaptureBackend(screen),
        action_backend=DryRunBackend(max_actions=8),
        root=tmp_path,
        output_dir=tmp_path / "output",
        max_loops=1,
        run_recorder=recorder,
        matcher=lambda *_, **__: MatchResult(0.0, (0, 0), (1, 1)),
        sleep=lambda _: None,
    )
    return runner, recorder


def _scrap_completion_runner(
    tmp_path: Path,
    strategy,
    *,
    repeat_after_reward: bool,
    stop_file: Path | None = None,
    sleep=lambda _: None,
):
    scrap_entry_template = tmp_path / "scrap_entry.png"
    scrap_entry_template.touch()
    strategy.strategy.targets = lambda: [
        TargetSpec("scrap_entry", str(scrap_entry_template), 0.80)
    ]
    screen = tmp_path / "home.png"
    screen.write_text("screen", encoding="utf-8")
    recorder = RunRecorder(
        output_root=tmp_path / "runs",
        capture_backend="fake",
        strategy_name="scrap_ad_battle",
        repeat_after_reward=repeat_after_reward,
        cycle_wait_seconds=1.0,
        run_id="scrap-complete",
    )

    def matcher(_screen: Path, template: Path, **_: object) -> MatchResult:
        confidence = 0.95 if template.name == "scrap_entry.png" else 0.0
        return MatchResult(confidence, (10, 20), (30, 40))

    runner = StrategyRunner(
        game=GameDefinition("test", tmp_path / "config.json", tmp_path),
        strategy=strategy,
        capture_backend=FakeCaptureBackend(screen),
        action_backend=DryRunBackend(max_actions=8),
        root=tmp_path,
        output_dir=tmp_path / "output",
        max_loops=1,
        run_recorder=recorder,
        stop_file=stop_file,
        repeat_after_reward=repeat_after_reward,
        cycle_wait_seconds=1.0,
        matcher=matcher,
        sleep=sleep,
    )
    return runner, recorder


def _read_records(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))

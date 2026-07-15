from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from cats_automatic.actions import ActionResult
from cats_automatic.game_loader import load_game, load_strategy
from cats_automatic.main import format_strategy_list
from cats_automatic.runtime_paths import pre_watch_optional_templates_dir, watch_button_templates_dir
from cats_automatic.strategy_base import DetectionResult, StrategyContext, StrategyDecision
from external_strategies.scrap_then_ad_reward_v2.close_markers import safe_close_marker_names
from external_strategies.scrap_then_ad_reward_v2.film_flow import (
    CLOSE_AD_MIN_CONFIDENCE,
    FILM_ENTRY_MARKER,
    WATCH_AD_MARKER,
)
from external_strategies.scrap_then_ad_reward_v2.strategy import Strategy
from external_strategies.scrap_then_ad_reward_v2.template_sources import V2_CANONICAL_TEMPLATE_DIRS


ROOT = Path(__file__).resolve().parents[1]


def test_list_strategies_includes_scrap_then_ad_reward_v2() -> None:
    output = format_strategy_list("cats")

    assert "scrap_then_ad_reward_v2" in output
    assert "source=external" in output


def test_load_strategy_returns_v2_external_strategy() -> None:
    strategy = load_strategy("cats", "scrap_then_ad_reward_v2")

    assert hasattr(strategy, "targets")
    assert hasattr(strategy, "decide")
    assert strategy.current_phase() == "START"


def test_v2_strategy_targets_use_canonical_or_explicit_runtime_user_templates() -> None:
    strategy = Strategy()
    allowed_dirs = tuple(
        path.resolve()
        for path in (
            *V2_CANONICAL_TEMPLATE_DIRS,
            pre_watch_optional_templates_dir(create=False),
            watch_button_templates_dir(create=False),
        )
    )

    assert strategy.targets()
    for target in strategy.targets():
        template = Path(target.template).resolve()
        assert any(_is_relative_to(template, directory) for directory in allowed_dirs)


def test_multiple_decide_loops_share_film_flow_context() -> None:
    strategy = Strategy()

    start = strategy.decide(_context({}))
    strategy.on_action_result(start, _result("no_action"))
    home_ready = strategy.decide(
        _context(
            {
                "main-definate": _detection("main-definate", 0.96),
                FILM_ENTRY_MARKER: _detection(FILM_ENTRY_MARKER, 0.92),
            }
        )
    )
    strategy.on_action_result(home_ready, _result("no_action"))
    enter_film = strategy.decide(
        _context(
            {
                "main-definate": _detection("main-definate", 0.96),
                FILM_ENTRY_MARKER: _detection(FILM_ENTRY_MARKER, 0.92),
            }
        )
    )

    assert home_ready.action_name == "no_action"
    assert strategy.flow_context.current_step == "ENTER_FILM"
    assert enter_film.action_name == "tap_marker"
    assert enter_film.action_params["marker"] == FILM_ENTRY_MARKER


def test_unknown_while_watching_ad_waits() -> None:
    strategy = Strategy()
    strategy.flow_context.current_step = "WATCH_AD"

    decision = strategy.decide(_context({}))

    assert decision.action_name == "wait"
    assert decision.reason == "wait_for_ad_close_marker"
    assert strategy.flow_context.current_step == "WATCH_AD"


def test_ad_close_page_uses_safe_close_marker_decision() -> None:
    strategy = Strategy()
    strategy.flow_context.current_step = "WATCH_AD"
    marker = safe_close_marker_names()[0]

    decision = strategy.decide(_context({marker: _close_detection(marker, 0.92)}))

    assert decision.action_name == "tap_marker"
    assert decision.action_params["marker"] == marker
    assert decision.action_params["min_confidence"] == CLOSE_AD_MIN_CONFIDENCE


def test_reward_page_presses_back_at_claim_reward_step() -> None:
    strategy = Strategy()
    strategy.flow_context.current_step = "CLAIM_REWARD"

    decision = strategy.decide(_context({"get_reward": _detection("get_reward", 0.91)}))

    assert decision == StrategyDecision.keyevent("BACK", "press_back", "reward_success_press_back")


def test_return_home_completes_flow() -> None:
    strategy = Strategy()
    strategy.flow_context.current_step = "RETURN_HOME"

    decision = strategy.decide(_context({"main-definate": _detection("main-definate", 0.96)}))

    assert decision.kind == "complete"
    assert strategy.flow_context.current_step == "FINISH"


def test_watch_ad_film_dry_run_sets_pending_watch_ad_without_faking_state() -> None:
    strategy = Strategy()
    strategy.flow_context.current_step = "START_AD"
    decision = strategy.decide(_context({WATCH_AD_MARKER: _detection(WATCH_AD_MARKER, 0.93)}))

    strategy.on_action_result(decision, _result("tap_marker", dry_run=True))
    wait_decision = strategy.decide(_context({}))

    assert strategy.flow_context.current_step == "WATCH_AD"
    assert wait_decision.action_name == "wait"
    assert wait_decision.reason == "wait_for_ad_close_marker"


def test_cli_list_strategies_no_longer_reports_unknown_v2() -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "cats_automatic.main",
            "--game",
            "cats",
            "--list-strategies",
        ],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    assert "scrap_then_ad_reward_v2" in result.stdout
    assert "Unknown strategy for game 'cats': scrap_then_ad_reward_v2" not in result.stdout


def _context(detections: dict[str, DetectionResult]) -> StrategyContext:
    return StrategyContext(
        loop_index=1,
        screen_path=Path("screen.png"),
        game=load_game("cats"),
        detections=detections,
        resolve_template=lambda value: Path(value),
    )


def _detection(name: str, confidence: float) -> DetectionResult:
    template = _template_path(name)
    return DetectionResult(
        name=name,
        template=template,
        confidence=confidence,
        center=(100, 120),
        top_left=(90, 110),
        size=(20, 20),
        scale=1.0,
        threshold=0.8,
    )


def _close_detection(name: str, confidence: float) -> DetectionResult:
    return _detection(name, confidence)


def _template_path(name: str) -> Path:
    if name == "close_buttons":
        from external_strategies.scrap_then_ad_reward_v2.screen_state_detector import _template_paths_for_marker

        return _template_paths_for_marker(name)[0]
    return Path(f"{name}.png")


def _result(action: str, *, dry_run: bool = True) -> ActionResult:
    return ActionResult(
        action,
        "skipped_dry_run" if dry_run else "executed",
        success=True,
        action=action,
        dry_run=dry_run,
    )


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True

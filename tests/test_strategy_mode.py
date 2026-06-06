from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import Mock

import pytest
from PIL import Image

from cats_automatic.actions import ClickAction, DryRunBackend, TapAction
from cats_automatic.backends import (
    CaptureBackendError,
    ReplayCaptureBackend,
    StaticImageCaptureBackend,
    create_capture_backend,
)
from cats_automatic.backends.window_capture import WindowCaptureBackend, WindowRect
from cats_automatic.game_base import GameDefinition
from cats_automatic.game_loader import (
    GameLoadError,
    load_game,
    load_strategy,
    resolve_template_path,
)
from cats_automatic.games.cats.strategies.ad_reward import Strategy as AdRewardStrategy
from cats_automatic.strategy_base import (
    DetectionResult,
    Region,
    StrategyContext,
    StrategyDecision,
    TargetSpec,
)
from cats_automatic.main import build_parser, build_strategy_capture_backend, parse_replay_screens
from cats_automatic.strategy_runner import StrategyRunner
from cats_automatic.vision import MatchResult
from cats_automatic.window_capture import WindowFrame


def test_game_loader_loads_cats_game() -> None:
    game = load_game("cats")

    assert game.name == "cats"


def test_strategy_loader_loads_named_strategy() -> None:
    strategy = load_strategy("cats", "ad_reward")

    assert [target.name for target in strategy.targets()] == [
        "close_end_2",
        "close_end_1",
        "page_marker",
        "reward_confirm_marker",
        "confirm_button",
        "watch_ad_button",
        "ad_entry",
    ]
    targets = {target.name: target for target in strategy.targets()}
    assert targets["close_end_2"].template == "templates/close-end-2.png"
    assert targets["close_end_2"].threshold == 0.75
    assert targets["close_end_2"].match_mode == "color"
    assert targets["close_end_2"].region == Region(x=1050, y=0, width=230, height=130)
    assert targets["close_end_1"].template == "templates/close-end-1.png"
    assert targets["close_end_1"].threshold == 0.90
    assert targets["close_end_1"].match_mode == "color"
    assert targets["close_end_1"].region == Region(x=80, y=0, width=220, height=130)
    assert targets["page_marker"].template == "templates/page-marker.png"
    assert targets["page_marker"].threshold == 0.80
    assert targets["page_marker"].match_mode == "color"
    assert targets["reward_confirm_marker"].template == "templates/reward-confirm-marker.png"
    assert targets["reward_confirm_marker"].threshold == 0.80
    assert targets["reward_confirm_marker"].match_mode == "color"
    assert targets["confirm_button"].template == "templates/confirm-button.png"
    assert targets["confirm_button"].threshold == 0.80
    assert targets["confirm_button"].match_mode == "color"
    assert targets["watch_ad_button"].template == "templates/watch-ad-button.png"
    assert targets["watch_ad_button"].threshold == 0.80
    assert targets["watch_ad_button"].match_mode == "color"


def test_strategy_loader_reports_unknown_strategy() -> None:
    with pytest.raises(GameLoadError, match="Unknown strategy for game 'cats': abc"):
        load_strategy("cats", "abc")


def test_ad_reward_strategy_clicks_watch_ad_button_on_target_page() -> None:
    strategy = AdRewardStrategy()
    context = StrategyContext(
        loop_index=1,
        screen_path=Path("screen.png"),
        game=load_game("cats"),
        detections={
            "page_marker": _detection("page_marker"),
            "watch_ad_button": _detection("watch_ad_button"),
        },
        resolve_template=lambda value: Path(value),
    )

    decision = strategy.decide(context)

    assert decision == StrategyDecision.click(
        "watch_ad_button",
        "click_watch_ad_button",
        "click_watch_ad_button",
    )


def test_ad_reward_strategy_confirms_reward_when_marker_and_button_detected() -> None:
    strategy = AdRewardStrategy()
    context = _context_with_detections(
        {
            "reward_confirm_marker": _detection("reward_confirm_marker"),
            "confirm_button": _detection("confirm_button"),
        }
    )

    decision = strategy.decide(context)

    assert decision == StrategyDecision.click("confirm_button", "confirm_reward", "confirm_reward")


def test_ad_reward_strategy_waits_when_reward_confirm_button_missing() -> None:
    strategy = AdRewardStrategy()
    context = _context_with_detections(
        {"reward_confirm_marker": _detection("reward_confirm_marker")}
    )

    decision = strategy.decide(context)

    assert decision == StrategyDecision.wait(1.0, "wait_reward_confirm_no_button")


def test_ad_reward_strategy_does_not_confirm_without_reward_marker() -> None:
    strategy = AdRewardStrategy()
    context = _context_with_detections({"confirm_button": _detection("confirm_button")})

    decision = strategy.decide(context)

    assert decision.action_name != "confirm_reward"
    assert decision == StrategyDecision.wait(1.0, "wait_not_on_target_page")


def test_ad_reward_strategy_clicks_right_close_first() -> None:
    strategy = AdRewardStrategy()
    context = StrategyContext(
        loop_index=1,
        screen_path=Path("screen.png"),
        game=load_game("cats"),
        detections={"close_end_2": _detection("close_end_2")},
        resolve_template=lambda value: Path(value),
    )

    decision = strategy.decide(context)

    assert decision == StrategyDecision.click("close_end_2", "close_ad", "close_ad")


def test_ad_reward_strategy_clicks_left_close_when_right_missing() -> None:
    strategy = AdRewardStrategy()
    context = StrategyContext(
        loop_index=1,
        screen_path=Path("screen.png"),
        game=load_game("cats"),
        detections={"close_end_1": _detection("close_end_1")},
        resolve_template=lambda value: Path(value),
    )

    decision = strategy.decide(context)

    assert decision == StrategyDecision.click("close_end_1", "close_ad", "close_ad")


def test_ad_reward_strategy_prefers_right_close_over_left_close() -> None:
    strategy = AdRewardStrategy()
    context = StrategyContext(
        loop_index=1,
        screen_path=Path("screen.png"),
        game=load_game("cats"),
        detections={
            "close_end_1": _detection("close_end_1"),
            "close_end_2": _detection("close_end_2"),
        },
        resolve_template=lambda value: Path(value),
    )

    decision = strategy.decide(context)

    assert decision == StrategyDecision.click("close_end_2", "close_ad", "close_ad")


def test_ad_reward_strategy_allows_three_consecutive_close_actions() -> None:
    strategy = AdRewardStrategy()
    decisions = [
        strategy.decide(_context_with_detections({"close_end_2": _detection("close_end_2")}))
        for _ in range(3)
    ]

    assert decisions == [
        StrategyDecision.click("close_end_2", "close_ad", "close_ad"),
        StrategyDecision.click("close_end_2", "close_ad", "close_ad"),
        StrategyDecision.click("close_end_2", "close_ad", "close_ad"),
    ]


def test_ad_reward_strategy_waits_on_fourth_consecutive_close_action() -> None:
    strategy = AdRewardStrategy()

    for _ in range(3):
        strategy.decide(_context_with_detections({"close_end_2": _detection("close_end_2")}))
    decision = strategy.decide(_context_with_detections({"close_end_2": _detection("close_end_2")}))

    assert decision == StrategyDecision.wait(1.0, "wait_close_limit_reached")


def test_ad_reward_strategy_resets_close_count_on_non_close_state() -> None:
    strategy = AdRewardStrategy()

    strategy.decide(_context_with_detections({"close_end_2": _detection("close_end_2")}))
    strategy.decide(_context_with_detections({"close_end_2": _detection("close_end_2")}))
    non_close_decision = strategy.decide(
        _context_with_detections(
            {
                "page_marker": _detection("page_marker"),
                "watch_ad_button": _detection("watch_ad_button"),
            }
        )
    )
    close_after_reset = strategy.decide(
        _context_with_detections({"close_end_2": _detection("close_end_2")})
    )

    assert non_close_decision == StrategyDecision.click(
        "watch_ad_button",
        "click_watch_ad_button",
        "click_watch_ad_button",
    )
    assert close_after_reset == StrategyDecision.click("close_end_2", "close_ad", "close_ad")


def test_ad_reward_strategy_close_limit_applies_to_left_close_too() -> None:
    strategy = AdRewardStrategy()

    for _ in range(3):
        strategy.decide(_context_with_detections({"close_end_1": _detection("close_end_1")}))
    decision = strategy.decide(_context_with_detections({"close_end_1": _detection("close_end_1")}))

    assert decision == StrategyDecision.wait(1.0, "wait_close_limit_reached")


def test_ad_reward_strategy_waits_when_not_on_target_page() -> None:
    strategy = AdRewardStrategy()
    context = StrategyContext(
        loop_index=1,
        screen_path=Path("screen.png"),
        game=load_game("cats"),
        detections={},
        resolve_template=lambda value: Path(value),
    )

    decision = strategy.decide(context)

    assert decision == StrategyDecision.wait(1.0, "wait_not_on_target_page")


def test_ad_reward_strategy_waits_when_watch_ad_button_missing() -> None:
    strategy = AdRewardStrategy()
    context = StrategyContext(
        loop_index=1,
        screen_path=Path("screen.png"),
        game=load_game("cats"),
        detections={"page_marker": _detection("page_marker")},
        resolve_template=lambda value: Path(value),
    )

    decision = strategy.decide(context)

    assert decision == StrategyDecision.wait(1.0, "wait_no_ad_button")


def test_ad_reward_strategy_does_not_close_without_close_buttons() -> None:
    strategy = AdRewardStrategy()
    context = StrategyContext(
        loop_index=1,
        screen_path=Path("screen.png"),
        game=load_game("cats"),
        detections={
            "page_marker": _detection("page_marker"),
            "watch_ad_button": _detection("watch_ad_button"),
        },
        resolve_template=lambda value: Path(value),
    )

    decision = strategy.decide(context)

    assert decision.action_name != "close_ad"


def test_template_resolver_prefers_game_templates(tmp_path: Path) -> None:
    game_templates = tmp_path / "game" / "templates"
    root_templates = tmp_path / "templates"
    game_templates.mkdir(parents=True)
    root_templates.mkdir()
    game_template = game_templates / "ad-entry.png"
    root_template = root_templates / "ad-entry.png"
    game_template.touch()
    root_template.touch()
    game = GameDefinition("test", tmp_path / "game" / "config.json", game_templates)

    assert resolve_template_path(game, tmp_path, "templates/ad-entry.png") == game_template


def test_template_resolver_falls_back_to_root_templates(tmp_path: Path) -> None:
    game_templates = tmp_path / "game" / "templates"
    root_templates = tmp_path / "templates"
    game_templates.mkdir(parents=True)
    root_templates.mkdir()
    root_template = root_templates / "ad-entry.png"
    root_template.touch()
    game = GameDefinition("test", tmp_path / "game" / "config.json", game_templates)

    assert resolve_template_path(game, tmp_path, "templates/ad-entry.png") == root_template


def test_ad_reward_ad_entry_template_resolves_to_game_template() -> None:
    root = Path(__file__).resolve().parents[1]
    game = load_game("cats")
    strategy = AdRewardStrategy()
    ad_entry_target = next(target for target in strategy.targets() if target.name == "ad_entry")

    resolved = resolve_template_path(game, root, ad_entry_target.template)

    assert resolved == game.templates_dir / "ad-entry.png"
    assert resolved.exists()


def test_ad_reward_page_targets_resolve_to_game_templates() -> None:
    root = Path(__file__).resolve().parents[1]
    game = load_game("cats")
    strategy = AdRewardStrategy()
    targets = {target.name: target for target in strategy.targets()}

    assert resolve_template_path(game, root, targets["page_marker"].template) == (
        game.templates_dir / "page-marker.png"
    )
    assert resolve_template_path(game, root, targets["watch_ad_button"].template) == (
        game.templates_dir / "watch-ad-button.png"
    )
    assert resolve_template_path(game, root, targets["reward_confirm_marker"].template) == (
        game.templates_dir / "reward-confirm-marker.png"
    )
    assert resolve_template_path(game, root, targets["confirm_button"].template) == (
        game.templates_dir / "confirm-button.png"
    )
    assert resolve_template_path(game, root, targets["close_end_2"].template) == (
        game.templates_dir / "close-end-2.png"
    )
    assert resolve_template_path(game, root, targets["close_end_1"].template) == (
        game.templates_dir / "close-end-1.png"
    )


def test_strategy_runner_executes_finite_dry_run_loop(tmp_path: Path) -> None:
    screen = tmp_path / "screen.png"
    screen.touch()
    templates = tmp_path / "templates"
    templates.mkdir()
    (templates / "target.png").touch()
    strategy = StaticStrategy()
    action_backend = RecordingActionBackend()
    runner = StrategyRunner(
        game=GameDefinition("test", tmp_path / "config.json", templates),
        strategy=strategy,
        capture_backend=FakeCaptureBackend(screen),
        action_backend=action_backend,
        root=tmp_path,
        output_dir=tmp_path / "output",
        max_loops=2,
        matcher=lambda *_, **__: MatchResult(0.95, (10, 20), (30, 40)),
        sleep=lambda _: None,
    )

    completed = runner.run()

    assert completed == 2
    assert [action.x for action in action_backend.clicks] == [25, 25]


def test_strategy_mode_screen_uses_static_capture_backend(tmp_path: Path) -> None:
    screen = tmp_path / "ad_entry_screen.png"
    Image.new("RGB", (120, 80), "white").save(screen)
    args = build_parser().parse_args(
        [
            "--game",
            "cats",
            "--strategy",
            "ad_reward",
            "--screen",
            str(screen),
            "--capture-backend",
            "window",
            "--max-loops",
            "1",
        ]
    )

    backend = build_strategy_capture_backend(args)
    frame = backend.capture(tmp_path / "should-not-be-written.png")

    assert isinstance(backend, StaticImageCaptureBackend)
    assert frame.path == screen
    assert frame.size == (120, 80)
    assert not (tmp_path / "should-not-be-written.png").exists()


def test_replay_capture_backend_args_parse_multiple_screens() -> None:
    args = build_parser().parse_args(
        [
            "--game",
            "cats",
            "--strategy",
            "ad_reward",
            "--capture-backend",
            "replay",
            "--replay-screens",
            "samples/cats/home_screen.png,samples/cats/jiao_juan_page.png",
            "--max-loops",
            "2",
        ]
    )

    assert args.capture_backend == "replay"
    assert parse_replay_screens(args.replay_screens) == [
        Path("samples/cats/home_screen.png"),
        Path("samples/cats/jiao_juan_page.png"),
    ]


def test_replay_capture_backend_returns_screens_in_order(tmp_path: Path) -> None:
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    Image.new("RGB", (10, 20), "red").save(first)
    Image.new("RGB", (30, 40), "blue").save(second)
    backend = ReplayCaptureBackend([first, second])

    first_frame = backend.capture(tmp_path / "unused-1.png")
    second_frame = backend.capture(tmp_path / "unused-2.png")

    assert first_frame.path == first
    assert first_frame.size == (10, 20)
    assert second_frame.path == second
    assert second_frame.size == (30, 40)


def test_replay_capture_backend_reuses_last_screen_when_exhausted(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    only = tmp_path / "only.png"
    Image.new("RGB", (10, 20), "red").save(only)
    backend = ReplayCaptureBackend([only])

    backend.capture(tmp_path / "unused-1.png")
    frame = backend.capture(tmp_path / "unused-2.png")

    assert frame.path == only
    assert "Replay screens exhausted; reusing last screen" in capsys.readouterr().out


def test_replay_capture_backend_reports_missing_screen(tmp_path: Path) -> None:
    with pytest.raises(CaptureBackendError, match="Replay screen image does not exist"):
        ReplayCaptureBackend([tmp_path / "missing.png"])


def test_build_strategy_capture_backend_supports_replay() -> None:
    root = Path(__file__).resolve().parents[1]
    args = build_parser().parse_args(
        [
            "--game",
            "cats",
            "--strategy",
            "ad_reward",
            "--capture-backend",
            "replay",
            "--replay-screens",
            str(root / "samples" / "cats" / "home_screen.png"),
            "--max-loops",
            "1",
        ]
    )

    backend = build_strategy_capture_backend(args)

    assert isinstance(backend, ReplayCaptureBackend)


def test_static_capture_backend_reports_missing_screen(tmp_path: Path) -> None:
    backend = StaticImageCaptureBackend(tmp_path / "missing.png")

    with pytest.raises(CaptureBackendError, match="Screen image does not exist"):
        backend.capture(tmp_path / "output.png")


def test_strategy_runner_can_use_static_screen_backend(tmp_path: Path) -> None:
    screen = tmp_path / "screen.png"
    Image.new("RGB", (64, 64), "white").save(screen)
    templates = tmp_path / "templates"
    templates.mkdir()
    template = templates / "target.png"
    Image.new("RGB", (4, 4), "white").save(template)
    action_backend = RecordingActionBackend()
    runner = StrategyRunner(
        game=GameDefinition("test", tmp_path / "config.json", templates),
        strategy=StaticStrategy(),
        capture_backend=StaticImageCaptureBackend(screen),
        action_backend=action_backend,
        root=tmp_path,
        output_dir=tmp_path / "output",
        max_loops=1,
        matcher=lambda screen_path, *_args, **_kwargs: MatchResult(
            0.95,
            (10, 20),
            (30, 40),
        )
        if screen_path == screen
        else MatchResult(0.0, (0, 0), (0, 0)),
        sleep=lambda _: None,
    )

    completed = runner.run()

    assert completed == 1
    assert [action.x for action in action_backend.clicks] == [25]


def test_ad_reward_static_home_screen_keeps_ad_entry_detection() -> None:
    root = Path(__file__).resolve().parents[1]
    game = load_game("cats")
    strategy = AdRewardStrategy()
    action_backend = RecordingActionBackend()
    runner = StrategyRunner(
        game=game,
        strategy=strategy,
        capture_backend=StaticImageCaptureBackend(root / "samples" / "cats" / "home_screen.png"),
        action_backend=action_backend,
        root=root,
        output_dir=root / "output" / "test-strategy",
        max_loops=1,
        sleep=lambda _: None,
    )

    completed = runner.run()

    assert completed == 1
    assert [(action.x, action.y, action.reason) for action in action_backend.clicks] == [
        (1225, 257, "click_ad_entry")
    ]


def test_ad_reward_static_jiao_juan_page_clicks_watch_ad_button() -> None:
    root = Path(__file__).resolve().parents[1]
    game = load_game("cats")
    strategy = AdRewardStrategy()
    action_backend = RecordingActionBackend()
    runner = StrategyRunner(
        game=game,
        strategy=strategy,
        capture_backend=StaticImageCaptureBackend(root / "samples" / "cats" / "jiao_juan_page.png"),
        action_backend=action_backend,
        root=root,
        output_dir=root / "output" / "test-strategy",
        max_loops=1,
        sleep=lambda _: None,
    )

    completed = runner.run()

    assert completed == 1
    assert [(action.x, action.y, action.reason) for action in action_backend.clicks] == [
        (636, 615, "click_watch_ad_button")
    ]


def test_ad_reward_static_reward_confirm_page_clicks_confirm_button() -> None:
    root = Path(__file__).resolve().parents[1]
    game = load_game("cats")
    action_backend = RecordingActionBackend()
    runner = StrategyRunner(
        game=game,
        strategy=AdRewardStrategy(),
        capture_backend=StaticImageCaptureBackend(
            root / "samples" / "cats" / "reward_confirm_page.png"
        ),
        action_backend=action_backend,
        root=root,
        output_dir=root / "output" / "test-strategy",
        max_loops=1,
        sleep=lambda _: None,
    )

    completed = runner.run()

    assert completed == 1
    assert [(action.x, action.y, action.reason) for action in action_backend.clicks] == [
        (631, 657, "confirm_reward")
    ]


def test_ad_reward_reward_confirm_click_uses_confirm_button_center(tmp_path: Path) -> None:
    screen = tmp_path / "screen.png"
    Image.new("RGB", (1280, 720), "black").save(screen)
    templates = tmp_path / "templates"
    templates.mkdir()
    (templates / "reward-confirm-marker.png").touch()
    (templates / "confirm-button.png").touch()
    action_backend = RecordingActionBackend()
    runner = StrategyRunner(
        game=GameDefinition("test", tmp_path / "config.json", templates),
        strategy=AdRewardStrategy(),
        capture_backend=StaticImageCaptureBackend(screen),
        action_backend=action_backend,
        root=tmp_path,
        output_dir=tmp_path / "output",
        max_loops=1,
        matcher=lambda _screen, template, **_kwargs: MatchResult(
            0.95,
            (621, 647) if Path(template).name == "confirm-button.png" else (300, 350),
            (20, 20),
        ),
        sleep=lambda _: None,
    )

    completed = runner.run()

    assert completed == 1
    assert [(action.x, action.y, action.reason) for action in action_backend.clicks] == [
        (631, 657, "confirm_reward")
    ]


def test_ad_reward_close_button_click_uses_selected_detection_center(tmp_path: Path) -> None:
    screen = tmp_path / "screen.png"
    Image.new("RGB", (1280, 720), "black").save(screen)
    templates = tmp_path / "templates"
    templates.mkdir()
    (templates / "close-end-1.png").touch()
    (templates / "close-end-2.png").touch()
    action_backend = RecordingActionBackend()
    strategy = AdRewardStrategy()
    runner = StrategyRunner(
        game=GameDefinition("test", tmp_path / "config.json", templates),
        strategy=strategy,
        capture_backend=StaticImageCaptureBackend(screen),
        action_backend=action_backend,
        root=tmp_path,
        output_dir=tmp_path / "output",
        max_loops=1,
        matcher=lambda _screen, template, **_kwargs: MatchResult(
            0.95,
            (1110, 44) if Path(template).name == "close-end-2.png" else (110, 44),
            (20, 20),
        ),
        sleep=lambda _: None,
    )

    completed = runner.run()

    assert completed == 1
    assert [(action.x, action.y, action.reason) for action in action_backend.clicks] == [
        (1120, 54, "close_ad")
    ]


def test_ad_reward_close_button_detection_passes_regions(tmp_path: Path) -> None:
    screen = tmp_path / "screen.png"
    Image.new("RGB", (1280, 720), "black").save(screen)
    templates = tmp_path / "templates"
    templates.mkdir()
    for name in ("close-end-1.png", "close-end-2.png"):
        (templates / name).touch()
    seen_regions: dict[str, tuple[int, int, int, int] | None] = {}

    def matcher(_screen: Path, template: Path, **kwargs: object) -> MatchResult:
        seen_regions[Path(template).name] = kwargs.get("region")  # type: ignore[assignment]
        return MatchResult(0.0, (0, 0), (1, 1))

    runner = StrategyRunner(
        game=GameDefinition("test", tmp_path / "config.json", templates),
        strategy=AdRewardStrategy(),
        capture_backend=StaticImageCaptureBackend(screen),
        action_backend=RecordingActionBackend(),
        root=tmp_path,
        output_dir=tmp_path / "output",
        max_loops=1,
        matcher=matcher,
        sleep=lambda _: None,
    )

    runner.run()

    assert seen_regions["close-end-2.png"] == (1050, 0, 230, 130)
    assert seen_regions["close-end-1.png"] == (80, 0, 220, 130)


@pytest.mark.parametrize(
    ("screenshot", "expected_click"),
    [
        ("Screenshot_20260531-222029.png", (1121, 54)),
        ("Screenshot_20260531-222057.png", (1121, 54)),
        ("Screenshot_20260531-222821.png", (1231, 48)),
    ],
)
def test_ad_reward_ad_close_screens_click_close_button(
    screenshot: str,
    expected_click: tuple[int, int],
) -> None:
    root = Path(__file__).resolve().parents[1]
    game = load_game("cats")
    action_backend = RecordingActionBackend()
    runner = StrategyRunner(
        game=game,
        strategy=AdRewardStrategy(),
        capture_backend=StaticImageCaptureBackend(
            root / "samples" / "cats" / "ad_close_tests" / screenshot
        ),
        action_backend=action_backend,
        root=root,
        output_dir=root / "output" / "test-strategy",
        max_loops=1,
        sleep=lambda _: None,
    )

    completed = runner.run()

    assert completed == 1
    assert [(action.x, action.y, action.reason) for action in action_backend.clicks] == [
        (*expected_click, "close_ad")
    ]


def test_ad_reward_ad_close_runner_limits_consecutive_close_actions() -> None:
    root = Path(__file__).resolve().parents[1]
    game = load_game("cats")
    action_backend = RecordingActionBackend()
    runner = StrategyRunner(
        game=game,
        strategy=AdRewardStrategy(),
        capture_backend=StaticImageCaptureBackend(
            root / "samples" / "cats" / "ad_close_tests" / "Screenshot_20260531-222029.png"
        ),
        action_backend=action_backend,
        root=root,
        output_dir=root / "output" / "test-strategy",
        max_loops=4,
        sleep=lambda _: None,
    )

    completed = runner.run()

    assert completed == 4
    assert [action.reason for action in action_backend.clicks] == [
        "close_ad",
        "close_ad",
        "close_ad",
    ]
    assert action_backend.waits == [(1.0, "wait_close_limit_reached")]


def test_ad_reward_replay_full_dry_run_chain() -> None:
    root = Path(__file__).resolve().parents[1]
    game = load_game("cats")
    action_backend = RecordingActionBackend()
    runner = StrategyRunner(
        game=game,
        strategy=AdRewardStrategy(),
        capture_backend=ReplayCaptureBackend(
            [
                root / "samples" / "cats" / "home_screen.png",
                root / "samples" / "cats" / "jiao_juan_page.png",
                root
                / "samples"
                / "cats"
                / "ad_close_tests"
                / "Screenshot_20260531-222029.png",
                root / "samples" / "cats" / "reward_confirm_page.png",
            ]
        ),
        action_backend=action_backend,
        root=root,
        output_dir=root / "output" / "test-strategy",
        max_loops=4,
        sleep=lambda _: None,
    )

    completed = runner.run()

    assert completed == 4
    assert [action.reason for action in action_backend.clicks] == [
        "click_ad_entry",
        "click_watch_ad_button",
        "close_ad",
        "confirm_reward",
    ]


def test_ad_reward_replay_cli_outputs_full_dry_run_chain() -> None:
    root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src")
    replay_screens = ",".join(
        [
            str(root / "samples" / "cats" / "home_screen.png"),
            str(root / "samples" / "cats" / "jiao_juan_page.png"),
            str(
                root
                / "samples"
                / "cats"
                / "ad_close_tests"
                / "Screenshot_20260531-222029.png"
            ),
            str(root / "samples" / "cats" / "reward_confirm_page.png"),
        ]
    )
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "cats_automatic.main",
            "--game",
            "cats",
            "--strategy",
            "ad_reward",
            "--capture-backend",
            "replay",
            "--replay-screens",
            replay_screens,
            "--max-loops",
            "4",
        ],
        cwd=root,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    assert "Decision: click_ad_entry" in result.stdout
    assert "Decision: click_watch_ad_button" in result.stdout
    assert "Decision: close_ad" in result.stdout
    assert "Decision: confirm_reward" in result.stdout


def test_ad_reward_static_jiao_juan_page_cli_outputs_dry_run() -> None:
    root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "cats_automatic.main",
            "--game",
            "cats",
            "--strategy",
            "ad_reward",
            "--screen",
            str(root / "samples" / "cats" / "jiao_juan_page.png"),
            "--max-loops",
            "1",
        ],
        cwd=root,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    assert "Detected: page_marker" in result.stdout
    assert "Detected: watch_ad_button" in result.stdout
    assert "Decision: click_watch_ad_button" in result.stdout
    assert "DRY RUN click x=636 y=615" in result.stdout


def test_ad_reward_static_reward_confirm_page_cli_outputs_dry_run() -> None:
    root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "cats_automatic.main",
            "--game",
            "cats",
            "--strategy",
            "ad_reward",
            "--screen",
            str(root / "samples" / "cats" / "reward_confirm_page.png"),
            "--max-loops",
            "1",
        ],
        cwd=root,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    assert "Detected: reward_confirm_marker" in result.stdout
    assert "Detected: confirm_button" in result.stdout
    assert "Decision: confirm_reward" in result.stdout
    assert "DRY RUN click x=631 y=657" in result.stdout


def test_dry_run_backend_does_not_call_real_input_api(capsys: pytest.CaptureFixture[str]) -> None:
    backend = DryRunBackend()
    fake_real_input_api = Mock()

    backend.click(ClickAction(1225, 257, 0.966, "click_ad_entry"))

    fake_real_input_api.assert_not_called()
    assert "DRY RUN click x=1225 y=257" in capsys.readouterr().out


def test_create_window_backend_requires_title() -> None:
    with pytest.raises(CaptureBackendError, match="--window-title is required"):
        create_capture_backend("window")


def test_window_backend_reports_missing_window(tmp_path: Path) -> None:
    backend = WindowCaptureBackend("Missing", finder=lambda _: [])

    with pytest.raises(CaptureBackendError, match="No window matched title keyword"):
        backend.capture(tmp_path / "window.png")


def test_window_backend_reports_minimized_window(tmp_path: Path) -> None:
    backend = WindowCaptureBackend(
        "MuMu",
        finder=lambda _: [WindowRect("MuMu", 0, 0, 100, 100, minimized=True)],
    )

    with pytest.raises(CaptureBackendError, match="Window is minimized"):
        backend.capture(tmp_path / "window.png")


def test_window_backend_captures_window_bbox(tmp_path: Path) -> None:
    calls: list[dict[str, object]] = []

    class FakeImage:
        def save(self, path: Path) -> None:
            path.touch()

    def grabber(**kwargs: object) -> FakeImage:
        calls.append(kwargs)
        return FakeImage()

    backend = WindowCaptureBackend(
        "MuMu",
        finder=lambda _: [WindowRect("MuMu Player", 10, 20, 110, 220)],
        grabber=grabber,
    )
    frame = backend.capture(tmp_path / "window.png")

    assert calls == [{"bbox": (10, 20, 110, 220), "all_screens": True}]
    assert frame.client_origin == (10, 20)
    assert frame.size == (100, 200)


def _detection(name: str) -> DetectionResult:
    return DetectionResult(
        name=name,
        template=Path(f"{name}.png"),
        confidence=0.95,
        center=(100, 200),
        top_left=(90, 190),
        size=(20, 20),
        scale=1.0,
        threshold=0.8,
    )


def _context_with_detections(detections: dict[str, DetectionResult]) -> StrategyContext:
    return StrategyContext(
        loop_index=1,
        screen_path=Path("screen.png"),
        game=load_game("cats"),
        detections=detections,
        resolve_template=lambda value: Path(value),
    )


class StaticStrategy:
    def targets(self) -> list[TargetSpec]:
        return [TargetSpec("target", "templates/target.png", 0.5)]

    def decide(self, context: StrategyContext) -> StrategyDecision:
        assert "target" in context.detections
        return StrategyDecision.click("target", "click_target")


@dataclass
class FakeCaptureBackend:
    path: Path
    name: str = "fake"

    def capture(self, output_path: Path) -> WindowFrame:
        return WindowFrame(self.path, "fake", (0, 0), (100, 100))


class RecordingActionBackend:
    def __init__(self) -> None:
        self.action_count = 0
        self.clicks: list[ClickAction] = []
        self.taps: list[TapAction] = []
        self.waits: list[tuple[float, str]] = []

    def click(self, action: ClickAction) -> None:
        self.action_count += 1
        self.clicks.append(action)

    def tap(self, action: TapAction) -> None:
        self.action_count += 1
        self.taps.append(action)

    def wait(self, seconds: float, reason: str = "") -> None:
        self.waits.append((seconds, reason))

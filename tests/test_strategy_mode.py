from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from cats_automatic.actions import ClickAction, TapAction
from cats_automatic.backends import CaptureBackendError, create_capture_backend
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
    StrategyContext,
    StrategyDecision,
    TargetSpec,
)
from cats_automatic.strategy_runner import StrategyRunner
from cats_automatic.vision import MatchResult
from cats_automatic.window_capture import WindowFrame


def test_game_loader_loads_cats_game() -> None:
    game = load_game("cats")

    assert game.name == "cats"


def test_strategy_loader_loads_named_strategy() -> None:
    strategy = load_strategy("cats", "ad_reward")

    assert [target.name for target in strategy.targets()] == [
        "close_button",
        "reward_button",
        "ad_entry",
    ]


def test_strategy_loader_reports_unknown_strategy() -> None:
    with pytest.raises(GameLoadError, match="Unknown strategy for game 'cats': abc"):
        load_strategy("cats", "abc")


def test_ad_reward_strategy_prefers_close_button() -> None:
    strategy = AdRewardStrategy()
    context = StrategyContext(
        loop_index=1,
        screen_path=Path("screen.png"),
        game=load_game("cats"),
        detections={
            "ad_entry": _detection("ad_entry"),
            "close_button": _detection("close_button"),
        },
        resolve_template=lambda value: Path(value),
    )

    decision = strategy.decide(context)

    assert decision == StrategyDecision.click("close_button", "close_ad")


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

    def click(self, action: ClickAction) -> None:
        self.action_count += 1
        self.clicks.append(action)

    def tap(self, action: TapAction) -> None:
        self.action_count += 1
        self.taps.append(action)

    def wait(self, seconds: float, reason: str = "") -> None:
        pass

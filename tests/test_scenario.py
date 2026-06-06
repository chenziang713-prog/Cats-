from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from cats_automatic.actions import ActionExecutor
from cats_automatic.scenario import (
    JsonlAuditLogger,
    ScaleConfig,
    ScenarioConfigError,
    ScenarioRunner,
    ScenarioState,
    load_scenario,
    select_best_template,
)
from cats_automatic.vision import MatchResult
from cats_automatic.window_capture import WindowFrame, WindowsDesktopCapture


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class FakeCapture:
    def __init__(self, path: Path) -> None:
        self.path = path

    def capture(self, _: Path) -> WindowFrame:
        return WindowFrame(
            path=self.path,
            title="C.A.T.S.",
            client_origin=(100, 200),
            size=(1280, 720),
        )


def write_config(path: Path, **overrides: object) -> None:
    raw = {
        "name": "test-flow",
        "window_title_contains": "C.A.T.S.",
        "cycle_interval_seconds": 1,
        "max_cycles": 1,
        "max_runtime_seconds": 120,
        "minimum_ad_wait_seconds": 2,
        "close_poll_interval_seconds": 1,
        "close_timeout_seconds": 5,
        "ready_timeout_seconds": 5,
        "return_timeout_seconds": 5,
        "scale": {"min": 0.5, "max": 1.0, "step": 0.1},
        "states": {
            "ready": {"templates": ["templates/ready.png"], "threshold": 0.5},
            "close_ad": {"templates": ["templates/close.png"], "threshold": 0.5},
            "returned": {"templates": ["templates/returned.png"], "threshold": 0.5},
        },
    }
    raw.update(overrides)
    path.write_text(json.dumps(raw), encoding="utf-8")


def test_load_scenario_resolves_templates(tmp_path: Path) -> None:
    config_path = tmp_path / "scenario.json"
    write_config(config_path)

    config = load_scenario(config_path, tmp_path)

    assert config.window_title_contains == "C.A.T.S."
    assert config.ready.templates == (tmp_path / "templates" / "ready.png",)
    assert config.scale == ScaleConfig(minimum=0.5, maximum=1.0, step=0.1)


def test_load_scenario_reports_missing_required_field(tmp_path: Path) -> None:
    config_path = tmp_path / "scenario.json"
    write_config(config_path, states={})

    with pytest.raises(ScenarioConfigError, match="Missing scenario config field"):
        load_scenario(config_path, tmp_path)


def test_select_best_template_uses_highest_confidence(tmp_path: Path) -> None:
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    first.touch()
    second.touch()

    def matcher(_: Path, template: Path, **__: object) -> MatchResult:
        confidence = 0.4 if template == first else 0.9
        return MatchResult(confidence, (5, 6), (10, 12))

    selected = select_best_template(
        tmp_path / "screen.png",
        ScenarioState((first, second), 0.5),
        ScaleConfig(1, 1, 0.1),
        matcher,
    )

    assert selected is not None
    assert selected[0] == second
    assert selected[1].confidence == 0.9


def test_window_frame_maps_client_point_to_screen() -> None:
    frame = WindowFrame(Path("screen.png"), "title", (100, 200), (300, 400))

    assert frame.to_screen_point((20, 30)) == (120, 230)


def test_desktop_capture_uses_all_screens_and_virtual_origin(tmp_path: Path) -> None:
    calls: list[dict[str, object]] = []

    class FakeImage:
        def save(self, path: Path) -> None:
            path.touch()

    def grabber(**kwargs: object) -> FakeImage:
        calls.append(kwargs)
        return FakeImage()

    output = tmp_path / "desktop.png"
    frame = WindowsDesktopCapture(
        grabber=grabber,
        bounds_provider=lambda: (-1920, 0, 4480, 1440),
    ).capture(output)

    assert calls == [{"all_screens": True}]
    assert frame.path == output
    assert frame.client_origin == (-1920, 0)
    assert frame.size == (4480, 1440)
    assert frame.to_screen_point((2000, 300)) == (80, 300)


def test_runner_completes_single_dry_run_cycle(tmp_path: Path) -> None:
    config_path = tmp_path / "scenario.json"
    write_config(config_path)
    config = load_scenario(config_path, tmp_path)
    for state in (config.ready, config.close_ad, config.returned):
        for template in state.templates:
            template.parent.mkdir(parents=True, exist_ok=True)
            template.touch()

    def matcher(_: Path, __: Path, **___: object) -> MatchResult:
        return MatchResult(0.95, (10, 20), (30, 40))

    clock = FakeClock()
    executor = ActionExecutor(
        dry_run=True,
        max_actions=2,
        click_cooldown=0,
        stop_file=tmp_path / "stop.flag",
    )
    runner = ScenarioRunner(
        config=config,
        capture_provider=FakeCapture(tmp_path / "screen.png"),
        executor=executor,
        audit=JsonlAuditLogger(None),
        output_dir=tmp_path / "output",
        stop_file=tmp_path / "stop.flag",
        matcher=matcher,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )

    assert runner.run() == 1
    assert executor.action_count == 2
    assert clock.now >= 2


def test_runner_clicks_optional_confirm_and_second_close(tmp_path: Path) -> None:
    config_path = tmp_path / "scenario.json"
    write_config(
        config_path,
        max_close_actions=2,
        post_close_wait_seconds=1,
        states={
            "ready": {"templates": ["templates/ready.png"], "threshold": 0.5},
            "confirm": {"templates": ["templates/confirm.png"], "threshold": 0.5},
            "close_ad": {"templates": ["templates/close.png"], "threshold": 0.5},
            "returned": {"templates": ["templates/returned.png"], "threshold": 0.5},
        },
    )
    config = load_scenario(config_path, tmp_path)
    assert config.confirm is not None
    for state in (config.ready, config.confirm, config.close_ad, config.returned):
        for template in state.templates:
            template.parent.mkdir(parents=True, exist_ok=True)
            template.touch()

    returned_checks = 0

    def matcher(_: Path, template: Path, **__: object) -> MatchResult:
        nonlocal returned_checks
        confidence = 0.95
        if template.name == "returned.png":
            returned_checks += 1
            confidence = 0.1 if returned_checks == 1 else 0.95
        return MatchResult(confidence, (10, 20), (30, 40))

    clock = FakeClock()
    executor = ActionExecutor(
        dry_run=True,
        max_actions=config.max_actions_per_cycle,
        click_cooldown=0,
        stop_file=tmp_path / "stop.flag",
    )
    runner = ScenarioRunner(
        config=config,
        capture_provider=FakeCapture(tmp_path / "screen.png"),
        executor=executor,
        audit=JsonlAuditLogger(None),
        output_dir=tmp_path / "output",
        stop_file=tmp_path / "stop.flag",
        matcher=matcher,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )

    assert runner.run() == 1
    assert executor.action_count == 4
    assert config.max_actions_per_cycle == 4


def test_runner_stops_when_stop_file_exists(tmp_path: Path) -> None:
    config_path = tmp_path / "scenario.json"
    write_config(config_path)
    config = load_scenario(config_path, tmp_path)
    stop_file = tmp_path / "stop.flag"
    stop_file.touch()
    executor = ActionExecutor(dry_run=True, stop_file=stop_file)
    runner = ScenarioRunner(
        config=replace(config, max_cycles=3),
        capture_provider=FakeCapture(tmp_path / "screen.png"),
        executor=executor,
        audit=JsonlAuditLogger(None),
        output_dir=tmp_path / "output",
        stop_file=stop_file,
    )

    assert runner.run() == 0
    assert executor.action_count == 0


def test_runner_does_not_click_unknown_close_position(tmp_path: Path) -> None:
    config_path = tmp_path / "scenario.json"
    write_config(config_path)
    config = load_scenario(config_path, tmp_path)
    for state in (config.ready, config.close_ad, config.returned):
        for template in state.templates:
            template.parent.mkdir(parents=True, exist_ok=True)
            template.touch()

    def matcher(_: Path, template: Path, **__: object) -> MatchResult:
        confidence = 0.1 if template.name == "close.png" else 0.95
        return MatchResult(confidence, (10, 20), (30, 40))

    clock = FakeClock()
    executor = ActionExecutor(
        dry_run=True,
        max_actions=2,
        click_cooldown=0,
        stop_file=tmp_path / "stop.flag",
    )
    runner = ScenarioRunner(
        config=replace(config, max_runtime_seconds=10),
        capture_provider=FakeCapture(tmp_path / "screen.png"),
        executor=executor,
        audit=JsonlAuditLogger(None),
        output_dir=tmp_path / "output",
        stop_file=tmp_path / "stop.flag",
        matcher=matcher,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )

    assert runner.run() == 0
    assert executor.action_count == 1


def test_runner_stops_when_runtime_limit_is_reached(tmp_path: Path) -> None:
    config_path = tmp_path / "scenario.json"
    write_config(config_path)
    config = load_scenario(config_path, tmp_path)
    clock = FakeClock()
    executor = ActionExecutor(dry_run=True, stop_file=tmp_path / "stop.flag")
    runner = ScenarioRunner(
        config=replace(config, max_runtime_seconds=1),
        capture_provider=FakeCapture(tmp_path / "screen.png"),
        executor=executor,
        audit=JsonlAuditLogger(None),
        output_dir=tmp_path / "output",
        stop_file=tmp_path / "stop.flag",
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )

    assert runner.run() == 0
    assert clock.now >= 1
    assert executor.action_count == 0

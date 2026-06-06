from __future__ import annotations

from pathlib import Path

from cats_automatic.config_loader import Flow, load_flow
from cats_automatic.games.cats.game import definition


def test_default_flow_loads_from_config() -> None:
    flow = load_flow(Path("configs/default-flow.json"))

    assert isinstance(flow, Flow)
    assert flow.name == "default-demo-flow"
    assert flow.steps[0].template == "templates/primary_button.png"


def test_cats_game_definition_points_to_module_files() -> None:
    game = definition()

    assert game.name == "cats"
    assert game.config_path.name == "config.json"
    assert game.templates_dir.name == "templates"

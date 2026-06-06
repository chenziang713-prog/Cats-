from __future__ import annotations

import importlib
from pathlib import Path
from types import ModuleType

from .game_base import GameDefinition
from .strategy_base import StrategyProtocol


class GameLoadError(ValueError):
    pass


def load_game(game_name: str) -> GameDefinition:
    if not game_name.strip():
        raise GameLoadError("Game name must not be empty.")
    module_name = f"cats_automatic.games.{game_name}.game"
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        raise GameLoadError(f"Unknown game: {game_name}") from exc
    if not hasattr(module, "definition"):
        raise GameLoadError(f"Game module has no definition(): {module_name}")
    return module.definition()


def load_strategy(game_name: str, strategy_name: str | None) -> StrategyProtocol:
    module = _load_strategy_module(game_name, strategy_name)
    if hasattr(module, "create_strategy"):
        strategy = module.create_strategy()
    elif hasattr(module, "Strategy"):
        strategy = module.Strategy()
    else:
        raise GameLoadError(f"Strategy module has no Strategy class: {module.__name__}")
    if not hasattr(strategy, "targets") or not hasattr(strategy, "decide"):
        raise GameLoadError(f"Strategy does not implement targets() and decide(): {module.__name__}")
    return strategy


def resolve_template_path(game: GameDefinition, root: Path, template: str) -> Path:
    template_path = Path(template)
    if template_path.parts and template_path.parts[0] == "templates":
        game_template = game.templates_dir / Path(*template_path.parts[1:])
        if game_template.exists():
            return game_template
    root_template = root / template_path
    if root_template.exists():
        return root_template
    if template_path.is_absolute():
        return template_path
    return game.templates_dir / template_path.name


def _load_strategy_module(game_name: str, strategy_name: str | None) -> ModuleType:
    module_name = (
        f"cats_automatic.games.{game_name}.strategy"
        if strategy_name is None
        else f"cats_automatic.games.{game_name}.strategies.{strategy_name}"
    )
    try:
        return importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        label = "default" if strategy_name is None else strategy_name
        raise GameLoadError(f"Unknown strategy for game '{game_name}': {label}") from exc

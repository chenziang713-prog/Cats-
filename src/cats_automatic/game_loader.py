from __future__ import annotations

import importlib
from pathlib import Path
from types import ModuleType

from .game_base import GameDefinition
from .external_strategy_loader import find_external_strategy, load_external_strategy
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
    if strategy_name is not None:
        external_manifest = find_external_strategy(strategy_name, game_name)
        if external_manifest is not None:
            print(
                "Loaded external strategy override: "
                f"{external_manifest.strategy_name} from {external_manifest.package_dir}"
            )
            try:
                return load_external_strategy(external_manifest)
            except (OSError, ValueError, ImportError) as exc:
                raise GameLoadError(
                    f"External strategy load failed: {external_manifest.package_dir}: {exc}"
                ) from exc
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

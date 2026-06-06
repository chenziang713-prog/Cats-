from __future__ import annotations

from pathlib import Path

from ...game_base import GameDefinition


def definition() -> GameDefinition:
    root = Path(__file__).resolve().parent
    return GameDefinition(
        name="cats",
        config_path=root / "config.json",
        templates_dir=root / "templates",
        description="C.A.T.S. desktop visual automation prototype.",
    )

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class GameDefinition:
    name: str
    config_path: Path
    templates_dir: Path
    description: str = ""


class GameModule(Protocol):
    def definition(self) -> GameDefinition:
        """Return static metadata for a game-specific module."""

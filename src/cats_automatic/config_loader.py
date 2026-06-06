from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class FlowStep:
    name: str
    template: str
    action: str
    timeout_seconds: int


@dataclass(frozen=True)
class Flow:
    name: str
    confidence_threshold: float
    steps: list[FlowStep]

    def with_threshold(self, confidence_threshold: float) -> "Flow":
        if not 0.0 <= confidence_threshold <= 1.0:
            raise ValueError("Confidence threshold must be between 0.0 and 1.0.")
        return replace(self, confidence_threshold=confidence_threshold)


def load_flow(path: Path) -> Flow:
    with path.open("r", encoding="utf-8") as file:
        raw: dict[str, Any] = json.load(file)

    return Flow(
        name=str(raw["name"]),
        confidence_threshold=float(raw.get("confidence_threshold", 0.85)),
        steps=[
            FlowStep(
                name=str(step["name"]),
                template=str(step["template"]),
                action=str(step["action"]),
                timeout_seconds=int(step.get("timeout_seconds", 5)),
            )
            for step in raw.get("steps", [])
        ],
    )

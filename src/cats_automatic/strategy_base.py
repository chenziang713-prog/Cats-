from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from .game_base import GameDefinition


@dataclass(frozen=True)
class Region:
    x: int
    y: int
    width: int
    height: int

    @property
    def as_tuple(self) -> tuple[int, int, int, int]:
        return self.x, self.y, self.width, self.height


@dataclass(frozen=True)
class RelativeRegion:
    x: float
    y: float
    width: float
    height: float

    def resolve(self, image_size: tuple[int, int]) -> tuple[int, int, int, int]:
        image_width, image_height = image_size
        return (
            round(image_width * self.x),
            round(image_height * self.y),
            round(image_width * self.width),
            round(image_height * self.height),
        )


@dataclass(frozen=True)
class TargetSpec:
    name: str
    template: str
    threshold: float
    match_mode: str = "color"
    region: Region | RelativeRegion | None = None
    scale_min: float = 1.0
    scale_max: float = 1.0
    scale_step: float = 0.1


@dataclass(frozen=True)
class DetectionResult:
    name: str
    template: Path
    confidence: float
    center: tuple[int, int]
    top_left: tuple[int, int]
    size: tuple[int, int]
    scale: float
    threshold: float


@dataclass(frozen=True)
class StrategyDecision:
    kind: str
    target_name: str | None = None
    action_name: str = ""
    wait_seconds: float = 0.0
    reason: str = ""
    post_action_delay_seconds: float = field(default=0.0, compare=False)

    @classmethod
    def click(
        cls,
        target_name: str,
        action_name: str,
        reason: str = "",
        post_action_delay_seconds: float = 0.0,
    ) -> "StrategyDecision":
        return cls(
            kind="click",
            target_name=target_name,
            action_name=action_name,
            reason=reason,
            post_action_delay_seconds=post_action_delay_seconds,
        )

    @classmethod
    def tap(
        cls,
        target_name: str,
        action_name: str,
        reason: str = "",
        post_action_delay_seconds: float = 0.0,
    ) -> "StrategyDecision":
        return cls(
            kind="tap",
            target_name=target_name,
            action_name=action_name,
            reason=reason,
            post_action_delay_seconds=post_action_delay_seconds,
        )

    @classmethod
    def wait(cls, seconds: float = 1.0, reason: str = "") -> "StrategyDecision":
        return cls(kind="wait", wait_seconds=seconds, reason=reason)

    @classmethod
    def stop(cls, reason: str = "") -> "StrategyDecision":
        return cls(kind="stop", reason=reason)


@dataclass(frozen=True)
class StrategyContext:
    loop_index: int
    screen_path: Path
    game: GameDefinition
    detections: Mapping[str, DetectionResult]
    resolve_template: Callable[[str], Path]


class StrategyProtocol:
    def targets(self) -> Sequence[TargetSpec]:
        raise NotImplementedError

    def decide(self, context: StrategyContext) -> StrategyDecision:
        raise NotImplementedError

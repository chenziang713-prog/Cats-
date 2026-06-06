from __future__ import annotations

from typing import Protocol

from .actions import ActionExecutor, ClickAction
from .config_loader import Flow, FlowStep, load_flow


class MatchLike(Protocol):
    confidence: float
    center: tuple[int, int]


class RuleEngine:
    def __init__(self, flow: Flow, executor: ActionExecutor) -> None:
        self.flow = flow
        self.executor = executor

    def describe_next_step(self) -> None:
        if not self.flow.steps:
            print("No flow steps configured.")
            return

        step = self.flow.steps[0]
        print(
            "Next step: "
            f"{step.name} template={step.template} action={step.action} "
            f"timeout={step.timeout_seconds}s"
        )

    def click_if_confident(self, match: MatchLike, reason: str) -> bool:
        if match.confidence < self.flow.confidence_threshold:
            return False

        center_x, center_y = match.center
        self.executor.click(
            ClickAction(
                x=center_x,
                y=center_y,
                confidence=match.confidence,
                reason=reason,
            )
        )
        return True

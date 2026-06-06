from __future__ import annotations

from dataclasses import dataclass

from cats_automatic.actions import ActionExecutor, ClickAction
from cats_automatic.rules import Flow, RuleEngine


@dataclass(frozen=True)
class FakeMatch:
    confidence: float
    center: tuple[int, int]


class RecordingExecutor(ActionExecutor):
    def __init__(self) -> None:
        super().__init__(dry_run=True)
        self.actions: list[ClickAction] = []

    def click(self, action: ClickAction) -> None:
        self.actions.append(action)


def test_click_if_confident_records_center_action() -> None:
    executor = RecordingExecutor()
    flow = Flow(name="test", confidence_threshold=0.8, steps=[])
    engine = RuleEngine(flow=flow, executor=executor)

    clicked = engine.click_if_confident(
        FakeMatch(confidence=0.91, center=(120, 240)),
        reason="unit-test",
    )

    assert clicked is True
    assert executor.actions == [
        ClickAction(x=120, y=240, confidence=0.91, reason="unit-test")
    ]


def test_click_if_confident_rejects_low_confidence_match() -> None:
    executor = RecordingExecutor()
    flow = Flow(name="test", confidence_threshold=0.8, steps=[])
    engine = RuleEngine(flow=flow, executor=executor)

    clicked = engine.click_if_confident(
        FakeMatch(confidence=0.5, center=(120, 240)),
        reason="unit-test",
    )

    assert clicked is False
    assert executor.actions == []


def test_threshold_override_validates_range() -> None:
    flow = Flow(name="test", confidence_threshold=0.8, steps=[])

    assert flow.with_threshold(0.95).confidence_threshold == 0.95


def test_real_click_backend_is_not_enabled() -> None:
    executor = ActionExecutor(dry_run=False)
    executor.click(ClickAction(x=1, y=2, confidence=1.0, reason="unit-test"))

    assert executor.action_count == 0

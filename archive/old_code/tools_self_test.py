from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


@dataclass(frozen=True)
class FakeMatch:
    confidence: float
    center: tuple[int, int]


def assert_rules() -> None:
    from src.cats_automatic.actions import ActionExecutor, ClickAction
    from src.cats_automatic.rules import Flow, RuleEngine, load_flow

    class RecordingExecutor(ActionExecutor):
        def __init__(self) -> None:
            super().__init__(dry_run=True)
            self.actions: list[ClickAction] = []

        def click(self, action: ClickAction) -> None:
            self.actions.append(action)

    flow = load_flow(ROOT / "configs" / "default-flow.json").with_threshold(0.8)
    executor = RecordingExecutor()
    engine = RuleEngine(flow=flow, executor=executor)

    assert engine.click_if_confident(FakeMatch(0.9, (10, 20)), "self-test")
    assert executor.actions[0].x == 10
    assert executor.actions[0].y == 20
    assert not engine.click_if_confident(FakeMatch(0.1, (30, 40)), "too-low")
    assert len(executor.actions) == 1


def assert_entrypoint() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "run_prototype.py")],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    assert "CATS Automatic desktop prototype" in result.stdout
    assert "default-demo-flow" in result.stdout

    help_result = subprocess.run(
        [sys.executable, str(ROOT / "run_prototype.py"), "--help"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    assert "--watch" in help_result.stdout
    assert "--max-failures" in help_result.stdout
    assert "--match-mode" in help_result.stdout
    assert "--allow-click" in help_result.stdout
    assert "--max-actions" in help_result.stdout
    assert "--repeat-actions" in help_result.stdout
    assert "--live" in help_result.stdout
    assert "--scale-min" in help_result.stdout
    assert "--scenario" in help_result.stdout


def main() -> int:
    assert_rules()
    print("OK rules")
    assert_entrypoint()
    print("OK entrypoint")
    print("Self test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

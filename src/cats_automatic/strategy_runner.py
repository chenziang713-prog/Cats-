from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

from .actions import ActionBackend, ClickAction, TapAction
from .backends import CaptureBackend, CaptureBackendError
from .game_base import GameDefinition
from .game_loader import resolve_template_path
from .strategy_base import (
    DetectionResult,
    StrategyContext,
    StrategyDecision,
    StrategyProtocol,
    TargetSpec,
)
from .vision import MatchResult, match_template

Matcher = Callable[..., MatchResult]


class StrategyRunner:
    def __init__(
        self,
        *,
        game: GameDefinition,
        strategy: StrategyProtocol,
        capture_backend: CaptureBackend,
        action_backend: ActionBackend,
        root: Path,
        output_dir: Path,
        max_loops: int,
        matcher: Matcher = match_template,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if max_loops <= 0:
            raise ValueError("max_loops must be greater than 0.")
        self.game = game
        self.strategy = strategy
        self.capture_backend = capture_backend
        self.action_backend = action_backend
        self.root = root
        self.output_dir = output_dir
        self.max_loops = max_loops
        self.matcher = matcher
        self.sleep = sleep

    def run(self) -> int:
        completed = 0
        for loop_index in range(1, self.max_loops + 1):
            print(f"[loop {loop_index}]")
            screen_path = self.output_dir / f"strategy-loop-{loop_index}.png"
            try:
                frame = self.capture_backend.capture(screen_path)
            except CaptureBackendError as exc:
                print(f"Capture error: {exc}")
                break

            detections = self._detect_targets(frame.path)
            for detection in detections.values():
                print(
                    f"Detected: {detection.name}\n"
                    f"confidence={detection.confidence:.3f}\n"
                    f"center={detection.center}"
                )

            context = StrategyContext(
                loop_index=loop_index,
                screen_path=frame.path,
                game=self.game,
                detections=detections,
                resolve_template=lambda template: resolve_template_path(self.game, self.root, template),
            )
            decision = self.strategy.decide(context)
            print(f"Decision: {decision.action_name or decision.kind}")
            if self._execute_decision(decision, detections):
                completed += 1
            if decision.kind == "stop":
                break
            if decision.kind == "wait" and decision.wait_seconds > 0:
                self.sleep(decision.wait_seconds)
        return completed

    def _detect_targets(self, screen_path: Path) -> dict[str, DetectionResult]:
        detections: dict[str, DetectionResult] = {}
        for target in self.strategy.targets():
            template_path = resolve_template_path(self.game, self.root, target.template)
            if not template_path.exists():
                print(f"Template missing: {target.name} -> {template_path}")
                continue
            try:
                match = self.matcher(
                    screen_path,
                    template_path,
                    mode=target.match_mode,
                    scale_min=target.scale_min,
                    scale_max=target.scale_max,
                    scale_step=target.scale_step,
                    region=target.region.as_tuple if target.region is not None else None,
                )
            except (FileNotFoundError, RuntimeError, ValueError) as exc:
                print(f"Detection error: {target.name}: {exc}")
                continue
            if match.confidence < target.threshold:
                continue
            detections[target.name] = _to_detection_result(target, template_path, match)
        return detections

    def _execute_decision(
        self,
        decision: StrategyDecision,
        detections: dict[str, DetectionResult],
    ) -> bool:
        if decision.kind == "wait":
            self.action_backend.wait(decision.wait_seconds, decision.reason)
            return True
        if decision.kind == "stop":
            return False
        if decision.kind not in {"click", "tap"}:
            print(f"Unknown decision kind: {decision.kind}")
            return False
        if decision.target_name is None or decision.target_name not in detections:
            print(f"Decision target not detected: {decision.target_name}")
            return False
        detection = detections[decision.target_name]
        reason = decision.reason or decision.action_name or detection.name
        if decision.kind == "click":
            self.action_backend.click(
                ClickAction(
                    x=detection.center[0],
                    y=detection.center[1],
                    confidence=detection.confidence,
                    reason=reason,
                )
            )
        else:
            self.action_backend.tap(
                TapAction(
                    x=detection.center[0],
                    y=detection.center[1],
                    confidence=detection.confidence,
                    reason=reason,
                )
            )
        return True


def _to_detection_result(
    target: TargetSpec,
    template_path: Path,
    match: MatchResult,
) -> DetectionResult:
    return DetectionResult(
        name=target.name,
        template=template_path,
        confidence=match.confidence,
        center=match.center,
        top_left=match.top_left,
        size=match.size,
        scale=match.scale,
        threshold=target.threshold,
    )

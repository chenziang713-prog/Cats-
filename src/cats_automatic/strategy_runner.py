from __future__ import annotations

import shutil
import time
from collections.abc import Callable
from pathlib import Path

from .actions import ActionBackend, ActionResult, ClickAction, TapAction
from .backends import CaptureBackend, CaptureBackendError
from .game_base import GameDefinition
from .game_loader import resolve_template_path
from .run_recording import RunRecorder
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
        debug_save_capture: Path | None = None,
        run_recorder: RunRecorder | None = None,
        stop_file: Path | None = None,
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
        self.debug_save_capture = debug_save_capture
        self.run_recorder = run_recorder
        self.stop_file = stop_file
        self.matcher = matcher
        self.sleep = sleep

    def run(self) -> int:
        completed = 0
        stop_reason = "completed"
        for loop_index in range(1, self.max_loops + 1):
            if self.stop_file is not None and self.stop_file.exists():
                stop_reason = "stop_file"
                self._record_stop(loop_index, "skipped_stop_file")
                break
            print(f"[loop {loop_index}]")
            screen_path = (
                self.run_recorder.screenshot_path(loop_index)
                if self.run_recorder is not None
                else self.output_dir / f"strategy-loop-{loop_index}.png"
            )
            try:
                frame = self.capture_backend.capture(screen_path)
            except CaptureBackendError as exc:
                print(f"Capture error: {exc}")
                stop_reason = f"capture_error: {exc}"
                if self.run_recorder is not None:
                    self.run_recorder.event("capture_error", loop=loop_index, error=str(exc))
                break
            print(f"Capture image size: width={frame.size[0]}, height={frame.size[1]}")
            if self.run_recorder is not None:
                frame_path = self.run_recorder.record_loop_capture(loop_index, frame.path)
                frame = type(frame)(
                    path=frame_path,
                    title=frame.title,
                    client_origin=frame.client_origin,
                    size=frame.size,
                )
            if self.debug_save_capture is not None:
                self._save_debug_capture(frame.path, loop_index)

            detections = self._detect_targets(frame.path, frame.size)
            if self.run_recorder is not None:
                self.run_recorder.record_detections(loop_index, detections)
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
                stop_reason = decision.reason or "stop"
                break
            if decision.kind == "wait" and decision.wait_seconds > 0:
                self.sleep(decision.wait_seconds)
        if self.run_recorder is not None:
            self.run_recorder.finish(stop_reason)
        return completed

    def _detect_targets(
        self,
        screen_path: Path,
        image_size: tuple[int, int],
    ) -> dict[str, DetectionResult]:
        detections: dict[str, DetectionResult] = {}
        for target in self.strategy.targets():
            template_path = resolve_template_path(self.game, self.root, target.template)
            if not template_path.exists():
                print(f"Template missing: {target.name} -> {template_path}")
                continue
            region = resolve_target_region(target, image_size)
            if region is not None and not region_overlaps(region, image_size):
                print(
                    f"Warning: target region does not overlap capture image; "
                    f"skipping {target.name}: region={region} image_size={image_size}"
                )
                continue
            try:
                match = self.matcher(
                    screen_path,
                    template_path,
                    mode=target.match_mode,
                    scale_min=target.scale_min,
                    scale_max=target.scale_max,
                    scale_step=target.scale_step,
                    region=region,
                )
            except (FileNotFoundError, RuntimeError, ValueError) as exc:
                print(f"Detection error: {target.name}: {exc}")
                continue
            if match.confidence < target.threshold:
                continue
            detections[target.name] = _to_detection_result(target, template_path, match)
        return detections

    def _save_debug_capture(self, capture_path: Path, loop_index: int) -> None:
        assert self.debug_save_capture is not None
        output_path = self.debug_save_capture
        if self.max_loops > 1:
            output_path = with_loop_suffix(output_path, loop_index)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(capture_path, output_path)
        print(f"Debug capture saved: {output_path}")

    def _execute_decision(
        self,
        decision: StrategyDecision,
        detections: dict[str, DetectionResult],
    ) -> bool:
        if decision.kind == "wait":
            action_result = self.action_backend.wait(decision.wait_seconds, decision.reason)
            self._record_action(decision, action_result, None)
            return True
        if decision.kind == "stop":
            self._record_action(
                decision,
                ActionResult("stop", "skipped_stop_file", decision.reason),
                None,
            )
            return False
        if decision.kind not in {"click", "tap"}:
            print(f"Unknown decision kind: {decision.kind}")
            self._record_action(
                decision,
                ActionResult(decision.kind, "unknown_decision", decision.reason),
                None,
            )
            return False
        if decision.target_name is None or decision.target_name not in detections:
            print(f"Decision target not detected: {decision.target_name}")
            self._record_action(
                decision,
                ActionResult(decision.kind, "target_not_detected", decision.reason),
                None,
            )
            return False
        detection = detections[decision.target_name]
        reason = decision.reason or decision.action_name or detection.name
        action_result: ActionResult | None = None
        if decision.kind == "click":
            action_result = self.action_backend.click(
                ClickAction(
                    x=detection.center[0],
                    y=detection.center[1],
                    confidence=detection.confidence,
                    reason=reason,
                )
            )
        else:
            action_result = self.action_backend.tap(
                TapAction(
                    x=detection.center[0],
                    y=detection.center[1],
                    confidence=detection.confidence,
                    reason=reason,
                )
            )
        if action_result is None:
            action_result = ActionResult("dry_run_click", "executed", reason)
        self._record_action(decision, action_result, detection)
        return True

    def _record_action(
        self,
        decision: StrategyDecision,
        action_result: ActionResult,
        detection: DetectionResult | None,
    ) -> None:
        if self.run_recorder is None:
            return
        notes = ""
        if (
            detection is not None
            and action_result.action_type == "dry_run_click"
            and detection.confidence < self.run_recorder.min_click_confidence
        ):
            notes = (
                f"below_min_click_confidence={self.run_recorder.min_click_confidence:.3f}"
            )
        self.run_recorder.record_action(
            loop_index=self.run_recorder.total_loops,
            decision=decision,
            action_result=action_result,
            detection=detection,
            max_actions_used=self.action_backend.action_count,
            close_streak=getattr(self.strategy, "_consecutive_close_actions", None),
            notes=notes,
        )

    def _record_stop(self, loop_index: int, result: str) -> None:
        if self.run_recorder is None:
            return
        self.run_recorder.total_loops = max(self.run_recorder.total_loops, loop_index - 1)
        self.run_recorder.record_action(
            loop_index=loop_index,
            decision=StrategyDecision.stop("stop_file"),
            action_result=ActionResult("stop", result, "stop_file"),
            detection=None,
            max_actions_used=self.action_backend.action_count,
            close_streak=getattr(self.strategy, "_consecutive_close_actions", None),
        )


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


def resolve_target_region(
    target: TargetSpec,
    image_size: tuple[int, int],
) -> tuple[int, int, int, int] | None:
    if target.region is None:
        return None
    if hasattr(target.region, "resolve"):
        return target.region.resolve(image_size)  # type: ignore[union-attr]
    return target.region.as_tuple


def region_overlaps(region: tuple[int, int, int, int], image_size: tuple[int, int]) -> bool:
    image_width, image_height = image_size
    x, y, width, height = region
    if x < 0 or y < 0 or width <= 0 or height <= 0:
        return False
    right = min(image_width, x + width)
    bottom = min(image_height, y + height)
    return x < image_width and y < image_height and right > x and bottom > y


def with_loop_suffix(path: Path, loop_index: int) -> Path:
    return path.with_name(f"{path.stem}-loop-{loop_index}{path.suffix}")

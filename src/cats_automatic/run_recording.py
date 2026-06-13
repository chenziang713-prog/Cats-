from __future__ import annotations

import csv
import json
import shutil
import traceback
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, TextIO

from .actions import ActionResult
from .strategy_base import DetectionResult, StrategyDecision


CLICK_RECORD_FIELDS = [
    "run_id",
    "timestamp",
    "loop",
    "capture_backend",
    "adb_serial",
    "screenshot_path",
    "decision",
    "action_type",
    "target_name",
    "confidence",
    "threshold",
    "click_x",
    "click_y",
    "reason",
    "max_actions_used",
    "max_actions_limit",
    "close_streak",
    "result",
    "notes",
]


@dataclass(frozen=True)
class RunRecordSummary:
    run_dir: Path
    click_records_path: Path
    last_adb_tap: dict[str, str]


class RunRecorder:
    def __init__(
        self,
        *,
        output_root: Path,
        capture_backend: str,
        adb_serial: str = "",
        max_actions_limit: int | None = None,
        min_click_confidence: float = 0.80,
        run_id: str | None = None,
    ) -> None:
        self.run_id = run_id or datetime.now().strftime("%Y%m%d-%H%M%S")
        self.run_dir = _unique_run_dir(output_root, self.run_id)
        self.run_id = self.run_dir.name
        self.screenshots_dir = self.run_dir / "screenshots"
        self.debug_dir = self.run_dir / "debug"
        self.log_path = self.run_dir / "run.log"
        self.click_records_path = self.run_dir / "click_records.csv"
        self.events_path = self.run_dir / "events.jsonl"
        self.summary_path = self.run_dir / "summary.txt"
        self.capture_backend = capture_backend
        self.adb_serial = adb_serial
        self.max_actions_limit = max_actions_limit
        self.min_click_confidence = min_click_confidence
        self.start_time = _timestamp()
        self.end_time = ""
        self.total_loops = 0
        self.total_clicks = 0
        self.last_decision = ""
        self.last_screenshot = ""
        self.stop_reason = "completed"
        self.last_adb_tap: dict[str, str] = {}
        self.finished = False
        self._csv_handle: TextIO | None = None
        self._events_handle: TextIO | None = None
        self._log_handle: TextIO | None = None

        self.screenshots_dir.mkdir(parents=True, exist_ok=True)
        self.debug_dir.mkdir(parents=True, exist_ok=True)
        self._csv_handle = self.click_records_path.open("w", newline="", encoding="utf-8")
        self._csv_writer = csv.DictWriter(self._csv_handle, fieldnames=CLICK_RECORD_FIELDS)
        self._csv_writer.writeheader()
        self._csv_handle.flush()
        self._events_handle = self.events_path.open("a", encoding="utf-8")
        self._log_handle = self.log_path.open("a", encoding="utf-8")
        self.event("run_started", run_id=self.run_id, capture_backend=capture_backend)

    def screenshot_path(self, loop_index: int) -> Path:
        return self.screenshots_dir / f"loop-{loop_index:03d}.png"

    def record_loop_capture(self, loop_index: int, capture_path: Path) -> Path:
        self.total_loops = max(self.total_loops, loop_index)
        destination = self.screenshot_path(loop_index)
        if Path(capture_path) != destination:
            shutil.copyfile(capture_path, destination)
        self.last_screenshot = str(destination)
        self.event("loop_capture", loop=loop_index, screenshot_path=str(destination))
        return destination

    def record_detections(
        self,
        loop_index: int,
        detections: dict[str, DetectionResult],
    ) -> None:
        output_path = self.debug_dir / f"loop-{loop_index:03d}-detections.json"
        payload = {
            "run_id": self.run_id,
            "timestamp": _timestamp(),
            "loop": loop_index,
            "detections": [
                {
                    "target": detection.name,
                    "confidence": detection.confidence,
                    "threshold": detection.threshold,
                    "center": list(detection.center),
                    "top_left": list(detection.top_left),
                    "size": list(detection.size),
                    "scale": detection.scale,
                    "template": str(detection.template),
                }
                for detection in detections.values()
            ],
        }
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        self.event("detections", loop=loop_index, count=len(detections), path=str(output_path))

    def record_action(
        self,
        *,
        loop_index: int,
        decision: StrategyDecision,
        action_result: ActionResult,
        detection: DetectionResult | None,
        max_actions_used: int,
        close_streak: int | None = None,
        notes: str = "",
    ) -> None:
        decision_name = decision.action_name or decision.kind
        self.last_decision = decision_name
        confidence = "" if detection is None else f"{detection.confidence:.3f}"
        threshold = "" if detection is None else f"{detection.threshold:.3f}"
        click_x = "" if detection is None else str(detection.center[0])
        click_y = "" if detection is None else str(detection.center[1])
        reason = action_result.reason or decision.reason
        action_notes = "; ".join(part for part in [action_result.notes, notes] if part)
        row = {
            "run_id": self.run_id,
            "timestamp": _timestamp(),
            "loop": loop_index,
            "capture_backend": self.capture_backend,
            "adb_serial": self.adb_serial,
            "screenshot_path": self.last_screenshot,
            "decision": decision_name,
            "action_type": action_result.action_type,
            "target_name": decision.target_name or "",
            "confidence": confidence,
            "threshold": threshold,
            "click_x": click_x,
            "click_y": click_y,
            "reason": reason,
            "max_actions_used": max_actions_used,
            "max_actions_limit": "" if self.max_actions_limit is None else self.max_actions_limit,
            "close_streak": "" if close_streak is None else close_streak,
            "result": action_result.result,
            "notes": action_notes,
        }
        self._csv_writer.writerow(row)
        assert self._csv_handle is not None
        self._csv_handle.flush()
        if action_result.result == "executed" and action_result.action_type in {
            "adb_tap",
            "dry_run_click",
        }:
            self.total_clicks += 1
        if action_result.action_type == "adb_tap" and action_result.result == "executed":
            self.last_adb_tap = {key: str(value) for key, value in row.items()}
        self.event("action", **row)

    def event(self, event_type: str, **payload: Any) -> None:
        event = {"timestamp": _timestamp(), "event": event_type, **payload}
        line = json.dumps(event, ensure_ascii=False)
        if self._events_handle is not None:
            self._events_handle.write(line + "\n")
            self._events_handle.flush()
        if self._log_handle is not None:
            self._log_handle.write(f"{event['timestamp']} {event_type} {payload}\n")
            self._log_handle.flush()

    def record_exception(self, exc: BaseException) -> None:
        self.stop_reason = f"exception: {exc}"
        self.event("exception", error=str(exc), traceback=traceback.format_exc())

    def finish(self, stop_reason: str | None = None) -> RunRecordSummary:
        if self.finished:
            return RunRecordSummary(
                run_dir=self.run_dir,
                click_records_path=self.click_records_path,
                last_adb_tap=self.last_adb_tap,
            )
        if stop_reason is not None:
            self.stop_reason = stop_reason
        self.end_time = _timestamp()
        self.event("run_finished", stop_reason=self.stop_reason)
        self.write_summary()
        self.finished = True
        self.close()
        return RunRecordSummary(
            run_dir=self.run_dir,
            click_records_path=self.click_records_path,
            last_adb_tap=self.last_adb_tap,
        )

    def write_summary(self) -> None:
        last_adb_tap = self.last_adb_tap or {}
        lines = [
            f"run_id: {self.run_id}",
            f"start_time: {self.start_time}",
            f"end_time: {self.end_time or _timestamp()}",
            f"adb_serial: {self.adb_serial}",
            f"total_loops: {self.total_loops}",
            f"total_clicks: {self.total_clicks}",
            f"last_decision: {self.last_decision}",
            "last_adb_tap: "
            + (
                "none"
                if not last_adb_tap
                else (
                    f"loop={last_adb_tap.get('loop')} "
                    f"decision={last_adb_tap.get('decision')} "
                    f"x={last_adb_tap.get('click_x')} "
                    f"y={last_adb_tap.get('click_y')} "
                    f"confidence={last_adb_tap.get('confidence')} "
                    f"screenshot_path={last_adb_tap.get('screenshot_path')}"
                )
            ),
            f"last_screenshot: {self.last_screenshot}",
            f"stop_reason: {self.stop_reason}",
        ]
        self.summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def close(self) -> None:
        for handle_name in ("_csv_handle", "_events_handle", "_log_handle"):
            handle = getattr(self, handle_name)
            if handle is not None:
                handle.close()
                setattr(self, handle_name, None)


def _timestamp() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _unique_run_dir(output_root: Path, run_id: str) -> Path:
    run_dir = output_root / run_id
    if not run_dir.exists():
        return run_dir
    index = 2
    while True:
        candidate = output_root / f"{run_id}-{index}"
        if not candidate.exists():
            return candidate
        index += 1

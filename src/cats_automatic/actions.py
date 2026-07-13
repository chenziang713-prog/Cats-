from __future__ import annotations

import time
import subprocess
from dataclasses import dataclass
from pathlib import Path
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Protocol, TextIO


@dataclass(frozen=True)
class ClickAction:
    """A guarded click candidate produced by the rule engine."""

    x: int
    y: int
    confidence: float
    reason: str
    min_confidence_override: float | None = None


@dataclass(frozen=True)
class TapAction:
    x: int
    y: int
    confidence: float
    reason: str
    min_confidence_override: float | None = None


@dataclass(frozen=True)
class ActionResult:
    action_type: str
    result: str
    reason: str = ""
    notes: str = ""
    success: bool | None = None
    action: str = ""
    dry_run: bool | None = None
    message: str = ""
    clicked_pos: tuple[int, int] | None = None
    duration: float = 0.0
    error: str = ""

    def __post_init__(self) -> None:
        if self.success is None:
            object.__setattr__(
                self,
                "success",
                self.result in {"executed", "skipped_wait", "skipped_dry_run", "no_action"},
            )
        if not self.action:
            object.__setattr__(self, "action", self.action_type)
        if self.dry_run is None:
            object.__setattr__(self, "dry_run", self.action_type.startswith("dry_run"))
        if not self.message:
            object.__setattr__(self, "message", self.notes or self.result)

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": bool(self.success),
            "action": self.action,
            "dry_run": bool(self.dry_run),
            "message": self.message,
            "clicked_pos": None if self.clicked_pos is None else list(self.clicked_pos),
            "duration": self.duration,
            "error": self.error or None,
            "action_type": self.action_type,
            "result": self.result,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class ActionInput:
    name: str
    params: Mapping[str, Any] | None = None
    reason: str = ""


LOW_RISK_ACTIONS = {"wait", "press_back", "no_action"}
DEFAULT_TAP_MARKER_ALLOW_LIST = frozenset(
    {
        "close_ad",
        "close_end_1",
        "close_end_2",
        "close_end_3",
        "close_end_4",
        "close_user_2_1",
        "close_user_2_2",
        "close_user_2_3",
        "close_user_2_4",
        "close_user_2_5",
    }
)
DEFAULT_MAX_WAIT_SECONDS = 5.0
DRY_RUN_MAX_WAIT_SECONDS = 0.05


class ActionBackend(Protocol):
    action_count: int

    def click(self, action: ClickAction) -> ActionResult: ...

    def tap(self, action: TapAction) -> ActionResult: ...

    def wait(self, seconds: float, reason: str = "") -> ActionResult: ...

    def keyevent(self, keycode: str, reason: str = "") -> ActionResult: ...

    def reset_cycle(self) -> None: ...


class DryRunBackend:
    def __init__(self, log_file: Path | None = None, max_actions: int | None = None) -> None:
        self.dry_run = True
        self.action_count = 0
        self.max_actions = max_actions
        self._log_handle: TextIO | None = None
        if self.max_actions is not None and self.max_actions <= 0:
            raise ValueError("max_actions must be greater than 0.")
        if log_file is not None:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            self._log_handle = log_file.open("a", encoding="utf-8")

    def click(self, action: ClickAction) -> ActionResult:
        if self.max_actions is not None and self.action_count >= self.max_actions:
            self._emit(f"Max actions reached ({self.max_actions}), skipping dry-run click.")
            return ActionResult("dry_run_click", "skipped_max_actions_reached", action.reason)
        self.action_count += 1
        self._emit(
            "DRY RUN click "
            f"x={action.x} y={action.y} confidence={action.confidence:.3f} "
            f"reason={action.reason}"
        )
        return ActionResult("dry_run_click", "executed", action.reason)

    def tap(self, action: TapAction) -> ActionResult:
        if self.max_actions is not None and self.action_count >= self.max_actions:
            self._emit(f"Max actions reached ({self.max_actions}), skipping dry-run tap.")
            return ActionResult("dry_run_click", "skipped_max_actions_reached", action.reason)
        self.action_count += 1
        self._emit(
            "DRY RUN tap "
            f"x={action.x} y={action.y} confidence={action.confidence:.3f} "
            f"reason={action.reason}"
        )
        return ActionResult("dry_run_click", "executed", action.reason)

    def wait(self, seconds: float, reason: str = "") -> ActionResult:
        self._emit(f"DRY RUN wait seconds={seconds:.2f} reason={reason}")
        return ActionResult(
            "wait",
            "skipped_wait",
            reason,
            success=True,
            action="wait",
            dry_run=True,
            message="dry_run_skipped_wait",
            duration=0.0,
        )

    def keyevent(self, keycode: str, reason: str = "") -> ActionResult:
        if self.max_actions is not None and self.action_count >= self.max_actions:
            self._emit(f"Max actions reached ({self.max_actions}), skipping dry-run keyevent.")
            return ActionResult(
                "dry_run_keyevent",
                "skipped_max_actions_reached",
                reason,
                success=False,
                action="press_back" if keycode.upper() == "BACK" else "keyevent",
                dry_run=True,
                message="max_actions_reached",
            )
        self.action_count += 1
        self._emit(f"DRY RUN keyevent keycode={keycode} reason={reason}")
        return ActionResult(
            "dry_run_keyevent",
            "executed",
            reason,
            success=True,
            action="press_back" if keycode.upper() == "BACK" else "keyevent",
            dry_run=True,
            message="dry_run_keyevent",
        )

    def reset_cycle(self) -> None:
        self.action_count = 0

    def close(self) -> None:
        if self._log_handle is not None:
            self._log_handle.close()
            self._log_handle = None

    def _emit(self, message: str) -> None:
        print(message)
        if self._log_handle is not None:
            timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
            self._log_handle.write(f"{timestamp} {message}\n")
            self._log_handle.flush()


SubprocessRun = Callable[..., subprocess.CompletedProcess[bytes]]


class AdbActionBackend:
    def __init__(
        self,
        *,
        adb_path: Path,
        adb_serial: str,
        max_actions: int = 1,
        click_cooldown: float = 1.0,
        min_click_confidence: float = 0.80,
        stop_file: Path | None = None,
        log_file: Path | None = None,
        runner: SubprocessRun = subprocess.run,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.dry_run = False
        self.adb_path = Path(adb_path)
        self.adb_serial = adb_serial
        self.max_actions = max_actions
        self.click_cooldown = click_cooldown
        self.min_click_confidence = min_click_confidence
        self.stop_file = stop_file
        self.runner = runner
        self.sleep = sleep
        self.action_count = 0
        self.last_click_at = 0.0
        self._log_handle: TextIO | None = None

        if self.max_actions <= 0:
            raise ValueError("max_actions must be greater than 0.")
        if self.click_cooldown < 0:
            raise ValueError("click_cooldown must not be negative.")
        if not 0 <= self.min_click_confidence <= 1:
            raise ValueError("min_click_confidence must be between 0 and 1.")
        if not self.adb_path.exists():
            raise ValueError(f"ADB executable does not exist: {self.adb_path}")
        if not self.adb_path.is_file():
            raise ValueError(f"ADB path is not a file: {self.adb_path}")
        if not self.adb_serial.strip():
            raise ValueError("adb_serial must not be empty.")
        if log_file is not None:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            self._log_handle = log_file.open("a", encoding="utf-8")

    def click(self, action: ClickAction) -> ActionResult:
        if self.stop_file is not None and self.stop_file.exists():
            self._emit(f"STOP file present, skipping ADB tap: {self.stop_file}")
            return ActionResult("adb_tap", "skipped_stop_file", action.reason)
        min_confidence = (
            self.min_click_confidence
            if action.min_confidence_override is None
            else action.min_confidence_override
        )
        if action.confidence < min_confidence:
            self._emit(
                "Confidence too low for ADB tap "
                f"confidence={action.confidence:.3f} min={min_confidence:.3f}"
            )
            return ActionResult(
                "adb_tap",
                "skipped_confidence_too_low",
                "click_confidence_too_low",
                f"original_reason={action.reason}",
            )
        if self.action_count >= self.max_actions:
            self._emit(f"Max actions reached ({self.max_actions}), skipping ADB tap.")
            return ActionResult("adb_tap", "skipped_max_actions_reached", action.reason)

        now = time.monotonic()
        elapsed = now - self.last_click_at
        if self.action_count > 0 and elapsed < self.click_cooldown:
            wait_seconds = self.click_cooldown - elapsed
            self._emit(f"Waiting {wait_seconds:.2f}s for click cooldown.")
            self.sleep(wait_seconds)
            now = time.monotonic()

        command = [
            str(self.adb_path),
            "-s",
            self.adb_serial,
            "shell",
            "input",
            "tap",
            str(action.x),
            str(action.y),
        ]
        result = self._run(command)
        if result.returncode != 0:
            self._emit(f"ADB tap failed: {_decode_output(result.stderr) or result.returncode}")
            return ActionResult("adb_tap", "adb_tap_failed", action.reason)

        self.action_count += 1
        self.last_click_at = now
        self._emit(
            "ADB tap "
            f"x={action.x} y={action.y} confidence={action.confidence:.3f} "
            f"reason={action.reason}"
        )
        return ActionResult("adb_tap", "executed", action.reason)

    def tap(self, action: TapAction) -> ActionResult:
        return self.click(
            ClickAction(
                x=action.x,
                y=action.y,
                confidence=action.confidence,
                reason=action.reason,
                min_confidence_override=action.min_confidence_override,
            )
        )

    def wait(self, seconds: float, reason: str = "") -> ActionResult:
        safe_seconds = max(0.0, seconds)
        self._emit(f"ADB wait seconds={safe_seconds:.2f} reason={reason}")
        started = time.monotonic()
        self.sleep(safe_seconds)
        return ActionResult(
            "wait",
            "executed",
            reason,
            success=True,
            action="wait",
            dry_run=False,
            message="wait_finished",
            duration=time.monotonic() - started,
        )

    def keyevent(self, keycode: str, reason: str = "") -> ActionResult:
        if self.stop_file is not None and self.stop_file.exists():
            self._emit(f"STOP file present, skipping ADB keyevent: {self.stop_file}")
            return ActionResult("adb_keyevent", "skipped_stop_file", reason)
        if self.action_count >= self.max_actions:
            self._emit(f"Max actions reached ({self.max_actions}), skipping ADB keyevent.")
            return ActionResult("adb_keyevent", "skipped_max_actions_reached", reason)

        now = time.monotonic()
        elapsed = now - self.last_click_at
        if self.action_count > 0 and elapsed < self.click_cooldown:
            wait_seconds = self.click_cooldown - elapsed
            self._emit(f"Waiting {wait_seconds:.2f}s for action cooldown.")
            self.sleep(wait_seconds)
            now = time.monotonic()

        command = [
            str(self.adb_path),
            "-s",
            self.adb_serial,
            "shell",
            "input",
            "keyevent",
            keycode,
        ]
        result = self._run(command)
        if result.returncode != 0:
            self._emit(f"ADB keyevent failed: {_decode_output(result.stderr) or result.returncode}")
            return ActionResult("adb_keyevent", "adb_keyevent_failed", reason)

        self.action_count += 1
        self.last_click_at = now
        self._emit(f"ADB keyevent keycode={keycode} reason={reason}")
        return ActionResult("adb_keyevent", "executed", reason)

    def reset_cycle(self) -> None:
        self.action_count = 0
        self.last_click_at = 0.0

    def close(self) -> None:
        if self._log_handle is not None:
            self._log_handle.close()
            self._log_handle = None

    def _run(self, command: Sequence[str]) -> subprocess.CompletedProcess[bytes]:
        try:
            return self.runner(command, capture_output=True)
        except OSError as exc:
            self._emit(f"Failed to run ADB tap command: {exc}")
            return subprocess.CompletedProcess(command, 1, stdout=b"", stderr=str(exc).encode())

    def _emit(self, message: str) -> None:
        print(message)
        if self._log_handle is not None:
            timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
            self._log_handle.write(f"{timestamp} {message}\n")
            self._log_handle.flush()


class ActionExecutor:
    """Action execution boundary.

    The prototype defaults to dry-run mode so recognition can be tested without
    sending real mouse input. A platform-specific implementation can replace this
    class later.
    """

    def __init__(
        self,
        dry_run: bool = True,
        *,
        max_actions: int = 1,
        repeat_actions: int = 1,
        click_cooldown: float = 1.0,
        stop_file: Path | None = None,
        log_file: Path | None = None,
    ) -> None:
        self.dry_run = dry_run
        self.max_actions = max_actions
        self.repeat_actions = repeat_actions
        self.click_cooldown = click_cooldown
        self.stop_file = stop_file
        self.action_count = 0
        self.last_click_at = 0.0
        self._log_handle: TextIO | None = None

        if self.max_actions <= 0:
            raise ValueError("max_actions must be greater than 0.")
        if self.repeat_actions <= 0:
            raise ValueError("repeat_actions must be greater than 0.")
        if self.click_cooldown < 0:
            raise ValueError("click_cooldown must not be negative.")
        if log_file is not None:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            self._log_handle = log_file.open("a", encoding="utf-8")

    def click(self, action: ClickAction) -> None:
        for index in range(self.repeat_actions):
            if not self._click_once(action, index + 1):
                return

    def _click_once(self, action: ClickAction, repeat_index: int) -> bool:
        if self.stop_file is not None and self.stop_file.exists():
            self._emit(f"STOP file present, skipping click: {self.stop_file}")
            return False
        if self.action_count >= self.max_actions:
            self._emit(f"Max actions reached ({self.max_actions}), skipping click.")
            return False

        now = time.monotonic()
        elapsed = now - self.last_click_at
        if self.action_count > 0 and elapsed < self.click_cooldown:
            wait_seconds = self.click_cooldown - elapsed
            self._emit(f"Waiting {wait_seconds:.2f}s for click cooldown.")
            time.sleep(wait_seconds)
            now = time.monotonic()

        if self.dry_run:
            self._emit(
                "DRY RUN click "
                f"({action.x}, {action.y}) confidence={action.confidence:.3f} "
                f"repeat={repeat_index}/{self.repeat_actions} "
                f"reason={action.reason}"
            )
            self.action_count += 1
            self.last_click_at = now
            return True

        self._emit(
            "REAL click requested but no input backend is enabled; "
            "staying in dry-run-only mode."
        )
        return False

    def close(self) -> None:
        if self._log_handle is not None:
            self._log_handle.close()
            self._log_handle = None

    def _emit(self, message: str) -> None:
        print(message)
        if self._log_handle is not None:
            timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
            self._log_handle.write(f"{timestamp} {message}\n")
            self._log_handle.flush()


def _decode_output(value: bytes | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return value.decode("utf-8", errors="replace").strip()


def normalize_action_input(action: str | Mapping[str, Any] | ActionInput) -> ActionInput:
    if isinstance(action, ActionInput):
        return action
    if isinstance(action, str):
        return ActionInput(name=action, params={}, reason="")
    name = str(action.get("name", "")).strip()
    params = action.get("params", {})
    if not isinstance(params, Mapping):
        params = {}
    reason = str(action.get("reason", ""))
    return ActionInput(name=name, params=params, reason=reason)


def execute_action(
    action: str | Mapping[str, Any] | ActionInput,
    backend: ActionBackend,
    *,
    state_result: Mapping[str, Any] | None = None,
    allowed_markers: set[str] | frozenset[str] | None = None,
    dry_run: bool | None = None,
    max_wait_seconds: float = DEFAULT_MAX_WAIT_SECONDS,
    dry_run_max_wait_seconds: float = DRY_RUN_MAX_WAIT_SECONDS,
) -> ActionResult:
    """Execute the small named-action surface shared by strategy tests.

    Only low-risk actions are wired here. Marker/point taps remain in the
    existing guarded click path until the real flow is ready.
    """

    action_input = normalize_action_input(action)
    name = action_input.name
    params = action_input.params or {}
    reason = action_input.reason
    is_dry_run = bool(getattr(backend, "dry_run", False)) if dry_run is None else dry_run

    if name == "wait":
        requested_seconds = _float_param(params, "seconds", 0.0)
        cap = dry_run_max_wait_seconds if is_dry_run else max_wait_seconds
        seconds = max(0.0, min(requested_seconds, cap))
        started = time.monotonic()
        result = backend.wait(seconds, reason)
        duration = time.monotonic() - started
        if result is None:
            return ActionResult(
                "wait",
                "skipped_wait" if is_dry_run else "executed",
                reason,
                success=True,
                action="wait",
                dry_run=is_dry_run,
                message="dry_run_skipped_wait" if is_dry_run else "wait_finished",
                duration=duration,
            )
        return _complete_result(
            result,
            action="wait",
            dry_run=is_dry_run,
            duration=result.duration or duration,
            message=result.message or ("dry_run_skipped_wait" if is_dry_run else "wait_finished"),
        )

    if name == "press_back":
        if is_dry_run:
            return ActionResult(
                "press_back",
                "skipped_dry_run",
                reason,
                success=True,
                action="press_back",
                dry_run=True,
                message="dry_run_skipped_press_back",
                duration=0.0,
            )
        started = time.monotonic()
        result = backend.keyevent("BACK", reason)
        duration = time.monotonic() - started
        if result is None:
            return ActionResult(
                "adb_keyevent",
                "executed",
                reason,
                success=True,
                action="press_back",
                dry_run=False,
                message="adb_back_sent",
                duration=duration,
            )
        return _complete_result(
            result,
            action="press_back",
            dry_run=False,
            duration=result.duration or duration,
            message=result.message or "adb_back_sent",
        )

    if name == "no_action":
        return ActionResult(
            "no_action",
            "no_action",
            reason,
            success=True,
            action="no_action",
            dry_run=is_dry_run,
            message="no_action",
            duration=0.0,
        )

    if name == "tap_marker":
        return _execute_tap_marker(
            params=params,
            reason=reason,
            backend=backend,
            state_result=state_result,
            allowed_markers=DEFAULT_TAP_MARKER_ALLOW_LIST if allowed_markers is None else allowed_markers,
            dry_run=is_dry_run,
        )

    return ActionResult(
        name or "unknown",
        "unknown_action",
        reason,
        success=False,
        action=name or "unknown",
        dry_run=is_dry_run,
        message=f"unsupported_action: {name or 'unknown'}",
        error="unknown_action",
    )


def _float_param(params: Mapping[str, Any], name: str, default: float) -> float:
    try:
        return float(params.get(name, default))
    except (TypeError, ValueError):
        return default


def _execute_tap_marker(
    *,
    params: Mapping[str, Any],
    reason: str,
    backend: ActionBackend,
    state_result: Mapping[str, Any] | None,
    allowed_markers: set[str] | frozenset[str],
    dry_run: bool,
) -> ActionResult:
    marker = str(params.get("marker", "")).strip()
    min_confidence = _float_param(params, "min_confidence", 0.8)
    fallback_to_best_marker = bool(params.get("fallback_to_best_marker", False))
    offset_x = round(_float_param(params, "offset_x", 0.0))
    offset_y = round(_float_param(params, "offset_y", 0.0))

    if not marker:
        return _tap_marker_error("marker_not_found", reason, dry_run, "marker parameter is required")
    if marker not in allowed_markers:
        return _tap_marker_error("marker_not_allowed", reason, dry_run, f"marker not allowed: {marker}")

    detections = _state_detections(state_result)
    detection = detections.get(marker)
    selected_marker = marker
    if detection is None and fallback_to_best_marker:
        best_marker = _state_best_marker(state_result)
        if best_marker is None or best_marker not in allowed_markers:
            return _tap_marker_error(
                "marker_not_allowed",
                reason,
                dry_run,
                "best_marker is missing or not allowed",
            )
        detection = detections.get(best_marker)
        selected_marker = best_marker
    if detection is None:
        return _tap_marker_error("marker_not_found", reason, dry_run, f"marker not found: {marker}")

    confidence = _detection_confidence(detection)
    if confidence is None or confidence < min_confidence:
        return _tap_marker_error(
            "confidence_too_low",
            reason,
            dry_run,
            f"confidence {confidence} below {min_confidence:.3f}",
        )

    center = _detection_center(detection)
    if center is None:
        return _tap_marker_error("marker_has_no_coordinates", reason, dry_run, "marker has no center or bbox")
    x = center[0] + offset_x
    y = center[1] + offset_y
    image_size = _state_image_size(state_result)
    if image_size is not None and not _point_in_bounds((x, y), image_size):
        return _tap_marker_error(
            "coordinates_out_of_bounds",
            reason,
            dry_run,
            f"tap coordinate out of bounds: ({x}, {y}) image_size={image_size}",
            clicked_pos=(x, y),
        )

    if dry_run:
        return ActionResult(
            "tap_marker",
            "skipped_dry_run",
            reason,
            success=True,
            action="tap_marker",
            dry_run=True,
            message=f"dry_run_skipped_adb_tap marker={selected_marker}",
            clicked_pos=(x, y),
            duration=0.0,
        )

    if getattr(backend, "dry_run", False) or not hasattr(backend, "tap"):
        return _tap_marker_error(
            "adb_backend_unavailable",
            reason,
            dry_run=False,
            message="real ADB tap backend is unavailable",
            clicked_pos=(x, y),
        )

    started = time.monotonic()
    result = backend.tap(
        TapAction(
            x=x,
            y=y,
            confidence=confidence,
            reason=reason or selected_marker,
            min_confidence_override=min_confidence,
        )
    )
    duration = time.monotonic() - started
    if result is None:
        return _tap_marker_error(
            "adb_backend_unavailable",
            reason,
            dry_run=False,
            message="ADB tap backend returned no result",
            clicked_pos=(x, y),
            duration=duration,
        )
    if result.result != "executed":
        return ActionResult(
            result.action_type,
            result.result,
            result.reason or reason,
            result.notes,
            success=False,
            action="tap_marker",
            dry_run=False,
            message=result.message or result.result,
            clicked_pos=(x, y),
            duration=result.duration or duration,
            error="adb_tap_failed",
        )
    return ActionResult(
        result.action_type,
        result.result,
        result.reason or reason,
        result.notes,
        success=True,
        action="tap_marker",
        dry_run=False,
        message=result.message or f"adb_tap_executed marker={selected_marker}",
        clicked_pos=(x, y),
        duration=result.duration or duration,
        error="",
    )


def _tap_marker_error(
    error: str,
    reason: str,
    dry_run: bool,
    message: str,
    *,
    clicked_pos: tuple[int, int] | None = None,
    duration: float = 0.0,
) -> ActionResult:
    return ActionResult(
        "tap_marker",
        error,
        reason,
        success=False,
        action="tap_marker",
        dry_run=dry_run,
        message=message,
        clicked_pos=clicked_pos,
        duration=duration,
        error=error,
    )


def _state_detections(state_result: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if state_result is None:
        return {}
    detections = state_result.get("detections", {})
    if isinstance(detections, Mapping):
        return detections
    return {}


def _state_best_marker(state_result: Mapping[str, Any] | None) -> str | None:
    if state_result is None:
        return None
    value = state_result.get("best_marker")
    if value is None:
        return None
    return str(value)


def _state_image_size(state_result: Mapping[str, Any] | None) -> tuple[int, int] | None:
    if state_result is None:
        return None
    raw = state_result.get("image_size") or state_result.get("screenshot_size")
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)) or len(raw) != 2:
        return None
    try:
        width = int(raw[0])
        height = int(raw[1])
    except (TypeError, ValueError):
        return None
    if width <= 0 or height <= 0:
        return None
    return width, height


def _detection_confidence(detection: Any) -> float | None:
    raw = _detection_value(detection, "confidence")
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _detection_center(detection: Any) -> tuple[int, int] | None:
    raw_center = _detection_value(detection, "center")
    center = _pair_to_ints(raw_center)
    if center is not None:
        return center
    top_left = _pair_to_ints(_detection_value(detection, "top_left"))
    size = _pair_to_ints(_detection_value(detection, "size"))
    if top_left is not None and size is not None and size[0] > 0 and size[1] > 0:
        return top_left[0] + size[0] // 2, top_left[1] + size[1] // 2
    bbox = _detection_value(detection, "bbox")
    if isinstance(bbox, Sequence) and not isinstance(bbox, (str, bytes)) and len(bbox) == 4:
        try:
            x, y, width, height = (int(value) for value in bbox)
        except (TypeError, ValueError):
            return None
        if width > 0 and height > 0:
            return x + width // 2, y + height // 2
    return None


def _detection_value(detection: Any, name: str) -> Any:
    if isinstance(detection, Mapping):
        return detection.get(name)
    return getattr(detection, name, None)


def _pair_to_ints(value: Any) -> tuple[int, int] | None:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or len(value) != 2:
        return None
    try:
        return int(value[0]), int(value[1])
    except (TypeError, ValueError):
        return None


def _point_in_bounds(point: tuple[int, int], image_size: tuple[int, int]) -> bool:
    x, y = point
    width, height = image_size
    return 0 <= x < width and 0 <= y < height


def _complete_result(
    result: ActionResult,
    *,
    action: str,
    dry_run: bool,
    duration: float,
    message: str,
) -> ActionResult:
    if (
        result.action == action
        and result.dry_run is dry_run
        and result.duration == duration
        and result.message == message
    ):
        return result
    return ActionResult(
        result.action_type,
        result.result,
        result.reason,
        result.notes,
        success=result.success,
        action=action,
        dry_run=dry_run,
        message=message,
        clicked_pos=result.clicked_pos,
        duration=duration,
        error=result.error,
    )

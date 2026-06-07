from __future__ import annotations

import time
import subprocess
from dataclasses import dataclass
from pathlib import Path
from collections.abc import Callable, Sequence
from typing import Protocol, TextIO


@dataclass(frozen=True)
class ClickAction:
    """A guarded click candidate produced by the rule engine."""

    x: int
    y: int
    confidence: float
    reason: str


@dataclass(frozen=True)
class TapAction:
    x: int
    y: int
    confidence: float
    reason: str


class ActionBackend(Protocol):
    action_count: int

    def click(self, action: ClickAction) -> None: ...

    def tap(self, action: TapAction) -> None: ...

    def wait(self, seconds: float, reason: str = "") -> None: ...


class DryRunBackend:
    def __init__(self, log_file: Path | None = None) -> None:
        self.action_count = 0
        self._log_handle: TextIO | None = None
        if log_file is not None:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            self._log_handle = log_file.open("a", encoding="utf-8")

    def click(self, action: ClickAction) -> None:
        self.action_count += 1
        self._emit(
            "DRY RUN click "
            f"x={action.x} y={action.y} confidence={action.confidence:.3f} "
            f"reason={action.reason}"
        )

    def tap(self, action: TapAction) -> None:
        self.action_count += 1
        self._emit(
            "DRY RUN tap "
            f"x={action.x} y={action.y} confidence={action.confidence:.3f} "
            f"reason={action.reason}"
        )

    def wait(self, seconds: float, reason: str = "") -> None:
        self._emit(f"DRY RUN wait seconds={seconds:.2f} reason={reason}")

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
        stop_file: Path | None = None,
        log_file: Path | None = None,
        runner: SubprocessRun = subprocess.run,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.adb_path = Path(adb_path)
        self.adb_serial = adb_serial
        self.max_actions = max_actions
        self.click_cooldown = click_cooldown
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
        if not self.adb_path.exists():
            raise ValueError(f"ADB executable does not exist: {self.adb_path}")
        if not self.adb_path.is_file():
            raise ValueError(f"ADB path is not a file: {self.adb_path}")
        if not self.adb_serial.strip():
            raise ValueError("adb_serial must not be empty.")
        if log_file is not None:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            self._log_handle = log_file.open("a", encoding="utf-8")

    def click(self, action: ClickAction) -> None:
        if self.stop_file is not None and self.stop_file.exists():
            self._emit(f"STOP file present, skipping ADB tap: {self.stop_file}")
            return
        if self.action_count >= self.max_actions:
            self._emit(f"Max actions reached ({self.max_actions}), skipping ADB tap.")
            return

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
            return

        self.action_count += 1
        self.last_click_at = now
        self._emit(
            "ADB tap "
            f"x={action.x} y={action.y} confidence={action.confidence:.3f} "
            f"reason={action.reason}"
        )

    def tap(self, action: TapAction) -> None:
        self.click(
            ClickAction(
                x=action.x,
                y=action.y,
                confidence=action.confidence,
                reason=action.reason,
            )
        )

    def wait(self, seconds: float, reason: str = "") -> None:
        self._emit(f"ADB wait seconds={seconds:.2f} reason={reason}")

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

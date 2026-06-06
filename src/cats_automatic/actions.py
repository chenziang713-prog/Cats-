from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
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

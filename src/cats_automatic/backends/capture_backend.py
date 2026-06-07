from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from ..window_capture import WindowFrame


class CaptureBackendError(RuntimeError):
    pass


class CaptureBackend(Protocol):
    name: str

    def capture(self, output_path: Path) -> WindowFrame:
        raise NotImplementedError


def create_capture_backend(
    kind: str,
    *,
    window_title: str | None = None,
    window_hwnd: int | None = None,
    adb_path: Path | None = None,
    adb_serial: str | None = None,
    replay_screens: Sequence[Path] | None = None,
) -> CaptureBackend:
    if kind == "fullscreen":
        from .fullscreen_capture import FullScreenCaptureBackend

        return FullScreenCaptureBackend()
    if kind == "window":
        if window_hwnd is None and (window_title is None or not window_title.strip()):
            raise CaptureBackendError("--window-title or --window-hwnd is required when --capture-backend window is used.")
        from .window_capture import WindowCaptureBackend

        return WindowCaptureBackend(window_title, window_hwnd=window_hwnd)
    if kind == "replay":
        from .replay_capture import ReplayCaptureBackend

        return ReplayCaptureBackend(replay_screens or [])
    if kind == "adb":
        if adb_path is None:
            raise CaptureBackendError("--adb-path is required when --capture-backend adb is used.")
        if adb_serial is None or not adb_serial.strip():
            raise CaptureBackendError("--adb-serial is required when --capture-backend adb is used.")
        from .adb_capture import AdbCaptureBackend

        return AdbCaptureBackend(adb_path, adb_serial)
    raise CaptureBackendError(f"Unsupported capture backend: {kind}")

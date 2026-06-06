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
    replay_screens: Sequence[Path] | None = None,
) -> CaptureBackend:
    if kind == "fullscreen":
        from .fullscreen_capture import FullScreenCaptureBackend

        return FullScreenCaptureBackend()
    if kind == "window":
        if window_title is None or not window_title.strip():
            raise CaptureBackendError("--window-title is required when --capture-backend window is used.")
        from .window_capture import WindowCaptureBackend

        return WindowCaptureBackend(window_title)
    if kind == "replay":
        from .replay_capture import ReplayCaptureBackend

        return ReplayCaptureBackend(replay_screens or [])
    raise CaptureBackendError(f"Unsupported capture backend: {kind}")

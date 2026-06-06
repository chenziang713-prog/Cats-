from __future__ import annotations

from pathlib import Path

from ..window_capture import WindowFrame, WindowsDesktopCapture


class FullScreenCaptureBackend:
    name = "fullscreen"

    def __init__(self, capture: WindowsDesktopCapture | None = None) -> None:
        self.capture_impl = capture or WindowsDesktopCapture()

    def capture(self, output_path: Path) -> WindowFrame:
        return self.capture_impl.capture(output_path)

from __future__ import annotations

from pathlib import Path

from PIL import Image

from ..window_capture import WindowFrame
from .capture_backend import CaptureBackendError


class StaticImageCaptureBackend:
    name = "static"

    def __init__(self, screen_path: Path) -> None:
        self.screen_path = Path(screen_path)

    def capture(self, output_path: Path) -> WindowFrame:
        if not self.screen_path.exists():
            raise CaptureBackendError(f"Screen image does not exist: {self.screen_path}")
        if not self.screen_path.is_file():
            raise CaptureBackendError(f"Screen image is not a file: {self.screen_path}")
        try:
            with Image.open(self.screen_path) as image:
                size = image.size
        except OSError as exc:
            raise CaptureBackendError(
                f"Screen image could not be opened: {self.screen_path}"
            ) from exc

        return WindowFrame(
            path=self.screen_path,
            title="static screen",
            client_origin=(0, 0),
            size=size,
        )

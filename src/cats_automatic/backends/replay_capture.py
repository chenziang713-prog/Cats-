from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from PIL import Image

from ..window_capture import WindowFrame
from .capture_backend import CaptureBackendError


class ReplayCaptureBackend:
    name = "replay"

    def __init__(self, screen_paths: Sequence[Path]) -> None:
        if not screen_paths:
            raise CaptureBackendError("--replay-screens is required when --capture-backend replay is used.")
        self.screen_paths = [Path(path) for path in screen_paths]
        self._next_index = 0
        for screen_path in self.screen_paths:
            _validate_image(screen_path)

    def capture(self, output_path: Path) -> WindowFrame:
        if self._next_index < len(self.screen_paths):
            screen_path = self.screen_paths[self._next_index]
            self._next_index += 1
        else:
            screen_path = self.screen_paths[-1]
            print(f"Replay screens exhausted; reusing last screen: {screen_path}")

        size = _image_size(screen_path)
        return WindowFrame(
            path=screen_path,
            title=f"replay screen {min(self._next_index, len(self.screen_paths))}/{len(self.screen_paths)}",
            client_origin=(0, 0),
            size=size,
        )


def _validate_image(screen_path: Path) -> None:
    if not screen_path.exists():
        raise CaptureBackendError(f"Replay screen image does not exist: {screen_path}")
    if not screen_path.is_file():
        raise CaptureBackendError(f"Replay screen image is not a file: {screen_path}")
    _image_size(screen_path)


def _image_size(screen_path: Path) -> tuple[int, int]:
    try:
        with Image.open(screen_path) as image:
            return image.size
    except OSError as exc:
        raise CaptureBackendError(f"Replay screen image could not be opened: {screen_path}") from exc

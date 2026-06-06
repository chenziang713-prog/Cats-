from __future__ import annotations

import ctypes
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import ImageGrab

from ..window_capture import WindowFrame
from .capture_backend import CaptureBackendError


@dataclass(frozen=True)
class WindowRect:
    title: str
    left: int
    top: int
    right: int
    bottom: int
    minimized: bool = False

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top


class WindowCaptureBackend:
    name = "window"

    def __init__(
        self,
        title_contains: str,
        *,
        finder: Callable[[str], list[WindowRect]] | None = None,
        grabber: Callable[..., Any] = ImageGrab.grab,
    ) -> None:
        if not title_contains.strip():
            raise CaptureBackendError("--window-title must not be empty.")
        self.title_contains = title_contains
        self.finder = finder or _find_windows_by_title
        self.grabber = grabber

    def capture(self, output_path: Path) -> WindowFrame:
        matches = self.finder(self.title_contains)
        if not matches:
            raise CaptureBackendError(f"No window matched title keyword: {self.title_contains}")
        usable = [match for match in matches if not match.minimized]
        if not usable:
            raise CaptureBackendError(f"Window is minimized: {self.title_contains}")
        window = max(usable, key=lambda item: item.width * item.height)
        if window.width <= 0 or window.height <= 0:
            raise CaptureBackendError(f"Matched window has invalid size: {window.title}")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        image = self.grabber(
            bbox=(window.left, window.top, window.right, window.bottom),
            all_screens=True,
        )
        image.save(output_path)
        return WindowFrame(
            path=output_path,
            title=window.title,
            client_origin=(window.left, window.top),
            size=(window.width, window.height),
        )


def _find_windows_by_title(title_contains: str) -> list[WindowRect]:
    user32 = ctypes.windll.user32
    target = title_contains.casefold()
    matches: list[WindowRect] = []
    enum_proc_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    @enum_proc_type
    def callback(handle: int, _: Any) -> bool:
        if not user32.IsWindowVisible(handle):
            return True
        length = user32.GetWindowTextLengthW(handle)
        if length <= 0:
            return True
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(handle, buffer, length + 1)
        title = buffer.value
        if target not in title.casefold():
            return True
        rect = RECT()
        if not user32.GetWindowRect(handle, ctypes.byref(rect)):
            return True
        matches.append(
            WindowRect(
                title=title,
                left=int(rect.left),
                top=int(rect.top),
                right=int(rect.right),
                bottom=int(rect.bottom),
                minimized=bool(user32.IsIconic(handle)),
            )
        )
        return True

    user32.EnumWindows(callback, 0)
    return matches


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]

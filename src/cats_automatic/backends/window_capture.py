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
    hwnd: int = 0
    client_left: int | None = None
    client_top: int | None = None
    client_right: int | None = None
    client_bottom: int | None = None
    visible: bool = True

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top

    @property
    def rect(self) -> tuple[int, int, int, int]:
        return self.left, self.top, self.right, self.bottom

    @property
    def client_rect(self) -> tuple[int, int, int, int] | None:
        if (
            self.client_left is None
            or self.client_top is None
            or self.client_right is None
            or self.client_bottom is None
        ):
            return None
        return self.client_left, self.client_top, self.client_right, self.client_bottom


class WindowCaptureBackend:
    name = "window"

    def __init__(
        self,
        title_contains: str | None = None,
        *,
        finder: Callable[[str], list[WindowRect]] | None = None,
        hwnd_finder: Callable[[int], WindowRect | None] | None = None,
        window_hwnd: int | None = None,
        grabber: Callable[..., Any] = ImageGrab.grab,
    ) -> None:
        if window_hwnd is None and (title_contains is None or not title_contains.strip()):
            raise CaptureBackendError(
                "--window-title or --window-hwnd is required when --capture-backend window is used."
            )
        if window_hwnd is not None and window_hwnd <= 0:
            raise CaptureBackendError("--window-hwnd must be a positive integer.")
        self.title_contains = title_contains
        self.window_hwnd = window_hwnd
        self.finder = finder or _find_windows_by_title
        self.hwnd_finder = hwnd_finder or _find_window_by_hwnd
        self.grabber = grabber

    def capture(self, output_path: Path) -> WindowFrame:
        window = self._select_window()
        if window.width <= 0 or window.height <= 0:
            raise CaptureBackendError(f"Matched window has invalid size: {window.title}")

        print(
            "Window capture selected: "
            f"hwnd={window.hwnd} title={window.title!r} rect={window.rect} "
            f"client_rect={window.client_rect}"
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        image = self.grabber(
            bbox=(window.left, window.top, window.right, window.bottom),
            all_screens=True,
        )
        image.save(output_path)
        print(f"Window capture image size: width={image.size[0]}, height={image.size[1]}")
        return WindowFrame(
            path=output_path,
            title=window.title,
            client_origin=(window.left, window.top),
            size=(window.width, window.height),
        )

    def _select_window(self) -> WindowRect:
        if self.window_hwnd is not None:
            window = self.hwnd_finder(self.window_hwnd)
            if window is None:
                raise CaptureBackendError(f"No window found for hwnd: {self.window_hwnd}")
            if not window.visible:
                raise CaptureBackendError(f"Window is not visible: hwnd={self.window_hwnd}")
            if window.minimized:
                raise CaptureBackendError(f"Window is minimized: hwnd={self.window_hwnd}")
            print("Window capture selection mode: exact hwnd")
            return window

        assert self.title_contains is not None
        matches = self.finder(self.title_contains)
        print(
            "Window capture selection mode: fuzzy title contains "
            f"{self.title_contains!r}; matches={len(matches)}"
        )
        for index, match in enumerate(matches):
            print(
                "Window candidate "
                f"{index}: hwnd={match.hwnd} title={match.title!r} rect={match.rect} "
                f"client_rect={match.client_rect} visible={match.visible} minimized={match.minimized}"
            )
        if not matches:
            raise CaptureBackendError(f"No window matched title keyword: {self.title_contains}")
        usable = [match for match in matches if match.visible and not match.minimized]
        if not usable:
            raise CaptureBackendError(f"Window is minimized or not visible: {self.title_contains}")
        window = max(usable, key=lambda item: item.width * item.height)
        if len(usable) > 1:
            print(
                "Multiple usable windows matched; selected largest area. "
                "Use --window-hwnd for an exact selection."
            )
        return window


def _find_windows_by_title(title_contains: str) -> list[WindowRect]:
    target = title_contains.casefold()
    return [
        window
        for window in list_windows()
        if window.title and target in window.title.casefold()
    ]


def _find_window_by_hwnd(hwnd: int) -> WindowRect | None:
    user32 = ctypes.windll.user32
    if not user32.IsWindow(hwnd):
        return None
    return _window_from_handle(hwnd)


def list_windows() -> list[WindowRect]:
    user32 = ctypes.windll.user32
    windows: list[WindowRect] = []
    enum_proc_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    @enum_proc_type
    def callback(handle: int, _: Any) -> bool:
        window = _window_from_handle(int(handle))
        if window is not None:
            windows.append(window)
        return True

    user32.EnumWindows(callback, 0)
    return windows


def format_window_list(windows: list[WindowRect]) -> str:
    lines = [
        "hwnd | visible | minimized | width x height | window rect | client rect | title"
    ]
    for window in windows:
        lines.append(
            f"{window.hwnd} | {window.visible} | {window.minimized} | "
            f"{window.width}x{window.height} | {window.rect} | {window.client_rect} | "
            f"{window.title!r}"
        )
    return "\n".join(lines)


def _window_from_handle(handle: int) -> WindowRect | None:
    user32 = ctypes.windll.user32
    rect = RECT()
    if not user32.GetWindowRect(handle, ctypes.byref(rect)):
        return None

    length = user32.GetWindowTextLengthW(handle)
    title_buffer = ctypes.create_unicode_buffer(length + 1)
    if length > 0:
        user32.GetWindowTextW(handle, title_buffer, length + 1)

    client_rect = RECT()
    client_origin = POINT(0, 0)
    has_client = bool(user32.GetClientRect(handle, ctypes.byref(client_rect))) and bool(
        user32.ClientToScreen(handle, ctypes.byref(client_origin))
    )
    client_left: int | None = None
    client_top: int | None = None
    client_right: int | None = None
    client_bottom: int | None = None
    if has_client:
        client_left = int(client_origin.x)
        client_top = int(client_origin.y)
        client_right = client_left + int(client_rect.right - client_rect.left)
        client_bottom = client_top + int(client_rect.bottom - client_rect.top)

    return WindowRect(
        hwnd=int(handle),
        title=title_buffer.value,
        left=int(rect.left),
        top=int(rect.top),
        right=int(rect.right),
        bottom=int(rect.bottom),
        client_left=client_left,
        client_top=client_top,
        client_right=client_right,
        client_bottom=client_bottom,
        visible=bool(user32.IsWindowVisible(handle)),
        minimized=bool(user32.IsIconic(handle)),
    )


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]

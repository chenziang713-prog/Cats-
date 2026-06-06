from __future__ import annotations

import ctypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from PIL import ImageGrab


@dataclass(frozen=True)
class WindowFrame:
    path: Path
    title: str
    client_origin: tuple[int, int]
    size: tuple[int, int]

    def to_screen_point(self, point: tuple[int, int]) -> tuple[int, int]:
        return self.client_origin[0] + point[0], self.client_origin[1] + point[1]


@dataclass(frozen=True)
class WindowInfo:
    handle: int
    title: str
    client_origin: tuple[int, int]
    size: tuple[int, int]


class WindowCaptureError(RuntimeError):
    pass


class WindowsDesktopCapture:
    def __init__(
        self,
        *,
        grabber: Callable[..., Any] = ImageGrab.grab,
        bounds_provider: Callable[[], tuple[int, int, int, int]] | None = None,
    ) -> None:
        self.grabber = grabber
        self.bounds_provider = bounds_provider or _virtual_desktop_bounds

    def capture(self, output_path: Path) -> WindowFrame:
        left, top, width, height = self.bounds_provider()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        image = self.grabber(all_screens=True)
        image.save(output_path)
        return WindowFrame(
            path=output_path,
            title="Desktop",
            client_origin=(left, top),
            size=(width, height),
        )


class WindowsWindowCapture:
    def __init__(
        self,
        title_contains: str,
        render_window_class: str = "RenderWindow",
    ) -> None:
        if not title_contains.strip():
            raise ValueError("title_contains must not be empty.")
        self.title_contains = title_contains
        self.render_window_class = render_window_class

    def capture(self, output_path: Path) -> WindowFrame:
        window = self.find_window()
        left, top = window.client_origin
        width, height = window.size
        output_path.parent.mkdir(parents=True, exist_ok=True)
        image = ImageGrab.grab(
            bbox=(left, top, left + width, top + height),
            all_screens=True,
        )
        image.save(output_path)
        return WindowFrame(
            path=output_path,
            title=window.title,
            client_origin=window.client_origin,
            size=window.size,
        )

    def find_window(self) -> WindowInfo:
        user32 = ctypes.windll.user32
        target = self.title_contains.casefold()
        matches: list[WindowInfo] = []

        enum_proc_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

        @enum_proc_type
        def callback(handle: int, _: Any) -> bool:
            if not user32.IsWindowVisible(handle) or user32.IsIconic(handle):
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
            if not user32.GetClientRect(handle, ctypes.byref(rect)):
                return True

            origin = POINT(0, 0)
            if not user32.ClientToScreen(handle, ctypes.byref(origin)):
                return True

            width = int(rect.right - rect.left)
            height = int(rect.bottom - rect.top)
            if width > 0 and height > 0:
                matches.append(
                    WindowInfo(
                        handle=int(handle),
                        title=title,
                        client_origin=(int(origin.x), int(origin.y)),
                        size=(width, height),
                    )
                )
            return True

        user32.EnumWindows(callback, 0)
        if not matches:
            raise WindowCaptureError(
                "No visible, non-minimized window matched title keyword: "
                f"{self.title_contains}"
            )
        top_level = max(matches, key=lambda item: item.size[0] * item.size[1])
        return self._find_render_window(top_level.handle)

    def _find_render_window(self, parent_handle: int) -> WindowInfo:
        user32 = ctypes.windll.user32
        matches: list[WindowInfo] = []
        enum_proc_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

        @enum_proc_type
        def callback(handle: int, _: Any) -> bool:
            if not user32.IsWindowVisible(handle):
                return True

            class_buffer = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(handle, class_buffer, 256)
            if class_buffer.value != self.render_window_class:
                return True

            title_length = user32.GetWindowTextLengthW(handle)
            title_buffer = ctypes.create_unicode_buffer(title_length + 1)
            user32.GetWindowTextW(handle, title_buffer, title_length + 1)
            rect = RECT()
            origin = POINT(0, 0)
            if not user32.GetClientRect(handle, ctypes.byref(rect)):
                return True
            if not user32.ClientToScreen(handle, ctypes.byref(origin)):
                return True
            width = int(rect.right - rect.left)
            height = int(rect.bottom - rect.top)
            if width > 0 and height > 0:
                matches.append(
                    WindowInfo(
                        handle=int(handle),
                        title=title_buffer.value,
                        client_origin=(int(origin.x), int(origin.y)),
                        size=(width, height),
                    )
                )
            return True

        user32.EnumChildWindows(parent_handle, callback, 0)
        if not matches:
            raise WindowCaptureError(
                "Matched emulator window but could not find visible render child "
                f"class: {self.render_window_class}"
            )
        return max(matches, key=lambda item: item.size[0] * item.size[1])


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


def _virtual_desktop_bounds() -> tuple[int, int, int, int]:
    user32 = ctypes.windll.user32
    return (
        int(user32.GetSystemMetrics(76)),
        int(user32.GetSystemMetrics(77)),
        int(user32.GetSystemMetrics(78)),
        int(user32.GetSystemMetrics(79)),
    )

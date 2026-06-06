from .capture_backend import CaptureBackend, CaptureBackendError, create_capture_backend
from .fullscreen_capture import FullScreenCaptureBackend
from .replay_capture import ReplayCaptureBackend
from .static_image_capture import StaticImageCaptureBackend
from .window_capture import WindowCaptureBackend

__all__ = [
    "CaptureBackend",
    "CaptureBackendError",
    "FullScreenCaptureBackend",
    "ReplayCaptureBackend",
    "StaticImageCaptureBackend",
    "WindowCaptureBackend",
    "create_capture_backend",
]

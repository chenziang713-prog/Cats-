from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class MatchResult:
    confidence: float
    top_left: tuple[int, int]
    size: tuple[int, int]
    scale: float = 1.0

    @property
    def center(self) -> tuple[int, int]:
        width, height = self.size
        x, y = self.top_left
        return x + width // 2, y + height // 2


def _load_cv2() -> Any:
    try:
        import cv2
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "OpenCV is required for template matching. "
            "Run: pip install -r requirements.txt"
        ) from exc
    return cv2


def load_image(path: Path) -> Any:
    if not path.exists():
        raise FileNotFoundError(f"Image path does not exist: {path}")

    cv2 = _load_cv2()
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None:
        raise FileNotFoundError(f"Could not read image: {path}")
    return image


def _prepare_for_matching(image: Any, mode: str) -> Any:
    cv2 = _load_cv2()
    if mode == "color":
        return image
    if mode == "gray":
        return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    if mode == "edge":
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        return cv2.Canny(gray, 50, 150)
    raise ValueError(f"Unsupported match mode: {mode}")


def match_template(
    screen_path: Path,
    template_path: Path,
    mode: str = "color",
    scale_min: float = 1.0,
    scale_max: float = 1.0,
    scale_step: float = 0.1,
    region: tuple[int, int, int, int] | None = None,
) -> MatchResult:
    cv2 = _load_cv2()
    screen = load_image(screen_path)
    template = load_image(template_path)
    offset_x = 0
    offset_y = 0
    if region is not None:
        x, y, width, height = region
        if x < 0 or y < 0 or width <= 0 or height <= 0:
            raise ValueError("region must define positive x, y, width, and height values.")
        right = min(screen.shape[1], x + width)
        bottom = min(screen.shape[0], y + height)
        if x >= screen.shape[1] or y >= screen.shape[0] or right <= x or bottom <= y:
            raise ValueError("region must overlap the screen image.")
        screen = screen[y:bottom, x:right]
        offset_x = x
        offset_y = y

    prepared_screen = _prepare_for_matching(screen, mode)
    if scale_min <= 0 or scale_max <= 0 or scale_step <= 0:
        raise ValueError("Template scales and step must be greater than 0.")
    if scale_min > scale_max:
        raise ValueError("scale_min must not exceed scale_max.")

    best_match: MatchResult | None = None
    scale = scale_min
    while scale <= scale_max + 1e-9:
        width = max(1, round(template.shape[1] * scale))
        height = max(1, round(template.shape[0] * scale))
        if width <= screen.shape[1] and height <= screen.shape[0]:
            scaled_template = cv2.resize(
                template,
                (width, height),
                interpolation=cv2.INTER_AREA if scale < 1.0 else cv2.INTER_CUBIC,
            )
            prepared_template = _prepare_for_matching(scaled_template, mode)
            result = cv2.matchTemplate(
                prepared_screen,
                prepared_template,
                cv2.TM_CCOEFF_NORMED,
            )
            _, max_value, _, max_location = cv2.minMaxLoc(result)
            candidate = MatchResult(
                confidence=float(max_value),
                top_left=(int(max_location[0]) + offset_x, int(max_location[1]) + offset_y),
                size=(int(width), int(height)),
                scale=scale,
            )
            if best_match is None or candidate.confidence > best_match.confidence:
                best_match = candidate
        scale += scale_step

    if best_match is None:
        raise ValueError("Template image must not be larger than screen image.")
    return best_match

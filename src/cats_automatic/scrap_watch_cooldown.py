from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from .runtime_paths import scrap_watch_cooldown_templates_dir
from .strategy_base import DetectionResult, TargetSpec

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}

@dataclass(frozen=True)
class CooldownResult:
    detected: bool
    score: float
    method: str
    template_name: str = ""
    roi: tuple[int, int, int, int] | None = None
    white_text_pixel_ratio: float = 0.0
    white_text_component_count: int = 0

def load_cooldown_targets(directory: Path | None = None, threshold: float = 0.80) -> tuple[TargetSpec, ...]:
    root = directory or scrap_watch_cooldown_templates_dir()
    root.mkdir(parents=True, exist_ok=True)
    return tuple(
        TargetSpec(f"scrap_watch_cooldown_{index:03d}", str(path), threshold, optional=True)
        for index, path in enumerate(sorted(path for path in root.iterdir() if path.suffix.lower() in IMAGE_SUFFIXES), 1)
    )

def detect_cooldown(
    screen_path: Path,
    button: DetectionResult,
    detections,
    *,
    white_ratio_threshold: float = 0.02,
    min_white_components: int = 2,
) -> CooldownResult:
    template_hits = [item for name, item in detections.items() if name.startswith("scrap_watch_cooldown_")]
    if template_hits:
        best = max(template_hits, key=lambda item: item.confidence)
        return CooldownResult(True, best.confidence, "template", best.name)
    left, top = button.top_left
    width, height = button.size
    roi = (left, top, left + width, top + height)
    try:
        image = Image.open(screen_path).convert("RGB").crop(roi)
    except (OSError, ValueError):
        return CooldownResult(False, 0.0, "white_text_roi", roi=roi)
    pixels = list(image.getdata())
    mask = [r > 220 and g > 220 and b > 220 for r, g, b in pixels]
    ratio = sum(mask) / max(1, len(mask))
    components = _component_count(mask, image.width, image.height)
    detected = ratio >= white_ratio_threshold and components >= min_white_components
    return CooldownResult(detected, ratio, "white_text_roi", roi=roi, white_text_pixel_ratio=ratio, white_text_component_count=components)

def _component_count(mask: list[bool], width: int, height: int) -> int:
    seen: set[int] = set()
    count = 0
    for start, active in enumerate(mask):
        if not active or start in seen:
            continue
        stack = [start]
        seen.add(start)
        size = 0
        while stack:
            index = stack.pop()
            size += 1
            x, y = index % width, index // width
            for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                neighbor = ny * width + nx
                if 0 <= nx < width and 0 <= ny < height and mask[neighbor] and neighbor not in seen:
                    seen.add(neighbor)
                    stack.append(neighbor)
        if size >= 2:
            count += 1
    return count

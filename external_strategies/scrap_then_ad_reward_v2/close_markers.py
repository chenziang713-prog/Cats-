from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, NamedTuple

from .template_sources import V2_CANONICAL_TEMPLATE_DIRS, collect_canonical_marker_names


SAFE_CLOSE_MARKER_PATTERNS = (
    "close_buttons",
    "close_ad",
    "close_user_*",
    "close_end_*",
)


class SafeCloseMarker(NamedTuple):
    name: str
    confidence: float
    center: tuple[int, int]
    template_path: str


def safe_close_marker_names() -> tuple[str, ...]:
    return tuple(
        sorted(
            name
            for name in collect_canonical_marker_names()
            if marker_matches_patterns(name, SAFE_CLOSE_MARKER_PATTERNS)
        )
    )


def marker_matches_patterns(marker_name: str, patterns: Sequence[str] = SAFE_CLOSE_MARKER_PATTERNS) -> bool:
    return any(_marker_matches(pattern, marker_name) for pattern in patterns)


def select_safe_close_marker(
    detections: Mapping[str, Any],
    *,
    min_confidence: float,
) -> SafeCloseMarker | None:
    candidates = safe_close_candidates(detections, min_confidence=min_confidence)
    if not candidates:
        return None
    return max(candidates, key=lambda item: (item.confidence, item.name))


def safe_close_candidates(
    detections: Mapping[str, Any],
    *,
    min_confidence: float,
) -> list[SafeCloseMarker]:
    candidates: list[SafeCloseMarker] = []
    actual_safe_names = set(safe_close_marker_names())
    for name, detection in detections.items():
        if name not in actual_safe_names:
            continue
        confidence = detection_confidence(detection)
        if confidence is None or confidence < min_confidence:
            continue
        center = detection_center(detection)
        if center is None:
            continue
        template_path = detection_template_path(detection)
        if not template_path or not is_canonical_v2_template_path(template_path):
            continue
        candidates.append(
            SafeCloseMarker(
                name=name,
                confidence=confidence,
                center=center,
                template_path=template_path,
            )
        )
    return candidates


def is_safe_close_marker_detection(
    marker_name: str,
    detection: Any,
    *,
    min_confidence: float,
) -> bool:
    return bool(
        marker_name in set(safe_close_marker_names())
        and (confidence := detection_confidence(detection)) is not None
        and confidence >= min_confidence
        and detection_center(detection) is not None
        and (template_path := detection_template_path(detection))
        and is_canonical_v2_template_path(template_path)
    )


def is_canonical_v2_template_path(path: str | Path) -> bool:
    try:
        candidate = Path(path).resolve()
    except (OSError, RuntimeError):
        return False
    for directory in V2_CANONICAL_TEMPLATE_DIRS:
        try:
            candidate.relative_to(directory.resolve())
        except ValueError:
            continue
        return True
    return False


def detection_confidence(detection: Any) -> float | None:
    raw = detection_value(detection, "confidence")
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def detection_center(detection: Any) -> tuple[int, int] | None:
    center = pair_to_ints(detection_value(detection, "center"))
    if center is not None:
        return center
    top_left = pair_to_ints(detection_value(detection, "top_left"))
    size = pair_to_ints(detection_value(detection, "size"))
    if top_left is not None and size is not None and size[0] > 0 and size[1] > 0:
        return top_left[0] + size[0] // 2, top_left[1] + size[1] // 2
    bbox = detection_value(detection, "bbox")
    if isinstance(bbox, Sequence) and not isinstance(bbox, (str, bytes)) and len(bbox) == 4:
        try:
            x, y, width, height = (int(value) for value in bbox)
        except (TypeError, ValueError):
            return None
        if width > 0 and height > 0:
            return x + width // 2, y + height // 2
    return None


def detection_template_path(detection: Any) -> str:
    raw = detection_value(detection, "template_path")
    if raw:
        return str(raw)
    raw = detection_value(detection, "template")
    return "" if raw is None else str(raw)


def detection_value(detection: Any, name: str) -> Any:
    if isinstance(detection, Mapping):
        return detection.get(name)
    return getattr(detection, name, None)


def pair_to_ints(value: Any) -> tuple[int, int] | None:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or len(value) != 2:
        return None
    try:
        return int(value[0]), int(value[1])
    except (TypeError, ValueError):
        return None


def _marker_matches(pattern: str, marker_name: str) -> bool:
    if pattern.endswith("*"):
        return marker_name.startswith(pattern[:-1])
    return marker_name == pattern

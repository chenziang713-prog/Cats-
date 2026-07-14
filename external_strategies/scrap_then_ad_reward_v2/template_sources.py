from __future__ import annotations

import re
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parent
V2_TEMPLATE_ROOT = PACKAGE_ROOT / "templates"
V2_PAGE_STATUS_TEMPLATE_DIR = V2_TEMPLATE_ROOT / "page_status_judge_page"
V2_USER_TEMPLATE_DIR = V2_TEMPLATE_ROOT / "user_templates"

V2_CANONICAL_TEMPLATE_DIRS = (
    V2_PAGE_STATUS_TEMPLATE_DIR,
    V2_USER_TEMPLATE_DIR,
)

V2_CANONICAL_TEMPLATE_DIR_NAMES = tuple(
    str(path.relative_to(PACKAGE_ROOT)).replace("\\", "/")
    for path in V2_CANONICAL_TEMPLATE_DIRS
)

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}

ACTION_ONLY_MARKERS = frozenset(
    {
        "ad_entry",
        "error_buttons",
        "retry_buttons",
        "reconnect_buttons",
    }
)


def normalize_user_marker_name(name: str) -> str:
    """Normalize user-supplied folder names that are known action markers."""

    value = re.sub(r"[^a-zA-Z0-9-]+", "_", name).strip("_").lower()
    return {
        "ad-entry": "ad_entry",
        "get_reward": "get_reward",
        "watch_ad_film": "watch_ad_film",
    }.get(value, value)


def iter_template_files(template_dirs: tuple[Path, ...] = V2_CANONICAL_TEMPLATE_DIRS) -> list[Path]:
    files: list[Path] = []
    for directory in template_dirs:
        if not directory.exists() or not directory.is_dir():
            continue
        files.extend(
            path.resolve()
            for path in directory.rglob("*")
            if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
        )
    return sorted(dict.fromkeys(files))


def marker_name_for_template_path(path: Path, source_dir: Path) -> str:
    """Return the marker folder name for a canonical v2 template image."""

    path = path.resolve()
    source_dir = source_dir.resolve()
    relative_parts = path.relative_to(source_dir).parts
    if not relative_parts:
        return path.stem

    if source_dir == V2_PAGE_STATUS_TEMPLATE_DIR.resolve():
        if len(relative_parts) >= 3:
            return relative_parts[-2]
        if len(relative_parts) >= 2:
            return relative_parts[0]
        return path.stem

    if source_dir == V2_USER_TEMPLATE_DIR.resolve():
        if len(relative_parts) >= 2:
            return normalize_user_marker_name(relative_parts[0])
        return normalize_user_marker_name(path.stem)

    if len(relative_parts) >= 2:
        return normalize_user_marker_name(relative_parts[-2])
    return normalize_user_marker_name(path.stem)


def collect_canonical_marker_names(
    template_dirs: tuple[Path, ...] = V2_CANONICAL_TEMPLATE_DIRS,
) -> list[str]:
    names: list[str] = []
    for template_path in iter_template_files(template_dirs):
        for source_dir in template_dirs:
            try:
                marker_name = marker_name_for_template_path(template_path, source_dir)
            except ValueError:
                continue
            if marker_name not in names:
                names.append(marker_name)
            break
    return sorted(names)


def template_paths_for_marker(
    marker_name: str,
    template_dirs: tuple[Path, ...] = V2_CANONICAL_TEMPLATE_DIRS,
) -> list[Path]:
    matches: list[Path] = []
    for template_path in iter_template_files(template_dirs):
        for source_dir in template_dirs:
            try:
                current_marker = marker_name_for_template_path(template_path, source_dir)
            except ValueError:
                continue
            if current_marker == marker_name:
                matches.append(template_path.resolve())
            break
    return sorted(dict.fromkeys(matches))

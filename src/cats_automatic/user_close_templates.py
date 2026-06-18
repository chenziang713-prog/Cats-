from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Callable

from PIL import Image

from .runtime_paths import close_button_templates_dir
from .strategy_base import RelativeRegion, TargetSpec


USER_CLOSE_TEMPLATE_PATTERN = re.compile(r"^close-user-(\d+)\.png$", re.IGNORECASE)


def user_close_target_name(path: Path) -> str:
    match = USER_CLOSE_TEMPLATE_PATTERN.match(path.name)
    if match:
        return f"close_user_{int(match.group(1)):03d}"
    safe_stem = re.sub(r"[^a-zA-Z0-9]+", "_", path.stem).strip("_").lower()
    if safe_stem.startswith("close_user_"):
        return safe_stem
    return f"close_user_{safe_stem or 'template'}"


def load_user_close_targets(
    template_dir: Path | None = None,
    *,
    log: Callable[[str], None] | None = None,
) -> tuple[TargetSpec, ...]:
    directory = template_dir or close_button_templates_dir()
    directory.mkdir(parents=True, exist_ok=True)
    targets: list[TargetSpec] = []
    used_names: set[str] = set()
    for path in sorted(directory.glob("*.png")):
        try:
            _validate_png(path)
            name = _unique_name(user_close_target_name(path), used_names)
            targets.append(
                TargetSpec(
                    name=name,
                    template=str(path.resolve()),
                    threshold=0.75,
                    match_mode="color",
                    region=RelativeRegion(x=0.0, y=0.0, width=1.0, height=0.20),
                    scale_min=0.4,
                    scale_max=1.1,
                    scale_step=0.05,
                )
            )
        except (OSError, ValueError) as exc:
            if log is not None:
                log(f"User close template load failed: path={path} error={exc}")
    return tuple(targets)


def next_close_button_template_path(template_dir: Path | None = None) -> Path:
    directory = template_dir or close_button_templates_dir()
    directory.mkdir(parents=True, exist_ok=True)
    used_numbers = {
        int(match.group(1))
        for path in directory.glob("close-user-*.png")
        if (match := USER_CLOSE_TEMPLATE_PATTERN.match(path.name))
    }
    index = 1
    while index in used_numbers:
        index += 1
    return directory / f"close-user-{index:03d}.png"


def add_close_button_template(source_path: Path, template_dir: Path | None = None) -> Path:
    source = Path(source_path)
    if source.suffix.lower() != ".png":
        raise ValueError("Close button template must be a PNG file.")
    if not source.exists():
        raise FileNotFoundError(f"Template source does not exist: {source}")
    _validate_png(source)
    destination = next_close_button_template_path(template_dir)
    if destination.exists():
        raise FileExistsError(f"Template destination already exists: {destination}")
    shutil.copy2(source, destination)
    return destination


def count_user_close_templates(template_dir: Path | None = None) -> int:
    directory = template_dir or close_button_templates_dir()
    directory.mkdir(parents=True, exist_ok=True)
    return len(list(directory.glob("*.png")))


def _validate_png(path: Path) -> None:
    with Image.open(path) as image:
        image.verify()


def _unique_name(name: str, used_names: set[str]) -> str:
    if name not in used_names:
        used_names.add(name)
        return name
    suffix = 2
    while f"{name}_{suffix}" in used_names:
        suffix += 1
    unique = f"{name}_{suffix}"
    used_names.add(unique)
    return unique

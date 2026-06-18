from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Callable

from PIL import Image

from .runtime_paths import pre_watch_optional_templates_dir, watch_button_templates_dir
from .strategy_base import TargetSpec


WATCH_TEMPLATE_PATTERN = re.compile(r"^watch-user-(\d+)\.png$", re.IGNORECASE)


def load_pre_watch_optional_target(
    template_dir: Path | None = None,
    *,
    log: Callable[[str], None] | None = None,
) -> TargetSpec | None:
    directory = template_dir or pre_watch_optional_templates_dir()
    directory.mkdir(parents=True, exist_ok=True)
    paths = sorted(directory.glob("*.png"))
    if len(paths) > 1 and log is not None:
        log("Warning: pre_watch_optional directory can contain only one png; using the first file.")
    for path in paths:
        try:
            _validate_png(path)
        except (OSError, ValueError) as exc:
            if log is not None:
                log(f"Pre-watch optional template load failed: path={path} error={exc}")
            continue
        return TargetSpec(
            name="pre_watch_optional",
            template=str(path.resolve()),
            threshold=0.80,
            match_mode="color",
            scale_min=0.4,
            scale_max=1.1,
            scale_step=0.05,
        )
    return None


def load_user_watch_targets(
    template_dir: Path | None = None,
    *,
    log: Callable[[str], None] | None = None,
) -> tuple[TargetSpec, ...]:
    directory = template_dir or watch_button_templates_dir()
    directory.mkdir(parents=True, exist_ok=True)
    targets: list[TargetSpec] = []
    for path in sorted(directory.glob("*.png")):
        try:
            _validate_png(path)
            targets.append(
                TargetSpec(
                    name=_watch_target_name(path),
                    template=str(path.resolve()),
                    threshold=0.80,
                    match_mode="color",
                    scale_min=0.4,
                    scale_max=1.1,
                    scale_step=0.05,
                )
            )
        except (OSError, ValueError) as exc:
            if log is not None:
                log(f"User watch template load failed: path={path} error={exc}")
    return tuple(targets)


def set_pre_watch_optional_template(source_path: Path, template_dir: Path | None = None) -> Path:
    source = Path(source_path)
    _validate_source_png(source)
    directory = template_dir or pre_watch_optional_templates_dir()
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / "optional.png"
    shutil.copy2(source, destination)
    for path in directory.glob("*.png"):
        if path != destination:
            path.unlink()
    return destination


def clear_pre_watch_optional_template(template_dir: Path | None = None) -> bool:
    directory = template_dir or pre_watch_optional_templates_dir()
    directory.mkdir(parents=True, exist_ok=True)
    removed = False
    for path in directory.glob("*.png"):
        path.unlink()
        removed = True
    return removed


def add_watch_button_template(source_path: Path, template_dir: Path | None = None) -> Path:
    source = Path(source_path)
    _validate_source_png(source)
    directory = template_dir or watch_button_templates_dir()
    directory.mkdir(parents=True, exist_ok=True)
    used = {
        int(match.group(1))
        for path in directory.glob("watch-user-*.png")
        if (match := WATCH_TEMPLATE_PATTERN.match(path.name))
    }
    index = 1
    while index in used:
        index += 1
    destination = directory / f"watch-user-{index:03d}.png"
    shutil.copy2(source, destination)
    return destination


def _watch_target_name(path: Path) -> str:
    match = WATCH_TEMPLATE_PATTERN.match(path.name)
    if match:
        return f"watch_user_{int(match.group(1)):03d}"
    safe_stem = re.sub(r"[^a-zA-Z0-9]+", "_", path.stem).strip("_").lower()
    return f"watch_user_{safe_stem or 'template'}"


def _validate_source_png(path: Path) -> None:
    if path.suffix.lower() != ".png":
        raise ValueError("Template must be a PNG file.")
    if not path.exists():
        raise FileNotFoundError(f"Template source does not exist: {path}")
    _validate_png(path)


def _validate_png(path: Path) -> None:
    with Image.open(path) as image:
        image.verify()

from __future__ import annotations

import sys
from pathlib import Path


def app_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def user_templates_dir(base_dir: Path | None = None, *, create: bool = True) -> Path:
    path = (base_dir or app_base_dir()) / "user_templates"
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def close_button_templates_dir(base_dir: Path | None = None, *, create: bool = True) -> Path:
    path = user_templates_dir(base_dir, create=create) / "close_buttons"
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def pre_watch_optional_templates_dir(base_dir: Path | None = None, *, create: bool = True) -> Path:
    path = user_templates_dir(base_dir, create=create) / "pre_watch_optional"
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def watch_button_templates_dir(base_dir: Path | None = None, *, create: bool = True) -> Path:
    path = user_templates_dir(base_dir, create=create) / "watch_buttons"
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def scrap_watch_cooldown_templates_dir(base_dir: Path | None = None, *, create: bool = True) -> Path:
    path = user_templates_dir(base_dir, create=create) / "scrap_watch_cooldown"
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def external_strategies_dir(base_dir: Path | None = None, *, create: bool = True) -> Path:
    path = (base_dir or app_base_dir()) / "external_strategies"
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def error_popup_templates_dir(base_dir: Path | None = None, *, create: bool = True) -> Path:
    path = user_templates_dir(base_dir, create=create) / "error_popups"
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def error_button_templates_dir(base_dir: Path | None = None, *, create: bool = True) -> Path:
    path = user_templates_dir(base_dir, create=create) / "error_buttons"
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path

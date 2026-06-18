from __future__ import annotations

from pathlib import Path

from PIL import Image

from cats_automatic.runtime_paths import (
    pre_watch_optional_templates_dir,
    watch_button_templates_dir,
)
from cats_automatic.user_ad_reward_templates import (
    add_watch_button_template,
    clear_pre_watch_optional_template,
    load_pre_watch_optional_target,
    load_user_watch_targets,
    set_pre_watch_optional_template,
)


def test_optional_and_watch_template_dirs_use_base_dir(tmp_path: Path) -> None:
    assert pre_watch_optional_templates_dir(tmp_path) == tmp_path / "user_templates" / "pre_watch_optional"
    assert watch_button_templates_dir(tmp_path) == tmp_path / "user_templates" / "watch_buttons"


def test_empty_optional_template_dir_returns_none(tmp_path: Path) -> None:
    directory = tmp_path / "pre_watch_optional"

    assert load_pre_watch_optional_target(directory) is None
    assert directory.exists()


def test_optional_template_uses_first_png_and_warns_for_multiple(tmp_path: Path) -> None:
    directory = tmp_path / "pre_watch_optional"
    _write_png(directory / "optional.png")
    _write_png(directory / "second.png")
    messages: list[str] = []

    target = load_pre_watch_optional_target(directory, log=messages.append)

    assert target is not None
    assert target.name == "pre_watch_optional"
    assert messages and "only one png" in messages[0]


def test_set_optional_template_replaces_and_keeps_only_optional_png(tmp_path: Path) -> None:
    directory = tmp_path / "pre_watch_optional"
    source = tmp_path / "source.png"
    _write_png(source, (255, 0, 0))
    _write_png(directory / "old.png", (0, 255, 0))

    destination = set_pre_watch_optional_template(source, directory)

    assert destination == directory / "optional.png"
    assert [path.name for path in directory.glob("*.png")] == ["optional.png"]
    assert clear_pre_watch_optional_template(directory) is True
    assert not list(directory.glob("*.png"))


def test_watch_templates_load_and_auto_number(tmp_path: Path) -> None:
    directory = tmp_path / "watch_buttons"
    first_source = tmp_path / "first.png"
    second_source = tmp_path / "second.png"
    _write_png(first_source)
    _write_png(second_source, (0, 255, 0))

    first = add_watch_button_template(first_source, directory)
    second = add_watch_button_template(second_source, directory)
    targets = load_user_watch_targets(directory)

    assert first.name == "watch-user-001.png"
    assert second.name == "watch-user-002.png"
    assert [target.name for target in targets] == ["watch_user_001", "watch_user_002"]


def _write_png(path: Path, color: tuple[int, int, int] = (255, 0, 0)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (8, 8), color).save(path)

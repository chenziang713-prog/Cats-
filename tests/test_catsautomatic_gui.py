from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

from tools.catsautomatic_gui import (
    GuiConfig,
    build_main_command,
    copy_close_button_template,
    copy_pre_watch_optional_template,
    copy_watch_button_template,
    gui_external_strategies_dir,
    gui_close_button_templates_dir,
    gui_pre_watch_optional_dir,
    gui_strategy_names,
    gui_watch_button_templates_dir,
    output_dir,
    load_config,
    save_config,
    update_config_from_adb_candidate,
)
from cats_automatic.adb_discovery import AdbCandidate, AdbDevice


def test_gui_dry_run_command_never_contains_allow_click() -> None:
    config = GuiConfig(repeat_after_reward=True)

    command = build_main_command(
        config,
        allow_click=True,
        dry_run_test=True,
        python_executable="python",
    )

    assert "--allow-click" not in command
    assert command[0:3] == ["python", "-m", "cats_automatic.main"]
    assert command[command.index("--max-actions") + 1] == "2"
    assert command[command.index("--max-loops") + 1] == "2"
    assert "--repeat-after-reward" not in command


def test_gui_allow_click_command_contains_allow_click() -> None:
    config = GuiConfig(repeat_after_reward=False)

    command = build_main_command(config, allow_click=True, python_executable="python")

    assert "--allow-click" in command
    assert command[command.index("--capture-backend") + 1] == "adb"
    assert command[command.index("--adb-path") + 1] == config.adb_path
    assert command[command.index("--adb-serial") + 1] == config.adb_serial


def test_gui_repeat_after_reward_adds_cycle_args() -> None:
    config = GuiConfig(
        repeat_after_reward=True,
        cycle_wait_seconds="123",
        max_cycles="2",
    )

    command = build_main_command(config, python_executable="python")

    assert "--repeat-after-reward" in command
    assert command[command.index("--cycle-wait-seconds") + 1] == "123"
    assert command[command.index("--max-cycles") + 1] == "2"


def test_gui_non_repeat_command_omits_cycle_args() -> None:
    config = GuiConfig(repeat_after_reward=False)

    command = build_main_command(config, python_executable="python")

    assert "--repeat-after-reward" not in command
    assert "--cycle-wait-seconds" not in command
    assert "--max-cycles" not in command


def test_gui_config_save_and_load_does_not_persist_allow_click(tmp_path: Path) -> None:
    config_path = tmp_path / "gui_config.json"
    config = GuiConfig(
        adb_path="C:/adb.exe",
        adb_serial="device-1",
        strategy="ad_reward",
        max_actions="7",
        repeat_after_reward=False,
    )

    save_config(config, config_path)
    raw = config_path.read_text(encoding="utf-8")
    loaded = load_config(config_path)

    assert "allow_click" not in raw
    assert loaded.adb_path == "C:/adb.exe"
    assert loaded.adb_serial == "device-1"
    assert loaded.max_actions == "7"
    assert loaded.repeat_after_reward is False


def test_gui_frozen_command_uses_sibling_cli_exe(monkeypatch) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", r"C:\Release\CATSautomatic.exe")

    command = build_main_command(GuiConfig(repeat_after_reward=False))

    assert command[0] == r"C:\Release\CATSautomatic-cli.exe"
    assert "-m" not in command
    assert "cats_automatic.main" not in command


def test_gui_output_dir_can_be_based_on_release_dir() -> None:
    assert output_dir(Path(r"C:\Release")) == Path(r"C:\Release\output")


def test_gui_close_button_template_dir_uses_release_base_dir() -> None:
    assert gui_close_button_templates_dir(Path(r"C:\Release")) == Path(
        r"C:\Release\user_templates\close_buttons"
    )


def test_gui_external_strategies_dir_uses_release_base_dir() -> None:
    assert gui_external_strategies_dir(Path(r"C:\Release")) == Path(
        r"C:\Release\external_strategies"
    )


def test_gui_optional_and_watch_dirs_use_release_base_dir() -> None:
    assert gui_pre_watch_optional_dir(Path(r"C:\Release")) == Path(
        r"C:\Release\user_templates\pre_watch_optional"
    )
    assert gui_watch_button_templates_dir(Path(r"C:\Release")) == Path(
        r"C:\Release\user_templates\watch_buttons"
    )


def test_gui_strategy_names_include_builtin(tmp_path: Path) -> None:
    assert "ad_reward" in gui_strategy_names(tmp_path / "external_strategies")


def test_gui_update_config_from_adb_candidate_fills_path_and_device() -> None:
    config = GuiConfig(adb_path="old", adb_serial="old-device")
    candidate = AdbCandidate(
        Path(r"C:\LDPlayer9\adb.exe"),
        (AdbDevice("emulator-5556", "device"),),
    )

    updated = update_config_from_adb_candidate(config, candidate)

    assert updated.adb_path == r"C:\LDPlayer9\adb.exe"
    assert updated.adb_serial == "emulator-5556"
    assert updated.repeat_after_reward == config.repeat_after_reward


def test_gui_add_close_button_template_copies_png_with_next_number(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    template_dir = tmp_path / "user_templates" / "close_buttons"
    _write_png(source)
    _write_png(template_dir / "close-user-001.png", color=(0, 255, 0))

    destination = copy_close_button_template(source, template_dir)

    assert destination == template_dir / "close-user-002.png"
    assert destination.exists()
    assert (template_dir / "close-user-001.png").exists()


def test_gui_add_close_button_template_does_not_overwrite_existing(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    template_dir = tmp_path / "user_templates" / "close_buttons"
    existing = template_dir / "close-user-001.png"
    _write_png(source, color=(255, 0, 0))
    _write_png(existing, color=(0, 255, 0))

    destination = copy_close_button_template(source, template_dir)

    assert destination.name == "close-user-002.png"
    assert existing.read_bytes() != destination.read_bytes()


def test_gui_copy_optional_template_replaces_optional_png(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    template_dir = tmp_path / "pre_watch_optional"
    _write_png(source)
    _write_png(template_dir / "old.png", color=(0, 255, 0))

    destination = copy_pre_watch_optional_template(source, template_dir)

    assert destination == template_dir / "optional.png"
    assert [path.name for path in template_dir.glob("*.png")] == ["optional.png"]


def test_gui_copy_watch_template_uses_next_number(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    template_dir = tmp_path / "watch_buttons"
    _write_png(source)
    _write_png(template_dir / "watch-user-001.png")

    destination = copy_watch_button_template(source, template_dir)

    assert destination.name == "watch-user-002.png"


def _write_png(path: Path, color: tuple[int, int, int] = (255, 0, 0)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (8, 8), color).save(path)

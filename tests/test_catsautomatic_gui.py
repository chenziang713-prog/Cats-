from __future__ import annotations

import sys
from pathlib import Path

from tools.catsautomatic_gui import (
    GuiConfig,
    build_main_command,
    output_dir,
    load_config,
    save_config,
)


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

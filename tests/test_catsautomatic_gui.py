from __future__ import annotations

import sys
import tkinter as tk
import json
from pathlib import Path

import pytest
from PIL import Image

import tools.catsautomatic_gui as gui_module
from tools.catsautomatic_gui import (
    SCRAP_REQUIRED_TEMPLATES,
    CatsAutomaticGui,
    V2_STRATEGY_NAME,
    build_combined_test_command,
    build_v2_film_command,
    GuiConfig,
    build_main_command,
    build_scrap_test_command,
    copy_close_button_template,
    copy_pre_watch_optional_template,
    copy_watch_button_template,
    feature_for_strategy,
    gui_external_strategies_dir,
    gui_close_button_templates_dir,
    gui_pre_watch_optional_dir,
    gui_scrap_templates_dir,
    gui_strategy_choices,
    gui_strategy_names,
    gui_watch_button_templates_dir,
    output_dir,
    load_config,
    missing_scrap_templates,
    save_config,
    update_config_from_adb_candidate,
)
from cats_automatic.license_client import LicenseCache, LicenseResult
from tools.build_release import copy_combined_strategy_package, copy_scrap_strategy_package
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


def test_gui_default_strategy_is_v2_film_and_device_is_not_hardcoded() -> None:
    config = GuiConfig()

    assert config.strategy == V2_STRATEGY_NAME
    assert config.adb_serial == ""
    assert config.repeat_after_reward is False


def test_v2_film_dry_run_command_is_one_cycle_without_allow_click() -> None:
    config = GuiConfig(adb_path="adb.exe", adb_serial="emulator-5556")

    command = build_v2_film_command(config, real_click=False, python_executable="python")

    assert command[command.index("--strategy") + 1] == V2_STRATEGY_NAME
    assert "--allow-click" not in command
    assert "--repeat-after-reward" not in command
    assert "--max-cycles" not in command
    assert "output\\v2-film-dry-run.log" in command


def test_v2_film_real_command_enables_allow_click_but_not_repeat() -> None:
    config = GuiConfig(adb_path="adb.exe", adb_serial="emulator-5556")

    command = build_v2_film_command(config, real_click=True, python_executable="python")

    assert command[command.index("--strategy") + 1] == V2_STRATEGY_NAME
    assert "--allow-click" in command
    assert "--repeat-after-reward" not in command
    assert "output\\v2-film-real.log" in command


def test_v2_strategy_reuses_ad_reward_license_feature() -> None:
    assert feature_for_strategy(V2_STRATEGY_NAME) == "ad_reward"
    assert feature_for_strategy("scrap_then_ad_reward") == "scrap_then_ad_reward"


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


def test_gui_command_adds_scrap_wait_arguments() -> None:
    config = GuiConfig(
        battle_wait_seconds="45",
        ad_wait_seconds="18",
        repeat_after_reward=False,
    )

    command = build_main_command(config, python_executable="python")

    assert command[command.index("--battle-wait-seconds") + 1] == "45"
    assert command[command.index("--ad-wait-seconds") + 1] == "18"


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
        battle_wait_seconds="44",
        ad_wait_seconds="17",
        repeat_after_reward=False,
    )

    save_config(config, config_path)
    raw = config_path.read_text(encoding="utf-8")
    loaded = load_config(config_path)

    assert "allow_click" not in raw
    assert loaded.adb_path == "C:/adb.exe"
    assert loaded.adb_serial == "device-1"
    assert loaded.max_actions == "7"
    assert loaded.battle_wait_seconds == "44"
    assert loaded.ad_wait_seconds == "17"
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


def test_gui_discovers_scrap_ad_battle_from_project() -> None:
    external_dir = Path(__file__).resolve().parents[1] / "external_strategies"

    assert "scrap_ad_battle" in gui_strategy_names(external_dir)
    assert "scrap_then_ad_reward" in gui_strategy_names(external_dir)
    choices = dict(gui_strategy_choices(external_dir))
    assert choices["废铁 + 胶卷广告 (scrap_then_ad_reward) [external]"] == "scrap_then_ad_reward"


def test_gui_scrap_templates_dir_uses_release_base_dir() -> None:
    assert gui_scrap_templates_dir(Path(r"C:\Release")) == Path(
        r"C:\Release\external_strategies\scrap_ad_battle\templates"
    )


def test_scrap_single_test_command_is_one_cycle_and_safe() -> None:
    config = GuiConfig(battle_wait_seconds="45", ad_wait_seconds="18")

    command = build_scrap_test_command(
        config,
        loop_test=False,
        python_executable="python",
    )

    assert command[command.index("--strategy") + 1] == "scrap_ad_battle"
    assert command[command.index("--battle-wait-seconds") + 1] == "45"
    assert command[command.index("--ad-wait-seconds") + 1] == "18"
    assert command[command.index("--max-loops") + 1] == "400"
    assert command[command.index("--max-actions") + 1] == "30"
    assert command[command.index("--click-cooldown") + 1] == "1.5"
    assert command[command.index("--interval") + 1] == "1"
    assert command[command.index("--stop-file") + 1] == r"output\STOP"
    assert command[command.index("--log-file") + 1] == r"output\real-scrap-ad-test.log"
    assert command[command.index("--debug-save-capture") + 1] == r"output\real-scrap-ad-test.png"
    assert "--repeat-after-reward" not in command
    assert "--allow-click" not in command


def test_scrap_loop_test_command_uses_two_short_cycles_and_is_safe() -> None:
    command = build_scrap_test_command(
        GuiConfig(),
        loop_test=True,
        python_executable="python",
    )

    assert command[command.index("--strategy") + 1] == "scrap_ad_battle"
    assert command[command.index("--max-loops") + 1] == "999999"
    assert command[command.index("--max-actions") + 1] == "30"
    assert command[command.index("--stop-file") + 1] == r"output\STOP"
    assert command[command.index("--log-file") + 1] == r"output\real-scrap-ad-loop-test.log"
    assert command[command.index("--debug-save-capture") + 1] == r"output\real-scrap-ad-loop-test.png"
    assert "--repeat-after-reward" in command
    assert command[command.index("--cycle-wait-seconds") + 1] == "60"
    assert command[command.index("--max-cycles") + 1] == "2"
    assert "--allow-click" not in command


def test_scrap_test_commands_only_add_allow_click_when_requested() -> None:
    single = build_scrap_test_command(
        GuiConfig(),
        loop_test=False,
        allow_click=True,
        python_executable="python",
    )
    loop = build_scrap_test_command(
        GuiConfig(),
        loop_test=True,
        allow_click=True,
        python_executable="python",
    )

    assert "--allow-click" in single
    assert "--allow-click" in loop


def test_combined_single_and_loop_commands_are_safe() -> None:
    config = GuiConfig(battle_wait_seconds="55", ad_wait_seconds="25")
    single = build_combined_test_command(
        config,
        loop_test=False,
        python_executable="python",
    )
    loop = build_combined_test_command(
        config,
        loop_test=True,
        python_executable="python",
    )

    assert single[single.index("--strategy") + 1] == "scrap_then_ad_reward"
    assert single[single.index("--max-actions") + 1] == "60"
    assert single[single.index("--battle-wait-seconds") + 1] == "55"
    assert single[single.index("--ad-wait-seconds") + 1] == "25"
    assert "--repeat-after-reward" not in single
    assert "--allow-click" not in single
    assert "--repeat-after-reward" in loop
    assert loop[loop.index("--cycle-wait-seconds") + 1] == "60"
    assert loop[loop.index("--max-cycles") + 1] == "2"
    assert "--allow-click" not in loop


def test_scrap_template_check_reports_missing_files(tmp_path: Path) -> None:
    template_dir = tmp_path / "templates"
    template_dir.mkdir()
    _write_png(template_dir / SCRAP_REQUIRED_TEMPLATES[0])

    missing = missing_scrap_templates(template_dir)

    assert SCRAP_REQUIRED_TEMPLATES[0] not in missing
    assert missing == list(SCRAP_REQUIRED_TEMPLATES[1:])


def test_scrap_template_check_reports_complete(tmp_path: Path) -> None:
    template_dir = tmp_path / "templates"
    for filename in SCRAP_REQUIRED_TEMPLATES:
        _write_png(template_dir / filename)

    assert missing_scrap_templates(template_dir) == []


def test_build_release_copies_scrap_strategy_package(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    templates = repo_root / "external_strategies" / "scrap_ad_battle" / "templates"
    templates.mkdir(parents=True)
    (templates / "README.txt").write_text("templates", encoding="utf-8")
    (templates.parent / "manifest.json").write_text("{}", encoding="utf-8")
    release_dir = tmp_path / "release"

    destination = copy_scrap_strategy_package(repo_root, release_dir)

    assert destination == release_dir / "external_strategies" / "scrap_ad_battle"
    assert (destination / "templates" / "README.txt").read_text(encoding="utf-8") == "templates"
    assert (destination / "manifest.json").exists()


def test_build_release_copies_combined_strategy_package(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    templates = repo_root / "external_strategies" / "scrap_then_ad_reward" / "templates"
    templates.mkdir(parents=True)
    (templates / "README.txt").write_text("combined", encoding="utf-8")
    (templates.parent / "strategy.py").write_text("class Strategy: pass", encoding="utf-8")
    release_dir = tmp_path / "release"

    destination = copy_combined_strategy_package(repo_root, release_dir)

    assert destination == release_dir / "external_strategies" / "scrap_then_ad_reward"
    assert (destination / "templates" / "README.txt").exists()
    assert (destination / "strategy.py").exists()


@pytest.fixture
def gui_app(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(gui_module, "load_config", lambda: GuiConfig())
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tk is unavailable: {exc}")
    root.withdraw()
    app = CatsAutomaticGui(root)
    root.update_idletasks()
    yield app
    root.destroy()


def test_gui_layout_keeps_visible_scrollable_log(gui_app: CatsAutomaticGui) -> None:
    assert isinstance(gui_app.log, tk.Text)
    assert gui_app.log.winfo_manager() == "grid"
    assert gui_app.log_scrollbar.winfo_manager() == "grid"
    assert len(gui_app.main_paned.panes()) == 2
    assert gui_app.log.cget("background") == "#020617"


def test_append_log_writes_and_scrolls_to_end(gui_app: CatsAutomaticGui) -> None:
    seen: list[str] = []
    gui_app.log.see = lambda index: seen.append(str(index))  # type: ignore[method-assign]

    gui_app.append_log("layout test")

    assert "layout test" in gui_app.log.get("1.0", "end-1c")
    assert seen[-1] == str(tk.END)


def test_clear_and_copy_all_log_do_not_remove_log_widget(
    gui_app: CatsAutomaticGui,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clipboard: list[str] = []
    monkeypatch.setattr(gui_app.root, "clipboard_clear", lambda: clipboard.clear())
    monkeypatch.setattr(gui_app.root, "clipboard_append", clipboard.append)
    gui_app.append_log("copy me")

    gui_app.copy_all_log()
    gui_app.clear_log()

    assert clipboard and "copy me" in clipboard[0]
    assert gui_app.log.get("1.0", "end-1c") == ""
    assert gui_app.log.winfo_exists()


def test_gui_button_groups_keep_scrap_and_existing_buttons(gui_app: CatsAutomaticGui) -> None:
    expected = {
        "废铁一轮测试",
        "废铁循环测试",
        "废铁+胶卷一轮测试",
        "废铁+胶卷循环测试",
        "打开废铁模板目录",
        "检查废铁模板",
        "模拟测试（先用这个）",
        "开始运行",
        "停止",
        "打开关闭按钮模板目录",
        "添加看广告按钮模板",
        "打开最新 run",
        "打开 click_records",
        "打开 summary（结果文件）",
        "打开 diagnosis（诊断报告）",
        "输入/激活卡密",
        "检查授权",
        "清除本地授权",
        "打开错误弹窗模板目录",
        "打开错误弹窗按钮目录",
    }

    assert expected.issubset(gui_app.buttons_by_text)
    assert "授权状态" in gui_app.license_status_var.get()


def test_gui_has_v2_film_shortcut_buttons(gui_app: CatsAutomaticGui) -> None:
    expected = {
        "胶卷 V2 模拟测试",
        "胶卷 V2 真实一轮",
        "打开最后动作截图",
    }

    assert expected.issubset(gui_app.buttons_by_text)


def test_gui_blocks_missing_license(
    gui_app: CatsAutomaticGui,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    errors: list[str] = []
    monkeypatch.delenv("CATS_LICENSE_DEV_BYPASS", raising=False)
    monkeypatch.setattr("tools.catsautomatic_gui.load_license_cache", lambda *_: None)
    monkeypatch.setattr(
        "tools.catsautomatic_gui.messagebox.showerror",
        lambda _title, message: errors.append(message),
    )

    assert gui_app._require_license("ad_reward") is False
    assert errors and "请先输入并激活卡密" in errors[0]


def test_gui_blocks_unlicensed_feature(
    gui_app: CatsAutomaticGui,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = LicenseCache(
        "CATS-ABCD-EFGH",
        "device",
        "token",
        ("ad_reward",),
        "expiry",
        "token-expiry",
        "http://demo",
    )
    monkeypatch.delenv("CATS_LICENSE_DEV_BYPASS", raising=False)
    monkeypatch.setattr("tools.catsautomatic_gui.load_license_cache", lambda *_: cache)
    monkeypatch.setattr(
        "tools.catsautomatic_gui.LicenseClient.heartbeat",
        lambda _self, _cache: LicenseResult(True, "active", "ok", cache=cache),
    )
    monkeypatch.setattr("tools.catsautomatic_gui.messagebox.showerror", lambda *_: None)

    assert gui_app._require_license("scrap_then_ad_reward") is False
    assert "功能未开通" in gui_app.license_status_var.get()


def test_gui_dev_environment_still_respects_cached_test_key_features(
    gui_app: CatsAutomaticGui,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = LicenseCache(
        "CATS-DEV-AD-ONLY",
        "device",
        "local-dev-token",
        ("ad_reward",),
        "expiry",
        "token-expiry",
        "http://demo",
    )
    monkeypatch.setenv("CATS_LICENSE_DEV_BYPASS", "1")
    monkeypatch.setattr("tools.catsautomatic_gui.load_license_cache", lambda *_: cache)
    monkeypatch.setattr(
        "tools.catsautomatic_gui.LicenseClient.heartbeat",
        lambda _self, _cache: LicenseResult(True, "active", "ok", cache=cache),
    )
    monkeypatch.setattr("tools.catsautomatic_gui.messagebox.showerror", lambda *_: None)

    assert gui_app._require_license("scrap_then_ad_reward") is False


def test_gui_v2_strategy_is_allowed_by_ad_reward_license(
    gui_app: CatsAutomaticGui,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = LicenseCache(
        "CATS-DEV-AD-ONLY",
        "device",
        "local-dev-token",
        ("ad_reward",),
        "expiry",
        "token-expiry",
        "http://demo",
    )
    monkeypatch.delenv("CATS_LICENSE_DEV_BYPASS", raising=False)
    monkeypatch.setattr("tools.catsautomatic_gui.load_license_cache", lambda *_: cache)
    monkeypatch.setattr(
        "tools.catsautomatic_gui.LicenseClient.heartbeat",
        lambda _self, _cache: LicenseResult(True, "active", "ok", cache=cache),
    )
    monkeypatch.setattr("tools.catsautomatic_gui.messagebox.showerror", lambda *_: None)

    assert gui_app._require_license(V2_STRATEGY_NAME) is True


def test_gui_applies_v2_flow_status_event(gui_app: CatsAutomaticGui) -> None:
    payload = {
        "event": "flow_status",
        "flow_status": "running",
        "run_id": "run-1",
        "loop": 5,
        "current_step": "WATCH_AD",
        "observed_state": "UNKNOWN",
        "accepted_state": "UNKNOWN",
        "decision": "wait",
        "pending_effect": "waiting_for_watch_ad_film_effect",
        "executed_actions": 2,
        "max_actions": 8,
    }

    gui_app.apply_gui_event(json.dumps(payload))

    text = gui_app.flow_status_var.get()
    assert "run-1" in text
    assert "WATCH_AD" in text
    assert "UNKNOWN" in text
    assert "wait" in text


def test_gui_log_uses_colored_tags(gui_app: CatsAutomaticGui) -> None:
    gui_app.append_log("[循环 1] 可疑：测试异常")

    assert "warning" in gui_app.log.tag_names("1.0")


def test_template_check_warns_when_watch_buttons_empty(
    gui_app: CatsAutomaticGui,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    warnings: list[str] = []
    monkeypatch.setattr("tools.catsautomatic_gui.gui_scrap_templates_dir", lambda: tmp_path / "scrap")
    monkeypatch.setattr("tools.catsautomatic_gui.gui_watch_button_templates_dir", lambda: tmp_path / "watch")
    monkeypatch.setattr("tools.catsautomatic_gui.gui_close_button_templates_dir", lambda: tmp_path / "close")
    monkeypatch.setattr("tools.catsautomatic_gui.gui_pre_watch_optional_dir", lambda: tmp_path / "optional")
    monkeypatch.setattr("tools.catsautomatic_gui.gui_error_popup_templates_dir", lambda: tmp_path / "error_popups")
    monkeypatch.setattr("tools.catsautomatic_gui.gui_error_button_templates_dir", lambda: tmp_path / "error_buttons")
    monkeypatch.setattr("tools.catsautomatic_gui.messagebox.showwarning", lambda _title, message: warnings.append(message))

    gui_app.check_scrap_templates()

    assert warnings
    assert "胶卷看广告按钮模板为空" in warnings[0]
    assert "胶卷看广告按钮模板为空" in gui_app.log.get("1.0", "end-1c")
    assert "error_popups：0 个" in gui_app.log.get("1.0", "end-1c")
    assert "error_buttons：0 个" in gui_app.log.get("1.0", "end-1c")


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

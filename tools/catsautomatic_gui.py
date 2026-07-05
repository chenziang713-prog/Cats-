from __future__ import annotations

import json
import csv
import os
import queue
import subprocess
import sys
import threading
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Callable

import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if SRC_DIR.exists() and str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from cats_automatic.adb_discovery import (
    AdbCandidate,
    discover_adb,
    parse_adb_devices_output,
    preferred_device,
)
from cats_automatic.external_strategy_loader import (
    import_strategy_package,
    list_available_strategies,
)
from cats_automatic.license_client import (
    DEFAULT_LICENSE_SERVER_URL,
    LicenseClient,
    LicenseResult,
    clear_license_cache,
    license_cache_path,
    load_license_cache,
    mask_license_key,
)
from cats_automatic.runtime_paths import (
    close_button_templates_dir as runtime_close_button_templates_dir,
    external_strategies_dir as runtime_external_strategies_dir,
    pre_watch_optional_templates_dir as runtime_pre_watch_optional_templates_dir,
    watch_button_templates_dir as runtime_watch_button_templates_dir,
    error_popup_templates_dir as runtime_error_popup_templates_dir,
    error_button_templates_dir as runtime_error_button_templates_dir,
    scrap_watch_cooldown_templates_dir as runtime_scrap_watch_cooldown_templates_dir,
)
from cats_automatic.display_text import to_display_decision
from cats_automatic.user_ad_reward_templates import (
    add_watch_button_template,
    clear_pre_watch_optional_template,
    set_pre_watch_optional_template,
)
from cats_automatic.user_close_templates import (
    add_close_button_template,
    count_user_close_templates,
)


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_base_dir() -> Path:
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def output_dir(base_dir: Path | None = None) -> Path:
    return (base_dir or app_base_dir()) / "output"


ROOT = app_base_dir()
OUTPUT_DIR = output_dir(ROOT)
CONFIG_PATH = OUTPUT_DIR / "gui_config.json"

def load_latest_decision_record(run_dir: Path) -> str:
    records_path = run_dir / "click_records.csv"
    if records_path.exists():
        with records_path.open(newline="", encoding="utf-8") as handle:
            rows = [row for row in csv.DictReader(handle) if row.get("decision")]
        if rows:
            return str(rows[-1]["decision"])
    journal_path = run_dir / "phase_journal.jsonl"
    if journal_path.exists():
        for line in reversed(journal_path.read_text(encoding="utf-8").splitlines()):
            try:
                decision = json.loads(line).get("chosen_decision")
            except json.JSONDecodeError:
                continue
            if decision:
                return str(decision)
    return ""
DEFAULT_ADB_PATH = r"C:\Program Files\ASUS\GlideX\adb.exe"
SCRAP_REQUIRED_TEMPLATES = (
    "scrap_entry.png",
    "scrap_next_button.png",
    "battle_button.png",
    "skip_button.png",
    "battle_result_popup.png",
    "scrap_watch_ad_button.png",
)


@dataclass
class GuiConfig:
    adb_path: str = DEFAULT_ADB_PATH
    adb_serial: str = "emulator-5556"
    strategy: str = "ad_reward"
    max_actions: str = "8"
    max_loops: str = "999999"
    click_cooldown: str = "1.5"
    interval: str = "1"
    min_click_confidence: str = "0.85"
    repeat_after_reward: bool = True
    cycle_wait_seconds: str = "1800"
    max_cycles: str = "0"
    battle_wait_seconds: str = "60"
    ad_wait_seconds: str = "20"
    stop_file: str = r"output\STOP"
    log_file: str = r"output\real-ad-reward-run.log"
    debug_save_capture: str = r"output\real-ad-reward-capture.png"


def load_config(config_path: Path = CONFIG_PATH) -> GuiConfig:
    if not config_path.exists():
        return GuiConfig()
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return GuiConfig()
    allowed = set(GuiConfig.__dataclass_fields__)
    values = {key: value for key, value in raw.items() if key in allowed}
    values.pop("allow_click", None)
    return GuiConfig(**values)


def save_config(config: GuiConfig, config_path: Path = CONFIG_PATH) -> None:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    data = asdict(config)
    data.pop("allow_click", None)
    config_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def build_main_command(
    config: GuiConfig,
    *,
    allow_click: bool = False,
    dry_run_test: bool = False,
    python_executable: str | None = None,
) -> list[str]:
    command = cli_command_prefix(python_executable)
    command.extend(
        [
        "--game",
        "cats",
        "--strategy",
        config.strategy,
        "--capture-backend",
        "adb",
        "--adb-path",
        config.adb_path,
        "--adb-serial",
        config.adb_serial,
        "--max-actions",
        "2" if dry_run_test else config.max_actions,
        "--max-loops",
        "2" if dry_run_test else config.max_loops,
        "--click-cooldown",
        config.click_cooldown,
        "--interval",
        config.interval,
        "--stop-file",
        config.stop_file,
        "--log-file",
        config.log_file,
        "--debug-save-capture",
        config.debug_save_capture,
        "--min-click-confidence",
        config.min_click_confidence,
        "--battle-wait-seconds",
        config.battle_wait_seconds,
        "--ad-wait-seconds",
        config.ad_wait_seconds,
        ]
    )
    if allow_click and not dry_run_test:
        command.append("--allow-click")
    if config.repeat_after_reward and not dry_run_test:
        command.extend(
            [
                "--repeat-after-reward",
                "--cycle-wait-seconds",
                config.cycle_wait_seconds,
                "--max-cycles",
                config.max_cycles,
            ]
        )
    if (
        os.environ.get("CATS_LICENSE_DEV_BYPASS") == "1"
        and load_license_cache(license_cache_path(ROOT)) is None
    ):
        command.append("--skip-license-check-for-dev")
    return command


def build_scrap_test_command(
    config: GuiConfig,
    *,
    loop_test: bool,
    allow_click: bool = False,
    python_executable: str | None = None,
) -> list[str]:
    test_config = replace(
        config,
        strategy="scrap_ad_battle",
        max_actions="30",
        max_loops="999999" if loop_test else "400",
        click_cooldown="1.5",
        interval="1",
        repeat_after_reward=loop_test,
        cycle_wait_seconds="60",
        max_cycles="2",
        stop_file=r"output\STOP",
        log_file=(
            r"output\real-scrap-ad-loop-test.log"
            if loop_test
            else r"output\real-scrap-ad-test.log"
        ),
        debug_save_capture=(
            r"output\real-scrap-ad-loop-test.png"
            if loop_test
            else r"output\real-scrap-ad-test.png"
        ),
    )
    return build_main_command(
        test_config,
        allow_click=allow_click,
        python_executable=python_executable,
    )


def build_combined_test_command(
    config: GuiConfig,
    *,
    loop_test: bool,
    allow_click: bool = False,
    python_executable: str | None = None,
) -> list[str]:
    test_config = replace(
        config,
        strategy="scrap_then_ad_reward",
        max_actions="60",
        max_loops="999999",
        click_cooldown="1.5",
        interval="1",
        repeat_after_reward=loop_test,
        cycle_wait_seconds="60",
        max_cycles="2",
        stop_file=r"output\STOP",
        log_file=(
            r"output\real-scrap-then-film-loop-test.log"
            if loop_test
            else r"output\real-scrap-then-film-test.log"
        ),
        debug_save_capture=(
            r"output\real-scrap-then-film-loop-test.png"
            if loop_test
            else r"output\real-scrap-then-film-test.png"
        ),
    )
    return build_main_command(
        test_config,
        allow_click=allow_click,
        python_executable=python_executable,
    )


def cli_command_prefix(python_executable: str | None = None) -> list[str]:
    if python_executable is not None:
        return [python_executable, "-m", "cats_automatic.main"]
    if is_frozen():
        return [str(Path(sys.executable).with_name("CATSautomatic-cli.exe"))]
    return [sys.executable, "-m", "cats_automatic.main"]


def build_adb_devices_command(adb_path: str) -> list[str]:
    return [adb_path, "devices"]


def build_screencap_command(adb_path: str, adb_serial: str) -> list[str]:
    return [adb_path, "-s", adb_serial, "exec-out", "screencap", "-p"]


def latest_run_dir(runs_dir: Path = OUTPUT_DIR / "runs") -> Path | None:
    if not runs_dir.exists():
        return None
    candidates = [path for path in runs_dir.iterdir() if path.is_dir()]
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def gui_close_button_templates_dir(base_dir: Path | None = None) -> Path:
    return runtime_close_button_templates_dir(base_dir or ROOT)


def gui_external_strategies_dir(base_dir: Path | None = None) -> Path:
    return runtime_external_strategies_dir(base_dir or ROOT)


def gui_scrap_templates_dir(base_dir: Path | None = None) -> Path:
    return gui_external_strategies_dir(base_dir) / "scrap_ad_battle" / "templates"


def missing_scrap_templates(template_dir: Path) -> list[str]:
    return [name for name in SCRAP_REQUIRED_TEMPLATES if not (template_dir / name).is_file()]


def gui_pre_watch_optional_dir(base_dir: Path | None = None) -> Path:
    return runtime_pre_watch_optional_templates_dir(base_dir or ROOT)


def gui_watch_button_templates_dir(base_dir: Path | None = None) -> Path:
    return runtime_watch_button_templates_dir(base_dir or ROOT)


def gui_error_popup_templates_dir(base_dir: Path | None = None) -> Path:
    return runtime_error_popup_templates_dir(base_dir or ROOT)


def gui_error_button_templates_dir(base_dir: Path | None = None) -> Path:
    return runtime_error_button_templates_dir(base_dir or ROOT)


def copy_close_button_template(source_path: Path, template_dir: Path | None = None) -> Path:
    return add_close_button_template(source_path, template_dir or gui_close_button_templates_dir())


def copy_pre_watch_optional_template(source_path: Path, template_dir: Path | None = None) -> Path:
    return set_pre_watch_optional_template(source_path, template_dir or gui_pre_watch_optional_dir())


def copy_watch_button_template(source_path: Path, template_dir: Path | None = None) -> Path:
    return add_watch_button_template(source_path, template_dir or gui_watch_button_templates_dir())


def gui_strategy_names(base_dir: Path | None = None) -> list[str]:
    return [
        info.strategy_name
        for info in list_available_strategies("cats", base_dir=base_dir or gui_external_strategies_dir())
        if not info.error
    ]


def gui_strategy_choices(base_dir: Path | None = None) -> list[tuple[str, str]]:
    return [
        (info.label, info.strategy_name)
        for info in list_available_strategies(
            "cats",
            base_dir=base_dir or gui_external_strategies_dir(),
        )
        if not info.error
    ]


def update_config_from_adb_candidate(config: GuiConfig, candidate: AdbCandidate) -> GuiConfig:
    device = preferred_device(candidate.devices)
    values = asdict(config)
    values["adb_path"] = str(candidate.adb_path)
    if device is not None:
        values["adb_serial"] = device.serial
    return GuiConfig(**values)


def command_to_text(command: list[str]) -> str:
    return subprocess.list2cmdline(command)


class CatsAutomaticGui:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("CATS自动脚本")
        self.root.geometry("1200x800")
        self.root.minsize(980, 650)
        self.log_queue: queue.Queue[str] = queue.Queue()
        self.process: subprocess.Popen[str] | None = None
        self.active_stop_file: str | None = None
        self.config_vars: dict[str, tk.StringVar | tk.BooleanVar] = {}
        self.allow_click_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="就绪  真实点击需勾选 allow-click 并确认")
        self.current_decision_var = tk.StringVar(value="当前决策：等待下一次识别结果")
        self.dashboard_var = tk.StringVar(value="状态：就绪  |  模式：DRY RUN  |  STOP：未检测")
        self.license_status_var = tk.StringVar(value="授权状态：未激活")
        self.start_button: ttk.Button | None = None
        self.stop_button: ttk.Button | None = None
        self.strategy_combobox: ttk.Combobox | None = None
        self.strategy_display_to_name: dict[str, str] = {}
        self.strategy_name_to_display: dict[str, str] = {}
        self.buttons_by_text: dict[str, ttk.Button] = {}
        self._build_ui(load_config())
        self._refresh_license_status()
        self.set_running(False)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self._poll_log_queue()

    def _build_ui(self, config: GuiConfig) -> None:
        colors = {
            "background": "#0f172a",
            "card": "#1e293b",
            "input": "#020617",
            "text": "#e5e7eb",
            "muted": "#94a3b8",
            "border": "#334155",
            "primary": "#2563eb",
            "success": "#16a34a",
            "warning": "#f59e0b",
            "danger": "#dc2626",
        }
        self.root.configure(background=colors["background"])
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TFrame", background=colors["background"])
        style.configure("Card.TFrame", background=colors["card"])
        style.configure("TLabel", background=colors["background"], foreground=colors["text"])
        style.configure("Title.TLabel", background=colors["card"], foreground=colors["text"], font=("Microsoft YaHei UI", 22, "bold"))
        style.configure("Brand.TLabel", background=colors["card"], foreground="#38bdf8", font=("Microsoft YaHei UI", 13, "bold"))
        style.configure("Dashboard.TLabel", background=colors["card"], foreground=colors["muted"], font=("Microsoft YaHei UI", 10))
        style.configure("Section.TLabelframe", background=colors["card"], bordercolor=colors["border"], relief="solid")
        style.configure("Section.TLabelframe.Label", background=colors["card"], foreground=colors["text"], font=("Microsoft YaHei UI", 10, "bold"))
        style.configure("TButton", background=colors["border"], foreground=colors["text"], padding=(10, 7), borderwidth=0)
        style.map("TButton", background=[("active", "#475569"), ("disabled", "#64748b")])
        style.configure("Primary.TButton", background=colors["primary"], foreground="#ffffff", font=("Microsoft YaHei UI", 10, "bold"))
        style.map("Primary.TButton", background=[("active", "#1d4ed8")])
        style.configure("Success.TButton", background=colors["success"], foreground="#ffffff", font=("Microsoft YaHei UI", 10, "bold"))
        style.configure("Danger.TButton", background=colors["danger"], foreground="#ffffff", font=("Microsoft YaHei UI", 10, "bold"))
        style.map("Danger.TButton", background=[("active", "#b91c1c")])
        style.configure("TEntry", fieldbackground=colors["input"], foreground=colors["text"], insertcolor=colors["text"], bordercolor=colors["border"])
        style.configure("TCombobox", fieldbackground=colors["input"], foreground=colors["text"], arrowcolor=colors["text"])
        style.configure("TCheckbutton", background=colors["card"], foreground=colors["text"])
        style.configure("Status.TLabel", background=colors["card"], foreground=colors["muted"], padding=(10, 7))

        container = ttk.Frame(self.root, padding=14)
        container.pack(fill=tk.BOTH, expand=True)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(1, weight=1)

        header = ttk.Frame(container, padding=(18, 14), style="Card.TFrame")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="CATS自动脚本", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(header, text="POWERED BY 神箭", style="Brand.TLabel").grid(row=1, column=0, sticky="w", pady=(4, 0))
        ttk.Label(
            header,
            text="CATSautomatic v1.4",
            style="Dashboard.TLabel",
        ).grid(row=0, column=1, sticky="e")
        ttk.Label(header, textvariable=self.dashboard_var, style="Dashboard.TLabel").grid(
            row=1, column=1, sticky="e", pady=(4, 0)
        )
        ttk.Label(header, textvariable=self.license_status_var, style="Dashboard.TLabel").grid(
            row=2, column=0, columnspan=2, sticky="ew", pady=(8, 0)
        )

        self.main_paned = tk.PanedWindow(
            container,
            orient=tk.VERTICAL,
            sashrelief=tk.RAISED,
            sashwidth=7,
            bd=0,
            background=colors["border"],
        )
        self.main_paned.grid(row=1, column=0, sticky="nsew", pady=(0, 8))

        config_holder = ttk.Frame(self.main_paned)
        config_holder.columnconfigure(0, weight=1)
        config_holder.rowconfigure(0, weight=1)
        self.config_canvas = tk.Canvas(
            config_holder,
            highlightthickness=0,
            height=300,
            background=colors["background"],
        )
        config_scrollbar = ttk.Scrollbar(
            config_holder,
            orient=tk.VERTICAL,
            command=self.config_canvas.yview,
        )
        self.config_canvas.configure(yscrollcommand=config_scrollbar.set)
        self.config_canvas.grid(row=0, column=0, sticky="nsew")
        config_scrollbar.grid(row=0, column=1, sticky="ns")
        config_content = ttk.Frame(self.config_canvas, padding=(0, 0, 8, 8))
        self.config_canvas_window = self.config_canvas.create_window(
            (0, 0),
            window=config_content,
            anchor="nw",
        )
        config_content.bind(
            "<Configure>",
            lambda _event: self.config_canvas.configure(
                scrollregion=self.config_canvas.bbox("all")
            ),
        )
        self.config_canvas.bind(
            "<Configure>",
            lambda event: self.config_canvas.itemconfigure(
                self.config_canvas_window,
                width=event.width,
            ),
        )
        self.config_canvas.bind("<Enter>", self._enable_config_mousewheel)
        self.config_canvas.bind("<Leave>", self._disable_config_mousewheel)
        config_content.columnconfigure(0, weight=1)
        config_content.columnconfigure(1, weight=1)

        adb_frame = ttk.LabelFrame(config_content, text="ADB 配置", style="Section.TLabelframe", padding=10)
        adb_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 4), pady=(0, 8))
        adb_frame.columnconfigure(1, weight=1)
        self._add_entry(adb_frame, 0, "ADB 路径", "adb_path", config.adb_path, browse=True)
        self._add_entry(adb_frame, 1, "设备 ID", "adb_serial", config.adb_serial)
        self._add_entry(adb_frame, 2, "strategy", "strategy", config.strategy)

        params_frame = ttk.LabelFrame(config_content, text="运行参数", style="Section.TLabelframe", padding=10)
        params_frame.grid(row=0, column=1, sticky="nsew", padx=(4, 0), pady=(0, 8))
        for column in range(4):
            params_frame.columnconfigure(column, weight=1)
        self._add_compact_entry(params_frame, 0, 0, "max-actions", "max_actions", config.max_actions)
        self._add_compact_entry(params_frame, 0, 2, "max-loops", "max_loops", config.max_loops)
        self._add_compact_entry(params_frame, 1, 0, "click-cooldown", "click_cooldown", config.click_cooldown)
        self._add_compact_entry(params_frame, 1, 2, "interval", "interval", config.interval)
        self._add_compact_entry(params_frame, 2, 0, "min-click-confidence", "min_click_confidence", config.min_click_confidence)
        self._add_compact_entry(params_frame, 2, 2, "cycle-wait-seconds", "cycle_wait_seconds", config.cycle_wait_seconds)
        self._add_compact_entry(params_frame, 3, 0, "max-cycles", "max_cycles", config.max_cycles)
        self._add_compact_entry(params_frame, 4, 0, "对战等待秒数", "battle_wait_seconds", config.battle_wait_seconds)
        self._add_compact_entry(params_frame, 4, 2, "广告等待秒数", "ad_wait_seconds", config.ad_wait_seconds)

        repeat_var = tk.BooleanVar(value=config.repeat_after_reward)
        self.config_vars["repeat_after_reward"] = repeat_var
        ttk.Checkbutton(params_frame, text="完成奖励后循环运行", variable=repeat_var).grid(
            row=3, column=2, sticky="w", padx=(8, 4), pady=5
        )
        ttk.Checkbutton(
            params_frame,
            text="allow-click（真实点击，默认关闭）",
            variable=self.allow_click_var,
        ).grid(row=3, column=3, sticky="w", padx=(8, 4), pady=5)

        paths_frame = ttk.LabelFrame(config_content, text="输出与记录", style="Section.TLabelframe", padding=10)
        paths_frame.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        paths_frame.columnconfigure(1, weight=1)
        self._add_entry(paths_frame, 0, "stop-file", "stop_file", config.stop_file)
        self._add_entry(paths_frame, 1, "log-file", "log_file", config.log_file)
        self._add_entry(paths_frame, 2, "debug-save-capture", "debug_save_capture", config.debug_save_capture)

        license_frame = ttk.LabelFrame(
            config_content,
            text="联网授权",
            style="Section.TLabelframe",
            padding=8,
        )
        license_frame.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        for column, (text, command) in enumerate(
            (
                ("输入/激活卡密", self.activate_license),
                ("检查授权", self.check_license),
                ("清除本地授权", self.clear_local_license),
            )
        ):
            license_frame.columnconfigure(column, weight=1)
            button = ttk.Button(license_frame, text=text, command=command)
            button.grid(row=0, column=column, sticky="ew", padx=4, pady=4)
            self.buttons_by_text[text] = button

        groups_frame = ttk.Frame(config_content)
        groups_frame.grid(row=3, column=0, columnspan=2, sticky="ew")
        for column in range(2):
            groups_frame.columnconfigure(column, weight=1)
        self._add_button_group(
            groups_frame,
            0,
            0,
            "基础操作",
            [
                ("自动查找 ADB", self.auto_find_adb, None),
                ("刷新设备列表", self.refresh_devices, None),
                ("检测设备（看设备名的）", self.check_devices, None),
                ("测试截图", self.test_screenshot, None),
                ("打开截图", self.open_gui_screenshot, None),
                ("模拟测试（先用这个）", self.dry_run_test, None),
                ("开始运行", self.start_run, "Primary.TButton"),
                ("停止", self.stop_run, "Danger.TButton"),
            ],
        )
        self._add_button_group(
            groups_frame,
            0,
            1,
            "废铁看广告",
            [
                ("废铁一轮测试", self.scrap_single_test, "Primary.TButton"),
                ("废铁循环测试", self.scrap_loop_test, "Primary.TButton"),
                ("废铁+胶卷一轮测试", self.combined_single_test, "Primary.TButton"),
                ("废铁+胶卷循环测试", self.combined_loop_test, "Primary.TButton"),
                ("打开废铁模板目录", self.open_scrap_templates_dir, None),
                ("检查废铁模板", self.check_scrap_templates, None),
            ],
        )
        self._add_button_group(
            groups_frame,
            1,
            0,
            "广告奖励与模板",
            [
                ("打开关闭按钮模板目录", self.open_close_template_dir, None),
                ("添加关闭按钮模板", self.add_close_template, None),
                ("重新扫描模板", self.reload_close_templates, None),
                ("打开可选点击模板目录", self.open_pre_watch_optional_dir, None),
                ("添加/替换可选点击模板", self.set_pre_watch_optional, None),
                ("清除可选点击模板", self.clear_pre_watch_optional, None),
                ("打开看广告按钮模板目录", self.open_watch_templates_dir, None),
                ("添加看广告按钮模板", self.add_watch_template, None),
                ("打开错误弹窗模板目录", self.open_error_popup_templates_dir, None),
                ("打开错误弹窗按钮目录", self.open_error_button_templates_dir, None),
            ],
        )
        self._add_button_group(
            groups_frame,
            1,
            1,
            "记录与功能包",
            [
                ("打开 output", self.open_output_dir, None),
                ("打开最新 run", self.open_latest_run, None),
                ("打开 click_records", self.open_latest_click_records, None),
                ("打开 summary（结果文件）", self.open_latest_summary, None),
                ("打开 diagnosis（诊断报告）", self.open_latest_diagnosis, None),
                ("打开功能目录", self.open_external_strategies_dir, None),
                ("导入功能包", self.import_external_strategy, None),
                ("刷新功能列表", self.refresh_strategy_list, None),
                ("保存配置", self.save_current_config, None),
            ],
        )

        log_frame = ttk.LabelFrame(
            self.main_paned,
            text="运行日志 / 输出日志",
            style="Section.TLabelframe",
            padding=8,
        )
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(1, weight=1)
        log_toolbar = ttk.Frame(log_frame)
        log_toolbar.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        ttk.Button(log_toolbar, text="清空日志", command=self.clear_log).pack(side=tk.LEFT)
        ttk.Button(log_toolbar, text="复制全部日志", command=self.copy_all_log).pack(
            side=tk.LEFT,
            padx=(8, 0),
        )
        self.log = tk.Text(
            log_frame,
            width=110,
            height=16,
            wrap=tk.WORD,
            background=colors["input"],
            foreground=colors["text"],
            insertbackground=colors["text"],
            selectbackground=colors["primary"],
            relief=tk.FLAT,
            padx=10,
            pady=8,
            font=("Consolas", 10),
        )
        self.log.tag_configure("detect", foreground="#22d3ee")
        self.log.tag_configure("action", foreground="#60a5fa")
        self.log.tag_configure("wait", foreground=colors["muted"])
        self.log.tag_configure("warning", foreground=colors["warning"])
        self.log.tag_configure("error", foreground="#f87171")
        self.log.tag_configure("success", foreground="#4ade80")
        self.log.tag_configure("recovery", foreground="#c084fc")
        self.log_scrollbar = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self.log.yview)
        self.log.configure(yscrollcommand=self.log_scrollbar.set)
        self.log.grid(row=1, column=0, sticky="nsew")
        self.log_scrollbar.grid(row=1, column=1, sticky="ns")
        ttk.Label(log_frame, textvariable=self.current_decision_var, style="Status.TLabel", anchor="w").grid(
            row=2, column=0, columnspan=2, sticky="ew", pady=(6, 0)
        )

        self.main_paned.add(config_holder, minsize=180, stretch="always")
        self.main_paned.add(log_frame, minsize=250, stretch="always")
        self.root.after_idle(self._position_main_pane)

        status = ttk.Label(container, textvariable=self.status_var, style="Status.TLabel", anchor="w")
        status.grid(row=2, column=0, sticky="ew")

    def _add_button_group(
        self,
        parent: ttk.Frame,
        row: int,
        column: int,
        title: str,
        buttons: list[tuple[str, Callable[[], None], str | None]],
    ) -> None:
        frame = ttk.LabelFrame(parent, text=title, style="Section.TLabelframe", padding=8)
        frame.grid(row=row, column=column, sticky="nsew", padx=4, pady=4)
        frame.columnconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)
        for index, (text, command, button_style) in enumerate(buttons):
            button = ttk.Button(
                frame,
                text=text,
                command=command,
                style=button_style or "TButton",
            )
            button.grid(
                row=index // 2,
                column=index % 2,
                padx=4,
                pady=4,
                sticky="ew",
            )
            self.buttons_by_text[text] = button
            if text == "开始运行":
                self.start_button = button
            elif text == "停止":
                self.stop_button = button

    def _position_main_pane(self) -> None:
        self.root.update_idletasks()
        height = self.main_paned.winfo_height()
        if height <= 1:
            return
        config_height = min(max(220, int(height * 0.42)), max(220, height - 250))
        self.main_paned.sash_place(0, 0, config_height)

    def _enable_config_mousewheel(self, _event: tk.Event) -> None:
        self.root.bind_all("<MouseWheel>", self._scroll_config, add="+")

    def _disable_config_mousewheel(self, _event: tk.Event) -> None:
        self.root.unbind_all("<MouseWheel>")

    def _scroll_config(self, event: tk.Event) -> None:
        delta = int(-event.delta / 120) if event.delta else 0
        if delta:
            self.config_canvas.yview_scroll(delta, "units")

    def _add_entry(
        self,
        parent: ttk.Frame,
        row: int,
        label: str,
        key: str,
        value: str,
        *,
        browse: bool = False,
    ) -> None:
        ttk.Label(parent, text=label, anchor="w").grid(row=row, column=0, sticky="w", padx=(0, 8), pady=4)
        var = tk.StringVar(value=value)
        self.config_vars[key] = var
        if key == "strategy":
            choices = gui_strategy_choices()
            self.strategy_display_to_name = dict(choices)
            self.strategy_name_to_display = {name: label for label, name in choices}
            var.set(self.strategy_name_to_display.get(value, value))
            self.strategy_combobox = ttk.Combobox(
                parent,
                textvariable=var,
                values=[label for label, _name in choices],
                state="normal",
            )
            self.strategy_combobox.grid(row=row, column=1, sticky="ew", pady=4)
        else:
            ttk.Entry(parent, textvariable=var).grid(row=row, column=1, sticky="ew", pady=4)
        if browse:
            ttk.Button(parent, text="浏览", command=lambda key=key: self.browse_file(key)).grid(
                row=row, column=2, padx=(8, 0), pady=4
            )

    def _add_compact_entry(
        self,
        parent: ttk.Frame,
        row: int,
        column: int,
        label: str,
        key: str,
        value: str,
    ) -> None:
        ttk.Label(parent, text=label, anchor="w").grid(row=row, column=column, sticky="w", padx=(0, 8), pady=5)
        var = tk.StringVar(value=value)
        self.config_vars[key] = var
        ttk.Entry(parent, textvariable=var, width=18).grid(row=row, column=column + 1, sticky="ew", padx=(0, 16), pady=5)

    def current_config(self) -> GuiConfig:
        values: dict[str, object] = {}
        for key, var in self.config_vars.items():
            value = var.get()
            values[key] = (
                self.strategy_display_to_name.get(str(value), value)
                if key == "strategy"
                else value
            )
        return GuiConfig(**values)

    def browse_file(self, key: str) -> None:
        selected = filedialog.askopenfilename()
        if selected:
            var = self.config_vars[key]
            assert isinstance(var, tk.StringVar)
            var.set(selected)

    def save_current_config(self) -> None:
        save_config(self.current_config())
        self.status_var.set("配置已保存")
        self.append_log(f"配置已保存: {CONFIG_PATH}")

    def validate_adb_inputs(self) -> bool:
        config = self.current_config()
        if not Path(config.adb_path).exists():
            messagebox.showerror("ADB 路径错误", f"ADB 路径不存在:\n{config.adb_path}")
            self.append_log(f"ERROR: ADB 路径不存在: {config.adb_path}")
            return False
        if not config.adb_serial.strip():
            messagebox.showerror("设备 ID 为空", "设备 ID 不能为空。")
            self.append_log("ERROR: 设备 ID 不能为空")
            return False
        return True

    def auto_find_adb(self) -> None:
        self.append_log("开始自动查找 ADB...")

        def worker() -> None:
            result = discover_adb(log=lambda message: self.log_queue.put(message + "\n"))
            self.root.after(0, lambda: self.apply_adb_discovery_result(result.recommended))

        threading.Thread(target=worker, daemon=True).start()

    def apply_adb_discovery_result(self, candidate: AdbCandidate | None) -> None:
        if candidate is None:
            self.append_log("未找到可用 adb.exe，请手动填写 ADB 路径。")
            return
        device = preferred_device(candidate.devices)
        if device is None:
            self.append_log("找到 adb.exe，但 adb devices 未发现 device 状态设备。请确认模拟器已打开。")
            return
        self._set_string_var("adb_path", str(candidate.adb_path))
        self._set_string_var("adb_serial", device.serial)
        save_config(self.current_config())
        self.append_log("已找到可用 ADB:")
        self.append_log(f"ADB 路径: {candidate.adb_path}")
        self.append_log(f"设备 ID: {device.serial}")
        self.append_log("下一步建议: 点击“测试截图”。")

    def refresh_devices(self) -> None:
        config = self.current_config()
        adb_path = Path(config.adb_path)
        if not adb_path.exists():
            self.append_log(f"ERROR: ADB 路径不存在: {adb_path}")
            return
        command = build_adb_devices_command(config.adb_path)
        self.append_log(f"刷新设备列表: {command_to_text(command)}")

        def worker() -> None:
            result = subprocess.run(
                command,
                cwd=ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=5,
            )
            output = (result.stdout or "") + "\n" + (result.stderr or "")
            devices = parse_adb_devices_output(output)
            self.log_queue.put(output)
            self.root.after(0, lambda: self.apply_refreshed_devices(devices))

        threading.Thread(target=worker, daemon=True).start()

    def apply_refreshed_devices(self, devices) -> None:
        device = preferred_device(devices)
        if device is None:
            self.append_log("未发现 device 状态设备；offline/unauthorized 会被忽略。")
            return
        self._set_string_var("adb_serial", device.serial)
        save_config(self.current_config())
        self.append_log(f"已自动填入设备 ID: {device.serial}")

    def check_devices(self) -> None:
        config = self.current_config()
        if not Path(config.adb_path).exists():
            self.append_log(f"ERROR: ADB 路径不存在: {config.adb_path}")
            return
        self.run_command(build_adb_devices_command(config.adb_path), title="检测设备")

    def test_screenshot(self) -> None:
        config = self.current_config()
        if not self.validate_adb_inputs():
            return
        output_path = OUTPUT_DIR / "gui-adb-check.png"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        command = build_screencap_command(config.adb_path, config.adb_serial)
        self.append_log(f"测试截图命令: {command_to_text(command)}")

        def worker() -> None:
            result = subprocess.run(command, cwd=ROOT, capture_output=True)
            if result.returncode == 0 and result.stdout:
                output_path.write_bytes(result.stdout)
                self.log_queue.put(f"截图已保存: {output_path}\n")
                self.open_path(output_path, log_only=True)
            else:
                self.log_queue.put(
                    "截图失败 "
                    f"returncode={result.returncode}\n"
                    f"stdout={result.stdout.decode('utf-8', errors='replace')}\n"
                    f"stderr={result.stderr.decode('utf-8', errors='replace')}\n"
                )

        threading.Thread(target=worker, daemon=True).start()

    def dry_run_test(self) -> None:
        if not self.validate_adb_inputs():
            return
        self.save_current_config()
        config = self.current_config()
        if not self._require_license(config.strategy):
            return
        self.clear_stop_file(config)
        command = build_main_command(config, dry_run_test=True)
        self.start_process(command, "Dry-run 测试")

    def start_run(self) -> None:
        if self.process is not None and self.process.poll() is None:
            self.append_log("已有任务正在运行，不能重复启动。")
            return
        if not self.validate_adb_inputs():
            return
        config = self.current_config()
        if not self._require_license(config.strategy):
            return
        allow_click = bool(self.allow_click_var.get())
        if allow_click and not self.confirm_real_click("开始运行"):
            return
        self.save_current_config()
        config = self.current_config()
        self.clear_stop_file(config)
        command = build_main_command(config, allow_click=allow_click)
        self.start_process(command, "开始运行")

    def scrap_single_test(self) -> None:
        self._start_scrap_test(loop_test=False)

    def scrap_loop_test(self) -> None:
        self._start_scrap_test(loop_test=True)

    def combined_single_test(self) -> None:
        self._start_combined_test(loop_test=False)

    def combined_loop_test(self) -> None:
        self._start_combined_test(loop_test=True)

    def _start_scrap_test(self, *, loop_test: bool) -> None:
        if self.process is not None and self.process.poll() is None:
            self.append_log("已有任务正在运行，不能重复启动。")
            return
        if not self.validate_adb_inputs():
            return
        if not self._require_license("scrap_ad_battle"):
            return
        allow_click = bool(self.allow_click_var.get())
        title = "废铁循环测试" if loop_test else "废铁一轮测试"
        if allow_click and not self.confirm_real_click(title):
            return
        self.save_current_config()
        config = self.current_config()
        self.clear_stop_file(replace(config, stop_file=r"output\STOP"))
        command = build_scrap_test_command(
            config,
            loop_test=loop_test,
            allow_click=allow_click,
        )
        self.append_log(f"正在运行：{title}")
        if loop_test:
            self.append_log("max_cycles=2")
            self.append_log("cycle_wait_seconds=60")
        self.start_process(command, title)

    def _start_combined_test(self, *, loop_test: bool) -> None:
        if self.process is not None and self.process.poll() is None:
            self.append_log("已有任务正在运行，不能重复启动。")
            return
        if not self.validate_adb_inputs():
            return
        if not self._require_license("scrap_then_ad_reward"):
            return
        allow_click = bool(self.allow_click_var.get())
        title = "废铁+胶卷循环测试" if loop_test else "废铁+胶卷一轮测试"
        if allow_click and not self.confirm_real_click(title):
            return
        self.save_current_config()
        config = self.current_config()
        self.clear_stop_file(replace(config, stop_file=r"output\STOP"))
        command = build_combined_test_command(
            config,
            loop_test=loop_test,
            allow_click=allow_click,
        )
        self.append_log(f"正在运行完整流程：{title}")
        self.append_log("废铁完成后将返回主页")
        self.append_log("回主页后执行胶卷广告")
        if loop_test:
            self.append_log("max_cycles=2")
            self.append_log("cycle_wait_seconds=60")
        self.start_process(command, title)

    def activate_license(self) -> None:
        server_url = simpledialog.askstring(
            "授权服务器",
            "请输入授权服务器地址：",
            initialvalue=DEFAULT_LICENSE_SERVER_URL,
            parent=self.root,
        )
        if not server_url:
            return
        license_key = simpledialog.askstring(
            "输入卡密",
            "请输入卡密：",
            show="*",
            parent=self.root,
        )
        if not license_key:
            return
        strategy = self.current_config().strategy
        client = LicenseClient(
            server_url=server_url,
            cache_path=license_cache_path(ROOT),
        )
        self.append_log(f"正在激活卡密：{mask_license_key(license_key)}")
        result = client.activate(license_key, strategy)
        self._apply_license_result(result, show_dialog=True)

    def check_license(self) -> None:
        cache = load_license_cache(license_cache_path(ROOT))
        if cache is None:
            result = LicenseResult(
                False,
                "not_activated",
                "未找到本地授权，请先输入卡密",
                "license_cache_missing",
            )
        else:
            result = LicenseClient(
                server_url=cache.server_url,
                cache_path=license_cache_path(ROOT),
            ).heartbeat(cache)
        self._apply_license_result(result, show_dialog=True)

    def clear_local_license(self) -> None:
        removed = clear_license_cache(license_cache_path(ROOT))
        self.license_status_var.set("授权状态：未激活")
        self.append_log("已清除本地授权。" if removed else "本地没有授权缓存。")

    def _require_license(self, strategy: str) -> bool:
        cache = load_license_cache(license_cache_path(ROOT))
        if cache is None and os.environ.get("CATS_LICENSE_DEV_BYPASS") == "1":
            self.license_status_var.set("授权状态：开发绕过（仅开发环境）")
            return True
        if cache is None:
            message = "授权失败：请先输入并激活卡密。"
            self.append_log(message)
            messagebox.showerror("授权失败", message)
            return False
        result = LicenseClient(
            server_url=cache.server_url,
            cache_path=license_cache_path(ROOT),
        ).heartbeat(cache)
        if not result.ok:
            self._apply_license_result(result, show_dialog=True)
            return False
        if result.cache is None or strategy not in result.cache.features:
            message = f"授权失败：当前卡密未开通 {strategy}。"
            self.append_log(message)
            messagebox.showerror("功能未授权", message)
            self._refresh_license_status(result.cache, status="功能未开通")
            return False
        self._apply_license_result(result, show_dialog=False)
        return True

    def _apply_license_result(self, result: LicenseResult, *, show_dialog: bool) -> None:
        if result.ok and result.cache is not None:
            self._refresh_license_status(result.cache, status="已激活")
            features = " / ".join(self._feature_names(result.cache.features))
            self.append_log(
                f"授权成功，到期时间 {result.cache.expires_at or '未提供'}，功能权限 {features}"
            )
            if show_dialog:
                messagebox.showinfo("授权成功", result.message)
            return
        self.license_status_var.set(f"授权状态：失败 · {result.message}")
        self.append_log(f"授权失败：{result.message}（{result.error}）")
        if show_dialog:
            messagebox.showerror("授权失败", result.message)

    def _refresh_license_status(
        self,
        cache=None,
        *,
        status: str = "本地缓存待检查",
    ) -> None:
        current = cache or load_license_cache(license_cache_path(ROOT))
        if current is None:
            self.license_status_var.set("授权状态：未激活")
            return
        features = " / ".join(self._feature_names(current.features))
        self.license_status_var.set(
            f"授权状态：{status}  |  卡密：{mask_license_key(current.license_key)}  |  "
            f"到期：{current.expires_at or '未提供'}  |  功能：{features}"
        )

    @staticmethod
    def _feature_names(features) -> list[str]:
        mapping = {
            "ad_reward": "胶卷",
            "scrap_ad_battle": "废铁",
            "scrap_then_ad_reward": "废铁+胶卷",
        }
        return [mapping.get(feature, feature) for feature in features]

    def confirm_real_click(self, run_name: str) -> bool:
        confirmed = messagebox.askyesno(
            "确认真实点击",
            f"{run_name} 即将启用真实 ADB 点击（--allow-click）。\n"
            "请确认模拟器界面、坐标和 stop-file 都已准备好。\n\n是否继续？",
        )
        if not confirmed:
            self.append_log("已取消真实点击运行。")
        return confirmed

    def clear_stop_file(self, config: GuiConfig) -> None:
        stop_path = ROOT / config.stop_file
        if stop_path.exists():
            stop_path.unlink()
            self.append_log(f"已清理旧 stop-file: {stop_path}")

    def start_process(self, command: list[str], title: str) -> None:
        if self.process is not None and self.process.poll() is None:
            self.append_log("已有任务正在运行，不能重复启动。")
            return
        self.append_log(f"{title}: {command_to_text(command)}")
        self.active_stop_file = (
            command[command.index("--stop-file") + 1]
            if "--stop-file" in command
            else None
        )
        self.set_running(True)
        try:
            process_env = os.environ.copy()
            process_env.update({"PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"})
            self.process = subprocess.Popen(
                command,
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                env=process_env,
            )
        except OSError as exc:
            self.set_running(False)
            self.append_log(f"启动失败: {exc}")
            return
        threading.Thread(target=self._read_stream, args=(self.process.stdout, "stdout"), daemon=True).start()
        threading.Thread(target=self._read_stream, args=(self.process.stderr, "stderr"), daemon=True).start()
        threading.Thread(target=self._wait_process, daemon=True).start()

    def run_command(self, command: list[str], title: str) -> None:
        self.append_log(f"{title}: {command_to_text(command)}")

        def worker() -> None:
            result = subprocess.run(
                command,
                cwd=ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            self.log_queue.put(f"returncode={result.returncode}\n")
            if result.stdout:
                self.log_queue.put(result.stdout)
            if result.stderr:
                self.log_queue.put(result.stderr)

        threading.Thread(target=worker, daemon=True).start()

    def stop_run(self) -> None:
        config = self.current_config()
        stop_path = ROOT / (self.active_stop_file or config.stop_file)
        stop_path.parent.mkdir(parents=True, exist_ok=True)
        stop_path.write_text("stop requested by GUI\n", encoding="utf-8")
        self.status_var.set("已请求停止")
        self.append_log(f"已请求停止，已创建 STOP 文件: {stop_path}")
        if self.process is not None and self.process.poll() is None:
            self.root.after(5000, self.terminate_if_still_running)

    def terminate_if_still_running(self) -> None:
        if self.process is not None and self.process.poll() is None:
            self.append_log("进程仍在运行，尝试 terminate。")
            self.process.terminate()

    def _read_stream(self, stream, name: str) -> None:
        if stream is None:
            return
        for line in stream:
            if "决策：" in line and "（" in line:
                self.log_queue.put(f"__DECISION__{line.split('决策：', 1)[1].split('（', 1)[0].strip()}")
            self.log_queue.put(f"[{name}] {line}")

    def _wait_process(self) -> None:
        assert self.process is not None
        returncode = self.process.wait()
        self.active_stop_file = None
        self.log_queue.put(f"进程结束 returncode={returncode}\n")
        latest = latest_run_dir()
        if latest is not None:
            self.log_queue.put(f"最新 run 目录: {latest}\n")
            self.log_queue.put(f"最新 click_records.csv: {latest / 'click_records.csv'}\n")
            self.log_queue.put(f"最新 summary.txt: {latest / 'summary.txt'}\n")
            fallback_decision = load_latest_decision_record(latest)
            if fallback_decision:
                self.log_queue.put(f"__DECISION__{to_display_decision(fallback_decision)}")
        self.log_queue.put("__PROCESS_DONE__")

    def _poll_log_queue(self) -> None:
        while True:
            try:
                message = self.log_queue.get_nowait()
            except queue.Empty:
                break
            if message == "__PROCESS_DONE__":
                self.set_running(False)
            elif message.startswith("__DECISION__"):
                self.current_decision_var.set(f"当前决策：{message.removeprefix('__DECISION__')}")
            else:
                self.append_log(message, from_queue=True)
        self.root.after(100, self._poll_log_queue)

    def set_running(self, running: bool) -> None:
        if self.start_button is not None:
            self.start_button.config(state=tk.DISABLED if running else tk.NORMAL)
        self.status_var.set("任务运行中 · 可点击停止创建 stop-file" if running else "就绪 · 默认 dry-run 安全模式")
        mode = "真实点击" if self.allow_click_var.get() else "DRY RUN"
        config = self.current_config()
        stop_value = Path(self.active_stop_file or config.stop_file)
        stop_path = stop_value if stop_value.is_absolute() else ROOT / stop_value
        stop_status = "存在" if stop_path.exists() else "未检测"
        self.dashboard_var.set(
            f"状态：{'运行中' if running else '就绪'}  |  策略：{config.strategy}  |  "
            f"设备：{config.adb_serial or '未设置'}  |  模式：{mode}  |  STOP：{stop_status}"
        )

    def append_log(self, message: str, *, from_queue: bool = False) -> None:
        if not message.endswith("\n"):
            message += "\n"
        tag = self._log_tag(message)
        self.log.insert(tk.END, message, tag)
        self.log.see(tk.END)
        if not from_queue:
            self.root.update_idletasks()

    @staticmethod
    def _log_tag(message: str) -> str:
        lowered = message.lower()
        if "error" in lowered or "失败" in message or "错误" in message:
            return "error"
        if "可疑" in message or "警告" in message or "不足" in message:
            return "warning"
        if "异常恢复" in message or "recovery" in lowered:
            return "recovery"
        if "检测到：" in message or "检测到" in message:
            return "detect"
        if "执行：" in message or "正在运行" in message:
            return "action"
        if "等待：" in message or "wait" in lowered:
            return "wait"
        if "完成" in message or "成功" in message or "已添加" in message:
            return "success"
        return "wait"

    def clear_log(self) -> None:
        self.log.delete("1.0", tk.END)

    def copy_all_log(self) -> None:
        content = self.log.get("1.0", "end-1c")
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(content)
            self.root.update_idletasks()
        except tk.TclError as exc:
            self.append_log(f"复制日志失败: {exc}")
            return
        self.append_log("已复制全部日志。")

    def open_scrap_templates_dir(self) -> None:
        template_dir = gui_scrap_templates_dir()
        template_dir.mkdir(parents=True, exist_ok=True)
        self.append_log(f"废铁模板目录: {template_dir}")
        self.open_path(template_dir)

    def check_scrap_templates(self) -> None:
        template_dir = gui_scrap_templates_dir()
        template_dir.mkdir(parents=True, exist_ok=True)
        missing = missing_scrap_templates(template_dir)
        self.append_log(f"检查废铁模板目录: {template_dir}")
        self.append_log("废铁模板：")
        for filename in SCRAP_REQUIRED_TEMPLATES:
            marker = "✓" if filename not in missing else "⚠"
            self.append_log(f"{marker} {filename}")
        watch_dir = gui_watch_button_templates_dir()
        watch_dir.mkdir(parents=True, exist_ok=True)
        watch_count = len(tuple(watch_dir.glob("*.png")))
        close_dir = gui_close_button_templates_dir()
        close_dir.mkdir(parents=True, exist_ok=True)
        close_count = count_user_close_templates(close_dir)
        optional_count = len(tuple(gui_pre_watch_optional_dir().glob("*.png")))
        error_popup_count = len(tuple(gui_error_popup_templates_dir().glob("*.png")))
        error_button_count = len(tuple(gui_error_button_templates_dir().glob("*.png")))
        cooldown_dir = runtime_scrap_watch_cooldown_templates_dir(ROOT)
        cooldown_count = len(tuple(cooldown_dir.glob("*.png")))
        self.append_log("胶卷模板：")
        self.append_log(f"{'✓' if watch_count else '⚠'} watch_buttons：{watch_count} 个")
        self.append_log(f"✓ close_buttons：{close_count} 个")
        self.append_log(f"✓ pre_watch_optional：{optional_count} 个")
        self.append_log(f"废铁广告冷却模板：{cooldown_count} 个")
        if cooldown_count == 0:
            self.append_log("废铁广告冷却模板为空，将使用按钮区域白色文字检测。如果识别不稳定，可手动添加冷却状态截图模板。")
        self.append_log("错误弹窗模板：")
        self.append_log(f"{'✓' if error_popup_count else '⚠'} error_popups：{error_popup_count} 个")
        self.append_log(f"{'✓' if error_button_count else '⚠'} error_buttons：{error_button_count} 个")
        if error_popup_count == 0 or error_button_count == 0:
            self.append_log("错误弹窗恢复未启用：请添加错误弹窗模板和按钮模板。")
        if watch_count == 0:
            warning = "警告：胶卷看广告按钮模板为空，ad_reward 可能无法识别胶卷页面。"
            self.append_log(warning)
            messagebox.showwarning("模板检查警告", warning)

    def open_close_template_dir(self) -> None:
        template_dir = gui_close_button_templates_dir()
        template_dir.mkdir(parents=True, exist_ok=True)
        self.append_log(f"关闭按钮模板目录: {template_dir}")
        self.open_path(template_dir)

    def open_error_popup_templates_dir(self) -> None:
        template_dir = gui_error_popup_templates_dir()
        self.append_log(f"错误弹窗模板目录: {template_dir}")
        self.open_path(template_dir)

    def open_error_button_templates_dir(self) -> None:
        template_dir = gui_error_button_templates_dir()
        self.append_log(f"错误弹窗按钮模板目录: {template_dir}")
        self.open_path(template_dir)

    def add_close_template(self) -> None:
        selected = filedialog.askopenfilename(
            title="选择关闭按钮 PNG 模板",
            filetypes=[("PNG 图片", "*.png"), ("所有文件", "*.*")],
        )
        if not selected:
            return
        try:
            destination = copy_close_button_template(Path(selected))
        except (OSError, ValueError) as exc:
            messagebox.showerror("添加模板失败", str(exc))
            self.append_log(f"添加关闭按钮模板失败: {exc}")
            return
        self.append_log(f"已添加关闭按钮模板: {destination}")
        self.append_log("提示: 添加模板后请重新 Dry-run 测试；运行中的任务请重新开始后再加载新模板。")

    def reload_close_templates(self) -> None:
        template_dir = gui_close_button_templates_dir()
        count = count_user_close_templates(template_dir)
        self.append_log(f"已扫描用户关闭按钮模板: {count} 个，目录: {template_dir}")
        self.append_log("提示: 如果任务已经在运行，请停止后重新开始以确保使用最新模板。")

    def open_pre_watch_optional_dir(self) -> None:
        template_dir = gui_pre_watch_optional_dir()
        self.append_log(f"可选点击模板目录: {template_dir}")
        self.open_path(template_dir)

    def set_pre_watch_optional(self) -> None:
        selected = filedialog.askopenfilename(
            title="选择可选点击 PNG 模板",
            filetypes=[("PNG 图片", "*.png")],
        )
        if not selected:
            return
        destination = gui_pre_watch_optional_dir() / "optional.png"
        if destination.exists() and not messagebox.askyesno("替换模板", "optional.png 已存在，是否替换？"):
            return
        try:
            destination = copy_pre_watch_optional_template(Path(selected))
        except (OSError, ValueError) as exc:
            messagebox.showerror("设置模板失败", str(exc))
            self.append_log(f"设置可选点击模板失败: {exc}")
            return
        self.append_log(f"已设置可选点击模板: {destination}")

    def clear_pre_watch_optional(self) -> None:
        removed = clear_pre_watch_optional_template(gui_pre_watch_optional_dir())
        self.append_log("已清除可选点击模板。" if removed else "当前没有可选点击模板。")

    def open_watch_templates_dir(self) -> None:
        template_dir = gui_watch_button_templates_dir()
        self.append_log(f"看广告按钮模板目录: {template_dir}")
        self.open_path(template_dir)

    def add_watch_template(self) -> None:
        selected = filedialog.askopenfilename(
            title="选择看广告按钮 PNG 模板",
            filetypes=[("PNG 图片", "*.png")],
        )
        if not selected:
            return
        try:
            destination = copy_watch_button_template(Path(selected))
        except (OSError, ValueError) as exc:
            messagebox.showerror("添加模板失败", str(exc))
            self.append_log(f"添加看广告按钮模板失败: {exc}")
            return
        self.append_log(f"已添加看广告按钮模板: {destination}")

    def open_external_strategies_dir(self) -> None:
        strategies_dir = gui_external_strategies_dir()
        strategies_dir.mkdir(parents=True, exist_ok=True)
        self.append_log(f"功能目录: {strategies_dir}")
        self.open_path(strategies_dir)

    def import_external_strategy(self) -> None:
        messagebox.showinfo("安全提示", "外部 strategy 是 Python 代码，请只导入可信来源的功能包。")
        selected = filedialog.askopenfilename(
            title="选择 strategy zip 功能包；如果要导入文件夹，请取消后选择文件夹",
            filetypes=[("ZIP 功能包", "*.zip"), ("所有文件", "*.*")],
        )
        source: Path | None = Path(selected) if selected else None
        if source is None:
            folder = filedialog.askdirectory(title="选择 strategy 功能包文件夹")
            source = Path(folder) if folder else None
        if source is None:
            return
        try:
            destination = import_strategy_package(source, gui_external_strategies_dir())
        except FileExistsError as exc:
            if not messagebox.askyesno("功能包已存在", f"{exc}\n是否覆盖？"):
                self.append_log("已取消导入功能包。")
                return
            destination = import_strategy_package(source, gui_external_strategies_dir(), overwrite=True)
        except (OSError, ValueError) as exc:
            messagebox.showerror("导入功能包失败", str(exc))
            self.append_log(f"导入功能包失败: {exc}")
            return
        self.append_log(f"已导入功能包: {destination}")
        self.refresh_strategy_list()

    def refresh_strategy_list(self) -> None:
        infos = list_available_strategies("cats", base_dir=gui_external_strategies_dir(), log=self.append_log)
        choices = [(info.label, info.strategy_name) for info in infos if not info.error]
        current_name = self.current_config().strategy
        self.strategy_display_to_name = dict(choices)
        self.strategy_name_to_display = {name: label for label, name in choices}
        if self.strategy_combobox is not None:
            self.strategy_combobox.configure(values=[label for label, _name in choices])
            strategy_var = self.config_vars["strategy"]
            strategy_var.set(self.strategy_name_to_display.get(current_name, current_name))
        self.append_log("已刷新功能列表:")
        for info in infos:
            if info.error:
                self.append_log(f"- {info.strategy_name} 加载失败: {info.error}")
            else:
                self.append_log(f"- {info.label}")

    def _set_string_var(self, key: str, value: str) -> None:
        var = self.config_vars[key]
        assert isinstance(var, tk.StringVar)
        var.set(value)

    def open_output_dir(self) -> None:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        self.open_path(OUTPUT_DIR)

    def open_latest_run(self) -> None:
        latest = latest_run_dir()
        if latest is None:
            self.append_log("没有找到最新 run 目录。")
            return
        self.append_log(f"最新 run 目录: {latest}")
        self.open_path(latest)

    def open_latest_click_records(self) -> None:
        self.open_latest_file("click_records.csv")

    def open_latest_summary(self) -> None:
        self.open_latest_file("summary.txt")

    def open_latest_diagnosis(self) -> None:
        self.open_latest_file("diagnosis.txt")

    def open_latest_file(self, filename: str) -> None:
        latest = latest_run_dir()
        if latest is None:
            self.append_log("没有找到最新 run 目录。")
            return
        target = latest / filename
        if not target.exists():
            self.append_log(f"文件不存在: {target}")
            return
        self.append_log(f"打开文件: {target}")
        self.open_path(target)

    def open_gui_screenshot(self) -> None:
        target = OUTPUT_DIR / "gui-adb-check.png"
        if not target.exists():
            self.append_log(f"截图不存在: {target}")
            return
        self.open_path(target)

    def open_path(self, path: Path, *, log_only: bool = False) -> None:
        if log_only:
            self.log_queue.put(f"打开: {path}\n")
        try:
            os.startfile(path)  # type: ignore[attr-defined]
        except OSError as exc:
            self.append_log(f"打开失败: {exc}")

    def on_close(self) -> None:
        if self.process is not None and self.process.poll() is None:
            should_stop = messagebox.askyesno(
                "任务仍在运行",
                "当前有运行中的任务。是否创建 stop-file 并关闭窗口？",
            )
            if not should_stop:
                return
            self.stop_run()
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    CatsAutomaticGui(root)
    root.mainloop()


if __name__ == "__main__":
    main()

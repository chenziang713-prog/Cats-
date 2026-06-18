from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

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
from cats_automatic.runtime_paths import (
    close_button_templates_dir as runtime_close_button_templates_dir,
    external_strategies_dir as runtime_external_strategies_dir,
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
DEFAULT_ADB_PATH = r"C:\Program Files\ASUS\GlideX\adb.exe"


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
    return command


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


def copy_close_button_template(source_path: Path, template_dir: Path | None = None) -> Path:
    return add_close_button_template(source_path, template_dir or gui_close_button_templates_dir())


def gui_strategy_names(base_dir: Path | None = None) -> list[str]:
    return [
        info.strategy_name
        for info in list_available_strategies("cats", base_dir=base_dir or gui_external_strategies_dir())
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
        self.root.geometry("1120x820")
        self.root.minsize(980, 720)
        self.log_queue: queue.Queue[str] = queue.Queue()
        self.process: subprocess.Popen[str] | None = None
        self.config_vars: dict[str, tk.StringVar | tk.BooleanVar] = {}
        self.allow_click_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="就绪  真实点击需勾选 allow-click 并确认")
        self.start_button: ttk.Button | None = None
        self.stop_button: ttk.Button | None = None
        self.strategy_combobox: ttk.Combobox | None = None
        self._build_ui(load_config())
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self._poll_log_queue()

    def _build_ui(self, config: GuiConfig) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Title.TLabel", font=("Microsoft YaHei UI", 22, "bold"))
        style.configure("Brand.TLabel", font=("Microsoft YaHei UI", 13, "bold"), foreground="#0f766e")
        style.configure("Section.TLabelframe.Label", font=("Microsoft YaHei UI", 10, "bold"))
        style.configure("Primary.TButton", font=("Microsoft YaHei UI", 10, "bold"))
        style.configure("Danger.TButton", font=("Microsoft YaHei UI", 10, "bold"), foreground="#b91c1c")
        style.configure("Status.TLabel", padding=(8, 4), foreground="#475569")

        container = ttk.Frame(self.root, padding=14)
        container.pack(fill=tk.BOTH, expand=True)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(1, weight=1)

        header = ttk.Frame(container, padding=(14, 12))
        header.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="CATS自动脚本", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(header, text="POWERED BY 神箭", style="Brand.TLabel").grid(row=1, column=0, sticky="w", pady=(4, 0))
        ttk.Label(
            header,
            text="CATS广告控制台 ",
            foreground="#64748b",
        ).grid(row=0, column=1, rowspan=2, sticky="e")

        log_frame = ttk.LabelFrame(container, text="日志输出", style="Section.TLabelframe", padding=8)
        log_frame.grid(row=1, column=0, sticky="nsew", pady=(0, 8))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        self.log = scrolledtext.ScrolledText(log_frame, width=110, height=18, wrap=tk.WORD)
        self.log.grid(row=0, column=0, sticky="nsew")

        actions_frame = ttk.LabelFrame(container, text="操作", style="Section.TLabelframe", padding=10)
        actions_frame.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        for column in range(6):
            actions_frame.columnconfigure(column, weight=1)
        buttons: list[tuple[str, Callable[[], None], str | None]] = [
            ("自动查找 ADB", self.auto_find_adb, None),
            ("刷新设备列表", self.refresh_devices, None),
            ("检测设备（看设备名的）", self.check_devices, None),
            ("测试截图", self.test_screenshot, None),
            ("打开截图", self.open_gui_screenshot, None),
            ("模拟测试（先用这个）", self.dry_run_test, None),
            ("开始运行", self.start_run, "Primary.TButton"),
            ("停止", self.stop_run, "Danger.TButton"),
            ("打开 output", self.open_output_dir, None),
            ("打开最新 run", self.open_latest_run, None),
            ("打开 click_records", self.open_latest_click_records, None),
            ("打开 summary（结果文件）", self.open_latest_summary, None),
            ("打开关闭按钮模板目录", self.open_close_template_dir, None),
            ("添加关闭按钮模板", self.add_close_template, None),
            ("重新扫描模板", self.reload_close_templates, None),
            ("打开功能目录", self.open_external_strategies_dir, None),
            ("导入功能包", self.import_external_strategy, None),
            ("刷新功能列表", self.refresh_strategy_list, None),
            ("保存配置", self.save_current_config, None),
            ("清空日志（清屏）", self.clear_log, None),
        ]
        for index, (text, command, button_style) in enumerate(buttons):
            button = ttk.Button(actions_frame, text=text, command=command, style=button_style or "TButton")
            button.grid(row=index // 6, column=index % 6, padx=4, pady=4, sticky="ew")
            if text == "开始运行":
                self.start_button = button
            if text == "停止":
                self.stop_button = button

        adb_frame = ttk.LabelFrame(container, text="ADB 配置", style="Section.TLabelframe", padding=10)
        adb_frame.grid(row=3, column=0, sticky="ew", pady=(0, 8))
        adb_frame.columnconfigure(1, weight=1)
        self._add_entry(adb_frame, 0, "ADB 路径", "adb_path", config.adb_path, browse=True)
        self._add_entry(adb_frame, 1, "设备 ID", "adb_serial", config.adb_serial)
        self._add_entry(adb_frame, 2, "strategy", "strategy", config.strategy)

        params_frame = ttk.LabelFrame(container, text="运行参数", style="Section.TLabelframe", padding=10)
        params_frame.grid(row=4, column=0, sticky="ew", pady=(0, 8))
        for column in range(4):
            params_frame.columnconfigure(column, weight=1)
        self._add_compact_entry(params_frame, 0, 0, "max-actions", "max_actions", config.max_actions)
        self._add_compact_entry(params_frame, 0, 2, "max-loops", "max_loops", config.max_loops)
        self._add_compact_entry(params_frame, 1, 0, "click-cooldown", "click_cooldown", config.click_cooldown)
        self._add_compact_entry(params_frame, 1, 2, "interval", "interval", config.interval)
        self._add_compact_entry(params_frame, 2, 0, "min-click-confidence", "min_click_confidence", config.min_click_confidence)
        self._add_compact_entry(params_frame, 2, 2, "cycle-wait-seconds", "cycle_wait_seconds", config.cycle_wait_seconds)
        self._add_compact_entry(params_frame, 3, 0, "max-cycles", "max_cycles", config.max_cycles)

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

        paths_frame = ttk.LabelFrame(container, text="输出与记录", style="Section.TLabelframe", padding=10)
        paths_frame.grid(row=5, column=0, sticky="ew", pady=(0, 8))
        paths_frame.columnconfigure(1, weight=1)
        self._add_entry(paths_frame, 0, "stop-file", "stop_file", config.stop_file)
        self._add_entry(paths_frame, 1, "log-file", "log_file", config.log_file)
        self._add_entry(paths_frame, 2, "debug-save-capture", "debug_save_capture", config.debug_save_capture)

        status = ttk.Label(container, textvariable=self.status_var, style="Status.TLabel", anchor="w")
        status.grid(row=6, column=0, sticky="ew")

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
            self.strategy_combobox = ttk.Combobox(parent, textvariable=var, values=gui_strategy_names(), state="normal")
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
            values[key] = var.get()
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
        self.clear_stop_file(config)
        command = build_main_command(config, dry_run_test=True)
        self.start_process(command, "Dry-run 测试")

    def start_run(self) -> None:
        if self.process is not None and self.process.poll() is None:
            self.append_log("已有任务正在运行，不能重复启动。")
            return
        if not self.validate_adb_inputs():
            return
        allow_click = bool(self.allow_click_var.get())
        if allow_click:
            confirmed = messagebox.askyesno(
                "确认真实点击",
                "即将启用真实 ADB 点击（--allow-click）。\n"
                "请确认模拟器界面、坐标和 stop-file 都已准备好。\n\n是否继续？",
            )
            if not confirmed:
                self.append_log("已取消真实点击运行。")
                return
        self.save_current_config()
        config = self.current_config()
        self.clear_stop_file(config)
        command = build_main_command(config, allow_click=allow_click)
        self.start_process(command, "开始运行")

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
        self.set_running(True)
        try:
            self.process = subprocess.Popen(
                command,
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
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
        stop_path = ROOT / config.stop_file
        stop_path.parent.mkdir(parents=True, exist_ok=True)
        stop_path.write_text("stop requested by GUI\n", encoding="utf-8")
        self.status_var.set("已请求停止")
        self.append_log(f"已请求停止，stop-file: {stop_path}")
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
            self.log_queue.put(f"[{name}] {line}")

    def _wait_process(self) -> None:
        assert self.process is not None
        returncode = self.process.wait()
        self.log_queue.put(f"进程结束 returncode={returncode}\n")
        latest = latest_run_dir()
        if latest is not None:
            self.log_queue.put(f"最新 run 目录: {latest}\n")
            self.log_queue.put(f"最新 click_records.csv: {latest / 'click_records.csv'}\n")
            self.log_queue.put(f"最新 summary.txt: {latest / 'summary.txt'}\n")
        self.log_queue.put("__PROCESS_DONE__")

    def _poll_log_queue(self) -> None:
        while True:
            try:
                message = self.log_queue.get_nowait()
            except queue.Empty:
                break
            if message == "__PROCESS_DONE__":
                self.set_running(False)
            else:
                self.append_log(message, from_queue=True)
        self.root.after(100, self._poll_log_queue)

    def set_running(self, running: bool) -> None:
        if self.start_button is not None:
            self.start_button.config(state=tk.DISABLED if running else tk.NORMAL)
        self.status_var.set("任务运行中 · 可点击停止创建 stop-file" if running else "就绪 · 默认 dry-run 安全模式")

    def append_log(self, message: str, *, from_queue: bool = False) -> None:
        if not message.endswith("\n"):
            message += "\n"
        self.log.insert(tk.END, message)
        self.log.see(tk.END)
        if not from_queue:
            self.root.update_idletasks()

    def clear_log(self) -> None:
        self.log.delete("1.0", tk.END)

    def open_close_template_dir(self) -> None:
        template_dir = gui_close_button_templates_dir()
        template_dir.mkdir(parents=True, exist_ok=True)
        self.append_log(f"关闭按钮模板目录: {template_dir}")
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
        names = [info.strategy_name for info in infos if not info.error]
        if self.strategy_combobox is not None:
            self.strategy_combobox.configure(values=names)
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

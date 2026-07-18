from __future__ import annotations

import contextlib
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import TextIO


V2_STRATEGY_NAME = "scrap_then_ad_reward_v2"
APP_TITLE = "CATS 胶卷广告 V2"


@dataclass(frozen=True)
class V2ReleaseConfig:
    adb_path: str = ""
    adb_serial: str = ""
    max_loops: str = "300"
    max_actions: str = "8"
    min_click_confidence: str = "0.85"
    click_cooldown: str = "1.5"


def runtime_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def build_v2_strategy_args(config: V2ReleaseConfig, *, real_click: bool) -> list[str]:
    log_name = "v2-real.log" if real_click else "v2-dry-run.log"
    capture_name = "v2-real-capture.png" if real_click else "v2-dry-run-capture.png"
    args = [
        "catsautomatic-v2",
        "--game",
        "cats",
        "--strategy",
        V2_STRATEGY_NAME,
        "--capture-backend",
        "adb",
        "--adb-path",
        config.adb_path,
        "--adb-serial",
        config.adb_serial,
        "--max-loops",
        config.max_loops or "300",
        "--max-actions",
        config.max_actions or "8",
        "--min-click-confidence",
        config.min_click_confidence or "0.85",
        "--click-cooldown",
        config.click_cooldown or "1.5",
        "--stop-file",
        "output/STOP",
        "--log-file",
        f"output/{log_name}",
        "--debug-save-capture",
        f"output/{capture_name}",
    ]
    if real_click:
        args.append("--allow-click")
    return args


def release_authorize_strategy_run(_args: object, _root: Path):
    from cats_automatic.license_client import DEFAULT_LICENSE_SERVER_URL, LicenseCache, LicenseResult

    cache = LicenseCache(
        license_key="V2-RELEASE",
        device_id="release",
        token="",
        features=("ad_reward",),
        expires_at="",
        token_expires_at="",
        server_url=DEFAULT_LICENSE_SERVER_URL,
    )
    return LicenseResult(
        True,
        "release_no_license",
        "V2 发布版免卡密",
        cache=cache,
        event="license_release_bypass",
    ), ReleaseLicenseClient()


class ReleaseLicenseClient:
    def heartbeat(self, cache):
        from cats_automatic.license_client import LicenseResult

        return LicenseResult(
            True,
            "release_no_license",
            "V2 发布版免卡密",
            cache=cache,
            event="license_release_bypass",
        )


def run_v2_strategy_in_process(config: V2ReleaseConfig, *, real_click: bool, output: TextIO) -> int:
    import cats_automatic.main as cats_main

    args = build_v2_strategy_args(config, real_click=real_click)
    old_argv = sys.argv[:]
    old_authorize = cats_main.authorize_strategy_run
    sys.argv = args
    cats_main.authorize_strategy_run = release_authorize_strategy_run
    try:
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            try:
                cats_main.main()
            except SystemExit as exc:
                code = exc.code
                if code is None:
                    return 0
                if isinstance(code, int):
                    return code
                print(code)
                return 1
            return 0
    finally:
        cats_main.authorize_strategy_run = old_authorize
        sys.argv = old_argv


class QueueWriter:
    def __init__(self, target: queue.Queue[str]) -> None:
        self.target = target
        self._buffer = ""

    def write(self, text: str) -> int:
        self._buffer += text
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            self.target.put(line)
        return len(text)

    def flush(self) -> None:
        if self._buffer:
            self.target.put(self._buffer)
            self._buffer = ""


class V2ReleaseGui:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(APP_TITLE)
        self.log_queue: queue.Queue[str] = queue.Queue()
        self.worker: threading.Thread | None = None
        self.config_vars: dict[str, tk.StringVar] = {}
        self.status_var = tk.StringVar(value="就绪：先检测设备，再 dry-run，确认后再真实运行一轮。")
        self._build_ui()
        self.root.after(100, self._poll_log_queue)

    def _build_ui(self) -> None:
        frame = ttk.Frame(self.root, padding=12)
        frame.grid(row=0, column=0, sticky="nsew")
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(3, weight=1)

        ttk.Label(frame, text="胶卷广告 V2 专用版", font=("", 15, "bold")).grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 10)
        )

        fields = [
            ("ADB 路径", "adb_path", ""),
            ("设备 ID", "adb_serial", ""),
            ("最大轮数", "max_loops", "300"),
            ("最大真实动作数", "max_actions", "8"),
            ("最低点击置信度", "min_click_confidence", "0.85"),
            ("动作冷却秒数", "click_cooldown", "1.5"),
        ]
        for index, (label, key, default) in enumerate(fields, start=1):
            ttk.Label(frame, text=label).grid(row=index, column=0, sticky="w", pady=3)
            var = tk.StringVar(value=default)
            self.config_vars[key] = var
            ttk.Entry(frame, textvariable=var).grid(row=index, column=1, sticky="ew", pady=3)
            if key == "adb_path":
                ttk.Button(frame, text="选择", command=self.choose_adb).grid(row=index, column=2, padx=(6, 0))

        actions = ttk.Frame(frame)
        actions.grid(row=7, column=0, columnspan=3, sticky="ew", pady=(10, 8))
        for index in range(4):
            actions.columnconfigure(index, weight=1)
        buttons = [
            ("自动查找 ADB", self.auto_find_adb),
            ("刷新设备", self.refresh_devices),
            ("测试截图", self.test_screenshot),
            ("V2 模拟测试", self.start_dry_run),
            ("V2 真实一轮", self.start_real_run),
            ("停止", self.stop_run),
            ("打开 output", lambda: self.open_path(runtime_root() / "output")),
            ("打开最新 run", self.open_latest_run),
        ]
        for index, (text, command) in enumerate(buttons):
            ttk.Button(actions, text=text, command=command).grid(
                row=index // 4,
                column=index % 4,
                sticky="ew",
                padx=3,
                pady=3,
            )

        template_actions = ttk.Frame(frame)
        template_actions.grid(row=8, column=0, columnspan=3, sticky="ew", pady=(0, 8))
        for index in range(3):
            template_actions.columnconfigure(index, weight=1)
        ttk.Button(
            template_actions,
            text="关闭按钮模板",
            command=lambda: self.open_path(runtime_root() / "user_templates" / "close_buttons"),
        ).grid(row=0, column=0, sticky="ew", padx=3)
        ttk.Button(
            template_actions,
            text="可选奖励模板",
            command=lambda: self.open_path(runtime_root() / "user_templates" / "pre_watch_optional"),
        ).grid(row=0, column=1, sticky="ew", padx=3)
        ttk.Button(
            template_actions,
            text="看广告按钮模板",
            command=lambda: self.open_path(runtime_root() / "user_templates" / "watch_buttons"),
        ).grid(row=0, column=2, sticky="ew", padx=3)

        self.log = tk.Text(frame, height=18, width=92, wrap=tk.WORD)
        self.log.grid(row=9, column=0, columnspan=3, sticky="nsew")
        ttk.Label(frame, textvariable=self.status_var).grid(row=10, column=0, columnspan=3, sticky="ew", pady=(8, 0))

    def current_config(self) -> V2ReleaseConfig:
        return V2ReleaseConfig(**{key: var.get().strip() for key, var in self.config_vars.items()})

    def choose_adb(self) -> None:
        selected = filedialog.askopenfilename(title="选择 adb.exe", filetypes=[("ADB", "adb.exe"), ("EXE", "*.exe")])
        if selected:
            self.config_vars["adb_path"].set(selected)

    def auto_find_adb(self) -> None:
        self.append_log("正在查找 ADB...")
        threading.Thread(target=self._auto_find_adb_worker, daemon=True).start()

    def _auto_find_adb_worker(self) -> None:
        from cats_automatic.adb_discovery import discover_adb, preferred_device

        result = discover_adb(log=self.log_queue.put)
        if result.recommended is None:
            self.log_queue.put("没有找到可用 ADB 设备。")
            return
        device = preferred_device(result.recommended.devices)
        self.root.after(0, lambda: self.config_vars["adb_path"].set(str(result.recommended.adb_path)))
        if device is not None:
            self.root.after(0, lambda: self.config_vars["adb_serial"].set(device.serial))
        self.log_queue.put(f"推荐 ADB：{result.recommended.adb_path}")

    def refresh_devices(self) -> None:
        config = self.current_config()
        if not self._validate_adb_fields(config, need_serial=False):
            return
        result = subprocess.run(
            [config.adb_path, "devices"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        self.append_log(result.stdout or result.stderr or "adb devices 没有输出")

    def test_screenshot(self) -> None:
        config = self.current_config()
        if not self._validate_adb_fields(config):
            return
        output = runtime_root() / "output" / "v2-gui-screenshot.png"
        output.parent.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            [config.adb_path, "-s", config.adb_serial, "exec-out", "screencap", "-p"],
            capture_output=True,
        )
        if result.returncode != 0 or not result.stdout:
            error_text = result.stderr.decode("utf-8", errors="replace") if result.stderr else "截图失败"
            self.append_log(error_text)
            return
        output.write_bytes(result.stdout)
        self.append_log(f"截图已保存：{output}")

    def start_dry_run(self) -> None:
        self._start_run(real_click=False)

    def start_real_run(self) -> None:
        if not messagebox.askyesno(
            "确认真实运行",
            "将执行真实 ADB 点击/返回，只运行胶卷广告 V2 一轮。确认继续？",
        ):
            return
        self._start_run(real_click=True)

    def _start_run(self, *, real_click: bool) -> None:
        if self.worker is not None and self.worker.is_alive():
            messagebox.showwarning("正在运行", "当前任务还在运行，请先停止或等待结束。")
            return
        config = self.current_config()
        if not self._validate_adb_fields(config):
            return
        stop_file = runtime_root() / "output" / "STOP"
        if stop_file.exists():
            stop_file.unlink()
        self.log.delete("1.0", tk.END)
        mode = "真实运行" if real_click else "模拟测试"
        self.status_var.set(f"{mode}启动中...")
        self.worker = threading.Thread(target=self._run_worker, args=(config, real_click), daemon=True)
        self.worker.start()

    def _run_worker(self, config: V2ReleaseConfig, real_click: bool) -> None:
        writer = QueueWriter(self.log_queue)
        code = run_v2_strategy_in_process(config, real_click=real_click, output=writer)
        writer.flush()
        self.log_queue.put(f"任务结束，退出码：{code}")

    def stop_run(self) -> None:
        stop_file = runtime_root() / "output" / "STOP"
        stop_file.parent.mkdir(parents=True, exist_ok=True)
        stop_file.write_text("stop\n", encoding="utf-8")
        self.append_log(f"已创建停止文件：{stop_file}")

    def open_latest_run(self) -> None:
        runs_dir = runtime_root() / "output" / "runs"
        runs = sorted((path for path in runs_dir.glob("*") if path.is_dir()), key=lambda path: path.stat().st_mtime)
        self.open_path(runs[-1] if runs else runs_dir)

    def open_path(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        os.startfile(path)  # type: ignore[attr-defined]

    def _validate_adb_fields(self, config: V2ReleaseConfig, *, need_serial: bool = True) -> bool:
        if not config.adb_path or not Path(config.adb_path).is_file():
            messagebox.showerror("ADB 路径错误", "请先选择有效的 adb.exe。")
            return False
        if need_serial and not config.adb_serial:
            messagebox.showerror("设备 ID 缺失", "请先填写设备 ID，或点击自动查找 ADB。")
            return False
        return True

    def append_log(self, message: str) -> None:
        self.log.insert(tk.END, message.rstrip() + "\n")
        self.log.see(tk.END)

    def _poll_log_queue(self) -> None:
        while True:
            try:
                message = self.log_queue.get_nowait()
            except queue.Empty:
                break
            self.append_log(message)
            if message.startswith("任务结束"):
                self.status_var.set(message)
        self.root.after(100, self._poll_log_queue)


def main() -> None:
    root = tk.Tk()
    V2ReleaseGui(root)
    root.mainloop()


if __name__ == "__main__":
    main()

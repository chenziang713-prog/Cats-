from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
RELEASE_DIR = REPO_ROOT / "CATSautomatic-release"
DIST_DIR = REPO_ROOT / "dist"
BUILD_DIR = REPO_ROOT / "build"


README_TEXT = """CATS自动脚本
POWERED BY 神箭

一、使用前准备
1. 安装并打开模拟器。
2. 确保 adb.exe 可用。
3. 打开 CATSautomatic.exe。
4. 可以点击“自动查找 ADB”自动填写 adb.exe 路径和设备 ID。
5. 也可以手动填写 adb.exe 路径和设备 ID，例如 emulator-5556。

二、如何查看设备 ID
1. 点击 GUI 的“检测设备（看设备名的）”按钮。
2. 或在命令行运行：adb devices。

三、推荐使用顺序
1. 检测设备。
2. 测试截图。
3. 模拟测试（先用这个）。
4. 确认日志和点击记录无误后，勾选 allow-click。
5. 点击开始运行。
6. 在二次确认窗口中确认真实 ADB 点击。

四、如何停止
1. 点击 GUI 的“停止”按钮。
2. 或手动创建 output\\STOP 文件。

五、日志在哪里
每次运行会生成一个 output\\runs\\<run_id>\\ 目录，里面包括：
1. run.log
2. click_records.csv
3. events.jsonl
4. summary.txt
5. screenshots\\
6. debug\\

六、误点后看哪里
1. 点击“打开 click_records”。
2. 找最后一条 action_type=adb_tap 且 result=executed 的记录。
3. 查看 click_x、click_y、confidence、decision、target_name。
4. 根据 screenshot_path 打开对应截图。

七、安全说明
1. 默认不会真实点击。
2. 只有勾选 allow-click 并二次确认后才会真实点击。
3. allow-click 不会保存为默认开启。
4. 仍然需要 CLI 安全限制：只有 --allow-click + --capture-backend adb 才能真实 ADB tap。

八、命令行检查
可运行：
.\\CATSautomatic-cli.exe --help

九、文件说明
1. CATSautomatic.exe：GUI 主程序。
2. CATSautomatic-cli.exe：命令行核心程序，GUI 会调用它。
3. output\\：配置、日志、截图、运行记录输出目录。

十、如何添加新的广告关闭按钮
1. 先截取广告关闭页。
2. 裁剪出关闭按钮小图，保存为 png。
3. 打开软件，点击“添加关闭按钮模板”。
4. 选择 png 图片。
5. 软件会复制到 user_templates\\close_buttons\\。
6. 重新 Dry-run 测试。
7. 确认识别 close_user_xxx 后，再真实运行。

提醒：
1. 图片要裁剪关闭按钮本身，不要整张截图。
2. 图片不要太大。
3. 建议包含按钮图标和少量边缘背景。
4. 如果误识别，删除对应 close-user-xxx.png。

十一、如何自动查找 ADB
1. 打开模拟器。
2. 点击 GUI 的“自动查找 ADB”。
3. 软件会搜索常见模拟器目录，例如雷电、LDPlayer、MuMu、Program Files。
4. 找到 device 状态设备后，会自动填写 ADB 路径和设备 ID。
5. 下一步请点击“测试截图”确认连接正常。
6. 自动查找不会勾选 allow-click，也不会自动真实运行。

十二、如何导入新的 strategy 功能包
1. 功能包放在 external_strategies\\ 下，或点击“导入功能包”选择文件夹/zip。
2. 功能包通常包含 manifest.json、strategy.py、templates\\。
3. 导入后点击“刷新功能列表”。
4. 在 strategy 下拉框中选择新的 strategy 名称。
5. 先 Dry-run 测试，确认日志和 click_records 正常后，再考虑真实运行。
6. 外部 strategy 是 Python 代码，请只导入可信来源。

十三、外部目录说明
1. user_templates\\close_buttons\\：用户新增关闭按钮模板。
2. external_strategies\\：外部 strategy 功能包。
3. 这两个目录不会打进 exe 内部，方便后续直接增删文件。
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Build CATSautomatic Windows release.")
    parser.add_argument("--python", default=str(REPO_ROOT / ".venv" / "Scripts" / "python.exe"))
    args = parser.parse_args()
    python = Path(args.python)
    if not python.exists():
        raise SystemExit(f"Python executable not found: {python}")

    clean()
    run_pyinstaller(python, "CATSautomatic", "tools/catsautomatic_gui.py", windowed=True)
    run_pyinstaller(python, "CATSautomatic-cli", "tools/catsautomatic_cli.py", windowed=False)
    create_release()
    clean_intermediate()
    print(f"Release created: {RELEASE_DIR}")
    print(f"GUI exe: {RELEASE_DIR / 'CATSautomatic.exe'}")
    print(f"CLI exe: {RELEASE_DIR / 'CATSautomatic-cli.exe'}")


def clean() -> None:
    for path in (BUILD_DIR, DIST_DIR, RELEASE_DIR):
        if path.exists():
            shutil.rmtree(path)


def run_pyinstaller(python: Path, name: str, entry: str, *, windowed: bool) -> None:
    command = [
        str(python),
        "-m",
        "PyInstaller",
        "--clean",
        "--onefile",
        "--name",
        name,
        "--paths",
        "src",
        "--collect-submodules",
        "cats_automatic",
        "--collect-data",
        "cats_automatic",
        "--add-data",
        r"src\cats_automatic\games\cats\templates;cats_automatic\games\cats\templates",
    ]
    command.append("--windowed" if windowed else "--console")
    command.append(entry)
    subprocess.run(command, cwd=REPO_ROOT, check=True)


def create_release() -> None:
    RELEASE_DIR.mkdir(parents=True, exist_ok=True)
    (RELEASE_DIR / "output").mkdir(parents=True, exist_ok=True)
    (RELEASE_DIR / "user_templates" / "close_buttons").mkdir(parents=True, exist_ok=True)
    (RELEASE_DIR / "external_strategies").mkdir(parents=True, exist_ok=True)
    shutil.copy2(DIST_DIR / "CATSautomatic.exe", RELEASE_DIR / "CATSautomatic.exe")
    shutil.copy2(DIST_DIR / "CATSautomatic-cli.exe", RELEASE_DIR / "CATSautomatic-cli.exe")
    (RELEASE_DIR / "README使用说明.txt").write_text(README_TEXT, encoding="utf-8")


def clean_intermediate() -> None:
    for path in (BUILD_DIR, DIST_DIR):
        if path.exists():
            shutil.rmtree(path)
    for spec_path in (REPO_ROOT / "CATSautomatic.spec", REPO_ROOT / "CATSautomatic-cli.spec"):
        if spec_path.exists():
            spec_path.unlink()


if __name__ == "__main__":
    main()

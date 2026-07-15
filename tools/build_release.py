from __future__ import annotations

import argparse
import shutil
import subprocess
import zipfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
RELEASE_DIR = REPO_ROOT / "CATSautomatic-release"
RELEASE_ZIP = REPO_ROOT / "CATSautomatic-release-v1.5.zip"
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
1. logs\\run.log
2. click_records.csv
3. events.jsonl
4. summary.txt
5. screenshots\\
6. state_results\\

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
2. user_templates\\pre_watch_optional\\：看广告前可选点击模板，只保留 optional.png。
3. user_templates\\watch_buttons\\：用户新增看广告按钮模板。
4. external_strategies\\：外部 strategy 功能包。
5. 这些目录不会打进 exe 内部，方便后续直接增删文件。

十四、看广告前的可选点击项
1. 如果胶卷页需要先点一个选项，点击“添加/替换可选点击模板”。
2. 软件保存为 user_templates\\pre_watch_optional\\optional.png。
3. 同一个 cycle 最多点击一次；识别不到会自动跳过，不影响看广告按钮。
4. 不再需要时点击“清除可选点击模板”。

十五、添加新的看广告按钮
1. 裁剪新的看广告按钮 png。
2. 点击“添加看广告按钮模板”。
3. 软件保存为 watch-user-001.png、watch-user-002.png 等。
4. 多个看广告按钮同时命中时，选择 confidence 最高的一个。
5. 请先 Dry-run 测试，再开启真实运行。

十六、cycle 完成判定
1. confirm_reward 成功执行时，cycle 正常完成。
2. 如果看广告并关闭广告后直接返回主页，高置信度 ad_entry 也会完成 cycle。
3. summary.txt 可查看 total_cycles_completed、last_cycle_completed_reason 和 next_cycle_scheduled_at。

十七、废铁看广告
1. 在 external_strategies\\scrap_ad_battle\\templates\\ 放入：scrap_entry.png、scrap_next_button.png、battle_button.png、skip_button.png、battle_result_popup.png、scrap_watch_ad_button.png。
2. 游戏停在主页，GUI strategy 选择 scrap_ad_battle。
3. 对战等待秒数默认 60，广告等待秒数默认 20。
4. 先 Dry-run，确认 click_records.csv 坐标后再勾选 allow-click。
5. 看不到 scrap_next_button 或 battle_button 时使用受保护 ADB BACK；识别 battle_result_popup 后再 BACK 一次。
6. scrap_page_marker.png 是可选模板；battle_confirm_button.png 已退出主流程，不再加载，缺失时不会报警。
7. 支持中途接管：主页、废铁页、对战按钮页、跳过页、结果弹窗页、看广告入口页都可启动。
8. 每一步都会先按当前截图恢复进度状态，再执行对应动作；恢复记录写入 events.jsonl 的 state_recovered 事件。
9. 关闭对战结果弹窗后会锁定到等待看广告按钮；同一 cycle 内不会再次点击 battle_button。
10. scrap_watch_ad_button 提前出现时不会点击；必须完成对战、两次跳过、等待和结果弹窗关闭后才会解锁。
11. GUI 可选择“废铁看广告 / scrap_ad_battle”，并设置对战等待秒数（默认 60）和广告等待秒数（默认 20）。
12. 先点击“检查废铁模板”，确认 6 张模板完整，再运行“废铁一轮测试”。
13. 一轮正常后可运行“废铁循环测试”；循环测试固定 cycle_wait_seconds=60、max_cycles=2。
14. 长期运行建议 cycle_wait_seconds=1800、max_cycles=0。
15. 阶段目标连续识别不到 3 次才会小退；第 1、2 次只等待并记录 waiting_for_miss_threshold。
16. 每个阶段最多小退 3 次；已有两次 scrap_next_button 点击记录时，也必须累计 3 次 miss 才小退。广告关闭阶段只等待，不自动小退。
17. 废铁阶段识别到 battle_result_popup 时优先处理：有 confirm_button 就点击确认，没有就 ADB BACK；不会进入 wait_close_ad_not_found。

十八、废铁 + 胶卷广告完整流程
1. GUI 选择“废铁 + 胶卷广告 (scrap_then_ad_reward)”，或点击“废铁+胶卷一轮测试”。
2. 一轮依次执行：废铁对战、废铁看广告、返回主页、胶卷广告奖励。
3. 废铁结束后连续 3 次未检测到主页才 ADB BACK；每次 BACK 后重新计数并检测主页。
4. 最多回退 5 次；仍不到主页时记录 max_back_to_home_attempts_reached 并等待。
5. 到主页后复用已有 ad_reward；胶卷广告完成后才记录 scrap_then_ad_reward_completed。
6. “废铁+胶卷循环测试”默认 cycle_wait_seconds=60、max_cycles=2；长期运行可改为 1800 和 0。
7. ad_entry 置信度低于 0.80 不算主页；battle_result_popup 未关闭前不会开始胶卷广告。
"""

README_TEXT += """

十九、胶卷广告 V2（v1.5）
1. 默认策略为“胶卷广告 V2 / scrap_then_ad_reward_v2”。
2. 第一次请先运行“胶卷 V2 模拟测试”，确认截图、状态和 click_records 正常。
3. “胶卷 V2 真实一轮”会启用 --allow-click，但不会默认无限循环。
4. 正常一轮只需要入口、观看广告、关闭广告和返回键这 4 个真实动作。
5. 程序会拦截连续重复点击；已发送点击后会等待下一帧确认页面变化。
6. 红色真实点击模式表示会发送 ADB tap/keyevent。
7. 点击停止会先创建 output\\STOP，让 CLI 写完 summary 后退出。
8. 可以在 GUI 打开最新运行目录、summary.txt 和最后动作截图。
9. 网络回闪时程序会等待，不会重新点击观看广告。
10. 换电脑运行时，先用“自动查找 ADB”和“刷新设备列表”确认设备。
"""


def copy_external_strategy_package(
    strategy_name: str,
    repo_root: Path = REPO_ROOT,
    release_dir: Path = RELEASE_DIR,
) -> Path | None:
    source = repo_root / "external_strategies" / strategy_name
    if not source.exists():
        return None
    destination = release_dir / "external_strategies" / strategy_name
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        source,
        destination,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns(
            "__pycache__",
            "*.pyc",
            "*.pyo",
            "*.broken-backup",
            "*.tmp",
            "*.tmp.png",
        ),
    )
    return destination


def copy_scrap_strategy_package(
    repo_root: Path = REPO_ROOT,
    release_dir: Path = RELEASE_DIR,
) -> Path | None:
    return copy_external_strategy_package("scrap_ad_battle", repo_root, release_dir)


def copy_combined_strategy_package(
    repo_root: Path = REPO_ROOT,
    release_dir: Path = RELEASE_DIR,
) -> Path | None:
    return copy_external_strategy_package("scrap_then_ad_reward", repo_root, release_dir)


def copy_user_templates(
    repo_root: Path = REPO_ROOT,
    release_dir: Path = RELEASE_DIR,
) -> int:
    source_root = repo_root / "user_templates"
    destination_root = release_dir / "user_templates"
    template_directories = (
        "watch_buttons",
        "close_buttons",
        "pre_watch_optional",
        "error_popups",
        "error_buttons",
        "scrap_watch_cooldown",
    )
    copied = 0
    for directory_name in template_directories:
        source = source_root / directory_name
        destination = destination_root / directory_name
        destination.mkdir(parents=True, exist_ok=True)
        if not source.exists():
            continue
        for path in source.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".bmp", ".webp"}:
                continue
            target = destination / path.relative_to(source)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            copied += 1
    return copied


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
    if RELEASE_ZIP.exists():
        RELEASE_ZIP.unlink()


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
    (RELEASE_DIR / "user_templates" / "pre_watch_optional").mkdir(parents=True, exist_ok=True)
    (RELEASE_DIR / "user_templates" / "watch_buttons").mkdir(parents=True, exist_ok=True)
    (RELEASE_DIR / "user_templates" / "error_popups").mkdir(parents=True, exist_ok=True)
    (RELEASE_DIR / "user_templates" / "error_buttons").mkdir(parents=True, exist_ok=True)
    (RELEASE_DIR / "user_templates" / "scrap_watch_cooldown").mkdir(parents=True, exist_ok=True)
    (RELEASE_DIR / "external_strategies").mkdir(parents=True, exist_ok=True)
    for strategy_name in (
        "scrap_ad_battle",
        "scrap_then_ad_reward",
        "scrap_then_ad_reward_v2",
    ):
        copy_external_strategy_package(strategy_name)
    copy_user_templates()
    shutil.copy2(DIST_DIR / "CATSautomatic.exe", RELEASE_DIR / "CATSautomatic.exe")
    shutil.copy2(DIST_DIR / "CATSautomatic-cli.exe", RELEASE_DIR / "CATSautomatic-cli.exe")
    (RELEASE_DIR / "README使用说明.txt").write_text(README_TEXT, encoding="utf-8")


    create_release_zip()


def create_release_zip(
    release_dir: Path = RELEASE_DIR,
    zip_path: Path = RELEASE_ZIP,
) -> Path:
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in release_dir.rglob("*"):
            if path.is_file():
                archive.write(path, path.relative_to(release_dir.parent))
    return zip_path


def clean_intermediate() -> None:
    for path in (BUILD_DIR, DIST_DIR):
        if path.exists():
            shutil.rmtree(path)
    for spec_path in (REPO_ROOT / "CATSautomatic.spec", REPO_ROOT / "CATSautomatic-cli.spec"):
        if spec_path.exists():
            spec_path.unlink()


if __name__ == "__main__":
    main()

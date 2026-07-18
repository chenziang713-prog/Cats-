from __future__ import annotations

import argparse
import shutil
import subprocess
import zipfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
RELEASE_NAME = "CATSautomaticV2-release"
RELEASE_DIR = REPO_ROOT / RELEASE_NAME
RELEASE_ZIP = REPO_ROOT / "CATSautomaticV2-release-v1.0.zip"
DIST_DIR = REPO_ROOT / "dist"
BUILD_DIR = REPO_ROOT / "build"
V2_STRATEGY_NAME = "scrap_then_ad_reward_v2"

README_TEXT = """CATS 胶卷广告 V2 专用版

这是精简发布版，只保留最新胶卷广告 V2 看广告流程。

使用顺序：
1. 打开模拟器和游戏，停在可进入胶卷广告的界面。
2. 运行 CATSautomaticV2.exe。
3. 点击“自动查找 ADB”，或手动选择 adb.exe 并填写设备 ID。
4. 点击“测试截图”，确认能正常截图。
5. 先点击“V2 模拟测试”，确认日志和 output/runs 中的识别结果正常。
6. 确认无误后再点击“V2 真实一轮”。
7. 如需停止，点击“停止”，程序会创建 output/STOP。

保留功能：
1. 胶卷广告 V2 dry-run。
2. 胶卷广告 V2 真实一轮。
3. ADB 查找、设备刷新和截图测试。
4. 用户模板目录：
   - user_templates/close_buttons
   - user_templates/pre_watch_optional
   - user_templates/watch_buttons
5. output/runs 运行记录。

已去掉：
1. 卡密输入和授权界面。
2. 废铁流程按钮。
3. 旧胶卷/组合流程按钮。
4. strategy 选择、导入功能包等开发入口。
5. 双 EXE 发布结构。

安全说明：
1. 默认请先 dry-run。
2. “V2 真实一轮”会发送真实 ADB tap/keyevent。
3. 真实点击仍受 v2 动作确认、防重复点击、最大动作数和 STOP 文件保护。
4. 发布版免卡密只在 CATSautomaticV2.exe 内生效，不改变开发版主程序。
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Build compact CATSautomatic V2-only Windows release.")
    parser.add_argument("--python", default=str(REPO_ROOT / ".venv" / "Scripts" / "python.exe"))
    args = parser.parse_args()
    python = Path(args.python)
    if not python.exists():
        raise SystemExit(f"Python executable not found: {python}")

    clean()
    run_pyinstaller(python)
    create_release()
    clean_intermediate()
    print(f"Release created: {RELEASE_DIR}")
    print(f"GUI exe: {RELEASE_DIR / 'CATSautomaticV2.exe'}")
    print(f"ZIP: {RELEASE_ZIP}")


def clean() -> None:
    for path in (RELEASE_DIR,):
        if path.exists():
            shutil.rmtree(path)
    if RELEASE_ZIP.exists():
        RELEASE_ZIP.unlink()


def run_pyinstaller(python: Path) -> None:
    command = [
        str(python),
        "-m",
        "PyInstaller",
        "--clean",
        "--onefile",
        "--windowed",
        "--name",
        "CATSautomaticV2",
        "--paths",
        "src",
        "--collect-submodules",
        "cats_automatic",
        "--collect-data",
        "cats_automatic",
        "tools/catsautomatic_v2_release_app.py",
    ]
    subprocess.run(command, cwd=REPO_ROOT, check=True)


def create_release() -> None:
    RELEASE_DIR.mkdir(parents=True, exist_ok=True)
    (RELEASE_DIR / "output").mkdir(parents=True, exist_ok=True)
    for directory in (
        "close_buttons",
        "pre_watch_optional",
        "watch_buttons",
    ):
        (RELEASE_DIR / "user_templates" / directory).mkdir(parents=True, exist_ok=True)
    (RELEASE_DIR / "external_strategies").mkdir(parents=True, exist_ok=True)
    copy_v2_strategy_package(REPO_ROOT, RELEASE_DIR)
    copy_v2_user_templates(REPO_ROOT, RELEASE_DIR)
    shutil.copy2(DIST_DIR / "CATSautomaticV2.exe", RELEASE_DIR / "CATSautomaticV2.exe")
    (RELEASE_DIR / "README使用说明.txt").write_text(README_TEXT, encoding="utf-8")
    create_release_zip(RELEASE_DIR, RELEASE_ZIP)


def copy_v2_strategy_package(repo_root: Path = REPO_ROOT, release_dir: Path = RELEASE_DIR) -> Path:
    source = repo_root / "external_strategies" / V2_STRATEGY_NAME
    if not source.exists():
        raise FileNotFoundError(f"V2 strategy package not found: {source}")
    destination = release_dir / "external_strategies" / V2_STRATEGY_NAME
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


def copy_v2_user_templates(repo_root: Path = REPO_ROOT, release_dir: Path = RELEASE_DIR) -> int:
    copied = 0
    allowed_dirs = ("close_buttons", "pre_watch_optional", "watch_buttons")
    for directory in allowed_dirs:
        source = repo_root / "user_templates" / directory
        destination = release_dir / "user_templates" / directory
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


def create_release_zip(release_dir: Path = RELEASE_DIR, zip_path: Path = RELEASE_ZIP) -> Path:
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
    for spec_path in (REPO_ROOT / "CATSautomaticV2.spec",):
        if spec_path.exists():
            spec_path.unlink()


if __name__ == "__main__":
    main()

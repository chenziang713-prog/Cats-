from __future__ import annotations

import argparse
import hashlib
import shutil
from dataclasses import dataclass, field
from pathlib import Path


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}
SENSITIVE_NAMES = {
    "license_auth.json",
    "gui_config.json",
    "stop",
    "stop.flag",
}
SYNC_DIRECTORIES = (
    (Path("user_templates/watch_buttons"), Path("user_templates/watch_buttons")),
    (Path("user_templates/close_buttons"), Path("user_templates/close_buttons")),
    (
        Path("user_templates/pre_watch_optional"),
        Path("user_templates/pre_watch_optional"),
    ),
    (Path("user_templates/error_popups"), Path("user_templates/error_popups")),
    (Path("user_templates/error_buttons"), Path("user_templates/error_buttons")),
    (Path("user_templates/scrap_watch_cooldown"), Path("user_templates/scrap_watch_cooldown")),
    (
        Path("external_strategies/scrap_ad_battle/templates"),
        Path("external_strategies/scrap_ad_battle/templates"),
    ),
    (
        Path("external_strategies/scrap_then_ad_reward/templates"),
        Path("external_strategies/scrap_then_ad_reward/templates"),
    ),
    (
        Path("external_strategies/scrap_then_ad_reward_v2/templates"),
        Path("external_strategies/scrap_then_ad_reward_v2/templates"),
    ),
)


@dataclass
class DirectorySyncResult:
    source_relative: str
    copied: int = 0
    skipped_same: int = 0
    backed_up: int = 0
    empty: bool = False
    missing: bool = False
    files: list[str] = field(default_factory=list)


@dataclass
class SyncReport:
    release_dir: Path
    project_dir: Path
    apply: bool
    directories: list[DirectorySyncResult]
    license_auth_found: bool
    license_auth_copied: bool = False

    @property
    def total_copied(self) -> int:
        return sum(item.copied for item in self.directories)

    @property
    def total_skipped(self) -> int:
        return sum(item.skipped_same for item in self.directories)

    @property
    def total_backed_up(self) -> int:
        return sum(item.backed_up for item in self.directories)


def default_desktop_roots() -> list[Path]:
    roots = {Path.home() / "Desktop"}
    users_root = Path("C:/Users")
    if users_root.exists():
        roots.update(path / "Desktop" for path in users_root.iterdir() if path.is_dir())
    return sorted(roots, key=lambda path: str(path).lower())


def discover_latest_release(desktop_roots: list[Path] | None = None) -> Path | None:
    candidates: list[Path] = []
    for desktop in desktop_roots or default_desktop_roots():
        try:
            exists = desktop.exists()
        except OSError:
            continue
        if not exists:
            continue
        try:
            candidates.extend(
                path
                for path in desktop.glob("CATSautomatic-release*")
                if path.is_dir()
            )
        except OSError:
            continue
    if not candidates:
        return None
    readable = []
    for path in candidates:
        try:
            readable.append((path.stat().st_mtime, path))
        except OSError:
            continue
    return None if not readable else max(readable, key=lambda item: item[0])[1]


def sync_release_templates(
    release_dir: Path,
    project_dir: Path,
    *,
    apply: bool = False,
) -> SyncReport:
    release = Path(release_dir).resolve()
    project = Path(project_dir).resolve()
    results: list[DirectorySyncResult] = []
    for source_relative, destination_relative in SYNC_DIRECTORIES:
        results.append(
            _sync_image_directory(
                release / source_relative,
                project / destination_relative,
                source_relative,
                apply=apply,
            )
        )
    results.append(_sync_template_configs(release / "config", project / "config", apply=apply))
    license_path = release / "config" / "license_auth.json"
    return SyncReport(
        release_dir=release,
        project_dir=project,
        apply=apply,
        directories=results,
        license_auth_found=license_path.exists(),
    )


def format_report(report: SyncReport) -> str:
    mode = "实际同步" if report.apply else "Dry-run 预览"
    lines = [
        f"========== 模板同步报告（{mode}）==========",
        f"桌面 release：{report.release_dir}",
        f"源码项目：{report.project_dir}",
        "",
    ]
    for item in report.directories:
        if item.missing:
            lines.append(f"[不存在] {item.source_relative}")
        elif item.empty:
            lines.append(f"[空目录] {item.source_relative}")
        else:
            lines.append(
                f"[{item.source_relative}] 复制={item.copied} "
                f"重复跳过={item.skipped_same} 备份旧文件={item.backed_up}"
            )
    lines.extend(
        [
            "",
            f"合计：复制={report.total_copied} 重复跳过={report.total_skipped} "
            f"备份={report.total_backed_up}",
            f"发现 license_auth.json：{'是' if report.license_auth_found else '否'}",
            "license_auth.json 已复制：否（安全排除）",
            "output / runs / STOP / 日志 / token / 设备绑定缓存：均未复制",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="从桌面 release 同步模板回源码项目。")
    parser.add_argument("--release-dir", type=Path, default=None)
    parser.add_argument("--project-dir", type=Path, default=Path(__file__).resolve().parents[1])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="只预览，不复制（默认）。")
    mode.add_argument("--apply", action="store_true", help="实际复制模板。")
    args = parser.parse_args()
    release_dir = args.release_dir or discover_latest_release()
    if release_dir is None:
        raise SystemExit("未在桌面找到 CATSautomatic-release* 文件夹。")
    report = sync_release_templates(
        release_dir,
        args.project_dir,
        apply=args.apply,
    )
    print(format_report(report))


def _sync_image_directory(
    source: Path,
    destination: Path,
    source_relative: Path,
    *,
    apply: bool,
) -> DirectorySyncResult:
    result = DirectorySyncResult(str(source_relative).replace("/", "\\"))
    if not source.exists():
        result.missing = True
        return result
    images = sorted(
        path for path in source.rglob("*") if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
    )
    if not images:
        result.empty = True
        return result
    for source_file in images:
        relative = source_file.relative_to(source)
        target = destination / relative
        _sync_file(source_file, target, result, apply=apply)
    return result


def _sync_template_configs(source: Path, destination: Path, *, apply: bool) -> DirectorySyncResult:
    result = DirectorySyncResult("config（仅模板相关配置）")
    if not source.exists():
        result.missing = True
        return result
    configs = sorted(
        path
        for path in source.rglob("*")
        if path.is_file()
        and "template" in path.stem.lower()
        and path.suffix.lower() in {".json", ".yaml", ".yml", ".toml"}
        and not _is_sensitive(path)
    )
    if not configs:
        result.empty = True
        return result
    for source_file in configs:
        _sync_file(source_file, destination / source_file.relative_to(source), result, apply=apply)
    return result


def _sync_file(
    source: Path,
    target: Path,
    result: DirectorySyncResult,
    *,
    apply: bool,
) -> None:
    if _is_sensitive(source):
        return
    if target.exists() and _sha256(source) == _sha256(target):
        result.skipped_same += 1
        return
    if target.exists():
        result.backed_up += 1
        if apply:
            backup = _backup_path(target)
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, backup)
    result.copied += 1
    result.files.append(str(target))
    if apply:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _backup_path(path: Path) -> Path:
    candidate = path.with_name(path.name + ".bak")
    index = 1
    while candidate.exists():
        candidate = path.with_name(f"{path.name}.bak.{index}")
        index += 1
    return candidate


def _is_sensitive(path: Path) -> bool:
    lowered = path.name.lower()
    return (
        lowered in SENSITIVE_NAMES
        or "license" in lowered
        or "token" in lowered
        or "device_binding" in lowered
        or "auth" in lowered
    )


if __name__ == "__main__":
    main()

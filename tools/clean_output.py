from __future__ import annotations

import argparse
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "output"
DEFAULT_KEEP_LAST = 3


@dataclass(frozen=True)
class RunDirectory:
    path: Path
    modified_time: float


@dataclass(frozen=True)
class CleanupPlan:
    runs_dir: Path
    archive_dir: Path
    keep: list[RunDirectory]
    archive: list[RunDirectory]
    delete: list[RunDirectory]
    dry_run: bool
    mode: str


def plan_cleanup(
    *,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    keep_last: int = DEFAULT_KEEP_LAST,
    dry_run: bool = True,
    mode: str = "archive",
) -> CleanupPlan:
    if keep_last < 0:
        raise ValueError("keep_last must be >= 0")
    if mode not in {"archive", "delete"}:
        raise ValueError("mode must be 'archive' or 'delete'")

    output_root = output_root.resolve()
    runs_dir = output_root / "runs"
    archive_dir = output_root / "archive" / "old_runs"
    ensure_safe_output_root(output_root)

    runs = list_run_dirs(runs_dir)
    keep = runs[:keep_last]
    old = runs[keep_last:]
    return CleanupPlan(
        runs_dir=runs_dir,
        archive_dir=archive_dir,
        keep=keep,
        archive=old if mode == "archive" else [],
        delete=old if mode == "delete" else [],
        dry_run=dry_run,
        mode=mode,
    )


def execute_cleanup(plan: CleanupPlan) -> None:
    print_plan(plan)
    if plan.dry_run:
        print("dry-run：未执行任何移动或删除。")
        print_remaining_dirs(plan.runs_dir)
        return

    for run in plan.archive:
        ensure_safe_run_dir(run.path, plan.runs_dir)
        plan.archive_dir.mkdir(parents=True, exist_ok=True)
        destination = unique_destination(plan.archive_dir / run.path.name)
        shutil.move(str(run.path), str(destination))
        print(f"已归档：{run.path} -> {destination}")

    for run in plan.delete:
        ensure_safe_run_dir(run.path, plan.runs_dir)
        shutil.rmtree(run.path)
        print(f"已删除：{run.path}")

    print_remaining_dirs(plan.runs_dir)


def list_run_dirs(runs_dir: Path) -> list[RunDirectory]:
    if not runs_dir.exists():
        return []
    ensure_safe_runs_dir(runs_dir)
    runs: list[RunDirectory] = []
    for path in runs_dir.iterdir():
        if not path.is_dir() or path.is_symlink():
            continue
        ensure_safe_run_dir(path, runs_dir)
        runs.append(RunDirectory(path=path.resolve(), modified_time=path.stat().st_mtime))
    return sorted(runs, key=lambda item: (item.modified_time, item.path.name), reverse=True)


def ensure_output_layout(output_root: Path = DEFAULT_OUTPUT_ROOT, *, dry_run: bool = True) -> None:
    output_root = output_root.resolve()
    ensure_safe_output_root(output_root)
    directories = [
        output_root / "runs",
        output_root / "latest",
        output_root / "archive" / "old_runs",
    ]
    for directory in directories:
        if dry_run:
            print(f"dry-run：将确保目录存在：{directory}")
        else:
            directory.mkdir(parents=True, exist_ok=True)
            print(f"已确保目录存在：{directory}")


def ensure_safe_output_root(output_root: Path) -> None:
    project_root = REPO_ROOT.resolve()
    output_root = output_root.resolve()
    if output_root == project_root:
        raise ValueError("拒绝把项目根目录当作 output_root。")
    forbidden = {
        "src",
        "tools",
        "tests",
        "templates",
        "user_templates",
        "config",
        "configs",
        "samples",
        "external_strategies",
        "docs",
    }
    if output_root.name in forbidden:
        raise ValueError(f"拒绝把核心目录当作 output_root：{output_root}")
    if not output_root.is_relative_to(project_root) and output_root.name != "output":
        raise ValueError(f"项目外路径必须明确指向 output 目录：{output_root}")


def ensure_safe_runs_dir(runs_dir: Path) -> None:
    runs_dir = runs_dir.resolve()
    expected_parent = runs_dir.parent
    ensure_safe_output_root(expected_parent)
    if runs_dir.name != "runs":
        raise ValueError(f"拒绝处理非 runs 目录：{runs_dir}")


def ensure_safe_run_dir(run_dir: Path, runs_dir: Path) -> None:
    run_dir = run_dir.resolve()
    runs_dir = runs_dir.resolve()
    ensure_safe_runs_dir(runs_dir)
    if run_dir == runs_dir or not run_dir.is_relative_to(runs_dir):
        raise ValueError(f"拒绝处理 runs 目录外路径：{run_dir}")
    if run_dir.parent != runs_dir:
        raise ValueError(f"拒绝处理非 runs 直接子目录：{run_dir}")
    if run_dir.name in {"latest", "archive", "old_runs"}:
        raise ValueError(f"拒绝处理保留目录名：{run_dir}")


def unique_destination(destination: Path) -> Path:
    if not destination.exists():
        return destination
    index = 2
    while True:
        candidate = destination.with_name(f"{destination.name}-{index}")
        if not candidate.exists():
            return candidate
        index += 1


def print_plan(plan: CleanupPlan) -> None:
    print(f"runs 目录：{plan.runs_dir}")
    print(f"归档目录：{plan.archive_dir}")
    print(f"模式：{plan.mode}")
    print(f"dry-run：{str(plan.dry_run).lower()}")
    print("清理前将处理的目录清单：")
    if not plan.keep and not plan.archive and not plan.delete:
        print("  无 runs 目录或无运行记录。")
    for run in plan.keep:
        print(f"  保留：{run.path}")
    for run in plan.archive:
        print(f"  将归档：{run.path}")
    for run in plan.delete:
        print(f"  将删除：{run.path}")


def print_remaining_dirs(runs_dir: Path) -> None:
    print("清理后剩余 runs 目录清单：")
    remaining = list_run_dirs(runs_dir)
    if not remaining:
        print("  无运行记录。")
        return
    for run in remaining:
        print(f"  {run.path}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Safely clean old CATSautomatic output runs.")
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--keep-last", type=int, default=DEFAULT_KEEP_LAST)
    parser.add_argument(
        "--mode",
        choices=["archive", "delete"],
        default="archive",
        help="archive moves old runs to output/archive/old_runs; delete removes them.",
    )
    parser.add_argument("--apply", action="store_true", help="Actually move/delete old runs.")
    parser.add_argument(
        "--ensure-layout",
        action="store_true",
        help="Create output/runs, output/latest, and output/archive/old_runs when used with --apply.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    dry_run = not args.apply
    if args.ensure_layout:
        ensure_output_layout(args.output_root, dry_run=dry_run)
    plan = plan_cleanup(
        output_root=args.output_root,
        keep_last=args.keep_last,
        dry_run=dry_run,
        mode=args.mode,
    )
    execute_cleanup(plan)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

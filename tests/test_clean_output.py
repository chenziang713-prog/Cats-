from __future__ import annotations

from pathlib import Path
import os

import pytest

from tools import clean_output
from tools.clean_output import execute_cleanup, plan_cleanup
from cats_automatic.run_recording import RunRecorder


def test_plan_cleanup_keeps_latest_three_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(clean_output, "REPO_ROOT", tmp_path)
    output = tmp_path / "output"
    runs = output / "runs"
    for index in range(5):
        run = runs / f"20260628-12000{index}"
        run.mkdir(parents=True)
        (run / "summary.txt").write_text(str(index), encoding="utf-8")
        os.utime(run, (100 + index, 100 + index))

    plan = plan_cleanup(output_root=output, keep_last=3, dry_run=True)

    assert [item.path.name for item in plan.keep] == [
        "20260628-120004",
        "20260628-120003",
        "20260628-120002",
    ]
    assert [item.path.name for item in plan.archive] == [
        "20260628-120001",
        "20260628-120000",
    ]


def test_dry_run_does_not_move_old_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(clean_output, "REPO_ROOT", tmp_path)
    output = tmp_path / "output"
    old_run = output / "runs" / "old"
    new_run = output / "runs" / "new"
    old_run.mkdir(parents=True)
    new_run.mkdir(parents=True)
    os.utime(old_run, (100, 100))
    os.utime(new_run, (200, 200))

    plan = plan_cleanup(output_root=output, keep_last=1, dry_run=True)
    execute_cleanup(plan)

    assert old_run.exists()
    assert not (output / "archive" / "old_runs" / "old").exists()


def test_apply_archives_old_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(clean_output, "REPO_ROOT", tmp_path)
    output = tmp_path / "output"
    old_run = output / "runs" / "old"
    new_run = output / "runs" / "new"
    old_run.mkdir(parents=True)
    new_run.mkdir(parents=True)
    os.utime(old_run, (100, 100))
    os.utime(new_run, (200, 200))

    plan = plan_cleanup(output_root=output, keep_last=1, dry_run=False)
    execute_cleanup(plan)

    assert not old_run.exists()
    assert new_run.exists()
    assert (output / "archive" / "old_runs" / "old").exists()


def test_refuses_core_directory_as_output_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(clean_output, "REPO_ROOT", tmp_path)
    with pytest.raises(ValueError, match="核心目录"):
        plan_cleanup(output_root=tmp_path / "templates", keep_last=3)


def test_external_output_root_is_allowed_when_named_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = tmp_path / "project"
    external = tmp_path / "other_copy" / "output"
    monkeypatch.setattr(clean_output, "REPO_ROOT", project)
    (external / "runs" / "old").mkdir(parents=True)

    plan = plan_cleanup(output_root=external, keep_last=0)

    assert plan.archive[0].path == (external / "runs" / "old").resolve()


def test_external_non_output_root_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = tmp_path / "project"
    monkeypatch.setattr(clean_output, "REPO_ROOT", project)

    with pytest.raises(ValueError, match="必须明确指向 output"):
        plan_cleanup(output_root=tmp_path / "other_copy")


def test_run_recorder_uses_structured_output_layout(tmp_path: Path) -> None:
    recorder = RunRecorder(output_root=tmp_path / "output" / "runs", capture_backend="replay")
    recorder.record_detections(1, {})
    summary = recorder.finish("test_done")

    assert summary.run_dir.parent == tmp_path / "output" / "runs"
    assert (summary.run_dir / "screenshots").exists()
    assert (summary.run_dir / "logs" / "run.log").exists()
    assert (summary.run_dir / "state_results" / "loop-001-detections.json").exists()
    assert (tmp_path / "output" / "latest" / "summary.txt").exists()
    assert (tmp_path / "output" / "latest" / "run_id.txt").read_text(encoding="utf-8").strip()

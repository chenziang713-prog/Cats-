from __future__ import annotations

import os
from pathlib import Path

from tools.build_release import (
    copy_external_strategy_package,
    copy_combined_strategy_package,
    copy_scrap_strategy_package,
    copy_user_templates,
)
from tools.sync_release_templates import (
    discover_latest_release,
    sync_release_templates,
)


def test_discovers_latest_desktop_release(tmp_path: Path) -> None:
    desktop = tmp_path / "Desktop"
    older = desktop / "CATSautomatic-release-v1.6"
    newer = desktop / "CATSautomatic-release-v1.7"
    older.mkdir(parents=True)
    newer.mkdir()
    os.utime(older, (100, 100))
    os.utime(newer, (200, 200))

    assert discover_latest_release([desktop]) == newer


def test_syncs_all_allowed_template_directories(tmp_path: Path) -> None:
    release = tmp_path / "release"
    project = tmp_path / "project"
    expected = {
        "user_templates/watch_buttons/watch.png",
        "user_templates/close_buttons/close.jpg",
        "user_templates/pre_watch_optional/optional.webp",
        "user_templates/error_popups/error.png",
        "user_templates/error_buttons/ok.bmp",
        "external_strategies/scrap_ad_battle/templates/battle.png",
        "external_strategies/scrap_then_ad_reward/templates/combined.jpeg",
        "external_strategies/scrap_then_ad_reward_v2/templates/user_templates/pre_watch_optional/optional.png",
    }
    for relative in expected:
        _write(release / relative, relative.encode())

    report = sync_release_templates(release, project, apply=True)

    assert report.total_copied == len(expected)
    assert all((project / relative).exists() for relative in expected)


def test_does_not_copy_output_or_license_cache(tmp_path: Path) -> None:
    release = tmp_path / "release"
    project = tmp_path / "project"
    _write(release / "output/runs/run/events.jsonl", b"secret")
    _write(release / "config/license_auth.json", b'{"token":"secret"}')
    _write(release / "config/template_settings.json", b'{"template":"ok"}')

    report = sync_release_templates(release, project, apply=True)

    assert not (project / "output").exists()
    assert not (project / "config/license_auth.json").exists()
    assert (project / "config/template_settings.json").exists()
    assert report.license_auth_found is True
    assert report.license_auth_copied is False


def test_same_hash_is_skipped(tmp_path: Path) -> None:
    release = tmp_path / "release"
    project = tmp_path / "project"
    source = release / "user_templates/close_buttons/close.png"
    target = project / "user_templates/close_buttons/close.png"
    _write(source, b"same")
    _write(target, b"same")

    report = sync_release_templates(release, project, apply=True)

    assert report.total_skipped == 1
    assert report.total_copied == 0
    assert not target.with_name("close.png.bak").exists()


def test_different_hash_backs_up_then_replaces(tmp_path: Path) -> None:
    release = tmp_path / "release"
    project = tmp_path / "project"
    source = release / "user_templates/watch_buttons/watch.png"
    target = project / "user_templates/watch_buttons/watch.png"
    _write(source, b"new")
    _write(target, b"old")

    report = sync_release_templates(release, project, apply=True)

    assert report.total_backed_up == 1
    assert target.read_bytes() == b"new"
    assert target.with_name("watch.png.bak").read_bytes() == b"old"


def test_dry_run_does_not_copy_or_backup(tmp_path: Path) -> None:
    release = tmp_path / "release"
    project = tmp_path / "project"
    source = release / "user_templates/error_popups/error.png"
    target = project / "user_templates/error_popups/error.png"
    _write(source, b"new")
    _write(target, b"old")

    report = sync_release_templates(release, project, apply=False)

    assert report.total_copied == 1
    assert report.total_backed_up == 1
    assert target.read_bytes() == b"old"
    assert not target.with_name("error.png.bak").exists()


def test_build_release_copies_user_and_strategy_templates(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    release = tmp_path / "release"
    _write(repo / "user_templates/watch_buttons/watch.png", b"watch")
    _write(repo / "user_templates/error_buttons/ok.png", b"ok")
    _write(repo / "external_strategies/scrap_ad_battle/templates/battle.png", b"battle")
    _write(repo / "external_strategies/scrap_then_ad_reward/templates/combined.png", b"combined")
    _write(repo / "external_strategies/scrap_then_ad_reward_v2/templates/user_templates/pre_watch_optional/optional.png", b"v2")
    _write(repo / "external_strategies/scrap_then_ad_reward_v2/film_flow.py.broken-backup", b"old")
    _write(repo / "external_strategies/scrap_then_ad_reward_v2/__pycache__/strategy.pyc", b"cache")
    _write(repo / "config/license_auth.json", b"secret")

    copied = copy_user_templates(repo, release)
    copy_scrap_strategy_package(repo, release)
    copy_combined_strategy_package(repo, release)
    copy_external_strategy_package("scrap_then_ad_reward_v2", repo, release)

    assert copied == 2
    assert (release / "user_templates/watch_buttons/watch.png").exists()
    assert (release / "user_templates/error_buttons/ok.png").exists()
    assert (release / "external_strategies/scrap_ad_battle/templates/battle.png").exists()
    assert (release / "external_strategies/scrap_then_ad_reward/templates/combined.png").exists()
    assert (
        release / "external_strategies/scrap_then_ad_reward_v2/templates/user_templates/pre_watch_optional/optional.png"
    ).exists()
    assert not (release / "external_strategies/scrap_then_ad_reward_v2/film_flow.py.broken-backup").exists()
    assert not (release / "external_strategies/scrap_then_ad_reward_v2/__pycache__/strategy.pyc").exists()
    assert not (release / "config/license_auth.json").exists()


def test_missing_and_empty_template_directories_do_not_error(tmp_path: Path) -> None:
    release = tmp_path / "release"
    (release / "user_templates/watch_buttons").mkdir(parents=True)

    report = sync_release_templates(release, tmp_path / "project", apply=True)

    assert any(item.empty for item in report.directories)
    assert any(item.missing for item in report.directories)


def _write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)

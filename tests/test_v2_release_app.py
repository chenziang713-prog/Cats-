from __future__ import annotations

from pathlib import Path

from tools.build_v2_release import (
    V2_STRATEGY_NAME,
    copy_v2_strategy_package,
    copy_v2_user_templates,
    create_release_zip,
)
from tools.catsautomatic_v2_release_app import (
    V2ReleaseConfig,
    build_v2_strategy_args,
    release_authorize_strategy_run,
)


def test_v2_release_dry_run_args_are_v2_only_and_have_no_license_flags() -> None:
    args = build_v2_strategy_args(
        V2ReleaseConfig(adb_path="adb.exe", adb_serial="emulator-5556"),
        real_click=False,
    )

    assert args[args.index("--strategy") + 1] == "scrap_then_ad_reward_v2"
    assert "--allow-click" not in args
    assert "--license-key" not in args
    assert "--skip-license-check-for-dev" not in args
    assert "--repeat-after-reward" not in args


def test_v2_release_real_args_enable_only_allow_click() -> None:
    args = build_v2_strategy_args(
        V2ReleaseConfig(adb_path="adb.exe", adb_serial="emulator-5556"),
        real_click=True,
    )

    assert "--allow-click" in args
    assert args[args.index("--capture-backend") + 1] == "adb"
    assert args[args.index("--max-actions") + 1] == "8"


def test_v2_release_authorization_is_local_no_card_mode(tmp_path: Path) -> None:
    result, client = release_authorize_strategy_run(object(), tmp_path)

    assert result.ok is True
    assert result.status == "release_no_license"
    assert result.cache is not None
    assert result.cache.features == ("ad_reward",)
    assert client.heartbeat(result.cache).ok is True


def test_v2_release_copies_only_v2_strategy_and_filters_temp_files(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    release = tmp_path / "release"
    _write(repo / "external_strategies" / V2_STRATEGY_NAME / "manifest.json", b"{}")
    _write(repo / "external_strategies" / V2_STRATEGY_NAME / "strategy.py", b"strategy")
    _write(repo / "external_strategies" / V2_STRATEGY_NAME / "templates/user_templates/watch_ad_film/a.png", b"png")
    _write(repo / "external_strategies" / V2_STRATEGY_NAME / "film_flow.py.broken-backup", b"old")
    _write(repo / "external_strategies" / V2_STRATEGY_NAME / "__pycache__/strategy.pyc", b"cache")
    _write(repo / "external_strategies/scrap_ad_battle/manifest.json", b"old")

    destination = copy_v2_strategy_package(repo, release)

    assert destination == release / "external_strategies" / V2_STRATEGY_NAME
    assert (destination / "strategy.py").exists()
    assert (destination / "templates/user_templates/watch_ad_film/a.png").exists()
    assert not (release / "external_strategies/scrap_ad_battle").exists()
    assert not (destination / "film_flow.py.broken-backup").exists()
    assert not (destination / "__pycache__/strategy.pyc").exists()


def test_v2_release_copies_only_required_user_template_dirs(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    release = tmp_path / "release"
    _write(repo / "user_templates/close_buttons/close.png", b"close")
    _write(repo / "user_templates/pre_watch_optional/optional.png", b"optional")
    _write(repo / "user_templates/watch_buttons/watch.png", b"watch")
    _write(repo / "user_templates/error_buttons/error.png", b"error")
    _write(repo / "user_templates/scrap_watch_cooldown/cooldown.png", b"cooldown")

    copied = copy_v2_user_templates(repo, release)

    assert copied == 3
    assert (release / "user_templates/close_buttons/close.png").exists()
    assert (release / "user_templates/pre_watch_optional/optional.png").exists()
    assert (release / "user_templates/watch_buttons/watch.png").exists()
    assert not (release / "user_templates/error_buttons/error.png").exists()
    assert not (release / "user_templates/scrap_watch_cooldown/cooldown.png").exists()


def test_v2_release_zip_contains_release_folder(tmp_path: Path) -> None:
    release = tmp_path / "CATSautomaticV2-release"
    _write(release / "CATSautomaticV2.exe", b"exe")

    zip_path = create_release_zip(release, tmp_path / "release.zip")

    assert zip_path.exists()
    assert zip_path.read_bytes()


def _write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)

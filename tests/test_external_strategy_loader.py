from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from cats_automatic.external_strategy_loader import (
    find_external_strategy,
    import_strategy_package,
    list_available_strategies,
    load_external_strategy,
    scan_external_strategies,
)
from cats_automatic.game_loader import load_strategy
from cats_automatic.main import format_strategy_list
from cats_automatic.runtime_paths import external_strategies_dir


def test_external_strategies_dir_uses_base_dir(tmp_path: Path) -> None:
    assert external_strategies_dir(tmp_path) == tmp_path / "external_strategies"


def test_empty_external_strategies_lists_builtin_only(tmp_path: Path) -> None:
    infos = list_available_strategies("cats", base_dir=tmp_path / "external_strategies")

    assert [info.strategy_name for info in infos] == ["ad_reward"]
    assert infos[0].source == "builtin"


def test_scan_external_strategy_reads_manifest(tmp_path: Path) -> None:
    _write_external_strategy(tmp_path / "external_strategies" / "demo")

    infos = scan_external_strategies(tmp_path / "external_strategies")

    assert len(infos) == 1
    assert infos[0].strategy_name == "demo"
    assert infos[0].display_name == "Demo"
    assert infos[0].source == "external"


def test_find_and_load_external_strategy_resolves_templates(tmp_path: Path) -> None:
    package = tmp_path / "external_strategies" / "demo"
    _write_external_strategy(package)

    manifest = find_external_strategy("demo", "cats", base_dir=tmp_path / "external_strategies")
    assert manifest is not None
    strategy = load_external_strategy(manifest)
    target = strategy.targets()[0]

    assert target.name == "demo_target"
    assert target.template == str((package / "templates" / "target.png").resolve())


def test_game_loader_can_load_external_strategy(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from cats_automatic import external_strategy_loader

    package = tmp_path / "external_strategies" / "demo"
    _write_external_strategy(package)
    monkeypatch.setattr(
        external_strategy_loader,
        "external_strategies_dir",
        lambda *_, **__: tmp_path / "external_strategies",
    )

    strategy = load_strategy("cats", "demo")

    assert strategy.targets()[0].name == "demo_target"


def test_format_strategy_list_shows_external_strategy(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from cats_automatic import external_strategy_loader

    package = tmp_path / "external_strategies" / "demo"
    _write_external_strategy(package)
    monkeypatch.setattr(
        external_strategy_loader,
        "external_strategies_dir",
        lambda *_, **__: tmp_path / "external_strategies",
    )

    output = format_strategy_list("cats")

    assert "ad_reward" in output
    assert "demo" in output
    assert "source=external" in output


def test_bad_external_strategy_is_reported_not_raised(tmp_path: Path) -> None:
    package = tmp_path / "external_strategies" / "bad"
    package.mkdir(parents=True)
    (package / "manifest.json").write_text('{"strategy_name": "bad"}', encoding="utf-8")
    messages: list[str] = []

    infos = scan_external_strategies(tmp_path / "external_strategies", log=messages.append)

    assert infos[0].error
    assert "strategy.py not found" in infos[0].error
    assert str(package / "manifest.json") in messages[0]


def test_import_strategy_package_copies_folder_and_refuses_overwrite(tmp_path: Path) -> None:
    source = tmp_path / "source_demo"
    _write_external_strategy(source, strategy_name="source_demo")
    destination_root = tmp_path / "external_strategies"

    destination = import_strategy_package(source, destination_root)

    assert destination == destination_root / "source_demo"
    assert (destination / "manifest.json").exists()
    with pytest.raises(FileExistsError):
        import_strategy_package(source, destination_root)


def test_import_strategy_package_extracts_zip(tmp_path: Path) -> None:
    source = tmp_path / "zip_demo"
    _write_external_strategy(source, strategy_name="zip_demo")
    zip_path = tmp_path / "zip_demo.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        for path in source.rglob("*"):
            archive.write(path, path.relative_to(source.parent))

    destination = import_strategy_package(zip_path, tmp_path / "external_strategies")

    assert destination.name == "zip_demo"
    assert (destination / "manifest.json").exists()


def _write_external_strategy(package: Path, strategy_name: str = "demo") -> None:
    package.mkdir(parents=True)
    (package / "templates").mkdir()
    (package / "templates" / "target.png").touch()
    (package / "manifest.json").write_text(
        json.dumps(
            {
                "strategy_name": strategy_name,
                "display_name": "Demo",
                "game": "cats",
                "entry_class": "Strategy",
                "templates_dir": "templates",
            }
        ),
        encoding="utf-8",
    )
    (package / "strategy.py").write_text(
        "from cats_automatic.strategy_base import StrategyDecision, TargetSpec\n"
        "class Strategy:\n"
        "    def targets(self):\n"
        "        return [TargetSpec('demo_target', 'target.png', 0.5)]\n"
        "    def decide(self, context):\n"
        "        return StrategyDecision.wait(0.0, 'demo')\n",
        encoding="utf-8",
    )

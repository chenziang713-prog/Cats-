from __future__ import annotations

import importlib.util
import json
import shutil
import zipfile
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from types import ModuleType

from .runtime_paths import external_strategies_dir
from .strategy_base import StrategyContext, StrategyDecision, StrategyProtocol, TargetSpec


@dataclass(frozen=True)
class StrategyInfo:
    strategy_name: str
    display_name: str
    game: str
    source: str
    description: str = ""
    version: str = ""
    path: Path | None = None
    error: str = ""

    @property
    def label(self) -> str:
        source_label = "external" if self.source == "external" else "builtin"
        return f"{self.display_name} ({self.strategy_name}) [{source_label}]"


@dataclass(frozen=True)
class ExternalStrategyManifest:
    strategy_name: str
    display_name: str
    game: str = "cats"
    entry_class: str = "Strategy"
    description: str = ""
    version: str = ""
    templates_dir: str = "templates"
    package_dir: Path = Path()

    @property
    def strategy_path(self) -> Path:
        return self.package_dir / "strategy.py"

    @property
    def template_root(self) -> Path:
        return self.package_dir / self.templates_dir


BUILTIN_STRATEGIES = (
    StrategyInfo(
        strategy_name="ad_reward",
        display_name="广告奖励",
        game="cats",
        source="builtin",
        description="自动领取广告奖励",
        version="builtin",
    ),
)


def scan_external_strategies(
    base_dir: Path | None = None,
    *,
    log: Callable[[str], None] | None = None,
) -> tuple[StrategyInfo, ...]:
    directory = base_dir or external_strategies_dir()
    directory.mkdir(parents=True, exist_ok=True)
    infos: list[StrategyInfo] = []
    for manifest_path in sorted(directory.glob("*/manifest.json")):
        try:
            manifest = read_manifest(manifest_path)
            if not manifest.strategy_path.exists():
                raise FileNotFoundError(f"strategy.py not found: {manifest.strategy_path}")
            infos.append(
                StrategyInfo(
                    strategy_name=manifest.strategy_name,
                    display_name=manifest.display_name,
                    game=manifest.game,
                    source="external",
                    description=manifest.description,
                    version=manifest.version,
                    path=manifest.package_dir,
                )
            )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            message = f"External strategy load failed: path={manifest_path} error={exc}"
            if log is not None:
                log(message)
            infos.append(
                StrategyInfo(
                    strategy_name=manifest_path.parent.name,
                    display_name=manifest_path.parent.name,
                    game="",
                    source="external",
                    path=manifest_path.parent,
                    error=str(exc),
                )
            )
    return tuple(infos)


def list_available_strategies(
    game_name: str = "cats",
    *,
    base_dir: Path | None = None,
    log: Callable[[str], None] | None = None,
) -> tuple[StrategyInfo, ...]:
    external = [
        info
        for info in scan_external_strategies(base_dir, log=log)
        if not info.error and info.game == game_name
    ]
    return tuple(BUILTIN_STRATEGIES) + tuple(external)


def find_external_strategy(
    strategy_name: str,
    game_name: str,
    *,
    base_dir: Path | None = None,
) -> ExternalStrategyManifest | None:
    directory = base_dir or external_strategies_dir()
    directory.mkdir(parents=True, exist_ok=True)
    for manifest_path in sorted(directory.glob("*/manifest.json")):
        try:
            manifest = read_manifest(manifest_path)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if manifest.strategy_name == strategy_name and manifest.game == game_name:
            return manifest
    return None


def read_manifest(manifest_path: Path) -> ExternalStrategyManifest:
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    strategy_name = str(raw.get("strategy_name") or "").strip()
    if not strategy_name:
        raise ValueError("manifest strategy_name must not be empty")
    display_name = str(raw.get("display_name") or strategy_name).strip()
    return ExternalStrategyManifest(
        strategy_name=strategy_name,
        display_name=display_name,
        game=str(raw.get("game") or "cats").strip() or "cats",
        entry_class=str(raw.get("entry_class") or "Strategy").strip() or "Strategy",
        description=str(raw.get("description") or ""),
        version=str(raw.get("version") or ""),
        templates_dir=str(raw.get("templates_dir") or "templates").strip() or "templates",
        package_dir=manifest_path.parent,
    )


def load_external_strategy(manifest: ExternalStrategyManifest) -> StrategyProtocol:
    if not manifest.strategy_path.exists():
        raise FileNotFoundError(f"strategy.py not found: {manifest.strategy_path}")
    module = _load_module(manifest.strategy_path, manifest.strategy_name)
    if not hasattr(module, manifest.entry_class):
        raise ValueError(f"entry_class not found: {manifest.entry_class}")
    strategy_class = getattr(module, manifest.entry_class)
    strategy = strategy_class()
    if not hasattr(strategy, "targets") or not hasattr(strategy, "decide"):
        raise ValueError("External strategy must implement targets() and decide().")
    return ExternalStrategyAdapter(strategy, manifest.template_root)


def import_strategy_package(source_path: Path, destination_root: Path | None = None, *, overwrite: bool = False) -> Path:
    source = Path(source_path)
    destination_base = destination_root or external_strategies_dir()
    destination_base.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        package_name = source.name
        destination = destination_base / package_name
        if destination.exists():
            if not overwrite:
                raise FileExistsError(f"External strategy already exists: {destination}")
            shutil.rmtree(destination)
        shutil.copytree(source, destination)
        return destination
    if source.suffix.lower() == ".zip":
        with zipfile.ZipFile(source) as archive:
            package_name = _zip_package_name(archive, source.stem)
            destination = destination_base / package_name
            if destination.exists():
                if not overwrite:
                    raise FileExistsError(f"External strategy already exists: {destination}")
                shutil.rmtree(destination)
            destination.mkdir(parents=True)
            archive.extractall(destination)
        _flatten_single_nested_dir(destination)
        return destination
    raise ValueError("External strategy package must be a folder or .zip file.")


class ExternalStrategyAdapter:
    def __init__(self, strategy: StrategyProtocol, template_root: Path) -> None:
        self.strategy = strategy
        self.template_root = template_root

    def targets(self) -> Sequence[TargetSpec]:
        return tuple(self._resolve_target(target) for target in self.strategy.targets())

    def decide(self, context: StrategyContext) -> StrategyDecision:
        return self.strategy.decide(context)

    def _resolve_target(self, target: TargetSpec) -> TargetSpec:
        template_path = Path(target.template)
        if template_path.is_absolute():
            return target
        if template_path.parts and template_path.parts[0] == "templates":
            resolved = self.template_root.parent / template_path
        else:
            resolved = self.template_root / template_path
        return replace(target, template=str(resolved.resolve()))


def _load_module(strategy_path: Path, strategy_name: str) -> ModuleType:
    module_name = f"cats_automatic_external_{strategy_name}_{abs(hash(strategy_path))}"
    spec = importlib.util.spec_from_file_location(module_name, strategy_path)
    if spec is None or spec.loader is None:
        raise ValueError(f"Could not load external strategy module: {strategy_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _zip_package_name(archive: zipfile.ZipFile, fallback: str) -> str:
    names = [name.split("/")[0] for name in archive.namelist() if name and not name.startswith("__MACOSX")]
    unique = {name for name in names if name}
    return next(iter(unique)) if len(unique) == 1 else fallback


def _flatten_single_nested_dir(destination: Path) -> None:
    entries = list(destination.iterdir())
    if len(entries) != 1 or not entries[0].is_dir():
        return
    nested = entries[0]
    temp = destination.with_name(destination.name + "__import_tmp")
    nested.rename(temp)
    shutil.rmtree(destination)
    temp.rename(destination)

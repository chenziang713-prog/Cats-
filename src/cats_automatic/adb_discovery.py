from __future__ import annotations

import subprocess
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path


DEFAULT_ADB_SEARCH_ROOTS = (
    Path(r"C:\leidian"),
    Path(r"C:\LDPlayer"),
    Path(r"C:\Program Files"),
    Path(r"C:\Program Files (x86)"),
    Path(r"D:\leidian"),
    Path(r"D:\LDPlayer"),
    Path(r"D:\Program Files"),
    Path(r"D:\Program Files (x86)"),
)

PATH_PRIORITY_KEYWORDS = (
    "ldplayer9",
    "leidian",
    "雷电",
    "ldplayer64",
    "ldplayer4",
    "mumu player",
    "netease",
    "adb.exe",
)

DEVICE_PRIORITY = ("emulator-5554", "emulator-5556")


@dataclass(frozen=True)
class AdbDevice:
    serial: str
    state: str


@dataclass(frozen=True)
class AdbCandidate:
    adb_path: Path
    devices: tuple[AdbDevice, ...]
    returncode: int = 0
    stdout: str = ""
    stderr: str = ""

    @property
    def available_devices(self) -> tuple[AdbDevice, ...]:
        return tuple(device for device in self.devices if device.state == "device")


@dataclass(frozen=True)
class AdbDiscoveryResult:
    candidates: tuple[AdbCandidate, ...]
    recommended: AdbCandidate | None


def parse_adb_devices_output(output: str) -> tuple[AdbDevice, ...]:
    devices: list[AdbDevice] = []
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line or line.lower().startswith("list of devices attached"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        devices.append(AdbDevice(serial=parts[0], state=parts[1]))
    return tuple(devices)


def collect_adb_candidates(search_roots: Iterable[Path] = DEFAULT_ADB_SEARCH_ROOTS) -> tuple[Path, ...]:
    candidates: set[Path] = set()
    for root in search_roots:
        if not root.exists():
            continue
        if root.is_file() and root.name.lower() == "adb.exe":
            candidates.add(root.resolve())
            continue
        if not root.is_dir():
            continue
        direct = root / "adb.exe"
        if direct.exists():
            candidates.add(direct.resolve())
        try:
            for path in root.rglob("adb.exe"):
                if path.is_file():
                    candidates.add(path.resolve())
        except OSError:
            continue
    return tuple(sorted(candidates, key=adb_path_sort_key))


def adb_path_sort_key(path: Path) -> tuple[int, str]:
    lowered = str(path).lower()
    for index, keyword in enumerate(PATH_PRIORITY_KEYWORDS):
        if keyword.lower() in lowered:
            return index, lowered
    return len(PATH_PRIORITY_KEYWORDS), lowered


def preferred_device(devices: Iterable[AdbDevice]) -> AdbDevice | None:
    available = [device for device in devices if device.state == "device"]
    if not available:
        return None
    for preferred_serial in DEVICE_PRIORITY:
        for device in available:
            if device.serial == preferred_serial:
                return device
    return available[0]


def choose_recommended_adb(candidates: Iterable[AdbCandidate]) -> AdbCandidate | None:
    available = [candidate for candidate in candidates if candidate.available_devices]
    if not available:
        return None
    return sorted(available, key=lambda candidate: adb_path_sort_key(candidate.adb_path))[0]


def discover_adb(
    *,
    search_roots: Iterable[Path] = DEFAULT_ADB_SEARCH_ROOTS,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    timeout_seconds: float = 5.0,
    log: Callable[[str], None] | None = None,
) -> AdbDiscoveryResult:
    candidates: list[AdbCandidate] = []
    for adb_path in collect_adb_candidates(search_roots):
        if log is not None:
            log(f"Checking adb: {adb_path}")
        try:
            result = runner(
                [str(adb_path), "devices"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_seconds,
            )
            devices = parse_adb_devices_output((result.stdout or "") + "\n" + (result.stderr or ""))
            candidate = AdbCandidate(
                adb_path=adb_path,
                devices=devices,
                returncode=result.returncode,
                stdout=result.stdout or "",
                stderr=result.stderr or "",
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            candidate = AdbCandidate(
                adb_path=adb_path,
                devices=(),
                returncode=-1,
                stderr=str(exc),
            )
        candidates.append(candidate)
        if log is not None:
            device_text = ", ".join(f"{device.serial} {device.state}" for device in candidate.devices) or "no devices"
            log(f"ADB result: {adb_path} -> {device_text}")
    return AdbDiscoveryResult(
        candidates=tuple(candidates),
        recommended=choose_recommended_adb(candidates),
    )

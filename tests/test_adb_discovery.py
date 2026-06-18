from __future__ import annotations

import subprocess
from pathlib import Path

from cats_automatic.adb_discovery import (
    AdbCandidate,
    AdbDevice,
    choose_recommended_adb,
    collect_adb_candidates,
    discover_adb,
    parse_adb_devices_output,
    preferred_device,
)


def test_parse_adb_devices_output_keeps_all_states() -> None:
    output = """
List of devices attached
emulator-5554	device
127.0.0.1:5555	device
offline-1	offline
bad-1	unauthorized
"""

    devices = parse_adb_devices_output(output)

    assert devices == (
        AdbDevice("emulator-5554", "device"),
        AdbDevice("127.0.0.1:5555", "device"),
        AdbDevice("offline-1", "offline"),
        AdbDevice("bad-1", "unauthorized"),
    )
    assert preferred_device(devices) == AdbDevice("emulator-5554", "device")


def test_preferred_device_ignores_offline_and_unauthorized() -> None:
    devices = (
        AdbDevice("offline-1", "offline"),
        AdbDevice("bad-1", "unauthorized"),
        AdbDevice("127.0.0.1:5555", "device"),
    )

    assert preferred_device(devices) == AdbDevice("127.0.0.1:5555", "device")


def test_collect_adb_candidates_sorts_ldplayer_first(tmp_path: Path) -> None:
    mumu = tmp_path / "MuMu Player" / "adb.exe"
    ldplayer = tmp_path / "LDPlayer9" / "adb.exe"
    generic = tmp_path / "Android" / "adb.exe"
    for path in (mumu, ldplayer, generic):
        path.parent.mkdir(parents=True)
        path.touch()

    candidates = collect_adb_candidates([tmp_path])

    assert candidates[0] == ldplayer.resolve()
    assert set(candidates) == {mumu.resolve(), ldplayer.resolve(), generic.resolve()}


def test_choose_recommended_adb_requires_device_state() -> None:
    ldplayer = AdbCandidate(
        Path(r"C:\LDPlayer9\adb.exe"),
        (AdbDevice("emulator-5556", "device"),),
    )
    mumu_offline = AdbCandidate(
        Path(r"C:\Program Files\MuMu Player\adb.exe"),
        (AdbDevice("emulator-5554", "offline"),),
    )

    assert choose_recommended_adb([mumu_offline, ldplayer]) == ldplayer


def test_discover_adb_runs_devices_and_recommends_candidate(tmp_path: Path) -> None:
    adb = tmp_path / "LDPlayer9" / "adb.exe"
    adb.parent.mkdir(parents=True)
    adb.touch()
    calls: list[list[str]] = []

    def runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, "List of devices attached\nemulator-5556\tdevice\n", "")

    result = discover_adb(search_roots=[tmp_path], runner=runner)

    assert calls == [[str(adb.resolve()), "devices"]]
    assert result.recommended is not None
    assert result.recommended.adb_path == adb.resolve()
    assert preferred_device(result.recommended.devices) == AdbDevice("emulator-5556", "device")

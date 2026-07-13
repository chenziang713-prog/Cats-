from __future__ import annotations

import subprocess
from pathlib import Path

from cats_automatic.actions import (
    ActionResult,
    AdbActionBackend,
    DryRunBackend,
    execute_action,
)


def test_wait_dry_run_returns_complete_result_without_sleeping() -> None:
    backend = DryRunBackend()

    result = execute_action(
        {"name": "wait", "params": {"seconds": 10}, "reason": "dry_wait"},
        backend,
        dry_run=True,
    )

    assert result.success is True
    assert result.action == "wait"
    assert result.dry_run is True
    assert result.clicked_pos is None
    assert result.error == ""
    assert result.duration < 0.5


def test_wait_non_dry_run_sleeps_with_reasonable_cap(tmp_path: Path) -> None:
    adb = tmp_path / "adb.exe"
    adb.touch()
    sleeps: list[float] = []
    backend = AdbActionBackend(
        adb_path=adb,
        adb_serial="emulator-5556",
        runner=lambda command, **_: subprocess.CompletedProcess(command, 0, b"", b""),
        sleep=sleeps.append,
    )

    result = execute_action(
        {"name": "wait", "params": {"seconds": 10}, "reason": "real_wait"},
        backend,
        dry_run=False,
        max_wait_seconds=0.25,
    )

    assert sleeps == [0.25]
    assert result.success is True
    assert result.action == "wait"
    assert result.dry_run is False
    assert result.error == ""


def test_press_back_dry_run_never_calls_adb() -> None:
    class Backend(DryRunBackend):
        def keyevent(self, keycode: str, reason: str = "") -> ActionResult:
            raise AssertionError("dry-run press_back must not call keyevent")

    backend = Backend()

    result = execute_action({"name": "press_back", "reason": "find_home"}, backend, dry_run=True)

    assert result.success is True
    assert result.action == "press_back"
    assert result.dry_run is True
    assert result.result == "skipped_dry_run"
    assert backend.action_count == 0


def test_no_action_does_nothing() -> None:
    backend = DryRunBackend()

    result = execute_action("no_action", backend, dry_run=True)

    assert result.to_dict() == {
        "success": True,
        "action": "no_action",
        "dry_run": True,
        "message": "no_action",
        "clicked_pos": None,
        "duration": 0.0,
        "error": None,
        "action_type": "no_action",
        "result": "no_action",
        "reason": "",
    }
    assert backend.action_count == 0


def test_unknown_action_returns_complete_error_result() -> None:
    result = execute_action({"name": "tap_point", "reason": "not_yet"}, DryRunBackend(), dry_run=True)

    assert result.success is False
    assert result.action == "tap_point"
    assert result.dry_run is True
    assert result.error == "unknown_action"
    assert result.clicked_pos is None


def test_string_and_dict_action_inputs_are_supported() -> None:
    backend = DryRunBackend()

    string_result = execute_action("no_action", backend, dry_run=True)
    dict_result = execute_action({"name": "no_action", "params": {}, "reason": "same"}, backend)

    assert string_result.action == "no_action"
    assert dict_result.action == "no_action"
    assert dict_result.reason == "same"


def test_action_result_has_complete_fields() -> None:
    result = ActionResult("wait", "executed", "reason")

    payload = result.to_dict()

    assert set(payload) == {
        "success",
        "action",
        "dry_run",
        "message",
        "clicked_pos",
        "duration",
        "error",
        "action_type",
        "result",
        "reason",
    }

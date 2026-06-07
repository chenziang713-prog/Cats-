from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path

from PIL import Image

from ..window_capture import WindowFrame
from .capture_backend import CaptureBackendError

SubprocessRun = Callable[..., subprocess.CompletedProcess[bytes]]


class AdbCaptureBackend:
    name = "adb"

    def __init__(
        self,
        adb_path: Path,
        adb_serial: str,
        *,
        runner: SubprocessRun = subprocess.run,
    ) -> None:
        self.adb_path = Path(adb_path)
        self.adb_serial = adb_serial
        self.runner = runner
        if not self.adb_path.exists():
            raise CaptureBackendError(f"ADB executable does not exist: {self.adb_path}")
        if not self.adb_path.is_file():
            raise CaptureBackendError(f"ADB path is not a file: {self.adb_path}")
        if not self.adb_serial.strip():
            raise CaptureBackendError("--adb-serial is required when --capture-backend adb is used.")
        self._ensure_device_available()

    def capture(self, output_path: Path) -> WindowFrame:
        command = [
            str(self.adb_path),
            "-s",
            self.adb_serial,
            "exec-out",
            "screencap",
            "-p",
        ]
        result = self._run(command)
        if result.returncode != 0:
            raise CaptureBackendError(
                "ADB screencap failed: "
                f"{_decode_output(result.stderr) or _decode_output(result.stdout) or result.returncode}"
            )
        if not result.stdout:
            raise CaptureBackendError("ADB screencap returned no image data.")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(result.stdout)
        try:
            with Image.open(output_path) as image:
                size = image.size
        except OSError as exc:
            raise CaptureBackendError("ADB screencap output was not a readable PNG image.") from exc

        print(f"ADB capture selected: serial={self.adb_serial}")
        print(f"ADB capture saved: {output_path}")
        print(f"ADB capture image size: width={size[0]}, height={size[1]}")
        return WindowFrame(
            path=output_path,
            title=f"ADB {self.adb_serial}",
            client_origin=(0, 0),
            size=size,
        )

    def _ensure_device_available(self) -> None:
        result = self._run([str(self.adb_path), "devices"])
        if result.returncode != 0:
            raise CaptureBackendError(
                "ADB devices failed: "
                f"{_decode_output(result.stderr) or _decode_output(result.stdout) or result.returncode}"
            )
        devices = parse_adb_devices(_decode_output(result.stdout))
        if not devices:
            raise CaptureBackendError("ADB devices returned no connected devices.")
        if self.adb_serial not in devices:
            raise CaptureBackendError(
                f"ADB serial not connected: {self.adb_serial}. Connected devices: {', '.join(devices)}"
            )

    def _run(self, command: Sequence[str]) -> subprocess.CompletedProcess[bytes]:
        try:
            return self.runner(command, capture_output=True)
        except OSError as exc:
            raise CaptureBackendError(f"Failed to run ADB command: {exc}") from exc


def parse_adb_devices(output: str) -> list[str]:
    devices: list[str] = []
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("List of devices"):
            continue
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            devices.append(parts[0])
    return devices


def _decode_output(value: bytes | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return value.decode("utf-8", errors="replace").strip()

from __future__ import annotations

import importlib.util
import shutil
import sys


def check_command(name: str) -> bool:
    path = shutil.which(name)
    if path:
        print(f"OK command {name}: {path}")
        return True
    print(f"MISSING command {name}: not found on PATH")
    return False


def check_module(name: str) -> bool:
    if importlib.util.find_spec(name) is not None:
        print(f"OK module {name}")
        return True
    print(f"MISSING module {name}: install requirements.txt")
    return False


def main() -> int:
    print(f"Python: {sys.version.split()[0]}")
    checks = [
        check_command("python"),
        check_command("git"),
        check_module("cv2"),
        check_module("numpy"),
        check_module("PIL"),
    ]
    if all(checks):
        print("Environment check passed.")
        return 0

    print("Environment check failed. See docs/windows-setup.md.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())


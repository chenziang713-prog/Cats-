from __future__ import annotations

from pathlib import Path

from PIL import ImageGrab


def capture_screen(output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image = ImageGrab.grab(all_screens=True)
    image.save(output_path)
    return output_path

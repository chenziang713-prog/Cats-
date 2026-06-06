from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from cats_automatic.vision import match_template


@pytest.fixture
def generated_match_images(tmp_path: Path) -> tuple[Path, Path]:
    screen = Image.new("RGB", (120, 90), "white")
    template = Image.new("RGB", (30, 30), (230, 230, 230))
    draw = ImageDraw.Draw(template)
    draw.rectangle((2, 2, 27, 27), outline="black", width=3)
    draw.line((7, 22, 22, 7), fill="red", width=3)
    draw.ellipse((11, 11, 18, 18), fill="blue")
    screen.paste(template, (40, 25))
    screen_path = tmp_path / "screen.png"
    template_path = tmp_path / "template.png"
    screen.save(screen_path)
    template.save(template_path)
    return screen_path, template_path


@pytest.mark.parametrize("mode", ["color", "gray", "edge"])
def test_match_template_generated_images(
    generated_match_images: tuple[Path, Path],
    mode: str,
) -> None:
    screen_path, template_path = generated_match_images

    match = match_template(screen_path, template_path, mode=mode)

    assert match.confidence >= 0.99
    assert match.center == (55, 40)


def test_match_template_region_returns_global_coordinates(
    generated_match_images: tuple[Path, Path],
) -> None:
    screen_path, template_path = generated_match_images

    match = match_template(
        screen_path,
        template_path,
        mode="color",
        region=(35, 20, 50, 50),
    )

    assert match.confidence >= 0.99
    assert match.center == (55, 40)

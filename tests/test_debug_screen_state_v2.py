from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from external_strategies.scrap_then_ad_reward_v2.screen_state_detector import (
    _template_paths_for_marker,
    detect_current_screen_state_from_detections,
)
from tools import debug_screen_state_v2


HOME_TEMPLATE = _template_paths_for_marker("main-definate")[0]
AD_ENTRY_TEMPLATE = _template_paths_for_marker("ad_entry")[0]


def test_debug_tool_handles_single_image(tmp_path: Path) -> None:
    image = _screen_with_template(tmp_path / "screen.png", HOME_TEMPLATE)

    record = debug_screen_state_v2.analyze_image(image)

    assert record["screen_state"] == "HOME"
    assert record["confidence"] >= 0.80
    assert "main-definate" in record["matched_markers"]
    assert record["best_marker"] == "main-definate"
    assert record["action_template"]["decision"] == "no_action"
    assert record["loaded_template_total"] > 0
    assert record["top_detections"]


def test_debug_tool_handles_run_dir_and_writes_outputs(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-001"
    screenshots = run_dir / "screenshots"
    _screen_with_template(screenshots / "loop-001.png", HOME_TEMPLATE)
    _screen_with_template(screenshots / "loop-002.png", HOME_TEMPLATE)

    records = debug_screen_state_v2.analyze_run(run_dir)

    journal_path = run_dir / debug_screen_state_v2.JOURNAL_NAME
    report_path = run_dir / debug_screen_state_v2.REPORT_NAME
    assert len(records) == 2
    assert journal_path.exists()
    assert report_path.exists()

    journal_records = [
        json.loads(line)
        for line in journal_path.read_text(encoding="utf-8").splitlines()
    ]
    assert [record["screen_state"] for record in journal_records] == ["HOME", "HOME"]
    report = report_path.read_text(encoding="utf-8")
    assert "当前界面状态: HOME" in report
    assert "前 20 个最高置信度 detection" in report


def test_debug_tool_cli_single_image_prints_no_action(tmp_path: Path, capsys) -> None:
    image = _screen_with_template(tmp_path / "screen.png", HOME_TEMPLATE)

    exit_code = debug_screen_state_v2.main(["--image", str(image)])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "当前界面状态: HOME" in output
    assert "动作模板: no_action" in output


def test_simple_image_and_template_match_above_090(tmp_path: Path) -> None:
    screen_path, template_path = _simple_match_images(tmp_path)
    candidate = debug_screen_state_v2.TemplateCandidate(
        marker_name="simple_marker",
        path=template_path,
        source_dir=tmp_path,
        size=(30, 30),
    )

    detections, scores = debug_screen_state_v2.build_detections_from_image(
        screen_path,
        [candidate],
    )

    assert detections["simple_marker"]["confidence"] > 0.90
    assert scores[0].confidence > 0.90


def test_fake_home_detections_return_home() -> None:
    result = detect_current_screen_state_from_detections(
        {
            "ad_entry": {"confidence": 0.95},
            "main-definate": {"confidence": 0.95},
        }
    )

    assert result.state_name == "HOME"


def test_loop_image_detects_ad_entry_and_home(tmp_path: Path) -> None:
    image = _home_screen_with_main_and_ad_entry(tmp_path / "loop-001.png")

    record = debug_screen_state_v2.analyze_image(image)

    assert record["screen_state"] == "HOME"
    assert record["generated_detections"]["ad_entry"]["confidence"] > 0.90
    assert record["generated_detections"]["main-definate"]["confidence"] > 0.90
    assert "main-definate" in record["matched_markers"]


def test_empty_template_directory_outputs_chinese_hint(tmp_path: Path) -> None:
    empty_dir = tmp_path / "empty_templates"
    empty_dir.mkdir()
    warnings: list[str] = []

    templates = debug_screen_state_v2.load_template_candidates([empty_dir], warnings)

    assert templates == []
    assert any("模板目录为空" in warning for warning in warnings)


def test_image_read_failure_outputs_chinese_error(tmp_path: Path) -> None:
    bad_image = tmp_path / "bad.png"
    bad_image.write_text("not an image", encoding="utf-8")
    warnings: list[str] = []

    with pytest.raises(OSError):
        debug_screen_state_v2.read_image_size(bad_image, "screenshot", warnings)

    assert any("图片读取失败" in warning for warning in warnings)


def test_debug_tool_does_not_include_adb_or_real_click_calls() -> None:
    source = Path(debug_screen_state_v2.__file__).read_text(encoding="utf-8").lower()

    assert "adb" not in source
    assert ".click" not in source


def _screen_with_template(path: Path, template_path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    template = Image.open(template_path).convert("RGB")
    screen = Image.new("RGB", (800, 800), "white")
    screen.paste(template, (120, 160))
    screen.save(path)
    return path


def _home_screen_with_main_and_ad_entry(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    main_template = Image.open(HOME_TEMPLATE).convert("RGB")
    ad_template = Image.open(AD_ENTRY_TEMPLATE).convert("RGB")
    screen = Image.new("RGB", (900, 900), "white")
    screen.paste(main_template, (40, 60))
    screen.paste(ad_template, (420, 60))
    screen.save(path)
    return path


def _simple_match_images(tmp_path: Path) -> tuple[Path, Path]:
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

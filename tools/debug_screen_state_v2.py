from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
for path in (REPO_ROOT, SRC_ROOT):
    path_text = str(path)
    if path_text not in sys.path:
        sys.path.insert(0, path_text)

from cats_automatic.vision import MatchResult, load_image, match_template
from external_strategies.scrap_then_ad_reward_v2.screen_state_detector import (
    detect_current_screen_state_from_detections,
)
from external_strategies.scrap_then_ad_reward_v2.screen_state_types import (
    ScreenStateResult,
)
from external_strategies.scrap_then_ad_reward_v2.state_action_templates import (
    handle_screen_state,
)


JOURNAL_NAME = "screen_state_journal_v2.jsonl"
REPORT_NAME = "screen_state_report_v2.txt"
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}
REQUIRED_TEMPLATE_DIRS = (
    REPO_ROOT / "external_strategies" / "scrap_ad_battle" / "templates",
    REPO_ROOT / "external_strategies" / "scrap_then_ad_reward" / "templates",
    REPO_ROOT / "user_templates",
)
SUPPLEMENTAL_TEMPLATE_DIRS = (
    REPO_ROOT / "src" / "cats_automatic" / "games" / "cats" / "templates",
    REPO_ROOT / "templates",
)
SPECIAL_MARKER_NAMES = {
    "ad_close_text": "close_ad",
    "ad_close_x": "close_ad",
    "ad_entry": "ad_entry",
    "ad_confirm_claim": "confirm_button",
    "watch_ad_button": "watch_ad_button",
}


@dataclass(frozen=True)
class TemplateCandidate:
    marker_name: str
    path: Path
    source_dir: Path
    size: tuple[int, int]


@dataclass(frozen=True)
class TemplateScore:
    marker_name: str
    path: str
    confidence: float
    center: tuple[int, int] | None
    size: tuple[int, int]


def analyze_image(
    image_path: Path,
    *,
    match_mode: str = "color",
    scale_min: float = 1.0,
    scale_max: float = 1.0,
    scale_step: float = 0.1,
    extra_template_dirs: Iterable[Path] = (),
    debug: bool = False,
) -> dict[str, Any]:
    image_path = image_path.resolve()
    debug_lines: list[str] = []
    screen_size = read_image_size(image_path, "截图", debug_lines)
    template_dirs = template_search_dirs(extra_template_dirs)
    templates = load_template_candidates(template_dirs, debug_lines)
    detections, template_scores = build_detections_from_image(
        image_path,
        templates,
        match_mode=match_mode,
        scale_min=scale_min,
        scale_max=scale_max,
        scale_step=scale_step,
        debug_lines=debug_lines,
    )

    if templates and template_scores and max(score.confidence for score in template_scores) == 0.0:
        debug_lines.append(
            "模板匹配异常：所有模板分数为 0，请检查图片读取格式、模板加载路径和匹配器调用。"
        )

    result = detect_current_screen_state_from_detections(
        detections,
        screenshot_path=str(image_path),
    )
    action_template = handle_screen_state(None, result)
    record = result_record(
        result,
        action_template,
        screen_size=screen_size,
        template_dirs=template_dirs,
        templates=templates,
        template_scores=template_scores,
        detections=detections,
        debug_lines=debug_lines,
    )
    if debug:
        print_debug_record(record)
    return record


def template_search_dirs(extra_template_dirs: Iterable[Path] = ()) -> list[Path]:
    dirs = [*REQUIRED_TEMPLATE_DIRS, *SUPPLEMENTAL_TEMPLATE_DIRS]
    dirs.extend(Path(path) for path in extra_template_dirs)
    resolved: list[Path] = []
    for directory in dirs:
        path = directory.resolve()
        if path not in resolved:
            resolved.append(path)
    return resolved


def load_template_candidates(
    template_dirs: Iterable[Path],
    debug_lines: list[str] | None = None,
) -> list[TemplateCandidate]:
    debug_lines = debug_lines if debug_lines is not None else []
    candidates: list[TemplateCandidate] = []
    for directory in template_dirs:
        if not directory.exists():
            debug_lines.append(f"中文提示：模板目录不存在，已跳过：{directory}")
            continue

        paths = sorted(
            path for path in directory.rglob("*")
            if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
        )
        if not paths:
            debug_lines.append(f"中文提示：模板目录为空：{directory}")
            continue

        for path in paths:
            try:
                size = read_image_size(path, "模板", debug_lines)
            except OSError:
                continue
            candidates.append(
                TemplateCandidate(
                    marker_name=marker_name_for_template(path, directory),
                    path=path.resolve(),
                    source_dir=directory.resolve(),
                    size=size,
                )
            )
    if not candidates:
        debug_lines.append("中文提示：没有加载到任何模板图片。")
    return candidates


def marker_name_for_template(path: Path, source_dir: Path) -> str:
    relative_parts = path.relative_to(source_dir).parts
    parent_names = {part.lower() for part in relative_parts[:-1]}
    safe_stem = normalize_marker_stem(path.stem)

    if "close_buttons" in parent_names:
        return safe_stem if safe_stem.startswith("close_user_") else f"close_user_{safe_stem}"
    if "watch_buttons" in parent_names:
        return safe_stem if safe_stem.startswith("watch_user_") else f"watch_user_{safe_stem}"
    if "pre_watch_optional" in parent_names:
        return "pre_watch_optional"
    if "error_popups" in parent_names:
        return "error_popup"
    if "error_buttons" in parent_names:
        return "retry_button"
    return SPECIAL_MARKER_NAMES.get(safe_stem, safe_stem)


def normalize_marker_stem(stem: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "_", stem).strip("_").lower()


def build_detections_from_image(
    image_path: Path,
    templates: Iterable[TemplateCandidate],
    *,
    match_mode: str = "color",
    scale_min: float = 1.0,
    scale_max: float = 1.0,
    scale_step: float = 0.1,
    debug_lines: list[str] | None = None,
) -> tuple[dict[str, dict[str, Any]], list[TemplateScore]]:
    debug_lines = debug_lines if debug_lines is not None else []
    detections: dict[str, dict[str, Any]] = {}
    scores: list[TemplateScore] = []

    for template in templates:
        try:
            match = match_template(
                image_path,
                template.path,
                mode=match_mode,
                scale_min=scale_min,
                scale_max=scale_max,
                scale_step=scale_step,
            )
        except Exception as exc:
            debug_lines.append(
                "模板匹配异常："
                f"模板路径={template.path} 截图路径={image_path} 异常原因={exc}"
            )
            continue

        score = TemplateScore(
            marker_name=template.marker_name,
            path=str(template.path),
            confidence=match.confidence,
            center=match.center,
            size=match.size,
        )
        scores.append(score)
        previous = detections.get(template.marker_name)
        if previous is None or match.confidence > float(previous["confidence"]):
            detections[template.marker_name] = {
                "confidence": match.confidence,
                "center": match.center,
                "template_path": str(template.path),
            }
    add_synthetic_detections(detections, debug_lines)
    return detections, scores


def add_synthetic_detections(
    detections: dict[str, dict[str, Any]],
    debug_lines: list[str],
) -> None:
    scrap_entry = detections.get("scrap_entry")
    ad_entry = detections.get("ad_entry")
    if (
        scrap_entry is not None
        and ad_entry is not None
        and float(scrap_entry["confidence"]) >= 0.80
        and float(ad_entry["confidence"]) >= 0.80
        and "main-definate" not in detections
    ):
        confidence = min(float(scrap_entry["confidence"]), float(ad_entry["confidence"]))
        detections["main-definate"] = {
            "confidence": confidence,
            "center": ad_entry.get("center"),
            "template_path": "synthetic:scrap_entry+ad_entry",
        }
        debug_lines.append(
            "中文提示：同时命中 scrap_entry 和 ad_entry，已生成 HOME 规则需要的 main-definate 标志。"
        )


def read_image_size(path: Path, label: str, debug_lines: list[str] | None = None) -> tuple[int, int]:
    debug_lines = debug_lines if debug_lines is not None else []
    if not path.exists():
        message = f"中文错误：{label}图片不存在：{path}"
        debug_lines.append(message)
        raise FileNotFoundError(message)
    try:
        image = load_image(path)
    except Exception as exc:
        message = f"中文错误：{label}图片读取失败：{path}；原因：{exc}"
        debug_lines.append(message)
        raise OSError(message) from exc
    if image is None or len(getattr(image, "shape", ())) < 2:
        message = f"中文错误：{label}图片为空或格式异常：{path}"
        debug_lines.append(message)
        raise OSError(message)
    height, width = int(image.shape[0]), int(image.shape[1])
    return width, height


def result_record(
    result: ScreenStateResult,
    action_template: dict[str, Any],
    *,
    screen_size: tuple[int, int],
    template_dirs: list[Path],
    templates: list[TemplateCandidate],
    template_scores: list[TemplateScore],
    detections: dict[str, dict[str, Any]],
    debug_lines: list[str],
) -> dict[str, Any]:
    marker_counts = Counter(template.marker_name for template in templates)
    template_sizes = [
        {
            "marker_name": template.marker_name,
            "path": str(template.path),
            "size": list(template.size),
        }
        for template in templates
    ]
    all_scores = sorted(
        (
            {
                "marker_name": score.marker_name,
                "template_path": score.path,
                "confidence": score.confidence,
                "center": list(score.center) if score.center is not None else None,
                "size": list(score.size),
            }
            for score in template_scores
        ),
        key=lambda item: float(item["confidence"]),
        reverse=True,
    )
    return {
        "image": result.screenshot_path,
        "screen_size": list(screen_size),
        "screen_state": result.state_name,
        "confidence": result.confidence,
        "matched": result.matched,
        "matched_markers": list(result.matched_markers),
        "excluded_markers": list(result.excluded_markers),
        "missing_markers": list(result.missing_markers),
        "best_marker": result.best_marker,
        "reason": result.reason,
        "raw_scores": dict(result.raw_scores),
        "generated_detections": {
            name: {
                "confidence": detection.get("confidence"),
                "center": list(detection["center"]) if detection.get("center") is not None else None,
                "template_path": detection.get("template_path"),
            }
            for name, detection in sorted(detections.items())
        },
        "action_template": dict(action_template),
        "loaded_template_dirs": [str(path) for path in template_dirs],
        "loaded_template_total": len(templates),
        "marker_template_counts": dict(sorted(marker_counts.items())),
        "template_sizes": template_sizes,
        "template_scores": all_scores,
        "top_detections": all_scores[:20],
        "debug_warnings": list(debug_lines),
    }


def analyze_run(
    run_dir: Path,
    *,
    match_mode: str = "color",
    scale_min: float = 1.0,
    scale_max: float = 1.0,
    scale_step: float = 0.1,
    debug: bool = False,
) -> list[dict[str, Any]]:
    run_dir = run_dir.resolve()
    screenshots_dir = run_dir / "screenshots"
    if not screenshots_dir.exists():
        raise FileNotFoundError(f"Run screenshots directory does not exist: {screenshots_dir}")

    screenshots = sorted(screenshots_dir.glob("loop-*.png"))
    if not screenshots:
        raise FileNotFoundError(f"No screenshots found: {screenshots_dir / 'loop-*.png'}")

    records = [
        analyze_image(
            screenshot,
            match_mode=match_mode,
            scale_min=scale_min,
            scale_max=scale_max,
            scale_step=scale_step,
            debug=debug,
        )
        for screenshot in screenshots
    ]
    write_run_outputs(run_dir, records)
    return records


def write_run_outputs(run_dir: Path, records: Iterable[dict[str, Any]]) -> None:
    records = list(records)
    journal_path = run_dir / JOURNAL_NAME
    report_path = run_dir / REPORT_NAME

    with journal_path.open("w", encoding="utf-8", newline="\n") as journal:
        for record in records:
            journal.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")

    report_lines = [
        "v2 screen state report",
        f"run_dir: {run_dir}",
        f"screenshots: {len(records)}",
        "",
    ]
    for index, record in enumerate(records, start=1):
        report_lines.extend(report_lines_for_record(record, index=index))
    report_path.write_text("\n".join(report_lines), encoding="utf-8")


def report_lines_for_record(record: dict[str, Any], *, index: int | None = None) -> list[str]:
    prefix = f"[{index}] " if index is not None else ""
    lines = [
        f"{prefix}{record['image']}",
        f"截图尺寸: {record['screen_size'][0]}x{record['screen_size'][1]}",
        f"当前界面状态: {record['screen_state']}",
        f"置信度: {record['confidence']:.3f}",
        f"命中标志: {', '.join(record['matched_markers']) or 'none'}",
        f"排除标志: {', '.join(record['excluded_markers']) or 'none'}",
        f"缺失标志: {', '.join(record['missing_markers']) or 'none'}",
        f"best_marker: {record['best_marker'] or 'none'}",
        f"reason: {record['reason']}",
        f"动作模板: {record['action_template'].get('decision', 'unknown')}",
        f"已加载模板总数: {record['loaded_template_total']}",
        "已加载模板目录:",
    ]
    lines.extend(f"  - {path}" for path in record["loaded_template_dirs"])
    lines.append("每个 marker_name 的模板数量:")
    lines.extend(
        f"  - {name}: {count}"
        for name, count in record["marker_template_counts"].items()
    )
    lines.append("前 20 个最高置信度 detection:")
    for item in record["top_detections"]:
        lines.append(
            "  - "
            f"{item['marker_name']} confidence={item['confidence']:.3f} "
            f"size={item['size']} template={item['template_path']}"
        )
    lines.append("生成的 detections:")
    for name, detection in record["generated_detections"].items():
        lines.append(
            "  - "
            f"{name} confidence={float(detection['confidence']):.3f} "
            f"template={detection['template_path']}"
        )
    if record["debug_warnings"]:
        lines.append("调试提示:")
        lines.extend(f"  - {warning}" for warning in record["debug_warnings"])
    lines.append("")
    return lines


def print_single_record(record: dict[str, Any]) -> None:
    for line in report_lines_for_record(record):
        print(line)


def print_debug_record(record: dict[str, Any]) -> None:
    print_single_record(record)
    print("每个模板的尺寸和最高匹配置信度:")
    score_by_path = {item["template_path"]: item for item in record["template_scores"]}
    for item in record["template_sizes"]:
        score = score_by_path.get(item["path"], {})
        confidence = float(score.get("confidence", 0.0))
        print(
            f"  - {item['marker_name']} size={item['size']} "
            f"confidence={confidence:.3f} template={item['path']}"
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Debug scrap_then_ad_reward_v2 screen state detection from saved screenshots.",
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--image", type=Path, help="Single screenshot image to identify.")
    source.add_argument("--run", type=Path, help="Run directory containing screenshots/loop-*.png.")
    parser.add_argument("--match-mode", choices=["color", "gray", "edge"], default="color")
    parser.add_argument("--scale-min", type=float, default=1.0)
    parser.add_argument("--scale-max", type=float, default=1.0)
    parser.add_argument("--scale-step", type=float, default=0.1)
    parser.add_argument("--debug", action="store_true", help="Print every template score.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.image is not None:
        print_single_record(
            analyze_image(
                args.image,
                match_mode=args.match_mode,
                scale_min=args.scale_min,
                scale_max=args.scale_max,
                scale_step=args.scale_step,
            )
        )
        return 0

    records = analyze_run(
        args.run,
        match_mode=args.match_mode,
        scale_min=args.scale_min,
        scale_max=args.scale_max,
        scale_step=args.scale_step,
        debug=args.debug,
    )
    print(f"识别完成: {len(records)} screenshots")
    print(f"JSONL: {args.run / JOURNAL_NAME}")
    print(f"Report: {args.run / REPORT_NAME}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

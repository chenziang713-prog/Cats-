from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .screen_state_templates import SCREEN_STATE_TEMPLATES
from .screen_state_types import MarkerMatchResult, ScreenStateResult, ScreenStateTemplate


def detect_current_screen_state_from_detections(
    detections: Mapping[str, Any],
    template_registry: Mapping[str, ScreenStateTemplate] | None = None,
    *,
    screenshot_path: str | None = None,
) -> ScreenStateResult:
    """基于现有 detections 判断当前界面状态。

    这里优先复用 runner 已经产出的模板匹配结果，不重新截图、不点击、不修改流程。
    """

    registry = template_registry or SCREEN_STATE_TEMPLATES
    results = [
        _evaluate_template(template, detections, screenshot_path=screenshot_path)
        for template in registry.values()
        if template.state_name != "UNKNOWN"
    ]
    matches = [result for result in results if result.matched]
    if not matches:
        return _unknown_result("没有任何状态命中", screenshot_path=screenshot_path)
    return max(matches, key=lambda result: (result.priority, result.confidence))


def detect_current_screen_state(
    screenshot: str | Path | None,
    template_registry: Mapping[str, ScreenStateTemplate] | None = None,
    matcher: Any | None = None,
) -> ScreenStateResult:
    """统一状态识别入口。

    如果传入 matcher，则尝试按模板配置做匹配；模板文件不存在时安全跳过。
    如果没有 matcher，则返回 UNKNOWN，避免第一阶段重复截图或误触真实流程。
    """

    registry = template_registry or SCREEN_STATE_TEMPLATES
    if screenshot is not None and not Path(screenshot).exists():
        return _unknown_result("截图文件不存在，已安全跳过模板匹配", screenshot_path=_path_text(screenshot))
    if matcher is None:
        return _unknown_result("未提供 matcher，第一阶段不重复截图匹配", screenshot_path=_path_text(screenshot))
    detections: dict[str, MarkerMatchResult] = {}
    marker_names = _collect_marker_names(registry.values())
    for marker_name in marker_names:
        marker_result = _match_marker_safely(marker_name, screenshot, registry.values(), matcher)
        if marker_result is not None and marker_result.matched:
            detections[marker_name] = marker_result
    return detect_current_screen_state_from_detections(
        detections,
        registry,
        screenshot_path=_path_text(screenshot),
    )


def explain_screen_state_result(result: ScreenStateResult) -> str:
    """输出中文调试说明，方便日志里直接查看识别依据。"""

    matched = ", ".join(result.matched_markers) if result.matched_markers else "无"
    excluded = ", ".join(result.excluded_markers) if result.excluded_markers else "无"
    missing = ", ".join(result.missing_markers) if result.missing_markers else "无"
    return "\n".join(
        [
            f"当前界面判断：{result.state_name}",
            f"置信度：{result.confidence:.3f}",
            f"命中标志：{matched}",
            f"缺失标志：{missing}",
            f"排除标志：{excluded}",
            f"原因：{result.reason}",
        ]
    )


def _evaluate_template(
    template: ScreenStateTemplate,
    detections: Mapping[str, Any],
    *,
    screenshot_path: str | None,
) -> ScreenStateResult:
    raw_scores = _raw_scores_for_template(template, detections)
    matched_required_any = _matched_names(template.required_any, raw_scores, template.threshold)
    matched_required_all = _matched_names(template.required_all, raw_scores, template.threshold)
    excluded_markers = _matched_names(template.exclude_any, raw_scores, template.threshold)

    has_required_any = not template.required_any or bool(matched_required_any)
    has_required_all = len(matched_required_all) == len(template.required_all)
    has_excluded = bool(excluded_markers)
    matched = has_required_any and has_required_all and not has_excluded

    required_names = list(dict.fromkeys([*template.required_any, *template.required_all]))
    matched_markers = _matched_names(required_names, raw_scores, template.threshold)
    missing_markers = [
        name for name in required_names
        if name not in matched_markers and not _pattern_has_match(name, raw_scores, template.threshold)
    ]
    confidence = max([raw_scores[name] for name in matched_markers], default=0.0)
    best_marker = None if not matched_markers else max(matched_markers, key=lambda name: raw_scores[name])

    if has_excluded:
        reason = f"命中排除标志：{', '.join(excluded_markers)}"
    elif matched:
        reason = f"命中{template.description}必要标志"
    else:
        reason = "必要标志未命中"

    return ScreenStateResult(
        state_name=template.state_name,
        matched=matched,
        confidence=confidence,
        priority=template.priority,
        matched_markers=matched_markers,
        missing_markers=missing_markers,
        excluded_markers=excluded_markers,
        best_marker=best_marker,
        reason=reason,
        raw_scores=raw_scores,
        screenshot_path=screenshot_path,
    )


def _raw_scores_for_template(template: ScreenStateTemplate, detections: Mapping[str, Any]) -> dict[str, float]:
    marker_patterns = list(dict.fromkeys([*template.required_any, *template.required_all, *template.exclude_any]))
    raw_scores: dict[str, float] = {}
    for pattern in marker_patterns:
        for name, detection in detections.items():
            if _marker_matches(pattern, name):
                raw_scores[name] = max(raw_scores.get(name, 0.0), _confidence(detection))
    return raw_scores


def _matched_names(patterns: list[str], raw_scores: Mapping[str, float], threshold: float) -> list[str]:
    matched: list[str] = []
    for pattern in patterns:
        for name, score in raw_scores.items():
            if _marker_matches(pattern, name) and score >= threshold and name not in matched:
                matched.append(name)
    return matched


def _pattern_has_match(pattern: str, raw_scores: Mapping[str, float], threshold: float) -> bool:
    return any(_marker_matches(pattern, name) and score >= threshold for name, score in raw_scores.items())


def _marker_matches(pattern: str, marker_name: str) -> bool:
    if pattern.endswith("*"):
        return marker_name.startswith(pattern[:-1])
    return marker_name == pattern


def _confidence(detection: Any) -> float:
    if isinstance(detection, MarkerMatchResult):
        return detection.confidence
    if isinstance(detection, Mapping):
        return float(detection.get("confidence", 0.0))
    return float(getattr(detection, "confidence", 0.0))


def _collect_marker_names(templates: Any) -> list[str]:
    names: list[str] = []
    for template in templates:
        for marker_name in [*template.required_any, *template.required_all, *template.exclude_any]:
            if marker_name.endswith("*"):
                continue
            if marker_name not in names:
                names.append(marker_name)
    return names


def _match_marker_safely(
    marker_name: str,
    screenshot: str | Path | None,
    templates: Any,
    matcher: Any,
) -> MarkerMatchResult | None:
    for template in templates:
        for template_dir in template.template_dirs:
            template_path = (Path(__file__).resolve().parent / template_dir / f"{marker_name}.png").resolve()
            if not template_path.exists():
                continue
            try:
                result = matcher(screenshot, template_path, template.threshold)
            except TypeError:
                result = matcher(screenshot=screenshot, template_path=template_path, threshold=template.threshold)
            confidence = _confidence(result)
            return MarkerMatchResult(
                marker_name=marker_name,
                matched=confidence >= template.threshold,
                confidence=confidence,
                center=getattr(result, "center", None),
                template_path=str(template_path),
            )
    return None


def _unknown_result(reason: str, *, screenshot_path: str | None = None) -> ScreenStateResult:
    return ScreenStateResult(
        state_name="UNKNOWN",
        matched=False,
        confidence=0.0,
        priority=-1,
        reason=reason,
        screenshot_path=screenshot_path,
    )


def _path_text(path: str | Path | None) -> str | None:
    return None if path is None else str(path)

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .close_markers import detection_confidence, safe_close_candidates
from .screen_state_templates import ACTIVE_STATE_NAMES, SCREEN_STATE_TEMPLATES
from .screen_state_types import MarkerMatchResult, ScreenStateResult, ScreenStateTemplate
from .template_sources import (
    V2_CANONICAL_TEMPLATE_DIRS,
    collect_canonical_marker_names,
    template_paths_for_marker,
)


def detect_current_screen_state_from_detections(
    detections: Mapping[str, Any],
    template_registry: Mapping[str, ScreenStateTemplate] | None = None,
    *,
    screenshot_path: str | None = None,
) -> ScreenStateResult:
    registry = template_registry or SCREEN_STATE_TEMPLATES
    active_registry = {
        name: template
        for name, template in registry.items()
        if name in ACTIVE_STATE_NAMES and name != "UNKNOWN"
    }
    evaluated = [
        _evaluate_template(template, detections, screenshot_path=screenshot_path)
        for template in active_registry.values()
    ]
    matches = [result for result in evaluated if result.matched]
    candidate_states = [_candidate_record(result) for result in matches]
    if not matches:
        return _unknown_result(
            "no active state markers matched",
            screenshot_path=screenshot_path,
            candidate_states=candidate_states,
            selection_reason="no_state_match",
        )
    if len(matches) > 1:
        return _unknown_result(
            "state_conflict",
            screenshot_path=screenshot_path,
            candidate_states=candidate_states,
            selection_reason="state_conflict",
        )
    selected = matches[0]
    return _with_selection_metadata(
        selected,
        candidate_states=candidate_states,
        selected_state=selected.state_name,
        selection_reason="single_active_state_match",
    )


def detect_current_screen_state(
    screenshot: str | Path | None,
    template_registry: Mapping[str, ScreenStateTemplate] | None = None,
    matcher: Any | None = None,
) -> ScreenStateResult:
    registry = template_registry or SCREEN_STATE_TEMPLATES
    if screenshot is not None and not Path(screenshot).exists():
        return _unknown_result(
            "screenshot file does not exist; skipped template matching",
            screenshot_path=_path_text(screenshot),
        )
    if matcher is None:
        return _unknown_result(
            "matcher was not provided; skipped template matching",
            screenshot_path=_path_text(screenshot),
        )

    detections: dict[str, MarkerMatchResult] = {}
    for marker_name in collect_canonical_marker_names():
        marker_result = _match_marker_safely(marker_name, screenshot, registry.values(), matcher)
        if marker_result is not None and marker_result.matched:
            detections[marker_name] = marker_result
    return detect_current_screen_state_from_detections(
        detections,
        registry,
        screenshot_path=_path_text(screenshot),
    )


def explain_screen_state_result(result: ScreenStateResult) -> str:
    matched = ", ".join(result.matched_markers) if result.matched_markers else "none"
    excluded = ", ".join(result.excluded_markers) if result.excluded_markers else "none"
    missing = ", ".join(result.missing_markers) if result.missing_markers else "none"
    return "\n".join(
        [
            f"current screen state: {result.state_name}",
            f"confidence: {result.confidence:.3f}",
            f"matched_markers: {matched}",
            f"missing_markers: {missing}",
            f"excluded_markers: {excluded}",
            f"best_marker: {result.best_marker or 'none'}",
            f"selection_reason: {result.selection_reason or result.reason}",
            f"reason: {result.reason}",
        ]
    )


def _evaluate_template(
    template: ScreenStateTemplate,
    detections: Mapping[str, Any],
    *,
    screenshot_path: str | None,
) -> ScreenStateResult:
    if template.state_name == "AD_CLOSE_PAGE":
        return _evaluate_ad_close_template(template, detections, screenshot_path=screenshot_path)

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
        name
        for name in required_names
        if name not in matched_markers and not _pattern_has_match(name, raw_scores, template.threshold)
    ]
    confidence = max([raw_scores[name] for name in matched_markers], default=0.0)
    best_marker = None if not matched_markers else max(matched_markers, key=lambda name: raw_scores[name])

    if has_excluded:
        reason = f"excluded marker matched: {', '.join(excluded_markers)}"
    elif matched:
        reason = f"matched required marker(s) for {template.description}"
    else:
        reason = "required markers did not match"

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
        loaded_template_dirs=[str(path) for path in V2_CANONICAL_TEMPLATE_DIRS],
        active_state_names=sorted(ACTIVE_STATE_NAMES),
    )


def _evaluate_ad_close_template(
    template: ScreenStateTemplate,
    detections: Mapping[str, Any],
    *,
    screenshot_path: str | None,
) -> ScreenStateResult:
    raw_scores = _raw_scores_for_template(template, detections)
    excluded_markers = _matched_names(template.exclude_any, raw_scores, template.threshold)
    candidates = safe_close_candidates(detections, min_confidence=template.threshold)
    matched_markers = [candidate.name for candidate in candidates]
    has_excluded = bool(excluded_markers)
    matched = bool(matched_markers) and not has_excluded
    confidence = max((candidate.confidence for candidate in candidates), default=0.0)
    best_marker = None if not candidates else max(candidates, key=lambda item: item.confidence).name
    missing_markers = [] if matched_markers else list(template.required_any)

    if has_excluded:
        reason = f"excluded marker matched: {', '.join(excluded_markers)}"
    elif matched:
        reason = "matched safe close marker(s) with canonical template path and coordinates"
    else:
        reason = "no safe close marker with canonical template path and coordinates matched"

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
        loaded_template_dirs=[str(path) for path in V2_CANONICAL_TEMPLATE_DIRS],
        active_state_names=sorted(ACTIVE_STATE_NAMES),
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
    value = detection_confidence(detection)
    return 0.0 if value is None else value


def _match_marker_safely(
    marker_name: str,
    screenshot: str | Path | None,
    templates: Any,
    matcher: Any,
) -> MarkerMatchResult | None:
    best: MarkerMatchResult | None = None
    threshold = min((template.threshold for template in templates), default=0.80)
    for template_path in template_paths_for_marker(marker_name):
        try:
            result = matcher(screenshot, template_path, threshold)
        except TypeError:
            result = matcher(screenshot=screenshot, template_path=template_path, threshold=threshold)
        confidence = _confidence(result)
        candidate = MarkerMatchResult(
            marker_name=marker_name,
            matched=confidence >= threshold,
            confidence=confidence,
            center=getattr(result, "center", None),
            template_path=str(template_path),
        )
        if best is None or candidate.confidence > best.confidence:
            best = candidate
    return best


def _template_paths_for_marker(marker_name: str, template_dir: str | Path | None = None) -> list[Path]:
    if template_dir is None:
        return template_paths_for_marker(marker_name)
    base = (Path(__file__).resolve().parent / template_dir).resolve()
    if base not in {path.resolve() for path in V2_CANONICAL_TEMPLATE_DIRS}:
        return []
    return template_paths_for_marker(marker_name, (base,))


def _candidate_record(result: ScreenStateResult) -> dict[str, object]:
    return {
        "state": result.state_name,
        "confidence": result.confidence,
        "priority": result.priority,
        "matched_markers": list(result.matched_markers),
        "best_marker": result.best_marker,
        "reason": result.reason,
    }


def _with_selection_metadata(
    result: ScreenStateResult,
    *,
    candidate_states: list[dict[str, object]],
    selected_state: str | None,
    selection_reason: str,
) -> ScreenStateResult:
    return ScreenStateResult(
        state_name=result.state_name,
        matched=result.matched,
        confidence=result.confidence,
        priority=result.priority,
        matched_markers=list(result.matched_markers),
        missing_markers=list(result.missing_markers),
        excluded_markers=list(result.excluded_markers),
        best_marker=result.best_marker,
        reason=result.reason,
        raw_scores=dict(result.raw_scores),
        screenshot_path=result.screenshot_path,
        candidate_states=candidate_states,
        selected_state=selected_state,
        selection_reason=selection_reason,
        loaded_template_dirs=[str(path) for path in V2_CANONICAL_TEMPLATE_DIRS],
        active_state_names=sorted(ACTIVE_STATE_NAMES),
    )


def _unknown_result(
    reason: str,
    *,
    screenshot_path: str | None = None,
    candidate_states: list[dict[str, object]] | None = None,
    selection_reason: str = "",
) -> ScreenStateResult:
    return ScreenStateResult(
        state_name="UNKNOWN",
        matched=False,
        confidence=0.0,
        priority=-1,
        reason=reason,
        screenshot_path=screenshot_path,
        candidate_states=candidate_states or [],
        selected_state="UNKNOWN",
        selection_reason=selection_reason or reason,
        loaded_template_dirs=[str(path) for path in V2_CANONICAL_TEMPLATE_DIRS],
        active_state_names=sorted(ACTIVE_STATE_NAMES),
    )


def _path_text(path: str | Path | None) -> str | None:
    return None if path is None else str(path)

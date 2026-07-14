from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
for path in (REPO_ROOT, SRC_ROOT):
    path_text = str(path)
    if path_text not in sys.path:
        sys.path.insert(0, path_text)

from cats_automatic.strategy_base import DetectionResult
from external_strategies.scrap_then_ad_reward_v2.film_flow import (
    FILM_CLOSE_AD_MAX_TOTAL_CLICKS,
    FILM_ENTRY_MARKER,
    WATCH_AD_MARKER,
    decide_film_flow_action,
)
from external_strategies.scrap_then_ad_reward_v2.state_names import normalize_state_name
from tools.debug_screen_state_v2 import analyze_image


MAX_DECISIONS_PER_IMAGE = 5
PAGE_CHANGING_ACTIONS = {"tap_marker", "press_back"}
STOP_ACTIONS = {*PAGE_CHANGING_ACTIONS, "wait"}


@dataclass
class FilmFlowReplayContext:
    current_step: str = "START"
    close_attempt_count: int = 0
    selected_reward: str | None = None
    last_state: str | None = None
    last_action: str | None = None
    pending_transition: str | None = None
    entry_click_attempts: int = 0
    watch_ad_click_attempts: int = 0
    reward_click_attempts: int = 0


@dataclass
class SequenceStepRecord:
    index: int
    name: str
    image_path: str
    detected_state: str
    expected_state: str | None
    state_matches_expected: bool
    before_step: str
    action: str
    target_marker: str | None
    target_confidence: float | None
    action_reason: str
    after_step: str
    close_attempt_count: int
    state_conflict: bool
    sequence_stuck: bool = False
    failure_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "name": self.name,
            "image_path": self.image_path,
            "detected_state": self.detected_state,
            "expected_state": self.expected_state,
            "state_matches_expected": self.state_matches_expected,
            "before_step": self.before_step,
            "action": self.action,
            "target_marker": self.target_marker,
            "target_confidence": self.target_confidence,
            "action_reason": self.action_reason,
            "after_step": self.after_step,
            "close_attempt_count": self.close_attempt_count,
            "state_conflict": self.state_conflict,
            "sequence_stuck": self.sequence_stuck,
            "failure_reason": self.failure_reason,
        }


@dataclass
class SequenceReplayResult:
    manifest_name: str
    records: list[SequenceStepRecord] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    final_step: str = "START"

    @property
    def total_images(self) -> int:
        return len({record.index for record in self.records})

    @property
    def correct_states(self) -> int:
        seen: dict[int, bool] = {}
        for record in self.records:
            seen.setdefault(record.index, record.state_matches_expected)
        return sum(1 for value in seen.values() if value)

    @property
    def wrong_states(self) -> int:
        seen: dict[int, bool] = {}
        for record in self.records:
            seen.setdefault(record.index, record.state_matches_expected)
        return sum(1 for value in seen.values() if not value)

    @property
    def reached_finish(self) -> bool:
        return self.final_step == "FINISH"

    @property
    def success(self) -> bool:
        return not self.failures and self.reached_finish


Analyzer = Callable[[Path], Mapping[str, Any]]


def replay_manifest(
    manifest_path: Path,
    *,
    analyzer: Analyzer = analyze_image,
    max_decisions_per_image: int = MAX_DECISIONS_PER_IMAGE,
) -> SequenceReplayResult:
    manifest_path = manifest_path.resolve()
    manifest = _load_manifest(manifest_path)
    context = FilmFlowReplayContext()
    result = SequenceReplayResult(manifest_name=str(manifest.get("name", manifest_path.stem)))

    screenshots = manifest.get("screenshots", [])
    if not isinstance(screenshots, list):
        raise ValueError("manifest screenshots must be a list")

    for index, item in enumerate(screenshots, start=1):
        if not isinstance(item, Mapping):
            raise ValueError(f"screenshot entry #{index} must be an object")
        image_path = resolve_manifest_path(str(item.get("image", "")), manifest_path)
        expected_state = _optional_text(item.get("expected_state"))
        expected_action = _optional_text(item.get("expected_action"))
        expected_marker = _optional_text(item.get("expected_marker"))
        record = analyzer(image_path)
        detected_state = str(record.get("selected_state") or record.get("screen_state") or "UNKNOWN")
        detections = detections_from_record(record)
        state_matches = expected_state_matches(detected_state, expected_state)
        state_conflict = str(record.get("selection_reason", "")) == "state_conflict"
        if not state_matches:
            result.failures.append(
                f"{index}:{item.get('name', image_path.name)} state mismatch expected={expected_state} detected={detected_state}"
            )
        if state_conflict:
            result.failures.append(f"{index}:{item.get('name', image_path.name)} state_conflict")

        consume_records = consume_image(
            context,
            image_index=index,
            name=str(item.get("name", image_path.stem)),
            image_path=image_path,
            detected_state=detected_state,
            expected_state=expected_state,
            state_matches_expected=state_matches,
            state_conflict=state_conflict,
            detections=detections,
            max_decisions=max_decisions_per_image,
        )
        result.records.extend(consume_records)

        if expected_action is not None and consume_records:
            actual_action = consume_records[-1].action
            if actual_action != expected_action:
                result.failures.append(
                    f"{index}:{item.get('name', image_path.name)} action mismatch expected={expected_action} actual={actual_action}"
                )
        if expected_marker is not None and consume_records:
            actual_marker = consume_records[-1].target_marker
            if actual_marker != expected_marker:
                result.failures.append(
                    f"{index}:{item.get('name', image_path.name)} marker mismatch expected={expected_marker} actual={actual_marker}"
                )

        for step_record in consume_records:
            if step_record.sequence_stuck or step_record.failure_reason:
                result.failures.append(
                    f"{index}:{step_record.name} {step_record.failure_reason or 'sequence_stuck'}"
                )
        if context.close_attempt_count > FILM_CLOSE_AD_MAX_TOTAL_CLICKS:
            result.failures.append(
                f"{index}:{item.get('name', image_path.name)} close attempts exceeded {FILM_CLOSE_AD_MAX_TOTAL_CLICKS}"
            )

    result.final_step = context.current_step
    if not result.reached_finish:
        result.failures.append(f"final step is {result.final_step}, expected FINISH")
    return result


def consume_image(
    context: FilmFlowReplayContext,
    *,
    image_index: int,
    name: str,
    image_path: Path,
    detected_state: str,
    expected_state: str | None,
    state_matches_expected: bool,
    state_conflict: bool,
    detections: Mapping[str, DetectionResult],
    max_decisions: int = MAX_DECISIONS_PER_IMAGE,
) -> list[SequenceStepRecord]:
    records: list[SequenceStepRecord] = []
    seen: set[tuple[str, str, str, str | None]] = set()

    for _ in range(max_decisions):
        apply_pending_transition(context, detected_state)
        before_step = context.current_step
        decision = decide_film_flow_action(
            step=context.current_step,
            state=detected_state,
            detections=detections,
            entry_click_attempts=context.entry_click_attempts,
            watch_ad_click_attempts=context.watch_ad_click_attempts,
            close_ad_attempts=context.close_attempt_count,
            reward_click_attempts=context.reward_click_attempts,
        )
        action = decision.action
        action_name = str(action.get("name", ""))
        target_marker = _action_marker(action)
        target_confidence = getattr(decision, "selected_confidence", None)
        if target_confidence is None and target_marker in detections:
            target_confidence = detections[target_marker].confidence
        repetition_key = (before_step, detected_state, action_name, target_marker)
        if repetition_key in seen:
            records.append(
                SequenceStepRecord(
                    index=image_index,
                    name=name,
                    image_path=str(image_path),
                    detected_state=detected_state,
                    expected_state=expected_state,
                    state_matches_expected=state_matches_expected,
                    before_step=before_step,
                    action=action_name,
                    target_marker=target_marker,
                    target_confidence=target_confidence,
                    action_reason=decision.reason,
                    after_step=context.current_step,
                    close_attempt_count=context.close_attempt_count,
                    state_conflict=state_conflict,
                    sequence_stuck=True,
                    failure_reason="sequence_stuck",
                )
            )
            break
        seen.add(repetition_key)

        update_context_after_decision(context, decision)
        after_step = context.current_step
        step_changed = after_step != before_step
        record = SequenceStepRecord(
            index=image_index,
            name=name,
            image_path=str(image_path),
            detected_state=detected_state,
            expected_state=expected_state,
            state_matches_expected=state_matches_expected,
            before_step=before_step,
            action=action_name,
            target_marker=target_marker,
            target_confidence=target_confidence,
            action_reason=decision.reason,
            after_step=after_step,
            close_attempt_count=context.close_attempt_count,
            state_conflict=state_conflict,
        )
        records.append(record)
        context.last_state = detected_state
        context.last_action = action_name

        if after_step == "FINISH":
            break
        if action_name in STOP_ACTIONS:
            break
        if action_name == "no_action" and step_changed:
            continue
        if not step_changed:
            record.sequence_stuck = True
            record.failure_reason = "sequence_stuck"
            break

    else:
        if records:
            records[-1].sequence_stuck = True
            records[-1].failure_reason = "sequence_stuck"

    return records


def update_context_after_decision(context: FilmFlowReplayContext, decision: Any) -> None:
    action = decision.action
    action_name = str(action.get("name", ""))
    marker = _action_marker(action)
    context.current_step = decision.next_step

    if action_name == "tap_marker":
        if marker == FILM_ENTRY_MARKER:
            context.entry_click_attempts += 1
            context.pending_transition = "SELECT_REWARD"
        elif marker == WATCH_AD_MARKER:
            context.watch_ad_click_attempts += 1
            context.pending_transition = "WATCH_AD"
        elif marker:
            context.close_attempt_count += 1
            context.pending_transition = "CLOSE_AD_DOING"
    elif action_name == "press_back":
        context.pending_transition = decision.next_step
    elif action_name == "no_action" and decision.next_step == "CLAIM_REWARD":
        context.close_attempt_count = 0

    if action_name == "tap_marker" and marker == "select_reward_mode":
        context.selected_reward = marker


def apply_pending_transition(context: FilmFlowReplayContext, detected_state: str) -> None:
    if context.pending_transition is None:
        return
    if context.pending_transition == "WATCH_AD" and detected_state in {"UNKNOWN", "UNKNOWN_PAGE", "AD_CLOSE_PAGE"}:
        context.current_step = "WATCH_AD"
        context.pending_transition = None
    elif context.pending_transition == "SELECT_REWARD" and detected_state == "FILM_WATCH_PAGE":
        context.current_step = "SELECT_REWARD"
        context.pending_transition = None
    elif context.pending_transition == "CLOSE_AD_DOING" and detected_state in {
        "AD_CLOSE_PAGE",
        "RIGHT_AD_REWARD_SUCCESS_PAGE",
        "HOME",
        "HOME_PAGE",
        "UNKNOWN",
        "UNKNOWN_PAGE",
    }:
        context.current_step = "CLOSE_AD_DOING"
        context.pending_transition = None
    elif context.pending_transition == "RETURN_HOME" and detected_state in {"HOME", "HOME_PAGE"}:
        context.current_step = "RETURN_HOME"
        context.pending_transition = None


def detections_from_record(record: Mapping[str, Any]) -> dict[str, DetectionResult]:
    detections: dict[str, DetectionResult] = {}
    generated = record.get("generated_detections", {})
    if not isinstance(generated, Mapping):
        return detections
    score_by_marker = _best_template_score_by_marker(record.get("template_scores", []))
    for name, raw in generated.items():
        if not isinstance(raw, Mapping):
            continue
        confidence = _float(raw.get("confidence"), 0.0)
        center = _pair(raw.get("center")) or (0, 0)
        score = score_by_marker.get(str(name), {})
        size = _pair(score.get("size")) or (1, 1)
        top_left = (center[0] - size[0] // 2, center[1] - size[1] // 2)
        detections[str(name)] = DetectionResult(
            name=str(name),
            template=Path(str(raw.get("template_path") or score.get("template_path") or f"{name}.png")),
            confidence=confidence,
            center=center,
            top_left=top_left,
            size=size,
            scale=1.0,
            threshold=0.0,
        )
    return detections


def expected_state_matches(detected_state: str, expected_state: str | None) -> bool:
    if expected_state is None:
        return True
    _, normalized_detected = normalize_state_name(detected_state)
    _, normalized_expected = normalize_state_name(expected_state)
    return normalized_detected == normalized_expected


def resolve_manifest_path(value: str, manifest_path: Path) -> Path:
    if not value:
        raise ValueError("screenshot image path is required")
    raw = Path(value)
    if raw.is_absolute():
        return raw
    manifest_relative = (manifest_path.parent / raw).resolve()
    if manifest_relative.exists():
        return manifest_relative
    return (REPO_ROOT / raw).resolve()


def print_report(result: SequenceReplayResult) -> None:
    print(f"Manifest: {result.manifest_name}")
    print("")
    for record in result.records:
        print(f"[{record.index}] {record.name}")
        print(f"  screenshot: {record.image_path}")
        print(f"  detected_state: {record.detected_state}")
        print(f"  expected_state: {record.expected_state or 'none'}")
        print(f"  state_ok: {record.state_matches_expected}")
        print(f"  before_step: {record.before_step}")
        print(f"  action: {record.action}")
        print(f"  target_marker: {record.target_marker or 'none'}")
        print(
            "  target_confidence: "
            f"{record.target_confidence:.3f}" if record.target_confidence is not None else "  target_confidence: none"
        )
        print(f"  action_reason: {record.action_reason}")
        print(f"  after_step: {record.after_step}")
        print(f"  close_attempt_count: {record.close_attempt_count}")
        print(f"  state_conflict: {record.state_conflict}")
        if record.sequence_stuck or record.failure_reason:
            print(f"  failure: {record.failure_reason or 'sequence_stuck'}")
        print("")
    print("Summary")
    print(f"  total_images: {result.total_images}")
    print(f"  correct_states: {result.correct_states}")
    print(f"  wrong_states: {result.wrong_states}")
    print(f"  final_step: {result.final_step}")
    print(f"  reached_finish: {result.reached_finish}")
    if result.failures:
        print("  failures:")
        for failure in result.failures:
            print(f"    - {failure}")
    else:
        print("  failures: none")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Replay a v2 film reward flow from ordered screenshots without ADB or real clicks.",
    )
    parser.add_argument("--manifest", type=Path, required=True, help="JSON manifest with ordered screenshots.")
    parser.add_argument("--max-decisions-per-image", type=int, default=MAX_DECISIONS_PER_IMAGE)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = replay_manifest(
        args.manifest,
        max_decisions_per_image=max(1, args.max_decisions_per_image),
    )
    print_report(result)
    return 0 if result.success else 1


def _load_manifest(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError("manifest root must be an object")
    return data


def _best_template_score_by_marker(raw_scores: Any) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    if not isinstance(raw_scores, Iterable) or isinstance(raw_scores, (str, bytes, Mapping)):
        return result
    for raw in raw_scores:
        if not isinstance(raw, Mapping):
            continue
        marker = str(raw.get("marker_name", ""))
        if not marker:
            continue
        current = result.get(marker)
        if current is None or _float(raw.get("confidence"), 0.0) > _float(current.get("confidence"), 0.0):
            result[marker] = raw
    return result


def _action_marker(action: Mapping[str, Any]) -> str | None:
    params = action.get("params", {})
    if not isinstance(params, Mapping):
        return None
    marker = params.get("marker")
    return None if marker is None else str(marker)


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _pair(value: Any) -> tuple[int, int] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    try:
        return int(value[0]), int(value[1])
    except (TypeError, ValueError):
        return None


def _float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


if __name__ == "__main__":
    raise SystemExit(main())

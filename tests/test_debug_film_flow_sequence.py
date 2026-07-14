from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from PIL import Image

from external_strategies.scrap_then_ad_reward_v2.close_markers import (
    SAFE_CLOSE_MARKER_PATTERNS,
    is_canonical_v2_template_path,
    marker_matches_patterns,
)
from external_strategies.scrap_then_ad_reward_v2.film_flow import CLOSE_AD_MIN_CONFIDENCE
from external_strategies.scrap_then_ad_reward_v2.screen_state_detector import _template_paths_for_marker
from tools import debug_film_flow_sequence as sequence


ROOT = Path(__file__).resolve().parents[1]


def test_flow_context_does_not_reset_between_screenshots(tmp_path: Path) -> None:
    manifest = _manifest(
        tmp_path,
        [
            ("home", "HOME", _record("HOME", {"main-definate": 0.96, "ad_entry": 0.92})),
            ("film", "FILM_WATCH_PAGE", _record("FILM_WATCH_PAGE", {"watch_ad_film": 0.93})),
        ],
    )

    result = sequence.replay_manifest(manifest, analyzer=_analyzer(_records(manifest)))

    second_first_record = next(record for record in result.records if record.index == 2)
    assert second_first_record.before_step == "SELECT_REWARD"
    assert result.final_step == "START_AD"


def test_same_screenshot_allows_no_action_step_progress(tmp_path: Path) -> None:
    manifest = _manifest(
        tmp_path,
        [("home", "HOME", _record("HOME", {"main-definate": 0.96, "ad_entry": 0.92}))],
    )

    result = sequence.replay_manifest(manifest, analyzer=_analyzer(_records(manifest)))

    assert [(record.before_step, record.action, record.after_step) for record in result.records] == [
        ("START", "no_action", "GO_HOME"),
        ("GO_HOME", "no_action", "ENTER_FILM"),
        ("ENTER_FILM", "tap_marker", "ENTER_FILM"),
    ]


def test_page_changing_actions_and_wait_stop_current_image(tmp_path: Path) -> None:
    manifest = _manifest(
        tmp_path,
        [
            ("home", "HOME", _record("HOME", {"main-definate": 0.96, "ad_entry": 0.92})),
            ("film", "FILM_WATCH_PAGE", _record("FILM_WATCH_PAGE", {"watch_ad_film": 0.93})),
            ("ad_playing", "UNKNOWN", _record("UNKNOWN", {})),
        ],
    )

    result = sequence.replay_manifest(manifest, analyzer=_analyzer(_records(manifest)))

    assert [record.action for record in result.records if record.index == 1][-1] == "tap_marker"
    assert [record.action for record in result.records if record.index == 2][-1] == "tap_marker"
    assert [record.action for record in result.records if record.index == 3] == ["wait"]


def test_repeated_no_progress_triggers_sequence_stuck(tmp_path: Path, monkeypatch) -> None:
    manifest = _manifest(tmp_path, [("finished", "HOME", _record("HOME", {"main-definate": 0.96}))])
    records = _records(manifest)
    context = sequence.FilmFlowReplayContext(current_step="GO_HOME")

    class NoProgressDecision:
        action = {"name": "no_action", "params": {}, "reason": "no_progress"}
        next_step = "GO_HOME"
        reason = "no_progress"

    monkeypatch.setattr(sequence, "decide_film_flow_action", lambda **_kwargs: NoProgressDecision())

    consumed = sequence.consume_image(
        context,
        image_index=1,
        name="finished",
        image_path=Path(json.loads(manifest.read_text(encoding="utf-8"))["screenshots"][0]["image"]),
        detected_state="HOME",
        expected_state="HOME",
        state_matches_expected=True,
        state_conflict=False,
        detections=sequence.detections_from_record(records[next(iter(records))]),
    )

    assert consumed[-1].sequence_stuck is True
    assert consumed[-1].failure_reason == "sequence_stuck"


def test_complete_constructed_sequence_reaches_finish(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path, _full_sequence_records())

    result = sequence.replay_manifest(manifest, analyzer=_analyzer(_records(manifest)))

    assert result.success is True
    assert result.final_step == "FINISH"
    assert result.records[-1].after_step == "FINISH"


def test_tool_does_not_call_adb_or_action_backend(tmp_path: Path, monkeypatch) -> None:
    def forbidden(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("ActionBackend should not be used by offline sequence replay")

    monkeypatch.setattr("cats_automatic.actions.execute_action", forbidden)
    manifest = _manifest(tmp_path, _full_sequence_records())

    result = sequence.replay_manifest(manifest, analyzer=_analyzer(_records(manifest)))

    assert result.success is True


def test_wrong_state_returns_nonzero_exit_code(tmp_path: Path, monkeypatch) -> None:
    manifest = _manifest(
        tmp_path,
        [("home", "FILM_WATCH_PAGE", _record("HOME", {"main-definate": 0.96, "ad_entry": 0.92}))],
    )
    monkeypatch.setattr(sequence, "analyze_image", _analyzer(_records(manifest)))

    exit_code = sequence.main(["--manifest", str(manifest)])

    assert exit_code != 0


def test_wrong_action_returns_nonzero_exit_code(tmp_path: Path, monkeypatch) -> None:
    image = tmp_path / "home.png"
    Image.new("RGB", (20, 20), "white").save(image)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "name": "wrong_action",
                "screenshots": [
                    {
                        "name": "home",
                        "image": str(image),
                        "expected_state": "HOME",
                        "expected_action": "wait",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        sequence,
        "analyze_image",
        lambda _path: _record("HOME", {"main-definate": 0.96, "ad_entry": 0.92}),
    )

    exit_code = sequence.main(["--manifest", str(manifest)])

    assert exit_code != 0


def test_path_with_spaces_can_be_read(tmp_path: Path) -> None:
    spaced = tmp_path / "dir with spaces" / "screen with spaces.png"
    spaced.parent.mkdir()
    Image.new("RGB", (20, 20), "white").save(spaced)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "name": "spaces",
                "screenshots": [
                    {
                        "name": "space_path",
                        "image": str(spaced),
                        "expected_state": "UNKNOWN",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = sequence.replay_manifest(manifest, analyzer=lambda path: _record("UNKNOWN", {}, image=path))

    assert result.records[0].image_path == str(spaced)


def test_scheme_b_ad_close_semantics_are_preserved(tmp_path: Path) -> None:
    manifest = _manifest(
        tmp_path,
        [
            ("home", "HOME", _record("HOME", {"main-definate": 0.96, "ad_entry": 0.92})),
            ("film", "FILM_WATCH_PAGE", _record("FILM_WATCH_PAGE", {"watch_ad_film": 0.93})),
            ("playing", "UNKNOWN", _record("UNKNOWN", {})),
            ("close", "AD_CLOSE_PAGE", _record("AD_CLOSE_PAGE", {"close_buttons": 0.94})),
        ],
    )

    result = sequence.replay_manifest(manifest, analyzer=_analyzer(_records(manifest)))
    close_record = [record for record in result.records if record.index == 4][-1]

    assert close_record.before_step == "WATCH_AD"
    assert close_record.action == "tap_marker"
    assert close_record.target_marker == "close_buttons"
    assert close_record.after_step == "CLOSE_AD_DOING"
    assert close_record.close_attempt_count == 1


def test_real_film_flow_sequence_reaches_finish_without_real_actions() -> None:
    manifest = ROOT / "test modes" / "film_flow_sequence" / "film_flow_sequence.json"

    result = sequence.replay_manifest(manifest)
    close_record = [record for record in result.records if record.name == "ad_close"][-1]

    assert result.success is True
    assert result.correct_states == 6
    assert result.wrong_states == 0
    assert result.final_step == "FINISH"
    assert result.sequence_stuck is False
    assert result.real_action_count == 0
    assert close_record.action == "tap_marker"
    assert close_record.target_marker == "close_buttons"
    assert close_record.target_confidence is not None
    assert close_record.target_confidence >= CLOSE_AD_MIN_CONFIDENCE
    assert marker_matches_patterns(close_record.target_marker, SAFE_CLOSE_MARKER_PATTERNS)


def test_real_ad_close_record_uses_canonical_close_template_and_coordinates() -> None:
    record = sequence.analyze_image(ROOT / "test modes" / "film_flow_sequence" / "04_ad_close.png")
    detections = sequence.detections_from_record(record)
    close_detection = detections["close_buttons"]

    assert record["screen_state"] == "AD_CLOSE_PAGE"
    assert close_detection.center == (1232, 49)
    assert is_canonical_v2_template_path(close_detection.template)


def _full_sequence_records() -> list[tuple[str, str, Mapping[str, Any]]]:
    return [
        ("home", "HOME", _record("HOME", {"main-definate": 0.96, "ad_entry": 0.92})),
        ("film_select", "FILM_WATCH_PAGE", _record("FILM_WATCH_PAGE", {"watch_ad_film": 0.93})),
        ("ad_playing", "UNKNOWN", _record("UNKNOWN", {})),
        ("ad_close", "AD_CLOSE_PAGE", _record("AD_CLOSE_PAGE", {"close_buttons": 0.94})),
        ("reward", "RIGHT_AD_REWARD_SUCCESS_PAGE", _record("RIGHT_AD_REWARD_SUCCESS_PAGE", {"get_reward": 0.91})),
        ("home_after", "HOME", _record("HOME", {"main-definate": 0.96})),
    ]


def _manifest(tmp_path: Path, entries: list[tuple[str, str, Mapping[str, Any]]]) -> Path:
    screenshots = []
    for name, expected_state, record in entries:
        image = tmp_path / f"{name}.png"
        Image.new("RGB", (20, 20), "white").save(image)
        screenshots.append({"name": name, "image": str(image), "expected_state": expected_state})
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({"name": "test_flow", "screenshots": screenshots}), encoding="utf-8")
    return path


def _records(manifest: Path) -> dict[str, Mapping[str, Any]]:
    data = json.loads(manifest.read_text(encoding="utf-8"))
    records: dict[str, Mapping[str, Any]] = {}
    for screenshot in data["screenshots"]:
        name = screenshot["name"]
        records[str(Path(screenshot["image"]).resolve())] = _RECORD_FIXTURES[name]
    return records


def _analyzer(records: Mapping[str, Mapping[str, Any]]):
    def analyze(path: Path) -> Mapping[str, Any]:
        return records[str(path.resolve())]

    return analyze


def _record(state: str, markers: Mapping[str, float], *, image: Path | None = None) -> dict[str, Any]:
    detections = {
        name: {
            "confidence": confidence,
            "center": [100, 120],
            "template_path": _template_path(name),
        }
        for name, confidence in markers.items()
    }
    return {
        "image": None if image is None else str(image),
        "screen_state": state,
        "selected_state": state,
        "selection_reason": "single_active_state_match" if state != "UNKNOWN" else "no_state_match",
        "generated_detections": detections,
        "template_scores": [
            {
                "marker_name": name,
                "template_path": _template_path(name),
                "confidence": confidence,
                "size": [20, 20],
            }
            for name, confidence in markers.items()
        ],
    }


def _template_path(name: str) -> str:
    paths = _template_paths_for_marker(name)
    return str(paths[0]) if paths else f"{name}.png"


_RECORD_FIXTURES = {
    "home": _record("HOME", {"main-definate": 0.96, "ad_entry": 0.92}),
    "film": _record("FILM_WATCH_PAGE", {"watch_ad_film": 0.93}),
    "film_select": _record("FILM_WATCH_PAGE", {"watch_ad_film": 0.93}),
    "ad_playing": _record("UNKNOWN", {}),
    "playing": _record("UNKNOWN", {}),
    "ad_close": _record("AD_CLOSE_PAGE", {"close_buttons": 0.94}),
    "close": _record("AD_CLOSE_PAGE", {"close_buttons": 0.94}),
    "reward": _record("RIGHT_AD_REWARD_SUCCESS_PAGE", {"get_reward": 0.91}),
    "home_after": _record("HOME", {"main-definate": 0.96}),
    "home_after_reward": _record("HOME", {"main-definate": 0.96}),
    "unknown": _record("UNKNOWN", {}),
    "finished": _record("HOME", {"main-definate": 0.96}),
}

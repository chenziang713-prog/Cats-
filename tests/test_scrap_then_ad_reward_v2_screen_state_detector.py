from __future__ import annotations

from pathlib import Path

from external_strategies.scrap_then_ad_reward_v2.screen_state_detector import (
    _template_paths_for_marker,
    detect_current_screen_state,
    detect_current_screen_state_from_detections,
    explain_screen_state_result,
)
from external_strategies.scrap_then_ad_reward_v2.screen_state_templates import SCREEN_STATE_TEMPLATES
from external_strategies.scrap_then_ad_reward_v2.screen_state_types import ScreenStateResult
from external_strategies.scrap_then_ad_reward_v2.state_action_templates import STATE_ACTION_HANDLERS
from external_strategies.scrap_then_ad_reward_v2.strategy import decide_next_action


def test_home_ignores_action_only_ad_entry() -> None:
    result = detect_current_screen_state_from_detections(
        {"main-definate": {"confidence": 0.91}, "ad_entry": {"confidence": 0.90}}
    )

    assert result.state_name == "HOME"
    assert result.matched is True
    assert result.selected_state == "HOME"


def test_film_watch_page_matches_watch_marker() -> None:
    result = detect_current_screen_state_from_detections(
        {"watch_ad_film": {"confidence": 0.93}}
    )

    assert result.state_name == "FILM_WATCH_PAGE"


def test_ad_close_page_matches_close_ad() -> None:
    result = detect_current_screen_state_from_detections(
        {"close_buttons": _close_button_detection(0.94)}
    )

    assert result.state_name == "AD_CLOSE_PAGE"
    assert result.matched_markers == ["close_buttons"]


def test_ad_close_page_rejects_close_marker_without_coordinates() -> None:
    result = detect_current_screen_state_from_detections(
        {
            "close_buttons": {
                "confidence": 0.94,
                "template_path": str(_template_paths_for_marker("close_buttons")[0]),
            }
        }
    )

    assert result.state_name == "UNKNOWN"


def test_reward_success_page_requires_own_markers() -> None:
    result = detect_current_screen_state_from_detections(
        {
            "right_ad_reward_success_buttons": {"confidence": 0.91},
            "right_ad_reward_success_marker": {"confidence": 0.92},
        }
    )

    assert result.state_name == "RIGHT_AD_REWARD_SUCCESS_PAGE"


def test_error_buttons_alone_are_action_only_and_do_not_create_error_page() -> None:
    result = detect_current_screen_state_from_detections(
        {"error_buttons": {"confidence": 0.96}}
    )

    assert result.state_name == "UNKNOWN"


def test_error_popup_body_plus_error_button_creates_error_page() -> None:
    result = detect_current_screen_state_from_detections(
        {
            "error_popups": {"confidence": 0.91},
            "error_buttons": {"confidence": 0.96},
        }
    )

    assert result.state_name == "ERROR_POPUP_PAGE"
    assert result.matched_markers == ["error_popups"]


def test_retry_buttons_alone_are_action_only_and_do_not_create_error_page() -> None:
    result = detect_current_screen_state_from_detections(
        {"retry_buttons": {"confidence": 0.96}}
    )

    assert result.state_name == "UNKNOWN"


def test_error_popup_body_plus_retry_button_creates_error_page() -> None:
    result = detect_current_screen_state_from_detections(
        {
            "error_popups": {"confidence": 0.91},
            "retry_buttons": {"confidence": 0.96},
        }
    )

    assert result.state_name == "ERROR_POPUP_PAGE"
    assert result.matched_markers == ["error_popups"]


def test_ad_playing_without_reliable_marker_is_unknown() -> None:
    result = detect_current_screen_state_from_detections({})

    assert result.state_name == "UNKNOWN"
    assert result.selection_reason == "no_state_match"


def test_conflicting_active_states_return_unknown() -> None:
    result = detect_current_screen_state_from_detections(
        {
            "main-definate": {"confidence": 0.90},
            "watch_ad_film": {"confidence": 0.91},
        }
    )

    assert result.state_name == "UNKNOWN"
    assert result.reason == "state_conflict"


def test_missing_template_images_are_skipped_safely() -> None:
    result = detect_current_screen_state(
        Path("missing-screen.png"),
        SCREEN_STATE_TEMPLATES,
        matcher=lambda *_args, **_kwargs: {"confidence": 1.0},
    )

    assert result.state_name == "UNKNOWN"


def test_state_action_templates_return_no_action() -> None:
    screen_state = ScreenStateResult(
        state_name="HOME",
        matched=True,
        confidence=0.9,
        priority=10,
    )

    for handler in STATE_ACTION_HANDLERS.values():
        result = handler(None, screen_state)
        assert result["decision"] == "no_action"


def test_decide_next_action_returns_no_action_in_phase_one() -> None:
    screen_state = ScreenStateResult(
        state_name="HOME",
        matched=True,
        confidence=0.9,
        priority=10,
    )

    result = decide_next_action("WAIT_HOME", screen_state, None)

    assert result["decision"] == "no_action"
    assert result["reason"] == "flow_controller_not_implemented_yet"


def test_explain_screen_state_result_outputs_debug_fields() -> None:
    screen_state = ScreenStateResult(
        state_name="HOME",
        matched=True,
        confidence=0.946,
        priority=50,
        matched_markers=["main-definate"],
        reason="matched",
        selection_reason="single_active_state_match",
    )

    explanation = explain_screen_state_result(screen_state)

    assert "current screen state: HOME" in explanation
    assert "confidence: 0.946" in explanation
    assert "selection_reason: single_active_state_match" in explanation


def _close_button_detection(confidence: float) -> dict[str, object]:
    return {
        "confidence": confidence,
        "center": (100, 40),
        "template_path": str(_template_paths_for_marker("close_buttons")[0]),
    }

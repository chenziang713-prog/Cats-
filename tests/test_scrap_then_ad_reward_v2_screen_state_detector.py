from __future__ import annotations

from pathlib import Path

from external_strategies.scrap_then_ad_reward_v2.screen_state_detector import (
    detect_current_screen_state,
    detect_current_screen_state_from_detections,
    explain_screen_state_result,
)
from external_strategies.scrap_then_ad_reward_v2.screen_state_templates import SCREEN_STATE_TEMPLATES
from external_strategies.scrap_then_ad_reward_v2.screen_state_types import (
    ScreenStateResult,
    ScreenStateTemplate,
)
from external_strategies.scrap_then_ad_reward_v2.state_action_templates import STATE_ACTION_HANDLERS
from external_strategies.scrap_then_ad_reward_v2.strategy import decide_next_action


def test_home_matches_scrap_or_ad_entry_without_exclusions() -> None:
    result = detect_current_screen_state_from_detections(
        {"main-definate": {"confidence": 0.91}, "scrap_entry": {"confidence": 0.91}, "ad_entry": {"confidence": 0.90}}
    )

    assert result.state_name == "HOME"
    assert result.matched is True


def test_home_is_excluded_when_battle_button_appears() -> None:
    result = detect_current_screen_state_from_detections(
        {"scrap_entry": {"confidence": 0.91}, "battle_button": {"confidence": 0.92}}
    )

    assert result.state_name != "HOME"
    assert result.state_name == "SCRAP_BATTLE_PAGE"


def test_scrap_battle_page_matches_battle_button() -> None:
    result = detect_current_screen_state_from_detections(
        {"battle_button": {"confidence": 0.93}}
    )

    assert result.state_name == "SCRAP_BATTLE_PAGE"


def test_battle_result_priority_beats_normal_page() -> None:
    result = detect_current_screen_state_from_detections(
        {
            "battle_button": {"confidence": 0.96},
            "battle_result_popup": {"confidence": 0.90},
            "confirm_button": {"confidence": 0.89},
        }
    )

    assert result.state_name == "BATTLE_RESULT_PAGE"


def test_ad_close_page_matches_close_ad() -> None:
    result = detect_current_screen_state_from_detections(
        {"close_ad": {"confidence": 0.94}}
    )

    assert result.state_name == "AD_CLOSE_PAGE"


def test_special_chest_page_matches_open_button() -> None:
    result = detect_current_screen_state_from_detections(
        {"chest_open_button": {"confidence": 0.95}}
    )

    assert result.state_name == "SPECIAL_CHEST_PAGE"


def test_high_priority_wins_when_multiple_states_match() -> None:
    registry = {
        "LOW": ScreenStateTemplate(
            state_name="LOW",
            required_any=["same_marker"],
            threshold=0.8,
            priority=1,
            description="低优先级状态",
        ),
        "HIGH": ScreenStateTemplate(
            state_name="HIGH",
            required_any=["same_marker"],
            threshold=0.8,
            priority=2,
            description="高优先级状态",
        ),
    }

    result = detect_current_screen_state_from_detections(
        {"same_marker": {"confidence": 0.90}},
        registry,
    )

    assert result.state_name == "HIGH"


def test_confidence_wins_when_priority_is_same() -> None:
    registry = {
        "A": ScreenStateTemplate(
            state_name="A",
            required_any=["marker_a"],
            threshold=0.8,
            priority=5,
            description="状态 A",
        ),
        "B": ScreenStateTemplate(
            state_name="B",
            required_any=["marker_b"],
            threshold=0.8,
            priority=5,
            description="状态 B",
        ),
    }

    result = detect_current_screen_state_from_detections(
        {"marker_a": {"confidence": 0.88}, "marker_b": {"confidence": 0.96}},
        registry,
    )

    assert result.state_name == "B"


def test_unknown_when_no_state_matches() -> None:
    result = detect_current_screen_state_from_detections({})

    assert result.state_name == "UNKNOWN"


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


def test_explain_screen_state_result_outputs_chinese_text() -> None:
    screen_state = ScreenStateResult(
        state_name="SCRAP_BATTLE_PAGE",
        matched=True,
        confidence=0.946,
        priority=50,
        matched_markers=["battle_button"],
        reason="命中废铁对战页必要标志",
    )

    explanation = explain_screen_state_result(screen_state)

    assert "当前界面判断：SCRAP_BATTLE_PAGE" in explanation
    assert "置信度：0.946" in explanation

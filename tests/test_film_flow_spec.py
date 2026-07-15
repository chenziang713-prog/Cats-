from __future__ import annotations

from pathlib import Path

from cats_automatic.actions import DEFAULT_TAP_MARKER_ALLOW_LIST
from cats_automatic.strategy_base import DetectionResult
from external_strategies.scrap_then_ad_reward_v2.film_flow import (
    FILM_CLOSE_AD_MAX_TOTAL_CLICKS,
    FILM_FLOW_RULES,
    FILM_REGISTERED_MARKERS,
    FILM_RULE_VALIDATION_TAP_MARKER_ALLOW_LIST,
    FILM_STATE_TEMPLATES,
    FILM_STATES,
    FILM_STEPS,
    FILM_UNRESOLVED_CONFIRMATIONS,
    V2_SAFE_CLOSE_MARKER_ALLOW_LIST,
    decide_film_flow_action,
)
from external_strategies.scrap_then_ad_reward_v2.screen_state_detector import _template_paths_for_marker
from external_strategies.scrap_then_ad_reward_v2.validation import validate_strategy_config


def test_film_flow_steps_and_states_match_spec() -> None:
    assert FILM_STEPS == (
        "START",
        "GO_HOME",
        "ENTER_FILM",
        "SELECT_REWARD",
        "START_AD",
        "WATCH_AD",
        "CLOSE_AD_DOING",
        "CLAIM_REWARD",
        "RETURN_HOME",
        "FINISH",
    )
    assert "FILM_WATCH_PAGE" in FILM_STATES
    assert "AD_CLOSE_PAGE" in FILM_STATES
    assert "AD_RUNNING_PAGE" not in FILM_STATES


def test_film_flow_rules_validate_with_draft_allow_list_only() -> None:
    report = validate_strategy_config(
        states=FILM_STATE_TEMPLATES,
        flow_rules=FILM_FLOW_RULES,
        registered_markers=FILM_REGISTERED_MARKERS,
        supported_actions=("wait", "no_action", "press_back", "tap_marker"),
        known_steps=FILM_STEPS,
        aliases={},
        tap_marker_allow_list=FILM_RULE_VALIDATION_TAP_MARKER_ALLOW_LIST,
    )

    assert report.errors == []


def test_film_business_markers_are_not_enabled_in_production_allow_list() -> None:
    assert "ad_entry" not in DEFAULT_TAP_MARKER_ALLOW_LIST
    assert "watch_ad_film" not in DEFAULT_TAP_MARKER_ALLOW_LIST
    assert "get_reward" not in DEFAULT_TAP_MARKER_ALLOW_LIST


def test_unresolved_detector_questions_are_explicit() -> None:
    joined = "\n".join(FILM_UNRESOLVED_CONFIRMATIONS)

    assert "4 close-ad click limit" in joined


def test_start_goes_to_go_home_without_real_action() -> None:
    decision = decide_film_flow_action(step="START", state="UNKNOWN_PAGE", detections={})

    assert decision.action["name"] == "no_action"
    assert decision.next_step == "GO_HOME"


def test_enter_film_home_taps_ad_entry_when_marker_exists() -> None:
    decision = decide_film_flow_action(
        step="ENTER_FILM",
        state="HOME_PAGE",
        detections={"ad_entry": _detection("ad_entry", 0.91)},
    )

    assert decision.action["name"] == "tap_marker"
    assert decision.action["params"]["marker"] == "ad_entry"
    assert decision.next_step == "ENTER_FILM"
    assert decision.reason == "film_entry_marker_selected"


def test_enter_film_missing_ad_entry_waits() -> None:
    decision = decide_film_flow_action(step="ENTER_FILM", state="HOME_PAGE", detections={})

    assert decision.action["name"] == "wait"
    assert decision.next_step == "ENTER_FILM"
    assert decision.reason == "film_entry_marker_not_found"


def test_select_reward_missing_optional_marker_does_not_block() -> None:
    decision = decide_film_flow_action(step="SELECT_REWARD", state="FILM_WATCH_PAGE", detections={})

    assert decision.action["name"] == "no_action"
    assert decision.next_step == "START_AD"
    assert decision.reason == "optional_reward_marker_not_found"


def test_select_reward_taps_user_optional_reward_template() -> None:
    decision = decide_film_flow_action(
        step="SELECT_REWARD",
        state="FILM_WATCH_PAGE",
        detections={"pre_watch_optional": _detection("pre_watch_optional", 0.91)},
    )

    assert decision.action["name"] == "tap_marker"
    assert decision.action["params"]["marker"] == "pre_watch_optional"
    assert decision.next_step == "START_AD"
    assert decision.reason == "optional_reward_marker_selected"


def test_select_reward_chooses_highest_confidence_reward_template() -> None:
    decision = decide_film_flow_action(
        step="SELECT_REWARD",
        state="FILM_WATCH_PAGE",
        detections={
            "select_reward_mode": _detection("select_reward_mode", 0.86),
            "pre_watch_optional": _detection("pre_watch_optional", 0.94),
        },
    )

    assert decision.action["params"]["marker"] == "pre_watch_optional"


def test_start_ad_taps_watch_ad_film_and_waits_for_confirmation() -> None:
    decision = decide_film_flow_action(
        step="START_AD",
        state="FILM_WATCH_PAGE",
        detections={"watch_ad_film": _detection("watch_ad_film", 0.93)},
    )

    assert decision.action["name"] == "tap_marker"
    assert decision.action["params"]["marker"] == "watch_ad_film"
    assert decision.next_step == "START_AD"


def test_start_ad_can_tap_user_watch_button_template() -> None:
    decision = decide_film_flow_action(
        step="START_AD",
        state="FILM_WATCH_PAGE",
        detections={"watch_user_001": _detection("watch_user_001", 0.97)},
    )

    assert decision.action["name"] == "tap_marker"
    assert decision.action["params"]["marker"] == "watch_user_001"
    assert decision.next_step == "START_AD"


def test_start_ad_user_watch_button_below_threshold_waits() -> None:
    decision = decide_film_flow_action(
        step="START_AD",
        state="FILM_WATCH_PAGE",
        detections={"watch_user_001": _detection("watch_user_001", 0.79)},
    )

    assert decision.action["name"] == "wait"
    assert decision.reason == "watch_ad_film_marker_not_found"


def test_watch_ad_unknown_waits_and_keeps_watch_ad() -> None:
    decision = decide_film_flow_action(step="WATCH_AD", state="UNKNOWN", detections={})

    assert decision.action["name"] == "wait"
    assert decision.next_step == "WATCH_AD"
    assert decision.reason == "wait_for_ad_close_marker"


def test_watch_ad_close_uses_only_safe_close_marker() -> None:
    decision = decide_film_flow_action(
        step="WATCH_AD",
        state="AD_CLOSE_PAGE",
        detections={
            "ad_entry": _detection("ad_entry", 0.99),
            "close_buttons": _close_detection(0.91),
        },
    )

    assert decision.action["name"] == "tap_marker"
    assert decision.action["params"]["marker"] == "close_buttons"
    assert decision.selected_marker == "close_buttons"
    assert decision.next_step == "CLOSE_AD_DOING"


def test_watch_ad_close_ignores_similar_non_canonical_marker_name() -> None:
    decision = decide_film_flow_action(
        step="WATCH_AD",
        state="AD_CLOSE_PAGE",
        detections={
            "close_buttons": _close_detection(0.91),
            "close_ad": _close_detection(0.95),
        },
    )

    assert decision.action["name"] == "tap_marker"
    assert decision.action["params"]["marker"] == "close_buttons"


def test_close_ad_doing_close_page_retries_safe_marker() -> None:
    decision = decide_film_flow_action(
        step="CLOSE_AD_DOING",
        state="AD_CLOSE_PAGE",
        detections={"close_buttons": _close_detection(0.91)},
    )

    assert decision.action["name"] == "tap_marker"
    assert decision.action["params"]["marker"] == "close_buttons"
    assert decision.next_step == "CLOSE_AD_DOING"


def test_close_ad_does_not_default_to_arbitrary_best_marker() -> None:
    decision = decide_film_flow_action(
        step="WATCH_AD",
        state="AD_CLOSE_PAGE",
        detections={"ad_entry": _detection("ad_entry", 0.99)},
    )

    assert decision.action["name"] == "wait"
    assert decision.reason == "no_safe_close_ad_marker"


def test_close_ad_page_marker_without_clickable_close_button_waits() -> None:
    decision = decide_film_flow_action(
        step="WATCH_AD",
        state="AD_CLOSE_PAGE",
        detections={"AD_CLOSE_PAGE": _detection("AD_CLOSE_PAGE", 0.99)},
    )

    assert decision.action["name"] == "wait"
    assert decision.reason == "no_safe_close_ad_marker"


def test_close_ad_total_attempt_limit_waits() -> None:
    decision = decide_film_flow_action(
        step="CLOSE_AD_DOING",
        state="AD_CLOSE_PAGE",
        detections={"close_buttons": _close_detection(0.99)},
        close_ad_attempts=FILM_CLOSE_AD_MAX_TOTAL_CLICKS,
    )

    assert decision.action["name"] == "wait"
    assert decision.reason == "close_ad_attempt_limit"


def test_close_ad_below_threshold_waits() -> None:
    decision = decide_film_flow_action(
        step="WATCH_AD",
        state="AD_CLOSE_PAGE",
        detections={"close_buttons": _close_detection(0.79)},
    )

    assert decision.action["name"] == "wait"
    assert decision.reason == "no_safe_close_ad_marker"


def test_safe_close_allow_list_is_v2_canonical_not_global_actions_list() -> None:
    assert "close_buttons" in V2_SAFE_CLOSE_MARKER_ALLOW_LIST
    assert "close_buttons" not in DEFAULT_TAP_MARKER_ALLOW_LIST


def test_close_ad_success_page_advances_to_claim_reward() -> None:
    decision = decide_film_flow_action(
        step="CLOSE_AD_DOING",
        state="RIGHT_AD_REWARD_SUCCESS_PAGE",
        detections={},
    )

    assert decision.action["name"] == "no_action"
    assert decision.next_step == "CLAIM_REWARD"


def test_claim_reward_success_page_uses_press_back() -> None:
    decision = decide_film_flow_action(
        step="CLAIM_REWARD",
        state="RIGHT_AD_REWARD_SUCCESS_PAGE",
        detections={},
    )

    assert decision.action["name"] == "press_back"
    assert decision.next_step == "RETURN_HOME"


def test_return_home_finishes_only_after_home_page() -> None:
    decision = decide_film_flow_action(step="RETURN_HOME", state="HOME_PAGE", detections={})

    assert decision.action["name"] == "no_action"
    assert decision.next_step == "FINISH"


def test_return_home_finishes_after_raw_home_state() -> None:
    decision = decide_film_flow_action(step="RETURN_HOME", state="HOME", detections={})

    assert decision.action["name"] == "no_action"
    assert decision.next_step == "FINISH"


def _detection(name: str, confidence: float) -> DetectionResult:
    return DetectionResult(
        name=name,
        template=Path(f"{name}.png"),
        confidence=confidence,
        center=(10, 20),
        top_left=(5, 15),
        size=(10, 10),
        scale=1.0,
        threshold=0.8,
    )


def _close_detection(confidence: float) -> DetectionResult:
    path = _template_paths_for_marker("close_buttons")[0]
    return DetectionResult(
        name="close_buttons",
        template=path,
        confidence=confidence,
        center=(10, 20),
        top_left=(5, 15),
        size=(10, 10),
        scale=1.0,
        threshold=0.8,
    )

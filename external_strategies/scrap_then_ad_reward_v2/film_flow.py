from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from cats_automatic.actions import DEFAULT_TAP_MARKER_ALLOW_LIST
from cats_automatic.strategy_base import DetectionResult
from external_strategies.minimal_dry_run.strategy import (
    CLOSE_AD_MARKER_PRIORITY,
    CLOSE_AD_MIN_CONFIDENCE,
    select_close_ad_marker,
)

from .authoring import define_flow, define_state, no_action, press_back_action, tap_marker_action, wait_action
from .marker_groups import (
    AD_CLOSE_MARKERS,
    HOME_MARKERS,
    POPUP_MARKERS,
    REGISTERED_MARKERS,
)


FILM_STEPS = (
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

FILM_STATES = (
    "HOME_PAGE",
    "HOME",
    "FILM_WATCH_PAGE",
    "AD_CLOSE_PAGE",
    "RIGHT_AD_REWARD_SUCCESS_PAGE",
    "LOADING_PAGE",
    "POPUP_PAGE",
    "UNKNOWN_PAGE",
    "UNKNOWN",
)

FILM_ENTRY_MARKER = "ad_entry"
OPTIONAL_REWARD_MARKER = "select_reward_mode"
WATCH_AD_MARKER = "watch_ad_film"
FILM_MARKER_MIN_CONFIDENCE = {
    FILM_ENTRY_MARKER: 0.85,
    OPTIONAL_REWARD_MARKER: 0.85,
    WATCH_AD_MARKER: 0.85,
    "get_reward": 0.85,
    "confirm_button": 0.85,
}

FILM_ENTRY_MAX_CLICKS = 3
WATCH_AD_MAX_CLICKS = 3
FILM_CLOSE_AD_MAX_TOTAL_CLICKS = 4

FILM_BUSINESS_TAP_MARKERS = (
    FILM_ENTRY_MARKER,
    OPTIONAL_REWARD_MARKER,
    WATCH_AD_MARKER,
    "get_reward",
    "confirm_button",
)

# Validation-only allow-list for this draft. It does not change actions.py.
FILM_RULE_VALIDATION_TAP_MARKER_ALLOW_LIST = tuple(
    dict.fromkeys((*AD_CLOSE_MARKERS, *FILM_BUSINESS_TAP_MARKERS))
)

FILM_REGISTERED_MARKERS = tuple(
    dict.fromkeys((*REGISTERED_MARKERS, *FILM_BUSINESS_TAP_MARKERS))
)

FILM_UNRESOLVED_CONFIRMATIONS = (
    "select_reward_mode template is still optional/incomplete",
    "whether get_reward and confirm_button are the same clickable object",
    "whether reward claim always returns to HOME_PAGE automatically",
    "whether one emulator BACK is allowed if reward claim does not return home",
    "whether the 4 close-ad click limit is total or per close page",
)

FILM_STATE_TEMPLATES = {
    "HOME_PAGE": define_state(
        "HOME_PAGE",
        require_any=HOME_MARKERS,
        reason="home page marker observed",
        priority=100,
    ),
    "FILM_WATCH_PAGE": define_state(
        "FILM_WATCH_PAGE",
        require_any=(WATCH_AD_MARKER, OPTIONAL_REWARD_MARKER),
        reason="film watch page marker observed",
        priority=90,
    ),
    "AD_CLOSE_PAGE": define_state(
        "AD_CLOSE_PAGE",
        require_any=AD_CLOSE_MARKERS,
        reason="ad close marker observed",
        priority=95,
    ),
    "RIGHT_AD_REWARD_SUCCESS_PAGE": define_state(
        "RIGHT_AD_REWARD_SUCCESS_PAGE",
        require_any=("right_ad_reward_success_buttons", "right_ad_reward_success_marker"),
        exclude=AD_CLOSE_MARKERS,
        reason="teammate right ad reward success marker observed",
        priority=85,
    ),
    "LOADING_PAGE": define_state(
        "LOADING_PAGE",
        require_any=(),
        reason="loading state placeholder; detector rule not defined here",
        priority=10,
    ),
    "POPUP_PAGE": define_state(
        "POPUP_PAGE",
        require_any=POPUP_MARKERS,
        reason="generic popup marker observed",
        priority=70,
    ),
    "UNKNOWN_PAGE": define_state(
        "UNKNOWN_PAGE",
        require_any=(),
        reason="no reliable page markers observed",
        priority=0,
    ),
}

FILM_FLOW_RULES = (
    define_flow(
        step="START",
        state="UNKNOWN_PAGE",
        action=no_action("film_flow_start"),
        next_step="GO_HOME",
        description="START initializes the film flow without real input.",
    ),
    define_flow(
        step="GO_HOME",
        state="HOME_PAGE",
        action=no_action("home_ready_for_film_entry"),
        next_step="ENTER_FILM",
        description="HOME_PAGE confirms the flow can look for the film entry.",
    ),
    define_flow(
        step="ENTER_FILM",
        state="HOME_PAGE",
        action=tap_marker_action(
            FILM_ENTRY_MARKER,
            min_confidence=FILM_MARKER_MIN_CONFIDENCE[FILM_ENTRY_MARKER],
            reason="film_entry_marker_selected",
        ),
        next_step="ENTER_FILM",
        description="Tap the film entry only after ad_entry is detected.",
    ),
    define_flow(
        step="SELECT_REWARD",
        state="FILM_WATCH_PAGE",
        action=tap_marker_action(
            OPTIONAL_REWARD_MARKER,
            min_confidence=FILM_MARKER_MIN_CONFIDENCE[OPTIONAL_REWARD_MARKER],
            reason="optional_reward_marker_selected",
        ),
        next_step="START_AD",
        description="Optional reward selection; runtime may skip if marker is absent.",
    ),
    define_flow(
        step="START_AD",
        state="FILM_WATCH_PAGE",
        action=tap_marker_action(
            WATCH_AD_MARKER,
            min_confidence=FILM_MARKER_MIN_CONFIDENCE[WATCH_AD_MARKER],
            reason="watch_ad_film_marker_selected",
        ),
        next_step="START_AD",
        description="Tap watch ad and wait for the next screenshot to confirm.",
    ),
    define_flow(
        step="WATCH_AD",
        state="UNKNOWN_PAGE",
        action=wait_action(1.0, "wait_for_ad_close_marker"),
        next_step="WATCH_AD",
        description="Ad playback has no reliable page marker; keep waiting.",
    ),
    define_flow(
        step="WATCH_AD",
        state="AD_CLOSE_PAGE",
        action=wait_action(1.0, "close action selected dynamically by marker detector"),
        next_step="CLOSE_AD_DOING",
        description="Runtime selects a safe close marker from detections.",
    ),
    define_flow(
        step="CLOSE_AD_DOING",
        state="RIGHT_AD_REWARD_SUCCESS_PAGE",
        action=no_action("reward_page_confirmed_after_ad_close"),
        next_step="CLAIM_REWARD",
        description="Only state change confirms the ad close finished.",
    ),
    define_flow(
        step="CLAIM_REWARD",
        state="RIGHT_AD_REWARD_SUCCESS_PAGE",
        action=press_back_action(count=1, interval=0.3, reason="reward_success_press_back"),
        next_step="RETURN_HOME",
        description="Reward success page is dismissed with back in dry-run validated flow.",
    ),
    define_flow(
        step="RETURN_HOME",
        state="HOME_PAGE",
        action=no_action("film_reward_flow_finished_home"),
        next_step="FINISH",
        description="HOME_PAGE confirms the film flow is done.",
    ),
)


@dataclass(frozen=True)
class FilmDecision:
    step: str
    state: str
    action: dict[str, Any]
    next_step: str
    reason: str
    selected_marker: str | None = None
    selected_confidence: float | None = None


def decide_film_flow_action(
    *,
    step: str,
    state: str,
    detections: Mapping[str, DetectionResult],
    entry_click_attempts: int = 0,
    watch_ad_click_attempts: int = 0,
    close_ad_attempts: int = 0,
    reward_click_attempts: int = 0,
) -> FilmDecision:
    current_step = step if step in FILM_STEPS else "START"
    current_state = state if state in FILM_STATES else "UNKNOWN_PAGE"

    if current_step == "START":
        return _decision(current_step, current_state, no_action("film_flow_start"), "GO_HOME")
    if current_step == "FINISH":
        return _decision(current_step, current_state, no_action("film_flow_finished"), "FINISH")

    if current_step == "GO_HOME":
        if _is_home_state(current_state):
            return _decision(current_step, current_state, no_action("home_ready_for_film_entry"), "ENTER_FILM")
        if _is_wait_state(current_state) or current_state == "POPUP_PAGE":
            return _wait(current_step, current_state, "wait_for_home_or_recovery")

    if current_step == "ENTER_FILM":
        if current_state == "FILM_WATCH_PAGE":
            return _decision(current_step, current_state, no_action("film_watch_page_confirmed"), "SELECT_REWARD")
        if _is_home_state(current_state):
            return _tap_or_wait(
                current_step,
                current_state,
                detections,
                marker=FILM_ENTRY_MARKER,
                max_attempts=FILM_ENTRY_MAX_CLICKS,
                attempts=entry_click_attempts,
                wait_reason="film_entry_marker_not_found",
                limit_reason="film_entry_click_limit_reached",
                tap_reason="film_entry_marker_selected",
                next_step="ENTER_FILM",
            )
        if _is_wait_state(current_state):
            return _wait(current_step, current_state, "wait_for_film_select_page")

    if current_step == "SELECT_REWARD" and current_state == "FILM_WATCH_PAGE":
        if _has_marker(detections, OPTIONAL_REWARD_MARKER):
            return _tap(
                current_step,
                current_state,
                OPTIONAL_REWARD_MARKER,
                "optional_reward_marker_selected",
                "START_AD",
            )
        return _decision(
            current_step,
            current_state,
            no_action("optional_reward_marker_not_found"),
            "START_AD",
        )

    if current_step == "START_AD":
        if current_state == "FILM_WATCH_PAGE":
            return _tap_or_wait(
                current_step,
                current_state,
                detections,
                marker=WATCH_AD_MARKER,
                max_attempts=WATCH_AD_MAX_CLICKS,
                attempts=watch_ad_click_attempts,
                wait_reason="watch_ad_film_marker_not_found",
                limit_reason="watch_ad_film_click_limit_reached",
                tap_reason="watch_ad_film_marker_selected",
                next_step="START_AD",
            )
        if current_state == "AD_CLOSE_PAGE":
            return _close_ad_or_wait(current_step, current_state, detections, close_ad_attempts, "CLOSE_AD_DOING")
        if _is_wait_state(current_state):
            return _wait(current_step, current_state, "wait_for_ad_close_marker")

    if current_step == "WATCH_AD":
        if current_state == "AD_CLOSE_PAGE":
            return _close_ad_or_wait(current_step, current_state, detections, close_ad_attempts, "CLOSE_AD_DOING")
        if _is_wait_state(current_state):
            return _wait(current_step, current_state, "wait_for_ad_close_marker")

    if current_step == "CLOSE_AD_DOING":
        if current_state == "AD_CLOSE_PAGE":
            return _close_ad_or_wait(current_step, current_state, detections, close_ad_attempts, "CLOSE_AD_DOING")
        if current_state == "RIGHT_AD_REWARD_SUCCESS_PAGE":
            return _decision(
                current_step,
                current_state,
                no_action("reward_page_confirmed_after_ad_close"),
                "CLAIM_REWARD",
            )
        if _is_home_state(current_state):
            return _decision(current_step, current_state, no_action("already_home_after_ad_close"), "RETURN_HOME")
        if _is_wait_state(current_state):
            return _wait(current_step, current_state, "wait_after_ad_close")

    if current_step == "CLAIM_REWARD":
        if current_state == "RIGHT_AD_REWARD_SUCCESS_PAGE":
            return _decision(
                current_step,
                current_state,
                press_back_action(count=1, interval=0.3, reason="reward_success_press_back"),
                "RETURN_HOME",
            )
        if _is_home_state(current_state):
            return _decision(current_step, current_state, no_action("reward_already_returned_home"), "RETURN_HOME")

    if current_step == "RETURN_HOME":
        if _is_home_state(current_state):
            return _decision(current_step, current_state, no_action("film_reward_flow_finished_home"), "FINISH")
        if current_state == "RIGHT_AD_REWARD_SUCCESS_PAGE":
            return _decision(
                current_step,
                current_state,
                press_back_action(count=1, interval=0.3, reason="reward_success_press_back_retry"),
                "RETURN_HOME",
            )
        if _is_wait_state(current_state):
            return _wait(current_step, current_state, "wait_for_home_after_reward")

    return _wait(current_step, current_state, "no_matching_film_flow_rule")


def _close_ad_or_wait(
    step: str,
    state: str,
    detections: Mapping[str, DetectionResult],
    attempts: int,
    next_step: str,
) -> FilmDecision:
    if attempts >= FILM_CLOSE_AD_MAX_TOTAL_CLICKS:
        return _wait(step, state, "close_ad_attempt_limit")
    selected = select_close_ad_marker(
        detections,
        DEFAULT_TAP_MARKER_ALLOW_LIST,
        CLOSE_AD_MIN_CONFIDENCE,
        CLOSE_AD_MARKER_PRIORITY,
    )
    if selected is None:
        return _wait(step, state, "no_safe_close_ad_marker")
    action = tap_marker_action(
        selected.name,
        min_confidence=CLOSE_AD_MIN_CONFIDENCE,
        fallback_to_best_marker=False,
        reason="close_ad_marker_selected",
    )
    return _decision(
        step,
        state,
        action,
        next_step,
        selected_marker=selected.name,
        selected_confidence=selected.confidence,
    )


def _tap_or_wait(
    step: str,
    state: str,
    detections: Mapping[str, DetectionResult],
    *,
    marker: str,
    max_attempts: int,
    attempts: int,
    wait_reason: str,
    limit_reason: str,
    tap_reason: str,
    next_step: str,
) -> FilmDecision:
    if attempts >= max_attempts:
        return _wait(step, state, limit_reason)
    if not _has_marker(detections, marker):
        return _wait(step, state, wait_reason)
    return _tap(step, state, marker, tap_reason, next_step)


def _tap(step: str, state: str, marker: str, reason: str, next_step: str) -> FilmDecision:
    return _decision(
        step,
        state,
        tap_marker_action(
            marker,
            min_confidence=FILM_MARKER_MIN_CONFIDENCE.get(marker, CLOSE_AD_MIN_CONFIDENCE),
            fallback_to_best_marker=False,
            reason=reason,
        ),
        next_step,
        selected_marker=marker,
    )


def _wait(step: str, state: str, reason: str) -> FilmDecision:
    return _decision(step, state, wait_action(1.0, reason), step)


def _decision(
    step: str,
    state: str,
    action: dict[str, Any],
    next_step: str,
    *,
    selected_marker: str | None = None,
    selected_confidence: float | None = None,
) -> FilmDecision:
    return FilmDecision(
        step=step,
        state=state,
        action=action,
        next_step=next_step,
        reason=str(action.get("reason", "")),
        selected_marker=selected_marker,
        selected_confidence=selected_confidence,
    )


def _has_marker(detections: Mapping[str, DetectionResult], marker: str) -> bool:
    detection = detections.get(marker)
    if detection is None:
        return False
    return detection.confidence >= FILM_MARKER_MIN_CONFIDENCE.get(marker, CLOSE_AD_MIN_CONFIDENCE)


def _is_home_state(state: str) -> bool:
    return state in {"HOME", "HOME_PAGE"}


def _is_wait_state(state: str) -> bool:
    return state in {"UNKNOWN", "UNKNOWN_PAGE", "LOADING_PAGE"}

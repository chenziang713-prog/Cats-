from __future__ import annotations

from external_strategies.scrap_then_ad_reward_v2.authoring import (
    define_flow,
    define_state,
    tap_marker_action,
    wait_action,
)
from external_strategies.scrap_then_ad_reward_v2.marker_groups import (
    AD_CLOSE_MARKERS,
    REGISTERED_MARKERS,
)
from external_strategies.scrap_then_ad_reward_v2.screen_state_templates import SCREEN_STATE_TEMPLATES
from external_strategies.scrap_then_ad_reward_v2.state_names import (
    NORMALIZED_STATES,
    STATE_ALIASES,
)
from external_strategies.scrap_then_ad_reward_v2.validation import validate_strategy_config


KNOWN_STEPS = ("START", "WATCH_AD", "CLOSE_AD", "RETURN_HOME", "FINISH")
SUPPORTED_ACTIONS = ("wait", "no_action", "press_back", "tap_marker")


def test_duplicate_state_is_reported() -> None:
    state = define_state("DUP", require_any=("main-definate",), reason="one")

    report = _validate(states=[state, state])

    assert _has_error(report, "duplicate state name")


def test_unregistered_marker_is_reported() -> None:
    state = define_state("BAD", require_any=("scrap_claim_btn",), reason="bad")

    report = _validate(states=[state])

    assert _has_error(report, "not registered")


def test_require_and_exclude_conflict_is_reported() -> None:
    state = define_state(
        "BAD",
        require_any=("main-definate",),
        exclude=("main-definate",),
        reason="bad",
    )

    report = _validate(states=[state])

    assert _has_error(report, "both require and exclude")


def test_unknown_action_is_reported() -> None:
    state = define_state("OK", require_any=("main-definate",), reason="ok")
    flow = define_flow(
        step="WATCH_AD",
        state="OK",
        action={"name": "claim_reward", "params": {}, "reason": "bad"},
        next_step="WATCH_AD",
    )

    report = _validate(states=[state], flow_rules=[flow])

    assert _has_error(report, "unknown action")


def test_unknown_step_is_reported() -> None:
    state = define_state("OK", require_any=("main-definate",), reason="ok")
    flow = define_flow(step="BAD_STEP", state="OK", action=wait_action(), next_step="WATCH_AD")

    report = _validate(states=[state], flow_rules=[flow])

    assert _has_error(report, "unknown step")


def test_unknown_next_step_is_reported_with_suggestion() -> None:
    state = define_state("OK", require_any=("main-definate",), reason="ok")
    flow = define_flow(step="WATCH_AD", state="OK", action=wait_action(), next_step="RETUN_HOME")

    report = _validate(states=[state], flow_rules=[flow])

    assert _has_error(report, "unknown next_step")
    assert any("RETURN_HOME" in error.suggestion for error in report.errors)


def test_duplicate_step_state_rule_is_reported() -> None:
    state = define_state("OK", require_any=("main-definate",), reason="ok")
    flow = define_flow(step="WATCH_AD", state="OK", action=wait_action(), next_step="WATCH_AD")

    report = _validate(states=[state], flow_rules=[flow, flow])

    assert _has_error(report, "duplicate step + state")


def test_alias_self_cycle_is_reported() -> None:
    report = _validate(aliases={"HOME": "HOME"})

    assert _has_error(report, "alias cannot point to itself")


def test_alias_multi_node_cycle_is_reported() -> None:
    report = _validate(aliases={"A": "B", "B": "A"})

    assert _has_error(report, "alias cycle")


def test_spelling_suggestion_for_marker() -> None:
    state = define_state("BAD", require_any=("confirm_buton",), reason="bad")

    report = _validate(states=[state])

    assert any("confirm_button" in error.suggestion for error in report.errors)


def test_valid_config_has_no_errors() -> None:
    state = define_state("OK", require_any=("main-definate",), reason="ok")
    flow = define_flow(step="WATCH_AD", state="OK", action=wait_action(), next_step="WATCH_AD")

    report = _validate(states=[state], flow_rules=[flow])

    assert report.errors == []


def test_warning_and_error_are_distinct() -> None:
    state = define_state("WARN", require_any=("not_registered",), reason="")

    report = _validate(states=[state])

    assert report.errors
    assert report.warnings


def test_existing_screen_state_templates_remain_compatible() -> None:
    report = validate_strategy_config(
        states=SCREEN_STATE_TEMPLATES,
        flow_rules=(),
        registered_markers=REGISTERED_MARKERS,
        supported_actions=SUPPORTED_ACTIONS,
        known_steps=KNOWN_STEPS,
        aliases=STATE_ALIASES,
        tap_marker_allow_list=AD_CLOSE_MARKERS,
    )

    assert report.errors == []


def test_tap_marker_marker_must_be_in_allow_list() -> None:
    state = define_state("OK", require_any=("main-definate",), reason="ok")
    flow = define_flow(
        step="WATCH_AD",
        state="OK",
        action=tap_marker_action("main-definate"),
        next_step="WATCH_AD",
    )

    report = _validate(states=[state], flow_rules=[flow])

    assert _has_error(report, "allow-list")


def _validate(
    *,
    states=None,
    flow_rules=(),
    aliases=None,
):
    states = states or [define_state("OK", require_any=("main-definate",), reason="ok")]
    return validate_strategy_config(
        states=states,
        flow_rules=flow_rules,
        registered_markers=REGISTERED_MARKERS,
        supported_actions=SUPPORTED_ACTIONS,
        known_steps=KNOWN_STEPS,
        aliases={} if aliases is None else aliases,
        tap_marker_allow_list=AD_CLOSE_MARKERS,
    )


def _has_error(report, text: str) -> bool:
    return any(text in error.message for error in report.errors)

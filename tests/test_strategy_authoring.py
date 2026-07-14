from __future__ import annotations

import json

import pytest

from cats_automatic.actions import DryRunBackend, execute_action
from external_strategies.scrap_then_ad_reward_v2.authoring import (
    action_to_decision,
    define_flow,
    define_state,
    no_action,
    press_back_action,
    tap_marker_action,
    wait_action,
)
from external_strategies.scrap_then_ad_reward_v2.screen_state_types import ScreenStateTemplate


def test_define_state_returns_existing_template_type() -> None:
    state = define_state(
        "EXAMPLE_STATE",
        require_all=("reward_confirm_marker",),
        require_any=("confirm_button",),
        exclude=("close_end_2",),
        priority=80,
        action="no_action",
        reason="example",
    )

    assert isinstance(state, ScreenStateTemplate)
    assert state.state_name == "EXAMPLE_STATE"
    assert state.description == "example"


def test_define_state_converts_marker_inputs() -> None:
    state = define_state(
        "EXAMPLE_STATE",
        require_all=["a"],
        require_any=["b"],
        exclude=["c"],
        reason="example",
    )

    assert state.required_all == ["a"]
    assert state.required_any == ["b"]
    assert state.exclude_any == ["c"]


def test_define_state_rejects_empty_name() -> None:
    with pytest.raises(ValueError, match="state name"):
        define_state("", reason="bad")


def test_define_state_rejects_non_integer_priority() -> None:
    with pytest.raises(ValueError, match="priority"):
        define_state("BAD", priority=1.5, reason="bad")  # type: ignore[arg-type]


def test_wait_action_parameters() -> None:
    action = wait_action(seconds=1.25, reason="wait_a_bit")

    assert action == {"name": "wait", "params": {"seconds": 1.25}, "reason": "wait_a_bit"}


def test_press_back_action_parameters() -> None:
    action = press_back_action(count=2, interval=0.4, reason="go_back")

    assert action["name"] == "press_back"
    assert action["params"] == {"count": 2, "interval": 0.4}


def test_tap_marker_action_defaults_fallback_false() -> None:
    action = tap_marker_action("close_end_2", reason="close")

    assert action["params"]["fallback_to_best_marker"] is False
    assert action["params"]["marker"] == "close_end_2"


def test_tap_marker_action_is_accepted_by_actions_layer() -> None:
    result = execute_action(
        tap_marker_action("close_end_2", reason="close"),
        DryRunBackend(),
        state_result={
            "detections": {
                "close_end_2": {
                    "confidence": 0.95,
                    "center": (10, 20),
                }
            },
            "image_size": (100, 100),
        },
        dry_run=True,
    )

    assert result.success is True
    assert result.clicked_pos == (10, 20)


def test_define_flow_generates_standard_rule() -> None:
    flow = define_flow(
        step="WATCH_AD",
        state="AD_RUNNING_PAGE",
        action=no_action(reason="noop"),
        next_step="WATCH_AD",
        description="example",
    )

    assert flow.step == "WATCH_AD"
    assert flow.action["name"] == "no_action"
    assert flow.next_step == "WATCH_AD"


def test_action_and_flow_are_json_serializable() -> None:
    flow = define_flow(
        step="WATCH_AD",
        state="AD_RUNNING_PAGE",
        action=tap_marker_action("close_end_2", reason="close"),
        next_step="CLOSE_AD",
    )

    json.dumps(flow.to_dict())


def test_action_to_decision_keeps_strategy_decision_compatibility() -> None:
    decision = action_to_decision(tap_marker_action("close_end_2", reason="close"))

    assert decision.kind == "wait"
    assert decision.action_name == "tap_marker"
    assert decision.action_params["marker"] == "close_end_2"

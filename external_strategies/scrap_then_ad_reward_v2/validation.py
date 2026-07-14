from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from difflib import get_close_matches
from typing import Any

from .authoring import FlowRule, SUPPORTED_ACTION_NAMES
from .screen_state_types import ScreenStateTemplate


@dataclass(frozen=True)
class ValidationIssue:
    config_type: str
    name: str
    field: str
    value: Any
    message: str
    suggestion: str = ""

    def format(self) -> str:
        suggestion = f"\nSuggestion: {self.suggestion}" if self.suggestion else ""
        return (
            f"Invalid {self.config_type} {self.name!r}: {self.message}\n"
            f"field={self.field!r}\nvalue={self.value!r}{suggestion}"
        )


@dataclass(frozen=True)
class ValidationReport:
    errors: list[ValidationIssue] = field(default_factory=list)
    warnings: list[ValidationIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def validate_strategy_config(
    *,
    states: Mapping[str, ScreenStateTemplate] | Sequence[ScreenStateTemplate],
    flow_rules: Sequence[FlowRule | Mapping[str, Any]] = (),
    registered_markers: Iterable[str] = (),
    supported_actions: Iterable[str] = SUPPORTED_ACTION_NAMES,
    known_steps: Iterable[str] = (),
    aliases: Mapping[str, str] | None = None,
    tap_marker_allow_list: Iterable[str] = (),
    allow_finish_to_jump: bool = False,
) -> ValidationReport:
    errors: list[ValidationIssue] = []
    warnings: list[ValidationIssue] = []
    state_list = _state_list(states)
    state_names = [state.state_name for state in state_list]
    state_name_set = set(state_names)
    registered = set(registered_markers)
    actions = set(supported_actions)
    steps = set(known_steps)
    clickable = set(tap_marker_allow_list)

    for name, count in Counter(state_names).items():
        if count > 1:
            errors.append(_issue("state", name, "state_name", name, "duplicate state name"))

    for state in state_list:
        _validate_state(
            state,
            registered=registered,
            actions=actions,
            errors=errors,
            warnings=warnings,
        )

    seen_flow_keys: set[tuple[str, str]] = set()
    for raw_rule in flow_rules:
        rule = _flow_dict(raw_rule)
        _validate_flow_rule(
            rule,
            state_names=state_name_set,
            steps=steps,
            actions=actions,
            clickable=clickable,
            seen_flow_keys=seen_flow_keys,
            allow_finish_to_jump=allow_finish_to_jump,
            errors=errors,
        )

    if aliases is not None:
        _validate_aliases(aliases, state_name_set, errors)

    return ValidationReport(errors=errors, warnings=warnings)


def _validate_state(
    state: ScreenStateTemplate,
    *,
    registered: set[str],
    actions: set[str],
    errors: list[ValidationIssue],
    warnings: list[ValidationIssue],
) -> None:
    if not state.state_name.strip():
        errors.append(_issue("state", state.state_name, "state_name", state.state_name, "state name is empty"))
    if not isinstance(state.priority, int):
        errors.append(_issue("state", state.state_name, "priority", state.priority, "priority must be integer"))
    required = [*state.required_any, *state.required_all]
    excluded = list(state.exclude_any)
    for field_name, markers in (
        ("required_any", state.required_any),
        ("required_all", state.required_all),
        ("exclude_any", state.exclude_any),
    ):
        for marker in markers:
            if not _marker_registered(marker, registered):
                errors.append(
                    _issue(
                        "state",
                        state.state_name,
                        field_name,
                        marker,
                        f"marker {marker!r} is not registered.",
                        _suggest(marker, registered),
                    )
                )
    conflicts = set(required) & set(excluded)
    for marker in conflicts:
        errors.append(
            _issue(
                "state",
                state.state_name,
                "marker_conflict",
                marker,
                "marker appears in both require and exclude.",
            )
        )
    if not state.description:
        warnings.append(
            _issue("state", state.state_name, "description", state.description, "reason/description is empty")
        )


def _validate_flow_rule(
    rule: dict[str, Any],
    *,
    state_names: set[str],
    steps: set[str],
    actions: set[str],
    clickable: set[str],
    seen_flow_keys: set[tuple[str, str]],
    allow_finish_to_jump: bool,
    errors: list[ValidationIssue],
) -> None:
    step = str(rule.get("step", ""))
    state = str(rule.get("state", ""))
    next_step = str(rule.get("next_step", ""))
    action = rule.get("action")
    action_name = action if isinstance(action, str) else str((action or {}).get("name", ""))
    name = f"{step}+{state}"

    if step not in steps:
        errors.append(_issue("flow rule", name, "step", step, "unknown step", _suggest(step, steps)))
    if next_step not in steps:
        errors.append(
            _issue("flow rule", name, "next_step", next_step, "unknown next_step", _suggest(next_step, steps))
        )
    if state not in state_names:
        errors.append(_issue("flow rule", name, "state", state, "unknown state", _suggest(state, state_names)))
    if action_name not in actions:
        errors.append(
            _issue("flow rule", name, "action", action_name, "unknown action", _suggest(action_name, actions))
        )
    key = (step, state)
    if key in seen_flow_keys:
        errors.append(_issue("flow rule", name, "step/state", key, "duplicate step + state rule"))
    seen_flow_keys.add(key)
    if step == "FINISH" and next_step != "FINISH" and not allow_finish_to_jump:
        errors.append(_issue("flow rule", name, "next_step", next_step, "FINISH should not jump to normal steps"))
    if isinstance(action, Mapping):
        _validate_action_params(name, action, clickable, errors)
        try:
            json.dumps(action)
        except TypeError as exc:
            errors.append(_issue("flow rule", name, "action", action, f"action is not JSON serializable: {exc}"))


def _validate_action_params(
    name: str,
    action: Mapping[str, Any],
    clickable: set[str],
    errors: list[ValidationIssue],
) -> None:
    if action.get("name") != "tap_marker":
        return
    params = action.get("params", {})
    marker = "" if not isinstance(params, Mapping) else str(params.get("marker", ""))
    if not marker:
        errors.append(_issue("flow rule", name, "action.params.marker", marker, "tap_marker marker is required"))
        return
    if clickable and not _marker_registered(marker, clickable):
        errors.append(
            _issue(
                "flow rule",
                name,
                "action.params.marker",
                marker,
                "tap_marker marker is not in the allow-list.",
                _suggest(marker, clickable),
            )
        )


def _validate_aliases(aliases: Mapping[str, str], state_names: set[str], errors: list[ValidationIssue]) -> None:
    for alias, target in aliases.items():
        if alias == target:
            errors.append(_issue("alias", alias, "target", target, "alias cannot point to itself"))
            continue
        seen = {alias}
        cursor = target
        while cursor in aliases:
            if cursor in seen:
                errors.append(_issue("alias", alias, "target", target, "alias cycle detected"))
                break
            seen.add(cursor)
            cursor = aliases[cursor]
        if cursor not in state_names:
            errors.append(_issue("alias", alias, "target", target, "alias target is not a known state"))


def _state_list(
    states: Mapping[str, ScreenStateTemplate] | Sequence[ScreenStateTemplate],
) -> list[ScreenStateTemplate]:
    return list(states.values()) if isinstance(states, Mapping) else list(states)


def _flow_dict(rule: FlowRule | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(rule, FlowRule):
        return rule.to_dict()
    return dict(rule)


def _marker_registered(marker: str, registered: set[str]) -> bool:
    if marker in registered:
        return True
    if marker.endswith("*"):
        return marker in registered or any(item.startswith(marker[:-1]) for item in registered)
    return any(item.endswith("*") and marker.startswith(item[:-1]) for item in registered)


def _suggest(value: str, choices: Iterable[str]) -> str:
    matches = get_close_matches(value, list(choices), n=1)
    if not matches:
        return ""
    return f"Did you mean {matches[0]!r}?"


def _issue(
    config_type: str,
    name: str,
    field: str,
    value: Any,
    message: str,
    suggestion: str = "",
) -> ValidationIssue:
    return ValidationIssue(
        config_type=config_type,
        name=str(name),
        field=field,
        value=value,
        message=message,
        suggestion=suggestion,
    )

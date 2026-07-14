from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from cats_automatic.strategy_base import StrategyDecision

from .screen_state_templates import DEFAULT_TEMPLATE_DIRS
from .screen_state_types import ScreenStateTemplate


SUPPORTED_ACTION_NAMES = frozenset({"wait", "no_action", "press_back", "tap_marker"})


@dataclass(frozen=True)
class FlowRule:
    step: str
    state: str
    action: dict[str, Any] | str
    next_step: str
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def define_state(
    name: str,
    *,
    require_all: tuple[str, ...] | list[str] = (),
    require_any: tuple[str, ...] | list[str] = (),
    exclude: tuple[str, ...] | list[str] = (),
    priority: int = 0,
    action: str = "no_action",
    reason: str = "",
    threshold: float = 0.80,
) -> ScreenStateTemplate:
    state_name = _required_text(name, "state name")
    if not isinstance(priority, int):
        raise ValueError("Invalid state priority: priority must be an integer.")
    if not isinstance(action, str):
        raise ValueError("Invalid state action: action must be a string.")
    if threshold < 0 or threshold > 1:
        raise ValueError("Invalid state threshold: threshold must be between 0 and 1.")
    return ScreenStateTemplate(
        state_name=state_name,
        required_any=list(_strings(require_any, "require_any")),
        required_all=list(_strings(require_all, "require_all")),
        exclude_any=list(_strings(exclude, "exclude")),
        threshold=float(threshold),
        priority=priority,
        description=str(reason),
        template_dirs=list(DEFAULT_TEMPLATE_DIRS),
    )


def no_action(reason: str = "") -> dict[str, Any]:
    return {"name": "no_action", "params": {}, "reason": str(reason)}


def wait_action(seconds: float = 1.0, reason: str = "") -> dict[str, Any]:
    seconds_value = _number(seconds, "seconds")
    if seconds_value < 0:
        raise ValueError("Invalid wait action: seconds must not be negative.")
    return {"name": "wait", "params": {"seconds": seconds_value}, "reason": str(reason)}


def press_back_action(count: int = 1, interval: float = 0.3, reason: str = "") -> dict[str, Any]:
    if not isinstance(count, int) or count <= 0:
        raise ValueError("Invalid press_back action: count must be a positive integer.")
    interval_value = _number(interval, "interval")
    if interval_value < 0:
        raise ValueError("Invalid press_back action: interval must not be negative.")
    return {
        "name": "press_back",
        "params": {"count": count, "interval": interval_value},
        "reason": str(reason),
    }


def tap_marker_action(
    marker: str,
    *,
    min_confidence: float = 0.80,
    fallback_to_best_marker: bool = False,
    offset_x: int = 0,
    offset_y: int = 0,
    reason: str = "",
) -> dict[str, Any]:
    marker_name = _required_text(marker, "tap_marker marker")
    confidence = _number(min_confidence, "min_confidence")
    if confidence < 0 or confidence > 1:
        raise ValueError("Invalid tap_marker action: min_confidence must be between 0 and 1.")
    if not isinstance(fallback_to_best_marker, bool):
        raise ValueError("Invalid tap_marker action: fallback_to_best_marker must be boolean.")
    return {
        "name": "tap_marker",
        "params": {
            "marker": marker_name,
            "min_confidence": confidence,
            "fallback_to_best_marker": fallback_to_best_marker,
            "offset_x": int(offset_x),
            "offset_y": int(offset_y),
        },
        "reason": str(reason),
    }


def define_flow(
    *,
    step: str,
    state: str,
    action: dict[str, Any] | str,
    next_step: str,
    description: str = "",
) -> FlowRule:
    return FlowRule(
        step=_required_text(step, "flow step"),
        state=_required_text(state, "flow state"),
        action=_normalize_action(action),
        next_step=_required_text(next_step, "flow next_step"),
        description=str(description),
    )


def action_to_decision(action: dict[str, Any] | str) -> StrategyDecision:
    normalized = _normalize_action(action)
    if isinstance(normalized, str):
        if normalized == "press_back":
            return StrategyDecision.keyevent("BACK", "press_back")
        return StrategyDecision.action(normalized)
    name = str(normalized["name"])
    reason = str(normalized.get("reason", ""))
    params = normalized.get("params", {})
    if name == "press_back":
        return StrategyDecision.keyevent("BACK", "press_back", reason)
    return StrategyDecision.action(name, params=params, reason=reason)


def _normalize_action(action: dict[str, Any] | str) -> dict[str, Any] | str:
    if isinstance(action, str):
        return _required_text(action, "flow action")
    if not isinstance(action, dict):
        raise ValueError("Invalid flow action: action must be a string or action helper dict.")
    name = _required_text(str(action.get("name", "")), "flow action name")
    params = action.get("params", {})
    if not isinstance(params, dict):
        raise ValueError("Invalid flow action: params must be a dict.")
    return {"name": name, "params": dict(params), "reason": str(action.get("reason", ""))}


def _strings(values: tuple[str, ...] | list[str], field_name: str) -> tuple[str, ...]:
    result = []
    for value in values:
        text = _required_text(value, field_name)
        result.append(text)
    return tuple(result)


def _required_text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Invalid {field_name}: value must be a non-empty string.")
    return value.strip()


def _number(value: float, field_name: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid {field_name}: value must be numeric.") from exc

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Protocol

from .actions import ActionExecutor, ClickAction
from .vision import MatchResult, match_template
from .window_capture import WindowCaptureError, WindowFrame


@dataclass(frozen=True)
class ScaleConfig:
    minimum: float
    maximum: float
    step: float


@dataclass(frozen=True)
class ScenarioState:
    templates: tuple[Path, ...]
    threshold: float
    match_mode: str = "edge"


@dataclass(frozen=True)
class ScenarioConfig:
    name: str
    window_title_contains: str
    render_window_class: str
    cycle_interval_seconds: float
    max_cycles: int
    max_runtime_seconds: float
    minimum_ad_wait_seconds: float
    confirm_timeout_seconds: float
    close_poll_interval_seconds: float
    close_timeout_seconds: float
    post_close_wait_seconds: float
    max_close_actions: int
    ready_timeout_seconds: float
    return_timeout_seconds: float
    scale: ScaleConfig
    ready: ScenarioState
    confirm: ScenarioState | None
    close_ad: ScenarioState
    returned: ScenarioState

    @property
    def max_actions_per_cycle(self) -> int:
        return 1 + int(self.confirm is not None) + self.max_close_actions


@dataclass(frozen=True)
class MatchCandidate:
    template: Path
    match: MatchResult
    frame: WindowFrame

    @property
    def screen_center(self) -> tuple[int, int]:
        return self.frame.to_screen_point(self.match.center)


class CaptureProvider(Protocol):
    def capture(self, output_path: Path) -> WindowFrame: ...


Matcher = Callable[..., MatchResult]


class ScenarioConfigError(ValueError):
    pass


class JsonlAuditLogger:
    def __init__(self, path: Path | None) -> None:
        self.path = path
        self._handle = None
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            self._handle = path.open("a", encoding="utf-8")

    def event(self, event: str, **fields: Any) -> None:
        record = {
            "timestamp": datetime.now(UTC).isoformat(),
            "event": event,
            **fields,
        }
        text = json.dumps(record, ensure_ascii=True, sort_keys=True)
        print(f"SCENARIO {text}")
        if self._handle is not None:
            self._handle.write(text + "\n")
            self._handle.flush()

    def close(self) -> None:
        if self._handle is not None:
            self._handle.close()
            self._handle = None


def load_scenario(path: Path, root: Path) -> ScenarioConfig:
    with path.open("r", encoding="utf-8") as file:
        raw: dict[str, Any] = json.load(file)

    try:
        scale = raw["scale"]
        states = raw["states"]
        return ScenarioConfig(
            name=str(raw["name"]),
            window_title_contains=str(raw["window_title_contains"]),
            render_window_class=str(raw.get("render_window_class", "RenderWindow")),
            cycle_interval_seconds=_positive(raw.get("cycle_interval_seconds", 600), "cycle_interval_seconds"),
            max_cycles=_positive_int(raw.get("max_cycles", 10), "max_cycles"),
            max_runtime_seconds=_positive(raw.get("max_runtime_seconds", 7200), "max_runtime_seconds"),
            minimum_ad_wait_seconds=_positive(raw.get("minimum_ad_wait_seconds", 35), "minimum_ad_wait_seconds"),
            confirm_timeout_seconds=_positive(raw.get("confirm_timeout_seconds", 15), "confirm_timeout_seconds"),
            close_poll_interval_seconds=_positive(raw.get("close_poll_interval_seconds", 1), "close_poll_interval_seconds"),
            close_timeout_seconds=_positive(raw.get("close_timeout_seconds", 45), "close_timeout_seconds"),
            post_close_wait_seconds=_positive(raw.get("post_close_wait_seconds", 2), "post_close_wait_seconds"),
            max_close_actions=_positive_int(raw.get("max_close_actions", 1), "max_close_actions"),
            ready_timeout_seconds=_positive(raw.get("ready_timeout_seconds", 60), "ready_timeout_seconds"),
            return_timeout_seconds=_positive(raw.get("return_timeout_seconds", 30), "return_timeout_seconds"),
            scale=ScaleConfig(
                minimum=_positive(scale["min"], "scale.min"),
                maximum=_positive(scale["max"], "scale.max"),
                step=_positive(scale["step"], "scale.step"),
            ),
            ready=_load_state(states["ready"], root, "ready"),
            confirm=_load_state(states["confirm"], root, "confirm") if "confirm" in states else None,
            close_ad=_load_state(states["close_ad"], root, "close_ad"),
            returned=_load_state(states["returned"], root, "returned"),
        )
    except KeyError as exc:
        raise ScenarioConfigError(f"Missing scenario config field: {exc.args[0]}") from exc


def select_best_template(
    screen_path: Path,
    state: ScenarioState,
    scale: ScaleConfig,
    matcher: Matcher = match_template,
) -> tuple[Path, MatchResult] | None:
    best: tuple[Path, MatchResult] | None = None
    for template in state.templates:
        if not template.exists():
            continue
        match = matcher(
            screen_path,
            template,
            mode=state.match_mode,
            scale_min=scale.minimum,
            scale_max=scale.maximum,
            scale_step=scale.step,
        )
        if best is None or match.confidence > best[1].confidence:
            best = (template, match)
    return best


class ScenarioRunner:
    def __init__(
        self,
        *,
        config: ScenarioConfig,
        capture_provider: CaptureProvider,
        executor: ActionExecutor,
        audit: JsonlAuditLogger,
        output_dir: Path,
        stop_file: Path,
        matcher: Matcher = match_template,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.config = config
        self.capture_provider = capture_provider
        self.executor = executor
        self.audit = audit
        self.output_dir = output_dir
        self.stop_file = stop_file
        self.matcher = matcher
        self.monotonic = monotonic
        self.sleep = sleep
        self.started_at = monotonic()

    def run(self) -> int:
        self.audit.event("runner_started", scenario=self.config.name)
        completed = 0
        stop_reason: str | None = None
        while completed < self.config.max_cycles and not self._runtime_exceeded():
            if self._stopped():
                break
            cycle = completed + 1
            self.audit.event("state", cycle=cycle, state="WAIT_READY")
            ready = self._wait_for("ready", self.config.ready_timeout_seconds, cycle)
            if ready is None:
                self._cycle_failed(cycle, "ready_not_found")
                self._sleep_interruptibly(self.config.cycle_interval_seconds)
                continue

            self.audit.event("state", cycle=cycle, state="CLICK_ENTRY")
            if not self._click_fresh("ready", cycle):
                self._cycle_failed(cycle, "entry_recheck_failed")
                self._sleep_interruptibly(self.config.cycle_interval_seconds)
                continue

            if self.config.confirm is not None:
                self.audit.event("state", cycle=cycle, state="WAIT_CONFIRM")
                confirm = self._wait_for("confirm", self.config.confirm_timeout_seconds, cycle)
                if confirm is None:
                    self._cycle_failed(cycle, "confirm_not_found")
                    stop_reason = "confirm_not_found"
                    break

                self.audit.event("state", cycle=cycle, state="CLICK_CONFIRM")
                if not self._click_fresh("confirm", cycle):
                    self._cycle_failed(cycle, "confirm_recheck_failed")
                    stop_reason = "confirm_recheck_failed"
                    break

            self.audit.event("state", cycle=cycle, state="WAIT_AD_MINIMUM")
            if not self._sleep_interruptibly(self.config.minimum_ad_wait_seconds):
                break

            returned = self._close_until_returned(cycle)
            if returned is None:
                self._cycle_failed(cycle, "return_not_confirmed")
                stop_reason = "return_not_confirmed"
                break

            completed += 1
            self.audit.event("cycle_completed", cycle=cycle)
            if completed < self.config.max_cycles:
                self.audit.event("state", cycle=cycle, state="COOLDOWN")
                if not self._sleep_interruptibly(self.config.cycle_interval_seconds):
                    break

        reason = (
            "stop_file"
            if self._stopped()
            else stop_reason
            or "runtime_limit"
            if self._runtime_exceeded()
            else "cycle_limit"
        )
        self.audit.event("runner_stopped", completed_cycles=completed, reason=reason)
        return completed

    def _close_until_returned(self, cycle: int) -> MatchCandidate | None:
        for attempt in range(1, self.config.max_close_actions + 1):
            self.audit.event("state", cycle=cycle, state="POLL_CLOSE", close_attempt=attempt)
            close_match = self._wait_for("close_ad", self.config.close_timeout_seconds, cycle)
            if close_match is None:
                self._cycle_failed(cycle, "close_button_not_found")
                return None

            self.audit.event("state", cycle=cycle, state="CLICK_CLOSE", close_attempt=attempt)
            if not self._click_fresh("close_ad", cycle):
                self._cycle_failed(cycle, "close_recheck_failed")
                return None

            if not self._sleep_interruptibly(self.config.post_close_wait_seconds):
                return None

            self.audit.event("state", cycle=cycle, state="VERIFY_RETURN", close_attempt=attempt)
            returned = self._detect("returned", cycle)
            if returned is not None:
                return returned

        self.audit.event("state", cycle=cycle, state="VERIFY_RETURN_FINAL")
        return self._wait_for("returned", self.config.return_timeout_seconds, cycle)

    def _click_fresh(self, state_name: str, cycle: int) -> bool:
        candidate = self._detect(state_name, cycle)
        if candidate is None:
            return False
        x, y = candidate.screen_center
        before = self.executor.action_count
        self.executor.click(
            ClickAction(
                x=x,
                y=y,
                confidence=candidate.match.confidence,
                reason=f"scenario={self.config.name} state={state_name}",
            )
        )
        clicked = self.executor.action_count > before
        self.audit.event(
            "action",
            cycle=cycle,
            state=state_name,
            template=str(candidate.template),
            confidence=candidate.match.confidence,
            window_center=candidate.match.center,
            screen_center=candidate.screen_center,
            clicked=clicked,
            dry_run=self.executor.dry_run,
        )
        return clicked

    def _wait_for(
        self,
        state_name: str,
        timeout_seconds: float,
        cycle: int,
    ) -> MatchCandidate | None:
        deadline = self.monotonic() + timeout_seconds
        while self.monotonic() <= deadline:
            if self._stopped() or self._runtime_exceeded():
                return None
            candidate = self._detect(state_name, cycle)
            if candidate is not None:
                return candidate
            self.sleep(self.config.close_poll_interval_seconds)
        return None

    def _detect(self, state_name: str, cycle: int) -> MatchCandidate | None:
        state = getattr(self.config, state_name)
        try:
            frame = self.capture_provider.capture(self.output_dir / f"{state_name}.png")
        except WindowCaptureError as exc:
            self.audit.event(
                "detection_failed",
                cycle=cycle,
                state=state_name,
                reason="window_capture_failed",
                detail=str(exc),
            )
            return None
        try:
            selected = select_best_template(frame.path, state, self.config.scale, self.matcher)
        except (FileNotFoundError, RuntimeError, ValueError) as exc:
            self.audit.event(
                "detection_failed",
                cycle=cycle,
                state=state_name,
                reason="template_match_failed",
                detail=str(exc),
            )
            return None
        if selected is None:
            self.audit.event("detection_failed", cycle=cycle, state=state_name, reason="no_template_file")
            return None
        template, match = selected
        passed = match.confidence >= state.threshold
        self.audit.event(
            "detection",
            cycle=cycle,
            state=state_name,
            template=str(template),
            confidence=match.confidence,
            threshold=state.threshold,
            passed=passed,
            scale=match.scale,
            window_center=match.center,
            screen_center=frame.to_screen_point(match.center),
            window_title=frame.title,
        )
        return MatchCandidate(template, match, frame) if passed else None

    def _cycle_failed(self, cycle: int, reason: str) -> None:
        self.audit.event("cycle_failed", cycle=cycle, reason=reason)

    def _sleep_interruptibly(self, seconds: float) -> bool:
        deadline = self.monotonic() + seconds
        while self.monotonic() < deadline:
            if self._stopped() or self._runtime_exceeded():
                return False
            self.sleep(min(1.0, deadline - self.monotonic()))
        return True

    def _stopped(self) -> bool:
        return self.stop_file.exists()

    def _runtime_exceeded(self) -> bool:
        return self.monotonic() - self.started_at >= self.config.max_runtime_seconds


def _load_state(raw: dict[str, Any], root: Path, name: str) -> ScenarioState:
    templates = tuple(root / Path(value) for value in raw["templates"])
    if not templates:
        raise ScenarioConfigError(f"Scenario state {name} must define templates.")
    threshold = float(raw["threshold"])
    if not 0.0 <= threshold <= 1.0:
        raise ScenarioConfigError(f"Scenario state {name} threshold must be between 0 and 1.")
    match_mode = str(raw.get("match_mode", "edge"))
    if match_mode not in {"color", "gray", "edge"}:
        raise ScenarioConfigError(f"Unsupported match mode for state {name}: {match_mode}")
    return ScenarioState(templates=templates, threshold=threshold, match_mode=match_mode)


def _positive(value: Any, name: str) -> float:
    number = float(value)
    if number <= 0:
        raise ScenarioConfigError(f"{name} must be greater than 0.")
    return number


def _positive_int(value: Any, name: str) -> int:
    number = int(value)
    if number <= 0:
        raise ScenarioConfigError(f"{name} must be greater than 0.")
    return number


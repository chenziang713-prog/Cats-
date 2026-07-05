from __future__ import annotations

import shutil
import time
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path

from .actions import ActionBackend, ActionResult, ClickAction, TapAction
from .backends import CaptureBackend, CaptureBackendError
from .console_output import (
    decision_summary,
    detection_summary,
    ignored_close_summary,
    recovery_summary,
    state_change_summary,
)
from .error_popup_recovery import ErrorPopupRecoveryManager
from .display_text import to_display_decision, to_display_target
from .game_base import GameDefinition
from .game_loader import resolve_template_path
from .license_client import LicenseResult, mask_license_key
from .recovery import GlobalStallWatchdog
from .run_recording import RunRecorder
from .strategy_base import (
    DetectionResult,
    StrategyContext,
    StrategyDecision,
    StrategyProtocol,
    TargetSpec,
)
from .vision import MatchResult, match_template

Matcher = Callable[..., MatchResult]


class StrategyRunner:
    def __init__(
        self,
        *,
        game: GameDefinition,
        strategy: StrategyProtocol,
        capture_backend: CaptureBackend,
        action_backend: ActionBackend,
        root: Path,
        output_dir: Path,
        max_loops: int,
        debug_save_capture: Path | None = None,
        run_recorder: RunRecorder | None = None,
        stop_file: Path | None = None,
        repeat_after_reward: bool = False,
        cycle_wait_seconds: float = 1800.0,
        max_cycles: int = 0,
        matcher: Matcher = match_template,
        sleep: Callable[[float], None] = time.sleep,
        recovery_watchdog: GlobalStallWatchdog | None = None,
        license_heartbeat: Callable[[], LicenseResult] | None = None,
        heartbeat_interval_seconds: float = 600.0,
        error_popup_recovery: ErrorPopupRecoveryManager | None = None,
    ) -> None:
        if max_loops <= 0:
            raise ValueError("max_loops must be greater than 0.")
        if cycle_wait_seconds < 0:
            raise ValueError("cycle_wait_seconds must not be negative.")
        if max_cycles < 0:
            raise ValueError("max_cycles must not be negative.")
        self.game = game
        self.strategy = strategy
        self.capture_backend = capture_backend
        self.action_backend = action_backend
        self.root = root
        self.output_dir = output_dir
        self.max_loops = max_loops
        self.debug_save_capture = debug_save_capture
        self.run_recorder = run_recorder
        self.stop_file = stop_file
        self.repeat_after_reward = repeat_after_reward
        self.cycle_wait_seconds = cycle_wait_seconds
        self.max_cycles = max_cycles
        self.matcher = matcher
        self.sleep = sleep
        self.recovery_watchdog = recovery_watchdog or GlobalStallWatchdog()
        self.license_heartbeat = license_heartbeat
        self.heartbeat_interval_seconds = heartbeat_interval_seconds
        self._next_license_heartbeat_at = time.monotonic() + heartbeat_interval_seconds
        self._license_failed = False
        self.error_popup_recovery = error_popup_recovery or ErrorPopupRecoveryManager()
        self._stop_requested = False
        self._last_decision: StrategyDecision | None = None
        self._last_action_result: ActionResult | None = None
        self._current_cycle_index = 1
        self.watch_ad_clicked_in_cycle = False
        self.close_ad_executed_in_cycle_count = 0
        self.confirm_reward_executed_in_cycle = False
        self.returned_to_home_after_ad = False
        self._current_screen_path: Path | None = None
        self._current_detections: dict[str, DetectionResult] = {}

    def run(self) -> int:
        completed = 0
        stop_reason = "completed"
        loop_index = 1
        self._start_cycle(self._current_cycle_index)
        while True:
            if self.stop_file is not None and self.stop_file.exists():
                stop_reason = "stop_file"
                self._record_stop(loop_index, "skipped_stop_file")
                break
            if not self._check_license_heartbeat():
                stop_reason = "license_heartbeat_failed"
                break
            if not self.repeat_after_reward and loop_index > self.max_loops:
                break
            print(f"[循环 {loop_index}]")
            print(f"轮次：{self._current_cycle_index}")
            screen_path = (
                self.run_recorder.screenshot_path(loop_index)
                if self.run_recorder is not None
                else self.output_dir / f"strategy-loop-{loop_index}.png"
            )
            try:
                frame = self.capture_backend.capture(screen_path)
            except CaptureBackendError as exc:
                print(f"Capture error: {exc}")
                stop_reason = f"capture_error: {exc}"
                if self.run_recorder is not None:
                    self.run_recorder.event("capture_error", loop=loop_index, error=str(exc))
                break
            print(f"Capture image size: width={frame.size[0]}, height={frame.size[1]}")
            if self.run_recorder is not None:
                frame_path = self.run_recorder.record_loop_capture(loop_index, frame.path)
                frame = type(frame)(
                    path=frame_path,
                    title=frame.title,
                    client_origin=frame.client_origin,
                    size=frame.size,
                )
            self._current_screen_path = frame.path
            if self.debug_save_capture is not None:
                self._save_debug_capture(frame.path, loop_index)

            detections = self._detect_targets(frame.path, frame.size)
            self._current_detections = detections
            if self.run_recorder is not None:
                self.run_recorder.record_detections(loop_index, detections)
            for detection in detections.values():
                print(
                    f"检测到：{to_display_target(detection.name)}（{detection.name}）\n"
                    f"置信度={detection.confidence:.3f}\n"
                    f"中心坐标={detection.center}"
                )
            chinese_detections = detection_summary(loop_index, detections)
            if chinese_detections is not None:
                print(chinese_detections)

            home_return_detection = (
                None
                if (
                    getattr(self.strategy, "handles_reward_cycle_completion", False)
                    or self.error_popup_recovery.active
                )
                else self._home_return_detection(detections)
            )
            if home_return_detection is not None:
                self.returned_to_home_after_ad = True
                completion_stop_reason = self._complete_cycle(
                    reason="home_return_after_ad",
                    last_seen_ad_entry=home_return_detection,
                )
                if completion_stop_reason is not None:
                    stop_reason = completion_stop_reason
                    break
                loop_index += 1
                continue

            context = StrategyContext(
                loop_index=loop_index,
                screen_path=frame.path,
                game=self.game,
                detections=detections,
                resolve_template=lambda template: resolve_template_path(self.game, self.root, template),
            )
            handling_error_popup = self.error_popup_recovery.active
            decision = (
                self.error_popup_recovery.decide(context)
                if handling_error_popup
                else None
            )
            self._record_error_popup_events(loop_index)
            if decision is None:
                decision = self.strategy.decide(context)
                if self.run_recorder is not None and hasattr(
                    self.strategy, "consume_state_recovery_event"
                ):
                    recovery_event = self.strategy.consume_state_recovery_event()
                    if recovery_event is not None:
                        self.run_recorder.event(
                            "state_recovered",
                            cycle_index=self._current_cycle_index,
                            **recovery_event,
                        )
                self._record_pending_strategy_events(detections)
            if not handling_error_popup:
                trigger = self.recovery_watchdog.observe(
                    state=str(getattr(self.strategy, "state", "unknown")),
                    decision=decision,
                    detections=detections,
                    screenshot_path=frame.path,
                )
                self._record_watchdog_events(loop_index)
                if trigger is not None:
                    print(recovery_summary(loop_index, trigger.reason))
                    recovery_lock = (
                        self.strategy.recovery_stage_lock()
                        if hasattr(self.strategy, "recovery_stage_lock")
                        else None
                    )
                    if recovery_lock is not None:
                        if self.run_recorder is not None:
                            self.run_recorder.event(
                                recovery_lock,
                                loop=loop_index,
                                cycle_index=self._current_cycle_index,
                                current_phase=getattr(self.strategy, "current_phase", ""),
                                watchdog_reason=trigger.reason,
                            )
                        print(f"[恢复] 阶段锁生效：{recovery_lock}")
                    elif trigger.should_recover and hasattr(self.action_backend, "keyevent"):
                        decision = StrategyDecision.keyevent(
                            "BACK",
                            "problem_recovery_adb_back",
                            trigger.reason,
                            post_action_delay_seconds=1.0,
                        )
                    elif not trigger.should_recover and self._can_enter_error_popup_recovery():
                        started = self.error_popup_recovery.start(
                            strategy=self.strategy,
                            cycle_index=self._current_cycle_index,
                            last_decision=self._last_decision or decision,
                        )
                        self._record_error_popup_events(loop_index)
                        if started:
                            decision = self.error_popup_recovery.decide(context) or StrategyDecision.wait(
                                1.0,
                                "error_popup_recovery_started",
                            )
                            self._record_error_popup_events(loop_index)
                        else:
                            decision = StrategyDecision.wait(1.0, trigger.reason)
                    elif not trigger.should_recover:
                        decision = StrategyDecision.wait(1.0, trigger.reason)
                    else:
                        print(
                            f"[循环 {loop_index}] 异常恢复：当前动作后端不支持 BACK，继续原策略"
                        )
            if self.run_recorder is not None and hasattr(self.strategy, "phase_snapshot"):
                self.run_recorder.record_phase_snapshot(
                    self.strategy.phase_snapshot(
                        loop_index=loop_index,
                        detections=detections,
                        decision=decision,
                    )
                )
            decision_name = decision.action_name or decision.kind
            print(f"决策：{to_display_decision(decision_name)}（{decision_name}）")
            print(decision_summary(loop_index, decision))
            if decision.kind == "complete":
                if self.run_recorder is not None:
                    self.run_recorder.last_decision = decision.action_name
                completion_stop_reason = self._complete_cycle(reason=decision.reason)
                if completion_stop_reason is not None:
                    stop_reason = completion_stop_reason
                    break
                loop_index += 1
                continue
            if self._execute_decision(decision, detections):
                completed += 1
            if self._stop_requested:
                stop_reason = "license_heartbeat_failed" if self._license_failed else "stop_file"
                break
            if self._is_reward_cycle_completed():
                completion_stop_reason = self._complete_cycle(reason="confirm_reward")
                if completion_stop_reason is not None:
                    stop_reason = completion_stop_reason
                    break
            if decision.kind == "stop":
                stop_reason = decision.reason or "stop"
                break
            loop_index += 1
        if self.run_recorder is not None:
            self.run_recorder.finish(stop_reason)
        return completed

    def _detect_targets(
        self,
        screen_path: Path,
        image_size: tuple[int, int],
    ) -> dict[str, DetectionResult]:
        detections: dict[str, DetectionResult] = {}
        targets = (*self.strategy.targets(), *self.error_popup_recovery.targets())
        for target in targets:
            template_path = resolve_template_path(self.game, self.root, target.template)
            if not template_path.exists():
                if not target.optional:
                    print(f"Template missing: {target.name} -> {template_path}")
                continue
            region = resolve_target_region(target, image_size)
            if region is not None and not region_overlaps(region, image_size):
                print(
                    f"Warning: target region does not overlap capture image; "
                    f"skipping {target.name}: region={region} image_size={image_size}"
                )
                continue
            try:
                match = self.matcher(
                    screen_path,
                    template_path,
                    mode=target.match_mode,
                    scale_min=target.scale_min,
                    scale_max=target.scale_max,
                    scale_step=target.scale_step,
                    region=region,
                )
            except (FileNotFoundError, RuntimeError, ValueError) as exc:
                print(f"Detection error: {target.name}: {exc}")
                continue
            if match.confidence < target.threshold:
                continue
            detections[target.name] = _to_detection_result(target, template_path, match)
        return detections

    def _save_debug_capture(self, capture_path: Path, loop_index: int) -> None:
        assert self.debug_save_capture is not None
        output_path = self.debug_save_capture
        if self.max_loops > 1:
            output_path = with_loop_suffix(output_path, loop_index)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(capture_path, output_path)
        print(f"Debug capture saved: {output_path}")

    def _execute_decision(
        self,
        decision: StrategyDecision,
        detections: dict[str, DetectionResult],
    ) -> bool:
        state_before = str(getattr(self.strategy, "state", "unknown"))
        if decision.kind == "wait":
            action_result = self.action_backend.wait(decision.wait_seconds, decision.reason)
            if decision.reason in {
                "watch_ad_detected_before_battle_complete_ignored",
                "close_ad_detected_before_ad_stage_ignored",
            }:
                action_result = ActionResult(
                    "wait",
                    "skipped_stage_not_ready",
                    decision.reason,
                )
            elif decision.reason == "close_ad_candidate_below_threshold_after_ad_wait":
                action_result = ActionResult(
                    "wait",
                    "waiting_close_ad",
                    decision.reason,
                )
            elif decision.reason == "scrap_watch_ad_button_cooldown_detected":
                action_result = ActionResult("state_transition", "skipped_cooldown", decision.reason)
            elif decision.reason.startswith("miss_count_") and "_waiting_" in decision.reason:
                action_result = ActionResult(
                    "wait",
                    "waiting_for_miss_threshold",
                    decision.reason,
                )
            self._last_decision = decision
            self._last_action_result = action_result
            detection = (
                detections.get(decision.target_name)
                if decision.target_name is not None
                else None
            )
            self._record_action(decision, action_result, detection, None)
            interrupted = self._perform_strategy_wait(decision)
            if interrupted:
                self._stop_requested = True
            else:
                self._notify_action_result(decision, action_result)
            self._register_watchdog_action(decision, action_result, state_before)
            return True
        if decision.kind == "stop":
            self._record_action(
                decision,
                ActionResult("stop", "skipped_stop_file", decision.reason),
                None,
                None,
            )
            return False
        if decision.kind == "keyevent":
            keycode = "BACK" if decision.target_name == "adb_back" else (decision.target_name or "BACK")
            action_result = self.action_backend.keyevent(keycode, decision.reason)
            if action_result is None:
                action_result = ActionResult("dry_run_keyevent", "executed", decision.reason)
            delay_info = None
            if action_result.result == "executed" and decision.post_action_delay_seconds > 0:
                delay_info = self._post_action_delay(decision)
            self._last_decision = decision
            self._last_action_result = action_result
            self._record_action(decision, action_result, None, delay_info)
            if self.run_recorder is not None:
                self.run_recorder.event(
                    decision.action_name or "keyevent",
                    keycode=keycode,
                    result=action_result.result,
                    reason=decision.reason,
                )
            self._register_watchdog_action(decision, action_result, state_before)
            if decision.action_name == "problem_recovery_adb_back":
                self.recovery_watchdog.record_recovery_action_result(
                    state=state_before,
                    action_result=action_result,
                )
                self._record_watchdog_events(
                    self.run_recorder.total_loops if self.run_recorder is not None else 0
                )
            self._notify_action_result(decision, action_result)
            return True
        if decision.kind not in {"click", "tap"}:
            print(f"Unknown decision kind: {decision.kind}")
            self._record_action(
                decision,
                ActionResult(decision.kind, "unknown_decision", decision.reason),
                None,
                None,
            )
            return False
        if decision.target_name is None or decision.target_name not in detections:
            print(f"Decision target not detected: {decision.target_name}")
            self._record_action(
                decision,
                ActionResult(decision.kind, "target_not_detected", decision.reason),
                None,
                None,
            )
            return False
        detection = detections[decision.target_name]
        reason = decision.reason or decision.action_name or detection.name
        action_result: ActionResult | None = None
        if decision.kind == "click":
            action_result = self.action_backend.click(
                ClickAction(
                    x=detection.center[0],
                    y=detection.center[1],
                    confidence=detection.confidence,
                    reason=reason,
                    min_confidence_override=decision.min_click_confidence_override,
                )
            )
        else:
            action_result = self.action_backend.tap(
                TapAction(
                    x=detection.center[0],
                    y=detection.center[1],
                    confidence=detection.confidence,
                    reason=reason,
                    min_confidence_override=decision.min_click_confidence_override,
                )
            )
        if action_result is None:
            action_result = ActionResult("dry_run_click", "executed", reason)
        delay_info = None
        if action_result.result == "executed" and decision.post_action_delay_seconds > 0:
            delay_info = self._post_action_delay(decision)
        self._last_decision = decision
        self._last_action_result = action_result
        self._record_action(decision, action_result, detection, delay_info)
        self._register_watchdog_action(decision, action_result, state_before)
        self._update_cycle_state(decision, action_result)
        self._notify_action_result(decision, action_result)
        return True

    def _is_reward_cycle_completed(self) -> bool:
        if getattr(self.strategy, "handles_reward_cycle_completion", False):
            return False
        return self.confirm_reward_executed_in_cycle

    def _completed_cycles(self) -> int:
        if self.run_recorder is None:
            return 0
        return self.run_recorder.total_cycles_completed

    def _start_cycle(self, cycle_index: int) -> None:
        print(f"Cycle {cycle_index} started")
        self._stop_requested = False
        self._last_decision = None
        self._last_action_result = None
        self.watch_ad_clicked_in_cycle = False
        self.close_ad_executed_in_cycle_count = 0
        self.confirm_reward_executed_in_cycle = False
        self.returned_to_home_after_ad = False
        self.recovery_watchdog.reset_cycle()
        self.error_popup_recovery.reset_cycle()
        if hasattr(self.strategy, "reset_cycle"):
            self.strategy.reset_cycle()
        elif hasattr(self.strategy, "_reset_close_limit"):
            self.strategy._reset_close_limit()
        if hasattr(self.action_backend, "reset_cycle"):
            self.action_backend.reset_cycle()
        if self.run_recorder is not None:
            self.run_recorder.record_cycle_started(cycle_index)
            strategy_state = getattr(self.strategy, "state", None)
            if strategy_state is not None:
                self.run_recorder.event(
                    "state_changed",
                    cycle_index=cycle_index,
                    from_state=None,
                    to_state=strategy_state,
                    decision="cycle_started",
                )

    def _record_cycle_completed(
        self,
        *,
        reason: str,
        last_seen_ad_entry: DetectionResult | None = None,
    ) -> None:
        print(f"Cycle {self._current_cycle_index} completed reason={reason}")
        if self.run_recorder is not None:
            self.run_recorder.record_cycle_completed(
                self._current_cycle_index,
                reason=reason,
                last_seen_ad_entry=last_seen_ad_entry,
            )
            if reason == "home_return_after_ad":
                self.run_recorder.event(
                    "cycle_completed_by_home_return",
                    cycle_index=self._current_cycle_index,
                    confidence=last_seen_ad_entry.confidence if last_seen_ad_entry else None,
                    center=list(last_seen_ad_entry.center) if last_seen_ad_entry else None,
                )

    def _complete_cycle(
        self,
        *,
        reason: str,
        last_seen_ad_entry: DetectionResult | None = None,
    ) -> str | None:
        self._record_cycle_completed(reason=reason, last_seen_ad_entry=last_seen_ad_entry)
        if not self.repeat_after_reward:
            if reason == "scrap_then_ad_reward_completed":
                return reason
            return (
                "reward_flow_completed_by_home_return"
                if reason.startswith("home_return_after_")
                else "reward_flow_completed"
            )
        if self.max_cycles > 0 and self._completed_cycles() >= self.max_cycles:
            return "max_cycles_reached"
        if self._cycle_wait():
            return "license_heartbeat_failed" if self._license_failed else "stop_file"
        self._current_cycle_index += 1
        self._start_cycle(self._current_cycle_index)
        return None

    def _home_return_detection(
        self,
        detections: dict[str, DetectionResult],
    ) -> DetectionResult | None:
        if not self.watch_ad_clicked_in_cycle or self.close_ad_executed_in_cycle_count < 1:
            return None
        if "reward_confirm_marker" in detections or "confirm_button" in detections:
            return None
        detection = detections.get("ad_entry")
        if detection is None:
            return None
        min_confidence = (
            self.run_recorder.min_click_confidence
            if self.run_recorder is not None
            else 0.80
        )
        if detection.confidence < min_confidence:
            return None
        return detection

    def _update_cycle_state(
        self,
        decision: StrategyDecision,
        action_result: ActionResult,
    ) -> None:
        if action_result.result != "executed":
            return
        if decision.action_name == "click_watch_ad_button":
            self.watch_ad_clicked_in_cycle = True
        elif decision.action_name == "close_ad":
            self.close_ad_executed_in_cycle_count += 1
        elif decision.action_name == "confirm_reward":
            self.confirm_reward_executed_in_cycle = True

    def _notify_action_result(
        self,
        decision: StrategyDecision,
        action_result: ActionResult,
    ) -> None:
        if decision.action_name.startswith("error_popup_recovery"):
            self.error_popup_recovery.on_action_result(decision, action_result)
            loop_index = self.run_recorder.total_loops if self.run_recorder is not None else 0
            self._record_error_popup_events(loop_index)
            return
        self._notify_strategy_action_result(decision, action_result)

    def _can_enter_error_popup_recovery(self) -> bool:
        if self.stop_file is not None and self.stop_file.exists():
            return False
        if self._license_failed:
            return False
        action_count = int(getattr(self.action_backend, "action_count", 0))
        max_actions = getattr(self.action_backend, "max_actions", None)
        if max_actions is not None and action_count >= int(max_actions):
            return False
        if not hasattr(self.action_backend, "click"):
            return False
        if type(self.action_backend).__name__ == "AdbActionBackend":
            adb_path = Path(getattr(self.action_backend, "adb_path", ""))
            adb_serial = str(getattr(self.action_backend, "adb_serial", ""))
            if not adb_path.is_file() or not adb_serial.strip():
                return False
        return True

    def _record_error_popup_events(self, loop_index: int) -> None:
        for event in self.error_popup_recovery.drain_events():
            event_name = str(event.pop("event"))
            if self.run_recorder is not None:
                self.run_recorder.event(
                    event_name,
                    loop=loop_index,
                    cycle_index=self._current_cycle_index,
                    **event,
                )
            if event_name == "error_popup_recovery_started":
                print(f"[循环 {loop_index}] 异常恢复：进入错误弹窗识别恢复")
            elif event_name == "error_popup_button_clicked":
                print(f"[循环 {loop_index}] 异常恢复：已处理错误弹窗按钮")
            elif event_name == "error_popup_recovery_succeeded":
                print(f"[循环 {loop_index}] 异常恢复：弹窗清除后已恢复原流程")
            elif event_name == "max_error_popup_recovery_attempts_reached":
                print(f"[循环 {loop_index}] 可疑：错误弹窗恢复次数已达上限")

    def _notify_strategy_action_result(
        self,
        decision: StrategyDecision,
        action_result: ActionResult,
    ) -> None:
        if not hasattr(self.strategy, "on_action_result"):
            return
        old_state = getattr(self.strategy, "state", None)
        self.strategy.on_action_result(decision, action_result)
        new_state = getattr(self.strategy, "state", None)
        if self.run_recorder is not None and old_state != new_state:
            state_change_details = {}
            if hasattr(self.strategy, "consume_state_change_details"):
                state_change_details = self.strategy.consume_state_change_details() or {}
            self.run_recorder.event(
                "state_changed",
                cycle_index=self._current_cycle_index,
                from_state=old_state,
                to_state=new_state,
                decision=decision.action_name or decision.kind,
                **state_change_details,
            )
        if old_state != new_state:
            loop_index = self.run_recorder.total_loops if self.run_recorder is not None else 0
            print(state_change_summary(loop_index, old_state, new_state))
        self._record_pending_strategy_events()

    def _record_pending_strategy_events(
        self,
        detections: dict[str, DetectionResult] | None = None,
    ) -> None:
        if self.run_recorder is None or not hasattr(self.strategy, "consume_strategy_events"):
            return
        for event in self.strategy.consume_strategy_events():
            event_name = str(event.pop("event"))
            record_in_click_records = bool(event.pop("record_in_click_records", False))
            self.run_recorder.event(
                event_name,
                cycle_index=self._current_cycle_index,
                **event,
            )
            if event_name == "close_ad_candidate_ignored":
                print(
                    ignored_close_summary(
                        self.run_recorder.total_loops,
                        event.get("confidence"),
                    )
                )
            target_name = str(event.get("target_name", ""))
            detection = None if detections is None else detections.get(target_name)
            if record_in_click_records and detection is not None:
                reason = str(event.get("reason", event_name))
                self.run_recorder.record_action(
                    loop_index=self.run_recorder.total_loops,
                    decision=StrategyDecision.wait(
                        0.0,
                        reason,
                        target_name=target_name,
                    ),
                    action_result=ActionResult(
                        "wait",
                        "skipped_stage_not_ready",
                        reason,
                    ),
                    detection=detection,
                    max_actions_used=self.action_backend.action_count,
                    close_streak=getattr(
                        self.strategy,
                        "close_streak",
                        getattr(self.strategy, "_consecutive_close_actions", None),
                    ),
                )

    def _register_watchdog_action(
        self,
        decision: StrategyDecision,
        action_result: ActionResult | None,
        state_before: str,
    ) -> None:
        if action_result is None:
            return
        if decision.action_name.startswith("error_popup_recovery"):
            return
        self.recovery_watchdog.register_action(
            decision=decision,
            action_result=action_result,
            state=state_before,
            screenshot_path=self._current_screen_path,
            detections=self._current_detections,
        )

    def _record_watchdog_events(self, loop_index: int) -> None:
        for event in self.recovery_watchdog.drain_events():
            event_name = str(event.pop("event"))
            if self.run_recorder is not None:
                self.run_recorder.event(
                    event_name,
                    loop=loop_index,
                    cycle_index=self._current_cycle_index,
                    **event,
                )
            if event_name == "recovery_succeeded":
                print(f"[循环 {loop_index}] 异常恢复：重新识别成功，继续当前策略")
            elif event_name == "recovery_failed":
                print(f"[循环 {loop_index}] 异常恢复：恢复未成功，等待下一次判断")
            elif event_name == "click_no_effect_detected":
                print(f"[循环 {loop_index}] 可疑：点击后页面未变化")

    def _record_license_result(self, result: LicenseResult) -> None:
        if self.run_recorder is None:
            return
        cache = result.cache
        self.run_recorder.record_license_status(
            event_type=result.event or ("license_heartbeat_ok" if result.ok else "license_heartbeat_failed"),
            status=result.status,
            license_key_masked=("" if cache is None else mask_license_key(cache.license_key)),
            expires_at=("" if cache is None else cache.expires_at),
            features=(() if cache is None else cache.features),
            error=result.error,
            message=result.message,
        )

    def _check_license_heartbeat(self) -> bool:
        if self.license_heartbeat is None:
            return True
        if time.monotonic() < self._next_license_heartbeat_at:
            return True
        result = self.license_heartbeat()
        self._record_license_result(result)
        self._next_license_heartbeat_at = time.monotonic() + self.heartbeat_interval_seconds
        if result.ok:
            return True
        self._license_failed = True
        print(f"授权心跳失败，任务停止：{result.message}")
        return False

    def _perform_strategy_wait(self, decision: StrategyDecision) -> bool:
        seconds = decision.wait_seconds
        if seconds <= 0:
            return False
        event_prefix = decision.reason if decision.reason in {"battle_wait", "ad_wait"} else ""
        if self.run_recorder is not None:
            if event_prefix:
                self.run_recorder.record_strategy_wait_started(event_prefix, seconds)
        remaining = seconds
        interrupted = False
        while remaining > 0:
            if self.stop_file is not None and self.stop_file.exists():
                interrupted = True
                break
            if not self._check_license_heartbeat():
                interrupted = True
                self._stop_requested = True
                break
            sleep_seconds = min(0.5, remaining)
            self.sleep(sleep_seconds)
            remaining -= sleep_seconds
        if self.stop_file is not None and self.stop_file.exists():
            interrupted = True
        if self.run_recorder is not None:
            if event_prefix:
                self.run_recorder.record_strategy_wait_finished(event_prefix, interrupted)
        return interrupted

    def _cycle_wait(self) -> bool:
        seconds = self.cycle_wait_seconds
        next_cycle_start = _future_timestamp(seconds)
        print(f"waiting {seconds:g} seconds before next cycle")
        print(f"next cycle start time: {next_cycle_start}")
        if self.run_recorder is not None:
            self.run_recorder.record_cycle_wait_started(
                cycle_index=self._current_cycle_index,
                seconds=seconds,
                next_cycle_scheduled_at=next_cycle_start,
            )
        remaining = seconds
        interrupted = False
        while remaining > 0:
            if self.stop_file is not None and self.stop_file.exists():
                interrupted = True
                break
            if not self._check_license_heartbeat():
                interrupted = True
                break
            sleep_seconds = min(0.5, remaining)
            self.sleep(sleep_seconds)
            remaining -= sleep_seconds
        if self.stop_file is not None and self.stop_file.exists():
            interrupted = True
        if interrupted:
            print("stopped during cycle wait")
        if self.run_recorder is not None:
            self.run_recorder.record_cycle_wait_finished(
                cycle_index=self._current_cycle_index,
                interrupted_by_stop_file=interrupted,
            )
        return interrupted

    def _post_action_delay(self, decision: StrategyDecision) -> dict[str, object]:
        seconds = decision.post_action_delay_seconds
        reason = decision.reason or decision.action_name or decision.kind
        started_at = _timestamp()
        print(f"post_action_delay seconds={seconds:g} reason={reason}")
        remaining = seconds
        interrupted = False
        while remaining > 0:
            if self.stop_file is not None and self.stop_file.exists():
                interrupted = True
                self._stop_requested = True
                break
            if not self._check_license_heartbeat():
                interrupted = True
                self._stop_requested = True
                break
            sleep_seconds = min(0.5, remaining)
            self.sleep(sleep_seconds)
            remaining -= sleep_seconds
        if self.stop_file is not None and self.stop_file.exists():
            interrupted = True
            self._stop_requested = True
        finished_at = _timestamp()
        if self.run_recorder is not None:
            self.run_recorder.record_delay(
                loop_index=self.run_recorder.total_loops,
                decision=decision.action_name or decision.kind,
                seconds=seconds,
                started_at=started_at,
                finished_at=finished_at,
                interrupted_by_stop_file=interrupted,
            )
        return {
            "seconds": seconds,
            "started_at": started_at,
            "finished_at": finished_at,
            "interrupted_by_stop_file": interrupted,
        }

    def _record_action(
        self,
        decision: StrategyDecision,
        action_result: ActionResult,
        detection: DetectionResult | None,
        delay_info: dict[str, object] | None,
    ) -> None:
        if self.run_recorder is None:
            return
        notes = ""
        effective_min_confidence = (
            decision.min_click_confidence_override
            if decision.min_click_confidence_override is not None
            else self.run_recorder.min_click_confidence
        )
        if (
            detection is not None
            and action_result.action_type == "dry_run_click"
            and detection.confidence < effective_min_confidence
        ):
            notes = (
                f"below_min_click_confidence={effective_min_confidence:.3f}"
            )
        self.run_recorder.record_action(
            loop_index=self.run_recorder.total_loops,
            decision=decision,
            action_result=action_result,
            detection=detection,
            max_actions_used=self.action_backend.action_count,
            close_streak=getattr(self.strategy, "_consecutive_close_actions", None),
            notes=notes,
            post_action_delay_seconds=(
                float(delay_info["seconds"]) if delay_info is not None else 0.0
            ),
            delay_started_at=str(delay_info["started_at"]) if delay_info is not None else "",
            delay_finished_at=str(delay_info["finished_at"]) if delay_info is not None else "",
            delay_interrupted_by_stop_file=(
                bool(delay_info["interrupted_by_stop_file"])
                if delay_info is not None
                else False
            ),
        )

    def _record_stop(self, loop_index: int, result: str) -> None:
        if self.run_recorder is None:
            return
        self.run_recorder.total_loops = max(self.run_recorder.total_loops, loop_index - 1)
        self.run_recorder.record_action(
            loop_index=loop_index,
            decision=StrategyDecision.stop("stop_file"),
            action_result=ActionResult("stop", result, "stop_file"),
            detection=None,
            max_actions_used=self.action_backend.action_count,
            close_streak=getattr(self.strategy, "_consecutive_close_actions", None),
        )


def _timestamp() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _future_timestamp(seconds: float) -> str:
    return (datetime.now() + timedelta(seconds=seconds)).isoformat(timespec="seconds")


def _to_detection_result(
    target: TargetSpec,
    template_path: Path,
    match: MatchResult,
) -> DetectionResult:
    return DetectionResult(
        name=target.name,
        template=template_path,
        confidence=match.confidence,
        center=match.center,
        top_left=match.top_left,
        size=match.size,
        scale=match.scale,
        threshold=target.threshold,
    )


def resolve_target_region(
    target: TargetSpec,
    image_size: tuple[int, int],
) -> tuple[int, int, int, int] | None:
    if target.region is None:
        return None
    if hasattr(target.region, "resolve"):
        return target.region.resolve(image_size)  # type: ignore[union-attr]
    return target.region.as_tuple


def region_overlaps(region: tuple[int, int, int, int], image_size: tuple[int, int]) -> bool:
    image_width, image_height = image_size
    x, y, width, height = region
    if x < 0 or y < 0 or width <= 0 or height <= 0:
        return False
    right = min(image_width, x + width)
    bottom = min(image_height, y + height)
    return x < image_width and y < image_height and right > x and bottom > y


def with_loop_suffix(path: Path, loop_index: int) -> Path:
    return path.with_name(f"{path.stem}-loop-{loop_index}{path.suffix}")

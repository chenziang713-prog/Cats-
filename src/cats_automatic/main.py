from __future__ import annotations

import argparse
from pathlib import Path

from .actions import ActionExecutor
from .actions import DryRunBackend
from .backends import (
    CaptureBackendError,
    StaticImageCaptureBackend,
    create_capture_backend,
    format_window_list,
    list_windows,
)
from .config_loader import load_flow
from .game_loader import GameLoadError, load_game, load_strategy
from .rules import RuleEngine
from .runner import run_match_once, run_watch
from .scenario import load_scenario
from .strategy_runner import StrategyRunner


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="CATS Automatic desktop vision prototype."
    )
    parser.add_argument(
        "--flow",
        type=Path,
        default=None,
        help="Path to a JSON flow config. Defaults to configs/default-flow.json.",
    )
    parser.add_argument(
        "--screen",
        type=Path,
        help="Screenshot image to inspect.",
    )
    parser.add_argument(
        "--template",
        type=Path,
        help="Template image to find inside the screenshot.",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=None,
        help="Override the flow confidence threshold.",
    )
    parser.add_argument(
        "--match-mode",
        choices=["color", "gray", "edge"],
        default="color",
        help="Template matching mode. Use edge for icons with changing backgrounds.",
    )
    parser.add_argument(
        "--capture",
        type=Path,
        help="Save a desktop screenshot to the given path, then exit.",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Capture the current desktop once, match the template, then exit.",
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Continuously capture and match until interrupted.",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=1.0,
        help="Seconds between watch iterations. Defaults to 1.0.",
    )
    parser.add_argument(
        "--max-failures",
        type=int,
        default=5,
        help="Stop watch mode after this many low-confidence matches.",
    )
    parser.add_argument(
        "--scale-min",
        type=float,
        default=1.0,
        help="Smallest template scale to try. Defaults to 1.0.",
    )
    parser.add_argument(
        "--scale-max",
        type=float,
        default=1.0,
        help="Largest template scale to try. Defaults to 1.0.",
    )
    parser.add_argument(
        "--scale-step",
        type=float,
        default=0.1,
        help="Template scale increment. Defaults to 0.1.",
    )
    parser.add_argument(
        "--allow-click",
        action="store_true",
        help="Reserved for future real-click support. Current builds stay dry-run only.",
    )
    parser.add_argument(
        "--click-cooldown",
        type=float,
        default=1.0,
        help="Minimum seconds between clicks. Defaults to 1.0.",
    )
    parser.add_argument(
        "--max-actions",
        type=int,
        default=None,
        help="Maximum clicks/dry-run actions. Defaults to 1, or two per scenario cycle.",
    )
    parser.add_argument(
        "--repeat-actions",
        type=int,
        default=1,
        help="Repeat each accepted action this many times. Defaults to 1.",
    )
    parser.add_argument(
        "--stop-file",
        type=Path,
        default=Path("stop.flag"),
        help="If this file exists, actions are skipped. Defaults to stop.flag.",
    )
    parser.add_argument(
        "--log-file",
        type=Path,
        default=None,
        help="Append action logs to this file.",
    )
    parser.add_argument(
        "--scenario",
        type=Path,
        default=None,
        help="Run an authorized QA scenario from a JSON config.",
    )
    parser.add_argument(
        "--scenario-log-file",
        type=Path,
        default=Path("output/qa-ad-flow.jsonl"),
        help="Append scenario audit events as JSONL.",
    )
    parser.add_argument(
        "--game",
        default=None,
        help="Load a game module, for example: cats.",
    )
    parser.add_argument(
        "--strategy",
        default=None,
        help="Strategy name inside the selected game. Defaults to the game's strategy.py.",
    )
    parser.add_argument(
        "--max-loops",
        type=int,
        default=3,
        help="Maximum strategy loops. Defaults to 3.",
    )
    parser.add_argument(
        "--capture-backend",
        choices=["fullscreen", "window", "replay", "adb"],
        default="fullscreen",
        help="Capture backend for live, watch, capture, and strategy modes.",
    )
    parser.add_argument(
        "--window-title",
        default=None,
        help="Window title keyword required by --capture-backend window.",
    )
    parser.add_argument(
        "--window-hwnd",
        type=parse_int,
        default=None,
        help="Exact window handle for --capture-backend window. Accepts decimal or 0x hex.",
    )
    parser.add_argument(
        "--list-windows",
        action="store_true",
        help="List top-level Windows windows and exit.",
    )
    parser.add_argument(
        "--replay-screens",
        action="append",
        nargs="+",
        default=None,
        help=(
            "Replay screenshot paths required by --capture-backend replay. "
            "Supports space-separated paths, repeated flags, and comma-separated legacy values."
        ),
    )
    parser.add_argument(
        "--adb-path",
        type=Path,
        default=None,
        help="Path to adb executable required by --capture-backend adb.",
    )
    parser.add_argument(
        "--adb-serial",
        default=None,
        help="ADB device serial required by --capture-backend adb.",
    )
    parser.add_argument(
        "--debug-save-capture",
        type=Path,
        default=None,
        help="Save each strategy capture for debugging. Multi-loop runs add a loop suffix.",
    )
    return parser


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    args = build_parser().parse_args()
    if args.list_windows:
        print(format_window_list(list_windows()))
        return
    flow_path = args.flow or root / "configs" / "default-flow.json"

    flow = load_flow(flow_path)
    if args.threshold is not None:
        flow = flow.with_threshold(args.threshold)
    if args.allow_click:
        raise SystemExit(
            "--allow-click is reserved for a future input backend. "
            "Current builds only support dry-run actions."
        )

    if args.game:
        run_strategy_mode(args, root)
        return

    scenario = load_scenario(args.scenario, root) if args.scenario else None
    max_actions = (
        args.max_actions
        if args.max_actions is not None
        else scenario.max_cycles * scenario.max_actions_per_cycle
        if scenario is not None
        else 1
    )
    executor = ActionExecutor(
        dry_run=True,
        max_actions=max_actions,
        repeat_actions=args.repeat_actions,
        click_cooldown=args.click_cooldown,
        stop_file=args.stop_file,
        log_file=args.log_file,
    )
    engine = RuleEngine(flow=flow, executor=executor)

    print("CATS Automatic desktop prototype")
    print(f"Loaded flow: {flow.name}")
    print(f"Configured steps: {len(flow.steps)}")
    print("Action mode: DRY RUN")

    try:
        if args.scenario:
            from .scenario import JsonlAuditLogger, ScenarioRunner
            from .window_capture import WindowsDesktopCapture

            assert scenario is not None
            audit = JsonlAuditLogger(args.scenario_log_file)
            try:
                runner = ScenarioRunner(
                    config=scenario,
                    capture_provider=WindowsDesktopCapture(),
                    executor=executor,
                    audit=audit,
                    output_dir=root / "output" / "scenario",
                    stop_file=args.stop_file,
                )
                runner.run()
            finally:
                audit.close()
            return

        if args.capture:
            capture_backend = build_capture_backend(args)
            frame = capture_backend.capture(args.capture)
            print(f"Captured screenshot: {frame.path}")
            return

        if args.live:
            if not args.template:
                raise SystemExit("--live requires --template.")
            capture_backend = build_capture_backend(args)
            live_screen = capture_backend.capture(root / "output" / "live-screen.png").path
            print(f"Captured live screenshot: {live_screen}")
            run_match_once(
                screen_path=live_screen,
                template_path=args.template,
                engine=engine,
                threshold=flow.confidence_threshold,
                match_mode=args.match_mode,
                scale_min=args.scale_min,
                scale_max=args.scale_max,
                scale_step=args.scale_step,
            )
            return

        if args.watch:
            if not args.template:
                raise SystemExit("--watch requires --template.")
            run_watch(
                template_path=args.template,
                screen_path=args.screen,
                engine=engine,
                interval=args.interval,
                max_failures=args.max_failures,
                threshold=flow.confidence_threshold,
                match_mode=args.match_mode,
                scale_min=args.scale_min,
                scale_max=args.scale_max,
                scale_step=args.scale_step,
                root=root,
                capture_backend=build_capture_backend(args),
            )
            return

        if args.screen or args.template:
            if not args.screen or not args.template:
                raise SystemExit("--screen and --template must be provided together.")
            run_match_once(
                screen_path=args.screen,
                template_path=args.template,
                engine=engine,
                threshold=flow.confidence_threshold,
                match_mode=args.match_mode,
                scale_min=args.scale_min,
                scale_max=args.scale_max,
                scale_step=args.scale_step,
            )
            return

        engine.describe_next_step()
    finally:
        executor.close()


def build_capture_backend(args: argparse.Namespace):
    try:
        return create_capture_backend(
            args.capture_backend,
            window_title=args.window_title,
            window_hwnd=args.window_hwnd,
            adb_path=args.adb_path,
            adb_serial=args.adb_serial,
            replay_screens=parse_replay_screens(args.replay_screens),
        )
    except CaptureBackendError as exc:
        raise SystemExit(str(exc)) from exc


def parse_replay_screens(raw_value: list[list[str]] | str | None) -> list[Path]:
    if raw_value is None:
        return []
    if isinstance(raw_value, str):
        groups = [[raw_value]]
    else:
        groups = raw_value

    paths: list[Path] = []
    for group in groups:
        for value in group:
            paths.extend(Path(part.strip()) for part in value.split(",") if part.strip())
    return paths


def parse_int(raw_value: str) -> int:
    return int(raw_value, 0)


def build_strategy_capture_backend(args: argparse.Namespace):
    if args.screen is not None:
        return StaticImageCaptureBackend(args.screen)
    return build_capture_backend(args)


def run_strategy_mode(args: argparse.Namespace, root: Path) -> None:
    try:
        game = load_game(args.game)
        strategy = load_strategy(args.game, args.strategy)
        capture_backend = build_strategy_capture_backend(args)
    except (GameLoadError, CaptureBackendError) as exc:
        raise SystemExit(str(exc)) from exc

    print(f"Loaded game: {game.name}")
    print(f"Loaded strategy: {args.strategy or 'default'}")
    print(f"Capture backend: {capture_backend.name}")
    action_backend = DryRunBackend(log_file=args.log_file)
    try:
        runner = StrategyRunner(
            game=game,
            strategy=strategy,
            capture_backend=capture_backend,
            action_backend=action_backend,
            root=root,
            output_dir=root / "output" / "strategy",
            max_loops=args.max_loops,
            debug_save_capture=args.debug_save_capture,
        )
        runner.run()
    finally:
        action_backend.close()


if __name__ == "__main__":
    main()

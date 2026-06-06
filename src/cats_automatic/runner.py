from __future__ import annotations

import time
from pathlib import Path

from .backends import CaptureBackend
from .rules import RuleEngine


def validate_existing_file(path: Path, label: str) -> None:
    if not path.exists():
        raise SystemExit(f"{label} does not exist: {path}")
    if not path.is_file():
        raise SystemExit(f"{label} is not a file: {path}")


def run_match_once(
    *,
    screen_path: Path,
    template_path: Path,
    engine: RuleEngine,
    threshold: float,
    match_mode: str,
    scale_min: float,
    scale_max: float,
    scale_step: float,
) -> bool:
    validate_existing_file(screen_path, "Screen image")
    validate_existing_file(template_path, "Template image")

    from .vision import match_template

    try:
        match = match_template(
            screen_path,
            template_path,
            mode=match_mode,
            scale_min=scale_min,
            scale_max=scale_max,
            scale_step=scale_step,
        )
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc

    print(
        "Template match: "
        f"mode={match_mode} "
        f"scale={match.scale:.2f} "
        f"confidence={match.confidence:.3f} "
        f"top_left={match.top_left} center={match.center} size={match.size}"
    )
    clicked = engine.click_if_confident(match, reason=f"matched {template_path.name}")
    if not clicked:
        print(
            "No action taken: "
            f"confidence {match.confidence:.3f} is below threshold {threshold:.3f}"
        )
    return clicked


def run_watch(
    *,
    template_path: Path,
    screen_path: Path | None,
    engine: RuleEngine,
    interval: float,
    max_failures: int,
    threshold: float,
    match_mode: str,
    scale_min: float,
    scale_max: float,
    scale_step: float,
    root: Path,
    capture_backend: CaptureBackend | None = None,
) -> None:
    if interval <= 0:
        raise SystemExit("--interval must be greater than 0.")
    if max_failures <= 0:
        raise SystemExit("--max-failures must be greater than 0.")

    validate_existing_file(template_path, "Template image")
    failures = 0
    iteration = 0
    capture_path = root / "output" / "watch-screen.png"

    print(
        "Watch mode started. Press Ctrl+C to stop. "
        f"interval={interval}s max_failures={max_failures}"
    )
    try:
        while True:
            iteration += 1
            current_screen = screen_path
            if current_screen is None:
                if capture_backend is None:
                    from .capture import capture_screen

                    current_screen = capture_screen(capture_path)
                else:
                    current_screen = capture_backend.capture(capture_path).path

            print(f"[watch #{iteration}] screen={current_screen}")
            clicked = run_match_once(
                screen_path=current_screen,
                template_path=template_path,
                engine=engine,
                threshold=threshold,
                match_mode=match_mode,
                scale_min=scale_min,
                scale_max=scale_max,
                scale_step=scale_step,
            )
            failures = 0 if clicked else failures + 1
            if failures >= max_failures:
                print(f"Watch stopped after {failures} consecutive failures.")
                return
            time.sleep(interval)
    except KeyboardInterrupt:
        print("Watch stopped by user.")

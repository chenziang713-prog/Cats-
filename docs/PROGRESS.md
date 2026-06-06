# CATS Automatic Progress

## Current Project Shape

The project is now a `src` layout Python package:

```text
src/cats_automatic/       Generic automation framework
src/cats_automatic/games/ Game-specific adapters
configs/                  Generic example flow configs
templates/                Root-level prototype templates
samples/                  Static screenshots for manual matching tests
tests/                    Unit tests
docs/                     Setup, usage, and progress notes
```

This structure is suitable for continued development because the core framework
can stay stable while game-specific files move under `games/<game_name>/`.

## Completed Features

- Command-line entrypoint with module execution support: `python -m cats_automatic.main`.
- Compatibility wrapper: `python run_prototype.py`.
- Strategy entrypoint: `--game cats --strategy ad_reward --max-loops 3`.
- Capture backend selection: `--capture-backend fullscreen|window`.
- JSON flow loading through `config_loader.py`.
- Flow rules and confidence gating through `rules.py`.
- Template matching through `vision.py`.
- `color`, `gray`, and `edge` match modes.
- Static `--screen + --template` matching.
- `--capture` screenshot saving.
- `--live` one-shot capture and match.
- `--watch` continuous dry-run matching.
- Dry-run action logging through `actions.py`.
- Scenario runner skeleton for multi-step QA flows.
- Game module scaffold under `games/cats`.
- Strategy loader and dry-run `StrategyRunner`.
- C.A.T.S. `ad_reward` strategy with target priority logic.
- Window capture backend interface and clear error handling.
- Tests for rules, scenario flow, desktop capture metadata, and framework config.

## File Responsibilities

- `main.py`: command-line parsing and dispatch.
- `runner.py`: one-shot matching and watch-loop execution.
- `config_loader.py`: generic flow config dataclasses and JSON loading.
- `rules.py`: rule engine and confidence-based action decisions.
- `vision.py`: OpenCV image loading, scaling, and template matching.
- `actions.py`: action boundary; currently dry-run only.
- `capture.py`: full-desktop screenshot capture.
- `window_capture.py`: optional Windows desktop/window capture helpers.
- `backends/`: capture backend abstractions for fullscreen and window capture.
- `game_loader.py`: game and strategy loading plus template resolution.
- `strategy_base.py`: target, detection, context, and decision dataclasses.
- `strategy_runner.py`: finite dry-run strategy loop.
- `scenario.py`: multi-step scenario config and dry-run scenario runner.
- `game_base.py`: game module interface definitions.
- `games/cats/game.py`: C.A.T.S. module metadata.
- `games/cats/strategy.py`: C.A.T.S.-specific template grouping helpers.

## Not Finished Yet

- Stable game-specific strategy execution is still minimal.
- The C.A.T.S. templates are not yet fully moved from root `templates/` into
  `src/cats_automatic/games/cats/templates/`.
- Scenario matching can still false-positive if unrelated UI contains a similar
  template.
- Android migration is only documented at a planning level.
- Real click/input is intentionally not implemented in this build.

## Current Risks

- Running `python src\cats_automatic\main.py` directly can fail because
  relative imports need package context.
- Live desktop screenshots are environment-dependent and should not be used as
  the primary automated test source.
- Template matching can identify visually similar areas; tighter templates and
  region constraints may be needed later.
- The window backend uses a window rectangle screenshot and may be affected by
  minimized, hidden, or occluded windows.
- Real input backends need stronger safeguards before being enabled.

## Dry-Run Only Features

- `RuleEngine.click_if_confident` produces click candidates.
- `ActionExecutor` logs accepted actions.
- `watch` mode prints matched coordinates.
- Scenario actions are recorded as dry-run actions.
- Strategy mode records `DRY RUN click`, `DRY RUN tap`, and `DRY RUN wait`.

## Future Real-Click Candidates

These can later connect to a real input backend, but should stay disabled now:

- `ActionExecutor` platform click backend.
- Scenario runner real action mode.
- Repeated click execution.
- Android/emulator input backend.

## Recommended Development Order

1. Keep package execution clean: `python -m cats_automatic.main`.
2. Move C.A.T.S.-specific templates/config fully under `games/cats/`.
3. Add more strategies such as `daily_reward` and `open_chest`.
4. Expand region-aware strategy targets from tests into real C.A.T.S. templates.
5. Add an ADB or emulator-native capture backend after the window backend is stable.
6. Only after stable dry-run verification, design a guarded real input backend.

## Switching To Another Game

Replace or add these files:

```text
src/cats_automatic/games/<new_game>/game.py
src/cats_automatic/games/<new_game>/strategy.py
src/cats_automatic/games/<new_game>/templates/
src/cats_automatic/games/<new_game>/config.json
tests/test_<new_game>.py
```

Do not rewrite these framework files for each game:

```text
main.py
runner.py
config_loader.py
rules.py
vision.py
actions.py
capture.py
game_base.py
```

## Next Tasks

- Move current root templates into the C.A.T.S. module once their roles are
  stable.
- Add `daily_reward` and `open_chest` strategies under `games/cats/strategies/`.
- Add richer strategy logs for no-match and low-confidence candidates.
- Add an optional emulator/ADB capture backend.

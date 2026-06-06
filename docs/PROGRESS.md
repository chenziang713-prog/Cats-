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
- C.A.T.S. `ad_reward` strategy first stable feature: detect `ad_entry` from
  `src/cats_automatic/games/cats/templates/ad-entry.png`.
- C.A.T.S. film ad page strategy step: detect `page_marker` from
  `templates/page-marker.png`, require `watch_ad_button` from
  `templates/watch-ad-button.png`, then return `click_watch_ad_button`.
- C.A.T.S. ad close strategy step: detect right-top `close-end-2` first, then
  left-top `close-end-1`, both with fixed regions, then return `close_ad`.
- Consecutive ad close guard: `ad_reward` allows up to three consecutive
  `close_ad` decisions, then returns `wait_close_limit_reached` until a
  non-close state resets the counter.
- Reward confirmation page step: detect `reward_confirm_marker`, require
  `confirm_button`, then return `confirm_reward` using the confirm button
  center.
- Replay capture backend: `--capture-backend replay --replay-screens ...`
  feeds a fixed screenshot sequence into strategy mode for full dry-run chain
  testing.
- Window capture backend interface and clear error handling.
- Static strategy screenshot backend: `--game cats --strategy ad_reward --screen ...`
  runs against a fixed image and bypasses fullscreen/window capture.
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

- Other reward-button flows outside the current confirmation page are not part
  of the current formalized feature.
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
- Strategy `--screen` tests require a real image file; missing or unreadable
  screenshots are reported clearly and do not trigger live capture.
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
- `ad_reward` currently keeps `ad_entry` as a target, but waits unless the
  film page `page_marker` is detected.
- On `samples/cats/jiao_juan_page.png`, `ad_reward` clicks only
  `watch_ad_button` after `page_marker` confirms the page. `page_marker` is not
  clickable.
- On `samples/cats/ad_close_tests/*.png`, `ad_reward` clicks only close-button
  detections in dry-run output. The right-top close target is preferred over
  the left-top close target.
- Continuous close detection is intentionally capped at three consecutive
  dry-run clicks to avoid loops that would repeatedly click the same close
  candidate forever.
- On `samples/cats/reward_confirm_page.png`, `ad_reward` clicks only
  `confirm_button` after `reward_confirm_marker` confirms the page.
- Replay mode reads screenshots in order and reuses the last screenshot when
  loops outnumber screenshots. It never captures the desktop or controls input.

## Current Stable Small Feature

Run this from the project root:

```powershell
.\.venv\Scripts\python.exe -m cats_automatic.main --game cats --strategy ad_reward --screen samples\cats\home_screen.png --max-loops 1
```

Success means the output contains:

```text
Detected: ad_entry
Decision: wait
DRY RUN wait
```

Run the film ad page check from the project root:

```powershell
.\.venv\Scripts\python.exe -m cats_automatic.main --game cats --strategy ad_reward --screen samples\cats\jiao_juan_page.png --max-loops 1
```

Success means the output contains:

```text
Detected: page_marker
Detected: watch_ad_button
Decision: click_watch_ad_button
DRY RUN click x=636 y=615
```

Run an ad-close check from the project root:

```powershell
.\.venv\Scripts\python.exe -m cats_automatic.main --game cats --strategy ad_reward --screen samples\cats\ad_close_tests\Screenshot_20260531-222029.png --max-loops 1
```

Success means the output contains:

```text
Decision: close_ad
DRY RUN click
```

Run a four-loop close-limit check:

```powershell
.\.venv\Scripts\python.exe -m cats_automatic.main --game cats --strategy ad_reward --screen samples\cats\ad_close_tests\Screenshot_20260531-222029.png --max-loops 4
```

Success means loops 1-3 print `Decision: close_ad`, and loop 4 prints:

```text
Decision: wait
DRY RUN wait seconds=1.00 reason=wait_close_limit_reached
```

Run a reward confirmation check from the project root:

```powershell
.\.venv\Scripts\python.exe -m cats_automatic.main --game cats --strategy ad_reward --screen samples\cats\reward_confirm_page.png --max-loops 1
```

Success means the output contains:

```text
Detected: reward_confirm_marker
Detected: confirm_button
Decision: confirm_reward
DRY RUN click x=631 y=657
```

Run the complete replay check:

```powershell
.\.venv\Scripts\python.exe -m cats_automatic.main --game cats --strategy ad_reward --capture-backend replay --replay-screens samples\cats\home_screen.png,samples\cats\jiao_juan_page.png,samples\cats\ad_close_tests\Screenshot_20260531-222029.png,samples\cats\reward_confirm_page.png --max-loops 4
```

Success means the decisions are:

```text
Decision: click_ad_entry
Decision: click_watch_ad_button
Decision: close_ad
Decision: confirm_reward
```

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
- Add the next C.A.T.S. strategy target as a separate small feature after ad
  close stays stable across more screenshots.
- Add richer strategy logs for no-match and low-confidence candidates.
- Add curated `samples/cats/` screenshots for repeatable manual strategy tests.
- Add an optional emulator/ADB capture backend.

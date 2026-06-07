# CATS Automatic

CATS Automatic is a desktop prototype for authorized game automation research.
The first version focuses on computer vision: capture a screen image, find known
buttons, produce safe click candidates, and run simple flow or strategy-driven
dry-run loops.

This repository is intended for owned games, internal QA, accessibility support,
or other explicitly authorized automation. It does not implement ad skipping,
fake ad views, anti-cheat bypasses, or platform policy evasion.

## Project Layout

```text
configs/                 Rule configuration examples
docs/                    Design notes and Android migration plan
samples/                 Test screenshots
templates/               Button template images
src/cats_automatic/      Python framework source
src/cats_automatic/games/ Game-specific strategies and templates
```

## Quick Start

For a full Windows setup checklist, see `docs/windows-setup.md`.

Prerequisites:

- Python 3.11 or newer available as `python`.
- Git available as `git` if you want to initialize version control.

Create and activate a Python virtual environment, then install dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Run the prototype entrypoint:

```powershell
python -m cats_automatic.main
```

Run the C.A.T.S. strategy mode:

```powershell
python -m cats_automatic.main --game cats --strategy ad_reward --max-loops 3
```

The first stable C.A.T.S. strategy feature was `ad_entry` detection. The current
`ad_reward` strategy also supports the first page-gated action on the film ad
page: it detects `page_marker` first, then clicks `watch_ad_button` only when
both are present. `page_marker` is a page marker only and is never clicked.
Advertisement close buttons have the highest priority: the strategy checks the
right-top `close-end-2` region first, then the left-top `close-end-1` region,
and prints `close_ad` as a dry-run click when either one is detected.
If close buttons remain visible across multiple loops, `ad_reward` can keep
closing them, but it stops after three consecutive `close_ad` decisions and
prints `wait_close_limit_reached` until a non-close state resets the counter.
After an ad finishes, the reward confirmation page is handled before the film
ad page: `reward_confirm_marker` confirms the page, and only `confirm_button`
is clicked with the `confirm_reward` decision.

Run the same strategy against a fixed test screenshot without capturing the
desktop or an emulator window:

```powershell
python -m cats_automatic.main `
  --game cats `
  --strategy ad_reward `
  --screen samples\cats\home_screen.png `
  --max-loops 1
```

When `--game` and `--screen` are used together, strategy mode uses the static
image every loop. This is the preferred path for repeatable pytest/manual
recognition tests because it bypasses fullscreen and window capture. A
successful `home_screen` run can still print `Detected: ad_entry`, but the
current page-gated strategy waits until the film page marker is present before
clicking any ad button.

Run the film ad page strategy test:

```powershell
python -m cats_automatic.main `
  --game cats `
  --strategy ad_reward `
  --screen samples\cats\jiao_juan_page.png `
  --max-loops 1
```

A successful film ad page run prints `Detected: page_marker`, `Detected:
watch_ad_button`, `Decision: click_watch_ad_button`, and `DRY RUN click x=636
y=615`.

Run an ad-close screenshot test:

```powershell
python -m cats_automatic.main `
  --game cats `
  --strategy ad_reward `
  --screen samples\cats\ad_close_tests\Screenshot_20260531-222029.png `
  --max-loops 1
```

A successful close run prints `Decision: close_ad` and `DRY RUN click`.
For a replay-style static close test, raise `--max-loops` to 4; the first three
loops should close, and the fourth should wait with `wait_close_limit_reached`.

Run a reward confirmation page test:

```powershell
python -m cats_automatic.main `
  --game cats `
  --strategy ad_reward `
  --screen samples\cats\reward_confirm_page.png `
  --max-loops 1
```

A successful reward confirmation run prints `Detected: reward_confirm_marker`,
`Detected: confirm_button`, `Decision: confirm_reward`, and `DRY RUN click
x=631 y=657`.

Run the complete dry-run replay chain without capturing the desktop:

```powershell
python -m cats_automatic.main `
  --game cats `
  --strategy ad_reward `
  --capture-backend replay `
  --replay-screens samples\cats\home_screen.png,samples\cats\jiao_juan_page.png,samples\cats\ad_close_tests\Screenshot_20260531-222029.png,samples\cats\reward_confirm_page.png `
  --max-loops 4
```

Replay mode returns the listed screenshots in order. If there are more loops
than screenshots, it reuses the last screenshot and prints a clear replay log.
The expected decisions are `click_ad_entry`, `click_watch_ad_button`,
`close_ad`, and `confirm_reward`.

Debug a live emulator/window capture without clicking:

```powershell
python -m cats_automatic.main `
  --game cats `
  --strategy ad_reward `
  --capture-backend window `
  --window-title "ANG" `
  --debug-save-capture output\ang-current.png `
  --max-loops 1
```

Strategy mode prints `Capture image size: width=..., height=...` after every
capture. The close-button search regions are computed from the captured image
size, so smaller ANG window captures no longer make fixed 1280x720 close
regions fail with a region-overlap error.

List available Windows windows before choosing a window capture target:

```powershell
python -m cats_automatic.main --list-windows
```

The list includes `hwnd`, title, window rect, client rect, size, visibility, and
minimized state. `--window-title` uses fuzzy title matching and selects the
largest usable match when multiple windows match; for exact selection, copy the
`hwnd` and run:

```powershell
python -m cats_automatic.main `
  --game cats `
  --strategy ad_reward `
  --capture-backend window `
  --window-hwnd 123456 `
  --debug-save-capture output\ang-current.png `
  --max-loops 1
```

Current limitation: the window backend captures the selected top-level window
rectangle with `ImageGrab`. Depending on emulator/window composition, this can
include borders, overlays, or stale/occluded content. Use `--list-windows` and
`--window-hwnd` to make the selected window explicit before adjusting templates.

Use ADB screenshot capture when the emulator window capture is unstable:

```powershell
python -m cats_automatic.main `
  --game cats `
  --strategy ad_reward `
  --capture-backend adb `
  --adb-path "C:\Program Files\ASUS\GlideX\adb.exe" `
  --adb-serial emulator-5556 `
  --debug-save-capture output\adb-current.png `
  --max-loops 1
```

ADB mode only runs `adb devices` and `adb -s SERIAL exec-out screencap -p`.
It does not implement `adb tap` or any real input action.

Use the window capture backend for an emulator window:

```powershell
python -m cats_automatic.main `
  --game cats `
  --strategy ad_reward `
  --capture-backend window `
  --window-title "模拟器" `
  --max-loops 3
```

In IntelliJ IDEA, open this folder as a project and run module
`cats_automatic.main`.
If the Python plugin is enabled, the shared run configuration named
`CATS Automatic Prototype` should also appear in the top-right run selector.
See `docs\RUN_IN_IDEA.md` for the full standalone IDEA setup.

The default command prints a placeholder flow and confirms that the core modules
can be imported. Add screenshots to `samples/` and button images to `templates/`
before using template matching.

Capture a desktop screenshot for later matching:

```powershell
python -m cats_automatic.main --capture samples\screen.png
```

Run template matching against a saved screenshot:

```powershell
python -m cats_automatic.main `
  --screen samples\screen.png `
  --template templates\primary_button.png `
  --threshold 0.85
```

If the icon sits on a changing background, try edge mode:

```powershell
python -m cats_automatic.main `
  --screen samples\screen.png `
  --template templates\primary_button.png `
  --match-mode edge `
  --threshold 0.40
```

For a resized emulator window, capture the current desktop and search multiple
template sizes in one command:

```powershell
python -m cats_automatic.main `
  --live `
  --template templates\primary_button.png `
  --match-mode edge `
  --scale-min 0.40 `
  --scale-max 1.10 `
  --scale-step 0.05 `
  --threshold 0.35
```

When the match confidence is high enough, the prototype prints a dry-run click
candidate instead of sending real mouse input.

Run continuous dry-run matching against the current desktop:

```powershell
python -m cats_automatic.main `
  --watch `
  --template templates\primary_button.png `
  --interval 1 `
  --max-failures 5
```

Watch mode captures the desktop into `output\watch-screen.png` on each loop,
prints confidence and click coordinates, and stops after repeated low-confidence
matches.

Run tests:

```powershell
python -m pytest -q
```

Run the authorized SDK Test Mode QA scenario:

```powershell
python -m cats_automatic.main `
  --scenario configs\qa-ad-flow.json `
  --scenario-log-file output\qa-ad-flow.jsonl
```

The scenario runs in dry-run mode. Real input is intentionally not implemented
in the current framework build. The runner captures the complete desktop, waits
for the configured minimum ad duration, then polls known close-button templates.
Full-desktop matching keeps screenshot and click coordinates aligned when the
emulator window moves or another window overlaps it.

The current example keeps `window_title_contains` in `configs\qa-ad-flow.json`
as emulator metadata, but scenario matching uses the complete desktop.

Before running the scenario, collect SDK Test Mode templates:

```text
templates/ad-entry.png
templates/ad-close-x.png
templates/game-home-marker.png
```

Optional close-button variants:

```text
templates/ad-close-text.png
templates/ad-skip.png
```

See `docs\qa-ad-flow.md` for the SDK Test Mode collection and rollout steps.

Log one accepted dry-run candidate after coordinates are correct:

```powershell
python -m cats_automatic.main `
  --screen samples\screen.png `
  --template templates\primary_button.png `
  --match-mode edge `
  --threshold 0.40 `
  --max-actions 1 `
  --log-file output\actions.log
```

Safety defaults:

- Real clicks are not implemented in this build.
- Strategy mode uses dry-run actions only.
- The current `ad_reward` strategy formalizes `ad_entry` detection plus the
  film page `page_marker -> watch_ad_button` dry-run action plus ad close
  buttons plus reward confirmation. Other reward flows are intentionally left
  for later small features.
- `--capture-backend replay` reads local screenshots only; it does not capture
  the desktop or control windows.
- `--max-actions 1` allows only one click by default.
- `--repeat-actions` defaults to 1 and must fit within `--max-actions`.
- `--click-cooldown` prevents rapid repeated clicks.
- If `stop.flag` exists in the project root, actions are skipped.

If `git` is installed after this skeleton is created, initialize the repository
from this directory:

```powershell
git init
git status
```

## Development Direction

1. Validate template matching with static screenshots.
2. Add screen capture for Windows desktop or emulator windows.
3. Add deterministic generated-image tests for confidence thresholds.
4. Add a guarded real input backend only after dry-run validation is stable.

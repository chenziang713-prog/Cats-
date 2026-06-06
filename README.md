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

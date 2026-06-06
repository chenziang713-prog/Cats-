# SDK Test Mode QA Ad Flow

Use this runner only with owned games, authorized QA environments, and ad SDK
test mode. It waits for normal playback and does not attempt to skip ads or
operate production ad inventory.

## Required Templates

Capture and crop these images from the emulator render window:

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

Keep crops tight around stable UI pixels. Avoid animated backgrounds where
possible.

## First Dry Run

Edit `configs\qa-ad-flow.json` if the emulator tab title differs from `ANG`.
Then run:

```powershell
py run_prototype.py `
  --scenario configs\qa-ad-flow.json `
  --scenario-log-file output\qa-ad-flow.jsonl
```

The default mode is dry-run. Each detection captures the complete desktop so
matching and click coordinates remain aligned even if the emulator moves.
Review JSONL events and generated screenshots under `output\scenario\` before
enabling real clicks.

## Dry-Run Scenario Loop

Start with one cycle by changing `max_cycles` to `1`, then run:

```powershell
python -m cats_automatic.main `
  --scenario configs\qa-ad-flow.json `
  --scenario-log-file output\qa-ad-flow.jsonl
```

Real input is intentionally not implemented in the current build. The scenario
records dry-run action candidates only. Create an empty `stop.flag` file in the
project root to suppress action candidates at any time.

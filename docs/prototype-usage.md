# Prototype Usage

This prototype is designed for static-image validation first. Capture or export
a screenshot from an authorized game/test environment, then crop the button you
want to detect into a separate template image.

## Matching Workflow

1. Put the full screenshot in `samples/`.
2. Put the cropped button image in `templates/`.
3. Run `python -m cats_automatic.main --screen samples\screen.png --template templates\button.png`.
4. Check the printed confidence and center point.
5. Increase the threshold if false positives appear.

## Capturing And Cropping

Capture the current desktop or emulator window:

```powershell
python -m cats_automatic.main --capture samples\screen.png
```

Open `samples\screen.png` in an image editor, crop only the target button, and
save it as `templates\primary_button.png`. Keep the crop tight around the visual
button. Large crops that include background make matching less stable.

## Continuous Watch Mode

After a reliable template exists, run:

```powershell
python -m cats_automatic.main --watch --template templates\primary_button.png
```

The prototype stays in dry-run mode. It captures the screen, runs template
matching, prints confidence and center coordinates, and stops after repeated
low-confidence results.

## Safety Defaults

- The executor runs in dry-run mode.
- Low-confidence matches do not trigger actions.
- Real mouse input is not implemented in the current build.
- `--max-actions` limits how many clicks can happen in one run.
- `--repeat-actions` repeats an accepted click target, but still obeys
  `--max-actions`.
- `stop.flag` in the project root prevents actions from running.
- Android input should only be enabled later behind explicit user controls.

## Guarded Dry-Run Candidate Test

Run this after the template crop is ready:

```powershell
python -m cats_automatic.main `
  --screen samples\screen.png `
  --template templates\primary_button.png `
  --match-mode edge `
  --threshold 0.40 `
  --max-actions 1 `
  --log-file output\actions.log
```

To suppress even dry-run action candidates before running, create an empty
`stop.flag` file in the project root. Delete it when you intentionally want
dry-run candidates to be logged again.

# Run In IntelliJ IDEA

This project uses a Python package under `src/cats_automatic`. Prefer running it
as a module instead of running `main.py` as a standalone script.

## Python SDK And Virtual Environment

1. Open `C:\Users\shenj\Documents\CATSautomatic` in IntelliJ IDEA.
2. Install or enable the IntelliJ Python plugin.
3. Open `File -> Project Structure -> SDKs`.
4. Add the interpreter at `.venv\Scripts\python.exe`.
5. If `.venv` does not exist yet, create it from PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

For command-line module execution without relying on IDEA source-root handling,
install the package in editable mode:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
```

## Script Path Or Module Name

Use `Module name` for the main run configuration.

```text
Module name: cats_automatic.main
Parameters: 
Working directory: C:\Users\shenj\Documents\CATSautomatic
Python interpreter: C:\Users\shenj\Documents\CATSautomatic\.venv\Scripts\python.exe
```

The working directory should be the project root, not `src`. The configs,
templates, samples, and output paths are resolved from the project root.

`Script path` can run `run_prototype.py` because that wrapper adds `src` to
`sys.path`, but `Module name` is the cleaner package-layout option.

## Why Direct main.py Can Fail

Do not run this as a standalone script:

```powershell
python src\cats_automatic\main.py
```

`main.py` uses relative imports such as `from .actions import ActionExecutor`.
Those imports require Python to know that `main.py` belongs to the
`cats_automatic` package. Running the file directly removes that package
context and can raise `ImportError: attempted relative import with no known
parent package`.

## Correct Commands

After activating `.venv` and installing the package:

```powershell
python -m cats_automatic.main
```

The compatibility wrapper also works:

```powershell
python run_prototype.py
```

## Strategy Run Configuration

Use this configuration to run the C.A.T.S. ad reward strategy in dry-run mode:

```text
Module name: cats_automatic.main
Parameters: --game cats --strategy ad_reward --max-loops 3
Working directory: C:\Users\shenj\Documents\CATSautomatic
Python interpreter: C:\Users\shenj\Documents\CATSautomatic\.venv\Scripts\python.exe
```

Use this configuration to capture only a matching emulator window:

```text
Module name: cats_automatic.main
Parameters: --game cats --strategy ad_reward --capture-backend window --window-title "模拟器" --max-loops 3
Working directory: C:\Users\shenj\Documents\CATSautomatic
Python interpreter: C:\Users\shenj\Documents\CATSautomatic\.venv\Scripts\python.exe
```

The window backend uses a Windows window rectangle screenshot. It can fail or
capture stale pixels when a window is minimized, hidden, or heavily occluded.
For stable automation later, an emulator or ADB capture backend is still the
better long-term direction.

## Capture A Screenshot

This saves a screenshot for later template matching:

```powershell
python -m cats_automatic.main --capture samples\screen.png
```

## Run One Template Match

Use a full screenshot and a cropped template:

```powershell
python -m cats_automatic.main `
  --screen samples\screen.png `
  --template templates\primary_button.png `
  --threshold 0.85
```

Try `gray` or `edge` mode when color matching is unstable:

```powershell
python -m cats_automatic.main `
  --screen samples\screen.png `
  --template templates\primary_button.png `
  --match-mode edge `
  --threshold 0.40
```

The current action backend is dry-run only. A confident match prints the click
candidate; it does not move the mouse.

## Run Watch Mode

Watch mode repeatedly captures and matches in dry-run mode:

```powershell
python -m cats_automatic.main `
  --watch `
  --template templates\primary_button.png `
  --interval 1 `
  --max-failures 5
```

To avoid live screen capture during tests, provide a static screen:

```powershell
python -m cats_automatic.main `
  --watch `
  --screen samples\screen.png `
  --template templates\primary_button.png `
  --interval 1 `
  --max-failures 2
```

## Run Unit Tests

From the project root:

```powershell
python -m pytest
```

The tests use dry-run executors, generated images, fake captures, and mocked
matchers. They do not click the mouse or control the desktop.

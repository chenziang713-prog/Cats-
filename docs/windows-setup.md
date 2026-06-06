# Windows Setup Guide

Install these tools before deeper development so the project can be tested from
IntelliJ IDEA and from PowerShell.

## Required Tools

1. Python 3.11 or newer
   - Download: https://www.python.org/downloads/windows/
   - During installation, enable `Add python.exe to PATH`.
   - Verify in a new PowerShell window:

```powershell
python --version
pip --version
```

2. Git for Windows
   - Download: https://git-scm.com/download/win
   - Keep the default option that adds Git to PATH.
   - Verify in a new PowerShell window:

```powershell
git --version
```

3. IntelliJ IDEA Python plugin
   - Open IDEA.
   - Go to `File -> Settings -> Plugins -> Marketplace`.
   - Search for `Python`, install it, then restart IDEA.

## Project Setup

Open PowerShell in `C:\Users\shenj\Documents\CATSautomatic` and run:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -e .
python tools\check_environment.py
python tools\self_test.py
python -m cats_automatic.main
```

When the environment is healthy, run the first visual loop:

```powershell
python -m cats_automatic.main --capture samples\screen.png
python -m cats_automatic.main --screen samples\screen.png --template templates\primary_button.png
```

Create `templates\primary_button.png` by cropping a button from
`samples\screen.png` before running the second command.

If PowerShell blocks virtual environment activation, run:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

Then close PowerShell, reopen it, and activate `.venv` again.

## IDEA Setup

1. Open `C:\Users\shenj\Documents\CATSautomatic` as the project directory.
2. Go to `File -> Project Structure -> SDKs`.
3. Add Python SDK from `.venv\Scripts\python.exe`.
4. Create a Python run configuration with module name `cats_automatic.main`.
5. Click the green Run button.

## Expected Output

`python -m cats_automatic.main` should print:

```text
CATS Automatic desktop prototype
Loaded flow: default-demo-flow
Configured steps: 1
Next step: find_primary_button template=primary_button.png action=click_center timeout=5s
```

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
built-in `close-end-1` / `close-end-2` / `close-end-3` / `close-end-4`
templates plus any user templates in `user_templates\close_buttons\`, then
clicks the close template with the highest confidence and prints `close_ad`.
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

After `click_watch_ad_button`, `ad_reward` keeps using the normal strategy flow
on every loop. It still checks close buttons first, then reward confirmation,
then the watch-ad button, then the ad entry, and otherwise waits.

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
By default, ADB mode is still dry-run and does not tap.

The Windows GUI can help find ADB on a new computer. Click `自动查找 ADB` to
scan common emulator locations such as LDPlayer, 雷电, MuMu, Netease, and
Program Files. It runs `adb devices`, ignores `offline` and `unauthorized`
devices, fills the first recommended `device` serial, saves
`output\gui_config.json`, and does not enable `allow-click`.

Real ADB taps are guarded and only enabled when both conditions are true:

```text
--allow-click
--capture-backend adb
```

Example guarded real-tap run:

```powershell
python -m cats_automatic.main `
  --game cats `
  --strategy ad_reward `
  --capture-backend adb `
  --adb-path "C:\Program Files\ASUS\GlideX\adb.exe" `
  --adb-serial emulator-5556 `
  --allow-click `
  --max-actions 1 `
  --max-loops 1
```

Replay, fullscreen, and window backends reject `--allow-click`. Wait decisions
and undetected/low-confidence targets never call `adb shell input tap`.

Each strategy run writes a troubleshooting record under
`output/runs/<run_id>/`. If a real ADB run mis-clicks, stop the run and open
`click_records.csv` in the newest run directory. The last row with
`action_type=adb_tap` is the most likely mis-click; it includes the loop,
decision, target, confidence, coordinates, and matching screenshot path.
The same directory also contains `summary.txt`, per-loop screenshots, and
per-loop detection JSON files. Ordinary real ADB taps require confidence greater
than or equal to `--min-click-confidence`, which defaults to `0.80`. Close-ad
targets use an independent `close_ad_min_confidence=0.72`; this lower threshold
is applied only to `close_ad` decisions and never lowers the safety threshold
for ordinary buttons.
After successful click decisions, the strategy pauses before the next screenshot
to avoid double-clicking during slow page transitions: `click_ad_entry` waits 5
seconds, `click_watch_ad_button` waits 15 seconds, and `close_ad` /
`confirm_reward` wait 1.5 seconds. The console and `events.jsonl` print
`post_action_delay`, while `click_records.csv` includes the delay seconds,
start/end timestamps, and whether a stop file interrupted the delay.

By default, a completed reward flow stops after `confirm_reward` succeeds and
`summary.txt` records `stop_reason=reward_flow_completed`. To keep farming on a
timer, add `--repeat-after-reward`. After each successful `confirm_reward`, the
runner writes `cycle_completed`, waits `--cycle-wait-seconds` seconds
(default `1800`), then starts the next cycle without creating a new `run_id`.
During this cycle wait it does not capture, detect, click, or consume
`--max-actions`; it checks the stop file every 0.5 seconds. Use `--max-cycles 2`
to stop after two completed cycles, or leave `--max-cycles 0` for unlimited
cycles.

Add new close-button templates without rebuilding:

```text
user_templates\close_buttons\close-user-001.png
user_templates\close_buttons\close-user-002.png
```

Crop the close button itself as a small PNG, click `添加关闭按钮模板` in the GUI,
then run Dry-run first. When recognized, `click_records.csv` and debug
detections show the real target name such as `close_user_001`. If a custom
template mis-recognizes, delete the matching `close-user-xxx.png`.

If the film page requires an optional choice before the watch button, add one
PNG as `user_templates\pre_watch_optional\optional.png` or use the GUI
`添加/替换可选点击模板` button. It is attempted only on the page-marker flow,
at most once per cycle, and uses a one-second post-action delay. If it is
missing or not detected, the strategy immediately continues to the watch
button instead of blocking the flow.

Additional watch-button styles can be added under
`user_templates\watch_buttons\` as `watch-user-001.png`,
`watch-user-002.png`, and so on. The built-in `watch_ad_button` remains active;
when several built-in/user watch templates match, the strategy clicks the one
with the highest confidence and records its real target name.

A reward cycle completes either after an executed `confirm_reward`, or when an
executed watch click plus at least one executed close action is followed by a
high-confidence `ad_entry` home-page detection. The latter records
`last_cycle_completed_reason: home_return_after_ad` and does not click the
newly detected ad entry before cycle wait/end handling.

External strategy packages can be placed under `external_strategies\` without
repacking the exe. Each package contains `manifest.json`, `strategy.py`, and
optional `templates\`. Use `python -m cats_automatic.main --list-strategies` or
the GUI `刷新功能列表` button to see built-in and external strategies. External
strategy code must be trusted Python and still returns normal strategy
decisions; real taps remain guarded by the existing `ActionBackend` and
`--allow-click --capture-backend adb` checks.

## Scrap Ad Battle

The external `scrap_ad_battle` strategy implements the 废铁看广告 state
machine. Add these cropped PNG files under
`external_strategies\scrap_ad_battle\templates\`:

```text
scrap_entry.png
scrap_next_button.png
battle_button.png
skip_button.png
battle_result_popup.png
scrap_watch_ad_button.png
```

`scrap_page_marker.png` is optional. `battle_confirm_button.png` is a legacy
template that is no longer loaded by the current flow, so its absence produces
no missing-template warning.

Start on the game home page and select `scrap_ad_battle` in the GUI. The
strategy uses guarded ADB BACK until `scrap_next_button` appears, clicks it,
waits 2 seconds, then uses guarded ADB BACK until `battle_button` appears
without the previous next button. It clicks the same `skip_button` at most
twice, recognizes `battle_result_popup`, closes it with one guarded ADB BACK,
starts the ad, reuses the existing built-in/user close-button library, and
completes when a known scrap/home target confirms the game page has returned.

The strategy supports taking over midway through the flow. It can start while
the game is on the home page, scrap page, battle-button page, skip page, battle
result popup, or watch-ad page. Before every decision it infers progress from
the current screenshot, recovers its state when necessary, records
`state_recovered` in `events.jsonl`, and then executes the action for the
recovered state. This prevents a detected `scrap_next_button` from being
ignored merely because the previously saved state was `home`.

Progress recovery also respects the current cycle stage. After
`adb_back_battle_result` succeeds, the cycle is locked to
`wait_scrap_watch_ad_button`: a stale `battle_button` match is recorded as
`awaiting_watch_ad_ignore_battle_button` and is never clicked. The lock clears
only after `scrap_watch_ad_button` executes or a new cycle starts.

Close-button detections are also stage-locked. Before the watch-ad button has
executed and the ad wait stage has started, built-in and `close_user_*`
candidates are logged as `close_ad_candidate_ignored` but cannot recover the
state to `close_ad` or trigger a click. During the ad-close stage, candidates at
or above `0.72` may execute `close_ad`; lower-confidence candidates produce
`close_ad_candidate_below_threshold_after_ad_wait`, while a frame with no close
candidate keeps `wait_close_ad_not_found_after_ad_wait`.

## Global Recovery Watchdog

Strategy runs include a public `GlobalStallWatchdog` in
`src/cats_automatic/recovery.py`. It watches repeated wait reasons, a state that
does not advance, long periods without progress or known targets, extended
`wait_not_on_target_page`, ad-close hard timeouts, and repeated clicks that
leave the same target, state, and screenshot unchanged. Screenshot comparison
is diagnostic only: frames are reduced to 160x90 grayscale and a difference
below 1% supports a click-no-effect finding, but screenshot similarity alone
never forces recovery.

Default limits are 180 seconds in one state, 60 identical wait reasons, 240
seconds without progress, 180 seconds on `wait_not_on_target_page`, 120 seconds
without known targets, 120 seconds in an ad stage without a close/home/reward
target, and two no-effect clicks. `battle_wait`, `ad_wait`, `cycle_wait`,
post-action delay, and click cooldown are treated as normal waits and do not
trigger recovery during their configured wait operation.

The default recovery plan is intentionally conservative: record
`global_stall_detected`, execute one guarded ADB BACK, wait one second, then
capture and detect again. It never restarts the game or emulator. Recovery is
limited to three attempts per cycle and ten per run, with a 60-second cooldown.
The BACK action still passes through the normal action backend: Dry-run records
`problem_recovery_adb_back` without invoking ADB, while `--allow-click` with the
ADB capture backend may execute a real BACK. Stop files and max-actions remain
higher-priority safety limits.

Console output now adds concise Chinese detection, decision, stage, suspicious
condition, and recovery lines while full details remain in `events.jsonl`.
When a run ends, `diagnosis.txt` and the bottom of `summary.txt` contain a
Chinese **本次运行总结 / 可疑问题 / 自动判断** report based on the click and event
records. It highlights missing target pages, close-button misses or weak
candidates, ignored close-template false matches, repeated BACK recovery,
click-no-effect findings, stop-file termination, and incomplete combined flows.

The Windows GUI uses a dark control-panel theme with grouped cards, colored log
categories, a fixed scrollable log area, status indicators, and a button to open
the newest `diagnosis.txt`. Template checking lists every scrap template and the
counts for `watch_buttons`, `close_buttons`, and `pre_watch_optional`. An empty
`user_templates\\watch_buttons` directory shows a prominent warning because
`ad_reward` may not recognize the watch-ad button. Real click mode remains off
by default and still requires confirmation.

Existing packaged EXE files do not contain these recovery, diagnosis, or GUI
changes. Rebuild the release only when you are ready to distribute them; this
development change does not run PyInstaller or modify a release archive.

## Network License Authorization

Strategy mode now requires online authorization before Dry-run or real ADB
automation can start. The first-stage client is implemented in
`src/cats_automatic/license_client.py` and defaults to the local demo server at
`http://127.0.0.1:8000`. The server URL remains configurable; the client calls
`POST /api/activate` for a new key and `POST /api/heartbeat` for cached sessions.

The device binding sends only a SHA-256 device ID. It combines available
Windows MachineGuid, computer/user names, and platform values locally, prefixes
them with `CATSautomatic|`, and uploads only the resulting hash. Missing machine
fields are tolerated and raw hardware values are never uploaded.

Successful activation is cached in `config/license_auth.json` beside the source
root, or beside the EXE in a frozen release. The cache contains the license key,
device hash, token, expiration timestamps, server URL, authorized features, and
last heartbeat time. Logs and events use a masked key such as
`CATS-ABCD-****`; tokens and complete keys are never printed.

GUI authorization controls appear in the **联网授权** card:

- **输入/激活卡密** asks for the server URL and key.
- **检查授权** sends a heartbeat using the local cache.
- **清除本地授权** removes `config/license_auth.json`.

The status bar shows activation state, masked key, expiration, and enabled
features. Every GUI task checks authorization before starting. Feature names map
directly to strategies: `ad_reward`, `scrap_ad_battle`, and
`scrap_then_ad_reward`; having one feature never grants another.

CLI activation example:

```powershell
python -m cats_automatic.main --game cats --strategy scrap_then_ad_reward `
  --license-key CATS-XXXX-XXXX-XXXX `
  --license-server-url http://127.0.0.1:8000
```

Without `--license-key`, CLI strategy mode loads the local cache and performs a
heartbeat. While running, heartbeat checks repeat every 600 seconds, including
long strategy and cycle waits. Failure records `license_heartbeat_failed`,
updates `summary.txt` / `diagnosis.txt`, and stops before GlobalStallWatchdog can
attempt recovery.

Common authorization failures include an unknown, expired, or disabled key;
device-limit exhaustion; a feature not enabled for the selected strategy;
server connection errors; and heartbeat rejection. Start the compatible local
demo authorization server on port 8000 before testing these endpoints.

For automated development tests only, set `CATS_LICENSE_DEV_BYPASS=1` and pass
`--skip-license-check-for-dev`. The flag does nothing without that environment
variable and must not be enabled in a published build. Authorization is not
source-code protection: external strategy packages still contain readable
`strategy.py` files, so formal distribution should address source protection
separately.

When that environment variable is enabled, these local test keys bypass the
demo server while still exercising feature checks and local heartbeat logic:

- `CATS-DEV-AD-ONLY`: only `ad_reward`.
- `CATS-DEV-SCRAP-ONLY`: only `scrap_ad_battle`.
- `CATS-DEV-FULL-ACCESS`: all three strategies.

They are rejected when `CATS_LICENSE_DEV_BYPASS` is absent and must never be
enabled in a release environment.

## Error Popup Recovery

If GlobalStallWatchdog exhausts its normal guarded BACK attempts, the runner can
enter `error_popup_recovery` instead of immediately abandoning the current
cycle. Stop files, license heartbeat failure, unavailable real-ADB configuration,
and max-actions remain higher priority and prevent this fallback.

User templates are external and loaded from:

```text
user_templates/error_popups/*.png
user_templates/error_buttons/*.png
```

Both directories are created automatically. Popup and button templates use
independent `0.80` thresholds. A button is clickable only while popup recovery
is active, when a popup template and a nearby button template are both detected.
A button without a popup is logged and ignored; a popup without a button waits
and recommends adding an error-button template. These templates never become
normal `confirm_button` targets.

Before recovery starts, the runner snapshots the strategy state, combined-flow
phase, cycle index, pending goal, expected target, stable decision, and important
per-cycle flags. It does not reset the strategy or cycle. After clicking the
popup button, it waits one second and captures again. If a known workflow target
appears, control returns to the existing strategy, preserving its normal
priority rules such as battle-result confirmation, scrap watch-ad continuation,
return-home detection, film reward, and close-ad stage locking. If the page is
still unknown, the saved state remains untouched and the runner waits one loop
with `resume_previous_state_after_error_popup_uncertain`.

Error-popup recovery is limited to two attempts per cycle and five per run, with
a 60-second cooldown. Dry-run records `error_popup_recovery_click` without real
input. Only `--allow-click` with the guarded ADB backend can perform a real tap.
`events.jsonl`, `click_records.csv`, `summary.txt`, and `diagnosis.txt` report the
popup/button names, attempts, successes, failures, missing-template cases, and
limit exhaustion. The GUI template check displays both template counts and
provides buttons to open each directory.

## Sync Templates From an Existing Release

`tools/sync_release_templates.py` imports externally configured image templates
from an existing desktop `CATSautomatic-release*` folder back into the source
tree. Without `--release-dir`, it selects the most recently modified matching
folder under Windows user Desktop directories.

Preview first, then apply:

```powershell
.venv\Scripts\python.exe tools\sync_release_templates.py --dry-run
.venv\Scripts\python.exe tools\sync_release_templates.py --apply
```

Use `--release-dir` and `--project-dir` to override either location. Only PNG,
JPG, JPEG, BMP, and WEBP files are synchronized from `user_templates` and the
two external strategy template directories. Template-named JSON/YAML/TOML files
under `config` may also be synchronized. Identical hashes are skipped; changed
same-name targets are copied to `.bak` before replacement.

The tool never reads an EXE and excludes `output`, runs, STOP files, logs,
`license_auth.json`, tokens, authorization caches, and device-binding data. Its
Chinese report lists copied, duplicate, backed-up, empty, and missing items and
explicitly confirms whether a discovered license cache was excluded.

The release builder now copies source-tree images from `watch_buttons`,
`close_buttons`, `pre_watch_optional`, `error_popups`, and `error_buttons`, plus
the full external strategy packages and their templates. It does not copy the
source `config` directory or any local authorization state.

Seeing `scrap_watch_ad_button` early does not unlock it. The strategy requires
the battle click, two skips, completed battle wait, closed result popup, and
the active watch-ad stage before clicking. Early matches are recorded as
`watch_ad_detected_before_battle_complete_ignored`; when battle and watch-ad
buttons appear together, `battle_button` keeps priority.

### Scrap Transition Watchdog

`scrap_ad_battle` tracks progress after each executed action. A target must be
missing for three consecutive recognition loops before guarded ADB BACK is
allowed. Misses 1 and 2 are recorded as `waiting_for_miss_threshold`; miss 3
records `miss_threshold_triggered_back` and performs the stage-specific BACK.
The existing elapsed-time watchdog values remain diagnostic context but never
override the three-miss minimum. Two historical `scrap_next_button` clicks
without a battle button still require three misses before BACK. Each step
allows at most three BACK attempts; afterward it waits with
`max_back_attempts_reached_for_step`. The ad-close stage never automatically
presses BACK. Watch-ad clicks are limited to two if no ad transition occurs.

During the scrap phase, `battle_result_popup` has priority over close-ad,
home, and film-ad detections. When the popup and the built-in `confirm_button`
are both detected, the strategy executes `click_battle_result_confirm`; when
the confirm button is absent it falls back to `adb_back_battle_result`. Both
paths enter `wait_scrap_watch_ad_button`. The same `confirm_button` is treated
as film reward confirmation only in `film_ad_reward_phase` together with
`reward_confirm_marker`.

Watchdog activity is recorded in `events.jsonl` as
`transition_watchdog_triggered`, `no_progress_detected`,
`repeated_click_without_progress`, or `max_back_attempts_reached`, while the
corresponding keyevents and reasons remain visible in `click_records.csv`.

### Scrap Ad Battle GUI

Put the six required PNG files in
`external_strategies\scrap_ad_battle\templates\`, open the GUI, and select
`scrap_ad_battle` (display name: 废铁看广告). Set battle wait to `60` and ad
wait to `20`, then use **废铁一轮测试** first. After one successful cycle, use
**废铁循环测试**, which intentionally uses `cycle_wait_seconds=60` and
`max_cycles=2`. For long-running operation, use the normal start button with
`cycle_wait_seconds=1800` and `max_cycles=0`. The GUI also provides **打开废铁模板目录**
and **检查废铁模板** for the six required files.

## v2 Screen State Debug

The v2 screen-state debug tool only reads saved screenshots and runs template
matching. It does not click, does not call ADB, and does not replace the old
execution flow.

Test one screenshot:

```powershell
.\.venv\Scripts\python.exe tools\debug_screen_state_v2.py --image "path\to\screenshot.png"
```

Batch-test one recorded run directory:

```powershell
.\.venv\Scripts\python.exe tools\debug_screen_state_v2.py --run "output\runs\run_id"
```

Run mode reads `screenshots\loop-*.png` and writes these files in the same run
directory:

- `screen_state_journal_v2.jsonl`
- `screen_state_report_v2.txt`

## Scrap Then Film Ad Reward

The external strategy `scrap_then_ad_reward` (GUI label: **废铁 + 胶卷广告**)
runs one scrap battle/ad flow, returns to the home page, and then delegates the
film-ad portion to the existing built-in `ad_reward` strategy. The combined
cycle completes only after `confirm_reward` executes or the film ad is closed
and the home page returns.

After the scrap phase, the strategy enters `return_home_after_scrap`. It checks
for a high-confidence `ad_entry` or `scrap_entry`, rejects the home result if a
scrap-internal button is also visible, and otherwise performs guarded
`adb_back_to_home_after_scrap`. It checks the screen after every BACK and stops
backing after five attempts with `max_back_to_home_attempts_reached`.
It waits for three consecutive failed home detections before each BACK.
An `ad_entry` below `0.80` is never accepted as home, and a visible
`battle_result_popup` always returns control to the scrap result phase before
film-ad processing begins.

GUI buttons **废铁+胶卷一轮测试** and **废铁+胶卷循环测试** use
`scrap_then_ad_reward`. The loop test uses `cycle_wait_seconds=60` and
`max_cycles=2`; long-running operation can use `1800` and `0`.

Dry-run example:

```powershell
python -m cats_automatic.main --game cats --strategy scrap_then_ad_reward --capture-backend adb --adb-path "D:\leidian\LDPlayer9\adb.exe" --adb-serial emulator-5560 --battle-wait-seconds 60 --ad-wait-seconds 20 --max-loops 500
```

The configurable waits are `--battle-wait-seconds` (default `60`) and
`--ad-wait-seconds` (default `20`). Both waits check the stop file every 0.5
seconds. Always run Dry-run first and inspect `click_records.csv` before using
`--allow-click --capture-backend adb`.

Example repeat run:

```powershell
python -m cats_automatic.main `
  --game cats `
  --strategy ad_reward `
  --capture-backend adb `
  --adb-path "C:\Program Files\ASUS\GlideX\adb.exe" `
  --adb-serial emulator-5556 `
  --allow-click `
  --repeat-after-reward `
  --cycle-wait-seconds 1800 `
  --max-cycles 0 `
  --stop-file output\STOP
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

- Real clicks are guarded and only available in strategy mode with
  `--allow-click --capture-backend adb`.
- Strategy mode defaults to dry-run actions.
- The current `ad_reward` strategy formalizes `ad_entry` detection plus the
  film page `page_marker -> watch_ad_button` dry-run action plus ad close
  buttons plus reward confirmation. Other reward flows are intentionally left
  for later small features.
- `--capture-backend replay` reads local screenshots only; it does not capture
  the desktop or control windows.
- In strategy mode, `--max-actions` is a per-cycle safety limit and defaults to
  8 clicks.
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

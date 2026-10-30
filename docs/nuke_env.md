# Nuke environment (Gate G1 + G2)

Fill this in as you run the Gate. Paste the G2 report back to Claude as well.

## G1 — Nuke version

| Item | Value |
|---|---|
| Version (Help → About Nuke) | 17.1v2 (17.1.2), Python 3.11, Qt 6 |
| Installed | 2026-10-30, `D:\nuke plugin\nuke software\Nuke17.1.exe` (start with `--nc`) |
| Build / release date | _from Help → About Nuke_ |
| NC stops working on (release + 180 days) | |
| Licence shown | Non-commercial |
| CorridorKey hook | `%USERPROFILE%\.nuke\init.py` → `nuke.pluginAddPath(r"D:/nuke plugin/nuke")` |

## G2 — Capability test

### How to run

1. Open Nuke NC with an empty script.
2. Open the Script Editor (Workspace → Script Editor, or the `{}` pane tab).
3. Paste this line into the input (lower) half and press **Ctrl+Enter**:

   ```python
   exec(open(r"D:\nuke plugin\nuke\tests\g2_capability_test.py").read())
   ```

4. Click through the three dialogs (any answer is fine): a file browser, a `nuke.Panel`, and a
   knob panel.
5. The script runs the engine's Python once (up to ~1 minute while torch loads), renders a Roto,
   then shows a progress bar for about 3 seconds. A summary box appears at the end.
6. The report is saved to `D:\nuke plugin\_g2_out\g2_report.txt`. Paste it into this
   section and send it to Claude.

### Results

| # | Check | Result | Notes |
|---|---|---|---|
| 1 | Environment (version, NC flag, Python) | | |
| 2 | Menu item | | |
| 3 | `nuke.getFilename` | | |
| 4 | `nuke.Panel` | | |
| 5 | `nuke.PythonPanel` (knob panel) | | |
| 6 | subprocess: `cmd /c echo` | | |
| 7 | subprocess: engine venv python + GPU (clean env) | | |
| 8 | Render Roto → Write 16-bit PNG 1920×1080 | | |
| 9 | ProgressTask from a background thread | | |
| 10 | `executeInMainThread` from a background thread | | |
| 11 | Read a 4K half-float EXR sequence | | |
| M1 | **Manual:** view `CK2_G2_4k` in the Viewer (grey-to-bright ramp, frames 1001–1003) | | |
| M2 | **Manual:** startup menu test (below) | | |

**If the summary box never appears** after the progress bar finishes, check 10 failed (or check 9
hung). Copy what the Script Editor printed and send it to Claude.

### Startup test (M2)

1. Open `%USERPROFILE%\.nuke\menu.py` (create the file if it doesn't exist).
2. Add these two lines at the end:

   ```python
   import nuke
   nuke.menu("Nuke").addCommand("CorridorKey 2.0/G2 startup test", "nuke.message('menu.py loaded OK')")
   ```

3. Restart Nuke. Click **CorridorKey 2.0 → G2 startup test** in the top menu bar.
4. Pass = a box saying "menu.py loaded OK". Then delete the two lines again (Phase 3 replaces
   them with the real hook).

## Gate decision

- [ ] All of 2–11 pass (WARN is acceptable for 8 if only the Roto shape failed) → **Plan A**, full Nuke tool.
- [ ] 6, 7 or 10 fails → **Plan B**, standalone tool only; load EXRs into Nuke by hand.
- [ ] Only 9 fails → Plan A with the blocking-loop fallback (PLAN.md task 3.4).

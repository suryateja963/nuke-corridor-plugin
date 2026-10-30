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

## Findings in real Nuke 17.1v2 Non-commercial (2026-10-30)

Measured by the automatic in-Nuke tests (`tests\run_nuke_auto.ps1`, probes in `nuke\tests\`).

| Finding | Evidence | What the tool does |
|---|---|---|
| **Python gets at most 10 Node objects per session, ever.** The 11th `nuke.nodes.X()` / `toNode()` returns None and stderr says *"The Non-Commercial mode 10-node limit for Node objects accessible in Python has been reached"*. Dropping references or deleting nodes doesn't free any. After the limit, `selectedNodes()` returns `[]` | `nc_limit_probe.py` | Never holds Node objects (`ck2nuke/nc.py`) |
| `nuke.nodePaste(file.nk)` creates nodes **without** using the budget, and a pasted node with an open input connects to the selected node | `nc_limit_probe.py`, `nc_limit_probe2.py` | The comp and the hint Write/Reformat are pasted `.nk` text |
| TCL works by name after the limit: `value X.knob`, `knob X.selected true`, `class X`, `delete X`, `execute X 1-1`, `value [input X 0].name`; `nuke.exists()` and `nuke.expression("X.width")` too | `nc_limit_probe2.py` | All node access is by name |
| TCL `selected_nodes` returns internal ids, and **raises "No nodes selected"** when the selection is empty | auto test | `nc.selected()` resolves ids to names; treats the error as empty |
| `nuke.PythonPanel` doesn't exist; it's **`nukescripts.PythonPanel`** | auto test | Panels subclass `nukescripts.PythonPanel` |
| `nuke.sample()` takes at most 6 arguments (no frame); it samples the current frame | load probe | Tests call `nuke.frame(f)` first |
| In `.nk` text the node on **top of the stack becomes input 0** (push A first, then B) | load probe: Copy B=fg, A=alpha; Merge B=bg, A=premult | `loader.comp_nk` |
| Default colour management is `Nuke` / `nuke-default`, where linear Rec.709 is called `linear` | probe | `nc.linear_colorspace()` picks `linear`, else `Linear Rec.709 (sRGB)` |
| subprocess, background threads, `nuke.ProgressTask` from a thread, `executeInMainThread`, 16-bit PNG renders (HD; 4K Roto scaled to 1920×1080) all work | auto test | as designed |
| Engine launched from Nuke sees the GPU once `PYTHONPATH`/`PYTHONHOME` are stripped | auto test: `CUDA True NVIDIA GeForce RTX 5060 Laptop GPU` | `runner._clean_env()` |

## G2 — Capability test

The automatic test (`tests\run_nuke_auto.ps1`) now covers everything below and more; the manual
G2 script stays as a quick check you can run by hand.

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

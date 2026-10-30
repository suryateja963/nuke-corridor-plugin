# CorridorKey 2.0 for Nuke — Plan v3

**Version:** 3.0 · **Date:** 2026-10-30
**Developer / QA:** You · **Pair developer:** Claude Code
**Machine:** Windows 11, RTX 5060 8 GB, 16 GB RAM · **Software:** Nuke Non-commercial (NC), CorridorKey 2.0 at commit `485f5e9`

---

## 0. Status (2026-10-30)

The code for every phase is written (you asked to build it all at once, ahead of the Gate).
Engine tested on this machine; **Nuke tool tested inside real Nuke 17.1v2 NC** (automatic test, 12/12 pass).

| Phase | Code | Verified | Still needs you |
|---|---|---|---|
| G1/G2 Nuke version, capability test | `nuke/tests/g2_capability_test.py`, `tests/run_nuke_auto.ps1` | Nuke 17.1v2 NC installed; automatic in-Nuke test 12/12 (see `docs/nuke_env.md` findings) | Release date from Help → About (expiry) |
| G3 real-footage check | — | 4K `pail.mp4` keyed cleanly (6 + 12 frames) | Your own footage, especially hair and log clips |
| G4 worker protocol | `docs/worker_api.md` | read from the code | — |
| 1 Colour prep | `ck_engine/probe.py`, `colour.py`, `prepare.py` | Unit tests: curve maths, matrices, exact limited/full decode (zscale), plate reuse. Real footage: sRGB MP4 only | Grey-card check per camera (S-Log3, V-Log, Apple Log, HLG untested); task 1.5 clamp vs keep |
| 2 Job runner | `ck_engine/run.py`, `hints.py`, `despill.py`, `jobio.py`, `run_job.bat`, `run_queue.bat` | GPU end-to-end: preview, versions, first-frame hint, despill, cancel, cleanup | Run a matte-sequence hint on real footage |
| 3 Nuke tool | `nuke/menu.py`, `nuke/ck2nuke/*`, `install_nuke_hook.py` | In real Nuke: menu, panel, Roto hint render (HD/4K), MP4 key and plate+Roto key through the panel, comp loaded and rendered | Use it by hand on your own shots |
| 4 Hardening | failure messages, `docs/troubleshooting.md`, `docs/upgrade_checklist.md` | cancel, missing-input and bad-hint cases in tests | Test matrix on your footage (`docs/test_matrix.md`) |

Changes from this plan, decided while building:
- **No OpenColorIO by default.** The camera curves are the makers' published formulas, and gamut
  matrices are derived from published primaries, all unit-tested. OCIO stays available as the "Other"
  space. This avoids changing the shared CorridorKey venv.
- **Decoding uses zscale, not swscale.** swscale was about 0.4 % off at the range ends.
- **Cutout output dropped** (the worker doesn't produce it). `fg_despill` is written instead.
- **No Node objects in the Nuke tool.** Nuke NC allows Python only 10 per session; nodes are made by pasting `.nk` text and handled by name via TCL (`ck2nuke/nc.py`).
- **"Prepare plate only"** is a mode of its own, so MP4 sources (which NC can't read) get a plate in
  Nuke to Roto on before keying.

## 1. Summary

A Python tool inside Nuke NC that sends a shot to CorridorKey 2.0 running as a separate process. The tool then loads the resulting EXRs back as Read nodes with a ready-made comp.

v3 differs from v2 in one way: **it builds on what already exists on D:**. The engine install, the weights, the measured speed and a long-running worker all come from the ComfyUI work done on 2026-10-28. Because of that, this plan is about **8–12 working days**, not 18–25. Most of that time goes to colour handling and the Nuke panel.

Build order stays as in v2: **gate → engine-side tools → Nuke wrapper → testing.** Nothing Nuke-specific is built until the engine pipeline works from a command prompt.

---

## 2. Starting point (already done)

From notes dated 2026-10-28. Gate task G4 confirms each item before anything depends on it.

| Item | State |
|---|---|
| Upstream code | `D:\CorridorKey2\upstream`, unmodified, commit `485f5e9` |
| Python env | `D:\CorridorKey2\venv`: Python 3.12, torch 2.9.1 + cu128, RTX 5060 detected |
| Weights | Downloaded, SHA checked |
| Measured speed | 48-frame 1080p clip ≈ 150 s (**≈ 3 s/frame**). Auto VRAM picked `hann_chunk=8`, low-VRAM mode. **4K not measured yet** |
| Accuracy | Subprocess output matches the official CLI (mean diff 3e-5); first-frame hint works |
| Reusable code (private repo CK2-roto, tags v0.2–v0.6) | Long-running worker (model loaded once), auto-crop, long-clip hints, matte refinement, despill, compositing, EXR I/O in the worker |
| **Not done** | **No real-footage test yet**; everything so far used synthetic clips |

---

## 3. Locked decisions

| # | Decision | Why |
|---|---|---|
| D1 | **Everything on D:.** (Tool folder has a space: always quote paths in .bat files and subprocess calls.) Tool code in `D:\nuke plugin\`; shots under a root you choose (default `D:\CKShots\`). Only a one-line hook lives in `%USERPROFILE%\.nuke\` | Your storage rule; a 4K shot can use about 30 GB |
| D2 | **Same engine as ComfyUI.** Reuse `D:\CorridorKey2\venv` and `upstream`; no second install | One 5 GB download, one place to update |
| D3 | **The existing worker is the engine API.** `ck_engine` talks to the CK2-roto worker as a subprocess using its own protocol (documented in G4); it doesn't import ComfyUI code | Model loads once per session; no coupling to ComfyUI internals |
| D4 | **Despill runs in the engine**, reusing the CK2 Despill logic | Already built and tested; closes v2's open decision 3.6 |
| D5 | **The engine does all colour work.** It writes one linear Rec.709 half-float EXR plate, which is both what the model reads and what Nuke reads | One source of truth; NC can't render 4K converted plates |
| D6 | **Comp route:** fg + copied alpha → Premult (only if fg is straight, checked in G4) → Merge over BG. Cutout stays a spare output | Avoids v2's duplicate fg/cutout merge |
| D7 | **Nuke UI uses only knob panels** (`nuke.Panel` / `nuke.PythonPanel`), no PySide | Works on any Nuke version |
| D8 | **Plates start at frame 1001** unless the job says otherwise | Nuke convention; easy to change per job |

---

## 4. Phases

### Phase G — Gate (day 1)

Four cheap checks that decide whether the rest is worth building.

| Task | Owner | Done when |
|---|---|---|
| G1 Find the Nuke version (Help → About) and its build date; NC stops working 180 days later | You | `docs/nuke_env.md` has the version and expiry date |
| G2 NC capability test, about 60 lines in the Script Editor. It must: add a menu item; open `nuke.getFilename` and a `nuke.PythonPanel` with an enum and a file knob; run `cmd /c echo ok` through `subprocess` and read its output; update `nuke.ProgressTask` from a background thread; create a Read via `nuke.executeInMainThread`; render Roto → Write to a 16-bit PNG at 1920×1080 with `nuke.execute`; Read and view a 3840×2160 half-float EXR sequence. Then put the menu code in `%USERPROFILE%\.nuke\menu.py`, restart, and confirm the menu appears | Claude writes, you run | Pass/fail recorded for each check in `docs/nuke_env.md` |
| G3 **Real-footage check:** run 2–3 of your own green-screen clips (one phone SDR clip, one with hair or motion blur, and one log clip if you have one) through the existing worker or CLI at 1080p, plus one 4K clip. View the alpha in Nuke | You run, Claude helps | `docs/quality_baseline/` has frames plus your verdict; `docs/performance.md` has s/frame and the auto-VRAM choice for 1080p and 4K |
| G4 Read the CK2-roto worker code and document its protocol: how it starts, request format, progress messages, how it reports errors, cancel, and output layout. Also check whether upstream fg is premultiplied, and the exact output file names | Claude | `docs/worker_api.md` exists; section 2 above confirmed or corrected |

**Gate decisions:**
- G3 keys not good enough on real footage → **stop** and rethink (more hint work, or a different keyer). Nothing below fixes model quality.
- G2 subprocess or main-thread node creation blocked → **Plan B:** build Phases 1–2 only and load EXRs into Nuke by hand. Phase 3.4 has a fallback for background threads only.
- Otherwise → continue.

---

### Phase 1 — Footage and colour prep, `ck_engine/prepare.py` (days 2–5)

The largest piece of new work, and the most likely to run over.

| Task | Owner | Done when |
|---|---|---|
| 1.1 **Probe** with `ffprobe -show_streams -of json`: resolution, fps as an exact fraction (30000/1001), frame count, `pix_fmt` and bit depth, `color_space` (matrix), `color_range`, `color_transfer`, `color_primaries`, timecode. Flag HDR when transfer is `arib-std-b67` (HLG) or `smpte2084` (PQ) | Claude writes, you test | Probe output for each test clip saved to `docs/probe_samples.md` |
| 1.2 **Decode** to `rgb48le` with the **input matrix and range set explicitly** (taken from the probe, overridable in the job), piped straight into Python with no 8-bit step | Claude + you | A limited-range test ramp decodes to 0–1 with no clipping or lifted blacks; a 10-bit log clip shows no banding |
| 1.3 **Choose the OCIO config:** list the colour spaces in OCIO's built-in studio config (`ocio://studio-config-latest`) and check for S-Log3/S-Gamut3, S-Log3/S-Gamut3.Cine, V-Log/V-Gamut, Apple Log, Rec.2100-HLG and Linear Rec.709. For any that are missing, use the camera maker's published formula or LUT | Claude | `docs/colour_spaces.md` lists which source each space comes from |
| 1.4 **SDR sRGB/Rec.709 path:** use upstream's own `srgb_to_linear` so results match the official CLI | Claude | Plate matches what upstream produces on the same clip (mean diff ≈ 0) |
| 1.5 **Out-of-gamut policy:** BT.2020 sources (Apple Log, HLG) go negative in Rec.709. Key one such clip twice, once with negatives clamped to 0 and once left as-is, compare, and lock the winner as the default | You compare, Claude builds | Policy written in `docs/colour_spaces.md` |
| 1.6 **HLG phone video:** convert it through OCIO instead of only warning. Keep the warning that HDR should be off for green-screen shoots | Claude | An HLG iPhone clip produces a plausible plate |
| 1.7 **Write the plate:** half-float EXR, ZIP compression, `plate_lin/plate.####.exr` from frame 1001. Sidecar `plate.json` holds fps, source path, input colour space, matrix/range used, and the frame mapping | Claude + you | Nuke reads the plate at the right fps and frame range, with the Read set to linear |
| 1.8 **EXR/DPX input:** convert through OCIO, or pass through untouched if it's already linear Rec.709 | Claude | An EXR sequence passes through bit-identical |
| 1.9 `docs/unsupported_formats.md`: BRAW, R3D and ARRIRAW → export EXR or ProRes from DaVinci Resolve | Claude | File exists |

**Done when:** every source type **you actually own** becomes a plate that looks right in Nuke. On a colour chart shot, the 18% grey patch lands at about 0.18 linear and the patches don't shift visibly in hue.

> Only test the cameras you have footage from. If you have no V-Log or Apple Log clips, keep those conversions in the code but mark them "untested" in the matrix.

---

### Phase 2 — Job runner and standalone tool, `ck_engine/run.py` (days 6–7)

| Task | Owner | Done when |
|---|---|---|
| 2.1 **`job.json` schema** with `schema_version: 1`: source, colour space, matrix/range override, hint mode, hint path and invert, hint quality, outputs, despill amount, frame range, **preview range**, shot root and temp folder | Claude | Schema documented in `docs/job_schema.md` with one example per hint mode |
| 2.2 **`hints.py`:** none; first frame (scaled up to the exact plate size, since upstream rejects a size mismatch); every frame (sequence); matte file with invert and a frame-count check. Hint-quality presets: 0.95 careful roto, 0.75 rough matte, 0.5 scribble | Claude + you | Each mode keys the intended person on a two-person test shot |
| 2.3 **Pipeline:** prepare → hints → worker (as in G4) → rename outputs to plate frame numbers (`alpha.1001.exr`) → despill → status | Claude | `run.py job.json` writes `key/v001/{alpha,fg,cutout}/` |
| 2.4 **Preview range:** key frames 1001–1024 only (about 1 minute at 1080p) before committing to the full shot | Claude | Preview finishes and goes into its own folder (`key/preview/`) |
| 2.5 **Progress and status:** print `PROGRESS 0.42 <stage>` lines; write `status.json` (`running` / `done` / `failed` / `cancelled`, with error text and output paths); keep a full `log.txt` | Claude | Progress shows in the console; every exit leaves a correct `status.json` |
| 2.6 **Cancel:** Ctrl+C or a `CANCEL` file in the shot folder → kill the process tree (`taskkill /T /F`) and delete temp memmaps | Claude | No leftover processes in Task Manager and no temp files after a cancel |
| 2.7 **Versions:** each re-key goes to the next `vNNN` folder; nothing is overwritten | Claude | Two keys in a row produce v001 and v002 |
| 2.8 **Launchers:** `run_job.bat job.json` (activates the D: venv) and `run_queue.bat <folder>` (runs every `job.json` in it, one after another) | Claude | Both work from a plain command prompt |

**Done when:** `run_job.bat` keys a phone MP4, a log clip and an EXR sequence with each hint mode. It also needs working progress, a correct `status.json`, and a clean cancel.

---

### Phase 3 — Nuke tool (days 8–10)

| Task | Owner | Done when |
|---|---|---|
| 3.1 **Install:** add one line to `%USERPROFILE%\.nuke\menu.py` that calls `nuke.pluginAddPath(r"D:\nuke plugin\nuke")`. Settings (engine folder, shot root) go in `D:\nuke plugin\settings.json` | Claude | Menu "CorridorKey 2.0" appears after restarting Nuke |
| 3.2 **Panel** (knobs only): Source (selected Read, or browse for an MP4/MOV, which NC can't read itself); Colour space; Hint mode, hint path/node, invert, quality; Outputs; Despill; Frame range; Preview checkbox | Claude + you | Panel writes a valid `job.json` |
| 3.3 **Hint from Nuke:** render the selected Roto through a Write into `hint/`. NC caps renders at 1920×1080 and the engine scales hints up to plate size | Claude + you | Roto hints from Nuke key the right subject on both an HD and a 4K plate |
| 3.4 **Run:** start `run_job.bat` from a background thread; feed `PROGRESS` lines to `nuke.ProgressTask`; Cancel writes the `CANCEL` file. **Fallback if G2's thread test failed:** a blocking loop on the main thread that reads `status.json` | Claude + you | Progress bar moves and Cancel works; Nuke stays usable during the key (or the fallback works) |
| 3.5 **Load results** on the main thread: Reads for plate, alpha, fg and cutout, set to linear, with frame range and fps from `plate.json`; comp (D6) inside a Backdrop with a BG input | Claude + you | Comp shows a clean result over a test background |
| 3.6 **NC limits:** only use `nuke.selectedNode()` and nodes the tool creates; never `nuke.allNodes()` | Claude | No NC limit errors in testing |
| 3.7 **Clean-up item:** for a chosen shot, delete temp files, previews and versions older than the newest (always asks first) | Claude | The newest version is never deleted |

**Done when:** from a fresh Nuke you can key an MP4, a log clip and an EXR sequence with each hint mode, without opening a command prompt.

---

### Phase 4 — Testing and hardening (days 11–12)

| Task | Owner | Done when |
|---|---|---|
| 4.1 **Test matrix:** (HD, 4K) × (no hint, Roto first frame, Roto every frame, matte) × (each source type you own). Record s/frame, the window chosen, flicker, and pass/fail | You | `docs/test_matrix.md` filled in |
| 4.2 **Quality baseline:** composite a known image with alpha over flat green, key it, and diff against the original alpha. Re-run this after every engine update | You + Claude | Baseline and diff numbers saved in `docs/quality_baseline/` |
| 4.3 **Failure tests:** missing weights, full disk, cancel mid-run, corrupt frame, hint with the wrong frame count, CUDA out of memory (key 4K with a heavy Nuke viewer open). Each must show a readable message in Nuke | You + Claude | All six give clear messages; none hangs Nuke |
| 4.4 `docs/upgrade_checklist.md`: moving to a new NC version (copy the hook line, re-run G2); updating upstream (new folder, re-run 4.1 and 4.2, keep the old one until they pass) | Claude | File exists |

---

## 5. Milestones

- [ ] **M0 — Gate passed:** real keys are good enough, NC capabilities confirmed (or Plan B chosen), worker protocol documented
- [ ] **M1 — Plates:** every owned source type becomes a correct linear plate, checked against a chart
- [ ] **M2 — Standalone:** `run_job.bat` / `run_queue.bat` key end to end with preview, progress, cancel and versions
- [ ] **M3 — In Nuke:** full key from the panel, results loaded with the comp
- [ ] **M4 — Hardened:** test matrix and failure tests pass; upgrade checklist written

## 6. Timeline

| Phase | Days | Ends |
|---|---|---|
| G — Gate | 1 | Day 1 |
| 1 — Colour prep | 3–4 | Day 5 |
| 2 — Job runner | 2 | Day 7 |
| 3 — Nuke tool | 2–3 | Day 10 |
| 4 — Testing | 2 | Day 12 |

Add 2–3 days of buffer for colour surprises. **Realistic total: 10–15 working days**, plus render time for 4K tests.

## 7. Risk register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Keys aren't good enough on real footage | **Unknown, test first** | **Project-level** | Gate G3, before any new code |
| Wrong YUV matrix or range crushes or lifts log levels | High if unhandled | High | Explicit matrix and range (1.2), ramp test, chart check |
| OCIO config lacks a camera space (e.g. Apple Log) | Medium | Medium | Check first (1.3); maker's formula or LUT fallback |
| Wide-gamut negatives confuse the model | Medium | Medium | A/B test and set a policy (1.5) |
| NC blocks background threads | Low–Medium | Medium | Blocking-loop fallback (3.4) |
| NC blocks subprocess or main-thread node creation | Low | High | Plan B: standalone only |
| 4K too slow on 8 GB | Medium | Low | Preview range; 1080p proxy key for long shots; measured in G3 |
| CUDA out of memory with Nuke open | Low–Medium | Medium | Engine's auto VRAM; readable error (4.3); close other GPU apps |
| Worker protocol changes when the ComfyUI pack is updated | Medium | Medium | `docs/worker_api.md`; pin the CK2-roto tag the Nuke tool was tested with |
| NC version expires | Certain (every ~180 days) | Low | Expiry date in G1; upgrade checklist |

## 8. Open questions (answer before or during the Gate)

1. Your exact Nuke version (G1).
2. Which cameras and log formats you **actually have footage from** right now? This decides the Phase 1 test list.
3. Shot root folder: is `D:\CKShots\` OK?
4. Plates starting at 1001: OK, or match source timecode?

## 9. Working with Claude Code

Put this file at `D:\nuke plugin\PLAN.md` and add a `CLAUDE.md` next to it:

```
Project plan: @PLAN.md
Work one phase at a time. Stop at each "Done when" and show me the result.
Don't start the next phase until I confirm the current one passes.
All files and outputs stay on D:. Engine = D:\CorridorKey2 (shared with the ComfyUI pack; don't modify upstream).
Claude can't click inside Nuke: write the scripts, tell me exactly how to run them, and wait for my results.
```

First prompt: *"Read PLAN.md. Do Gate task G4 (document the worker protocol) and write the G2 capability-test script."*

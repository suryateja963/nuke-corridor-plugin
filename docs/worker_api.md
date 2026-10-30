# CK2 worker API (Gate G4)

What the Nuke tool's engine (`ck_engine/run.py`) can rely on when it drives the existing
CorridorKey 2.0 worker. Read from the code on 2026-10-30:

- Worker: `D:\CorridorKey2\ComfyUI-CorridorKey2\ck2\worker.py`, private repo CK2-roto,
  commit `f7053e1` (main, after tag v0.6). **Pin to this commit**; re-check this file after
  any update there.
- Bridge (reference client): `ck2/bridge.py`, same commit.
- Upstream: `D:\CorridorKey2\upstream`, commit `485f5e9`, unmodified.

## 1. Launching

| Item | Value |
|---|---|
| Python | `D:\CorridorKey2\venv\Scripts\python.exe` |
| Command | `python -u worker.py <job.json>` (one job, then exit) or `python -u worker.py --serve <upstream_root>` (load once, take jobs on stdin) |
| Working dir | `upstream_root` (`D:\CorridorKey2\upstream`) |
| Env | **Remove `PYTHONPATH` and `PYTHONHOME`**, set `PYTHONUNBUFFERED=1`, `PYTHONIOENCODING=utf-8`. The worker itself forces `HF_HUB_OFFLINE=1` / `TRANSFORMERS_OFFLINE=1` |
| Window | `creationflags=CREATE_NO_WINDOW` |
| Output | stdout and stderr merged; read line by line |

**Nuke trap:** Nuke sets `PYTHONPATH`/`PYTHONHOME` for its own Python. A child process that
inherits them loads Nuke's libraries instead of the venv's and crashes or misbehaves. The bridge
already strips them; `run.py`, `run_job.bat` and the Nuke panel's launcher must do the same.
Gate G2 check 5 tests exactly this from inside Nuke.

The bridge checks these before starting; `run.py` should too, with the same messages:
venv python exists, `upstream/corridorkey/runtime.py` exists,
`upstream/weights/corridorkey_v2.safetensors` exists.

## 2. Job file

JSON, UTF-8. Fields the worker reads (anything else is ignored):

| Field | Type | Meaning |
|---|---|---|
| `upstream_root` | str | Needed in one-shot mode (the bridge adds it) |
| `work_dir` | str | Scratch folder; its **folder name is the job id**. `CANCEL` file goes here |
| `output_dir` | str | EXRs go to `<output_dir>/exr/` |
| `input_path` | str | Video file or frame folder. **For us: the prepared linear EXR plate folder** |
| `frames_npy` | str | Alternative input (ComfyUI only) — not used by the Nuke tool |
| `expected_frames` | int | Frame count (used when cropping; also sets progress total) |
| `frame_size` | [w, h] | Plate size; read from the first frame if missing |
| `crop` | [x, y, w, h] | Optional fixed crop box; outputs stay crop-sized. Not used in v1 |
| `hint_npy` + `hint_mode` | str, `"first_frame"`/other | Hint as a .npy array `[T,H,W]` float 0–1. `first_frame` uses frame 0 only and **resizes it to the plate size** |
| `hint_path` | str | Hint video or folder, one mask per frame |
| `keep_exr` | bool | **Must be `true`** for us (otherwise the EXRs are deleted) |
| `return_arrays` | bool | **Set `false`** for us (skips the .npy conversion for ComfyUI) |
| `settings.window` | `"auto"` or int | `"auto"` → upstream auto-VRAM picks the window |
| `settings.low_vram` | bool | Forces low-VRAM mode (disables auto-VRAM) |
| `settings.carry_hint` | bool | Default true |
| `settings.hint_quality` | float | Default 0.95; also used as carry-hint quality |
| `settings.max_frames` | int | -1 = all. Usable for the preview range (from the start only) |
| `settings.fps` | float | fps for frame-folder input |
| `settings.input_is_linear` | bool | **Must be `true`** for our linear EXR plates. Otherwise upstream treats EXRs as display-coded and clips to [0, 1] |

Hard-coded in the worker, not settable: `outputs = {"alpha", "fg"}`, `output_format = "exr"`,
`exr_dtype = "half"`, `hann_stride = window/2`, `despill_strength` = upstream default 0.5
(only affects cutout/checker, which the worker doesn't request).

## 3. Messages on stdout

| Line | Meaning |
|---|---|
| `CK2_READY` | Serve mode only: model loaded, send jobs |
| `CK2_PROGRESS <done> <total>` | Frames written by the alpha writer |
| `CK2_DONE <job_id>` | Success |
| `CK2_ERROR <job_id> cancelled` | Cancelled via the `CANCEL` file |
| `CK2_ERROR <job_id> CUDA out of memory: …` | OOM; worker stays usable |
| `CK2_ERROR <job_id> <Type>: <msg>` | Any other error (traceback printed just before it) |
| anything else | Log line (upstream prints, e.g. `Auto VRAM: …`, `window i/N [t0:t1]`) |

Exit codes (one-shot mode): 0 after `CK2_DONE`; non-zero on error. In serve mode a CUDA
fault (`CUDA error`, `device-side assert`) makes the worker exit with code 3 so the client
starts a fresh one; the bridge retries the job once.

**Progress gap:** `CK2_PROGRESS` only moves once frames are written (stage 2). During
stage 1 the bar would sit at 0 — on a long 4K shot that could be minutes. `run.py` should also
parse the log line `window i/N` and map stage 1 to 0–50 % and frames written to 50–100 %.

## 4. Serve mode (persistent worker)

stdin, one JSON per line:
`{"cmd": "job", "job_path": "<path>", "keep_model": "gpu"|"cpu"}` or `{"cmd": "quit"}`.
Before each job the worker restores the model's freshly-loaded state, so reuse is safe
(covered by the pack's `tests/test_worker_reuse.py`). `keep_model: "cpu"` moves the model
off the GPU between jobs, freeing VRAM for Nuke.

## 5. Cancel

Create `<work_dir>/CANCEL`. The worker checks it in readers, writers and while preparing
inputs, then reports `CK2_ERROR <id> cancelled` (one-shot: exits). The bridge waits
**30 s** after creating the file, then kills the process. `run.py` should do the same, using
`taskkill /T /F /PID` so child processes die too, then delete `work_dir/upstream_tmp`.

## 6. Outputs

With `keep_exr: true`:

```
<output_dir>/exr/<clip>_alpha_exr/   1-channel half EXR, clamped 0–1
<output_dir>/exr/<clip>_fg_exr/      3-channel half EXR
```

- `<clip>` comes from upstream's `raw_clip_name(input_path)` — for a folder input, the
  folder name (`plate_lin`). Files are `<name>_<index:06d>.exr` starting at 0
  (`alpha_000000.exr`, `fg_000000.exr`; from upstream `video_io.ExrSequenceWriter`).
- **fg is straight (not premultiplied) scene-linear colour**, unclamped (values >1 and
  small negatives survive), **with no despill**. → The Nuke comp needs **Premult** after
  copying alpha in (plan D6 confirmed), and despill must be applied by us (plan D4).
- **cutout** (if ever requested) is linear despilled RGB + alpha as straight RGBA.

## 7. First-frame hint size rule (upstream)

`load_initial_hint_frame` accepts a hint whose size equals either the plate's native size
or the model's internal size; anything else raises
`hint shape … does not match native … or model …`. The worker's `first_frame` mode resizes
to the plate size, so going through `hint_npy` is safe.

## 8. Gaps for the Nuke tool and what to do

| # | Gap | Recommendation |
|---|---|---|
| W1 | Worker decodes **video at 8 bits** with OpenCV | Already planned: always pass the prepared linear EXR folder with `input_is_linear: true` |
| W2 | No first-frame hint from a file path (only `hint_npy`) | `run.py` (running in the venv) loads the Nuke-rendered PNG and writes a 1-frame `.npy` → `hint_mode: "first_frame"`. **No worker change** |
| W3 | Outputs fixed to alpha + fg; no cutout, no despill setting | Drop cutout from v1 (it's only fg + alpha + despill anyway). Despill in `run.py` with the CK2 Despill logic, writing `fg_despill` EXRs. **No worker change** |
| W4 | Preview range only from the first frame (`max_frames`) | Fine for v1. A mid-shot preview = prepare only that frame range as the plate |
| W5 | Stage-1 progress invisible | Parse `window i/N` in `run.py` (section 3) |
| W6 | Output names `<clip>_alpha_exr/alpha_000000.exr` | `run.py` renames to `key/vNNN/alpha/alpha.1001.exr` etc. |
| W7 | Worker lives in another repo | Call it by path from `settings.json`; pin commit `f7053e1`; don't copy its code into this repo |

Net result: **the Nuke tool needs no changes to the worker or to upstream.**

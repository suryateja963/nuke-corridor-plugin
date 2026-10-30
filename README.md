# CorridorKey 2.0 for Nuke

Key green/blue screen shots with **CorridorKey 2.0** from inside **Nuke Non-commercial**. Pick a
shot, choose its colour space and an optional hint, press OK. The tool prepares a linear EXR plate,
keys it on your GPU, and loads the alpha, fg and a ready-made comp back into Nuke.

Nuke never loads the model. A separate engine (`ck_engine`, running in the CorridorKey venv) does the
work, so Nuke NC's restrictions on plug-ins and Python barely matter.

Personal, internal tool. CorridorKey 2.0 and its weights are under the Corridor Key Licence
(`D:\CorridorKey2\upstream\LICENSE`).

## Requirements

| What | Where it is expected |
|---|---|
| CorridorKey 2.0 upstream (commit `485f5e9`) + weights | `D:\CorridorKey2\upstream` |
| CorridorKey venv (Python 3.12, torch cu128) | `D:\CorridorKey2\venv` |
| CK2 worker (CK2-roto repo, commit `f7053e1`) | `D:\CorridorKey2\ComfyUI-CorridorKey2\ck2\worker.py` |
| ffmpeg + ffprobe with zscale (e.g. gyan.dev "full" build) | on PATH |
| Nuke Non-commercial | any recent version |
| NVIDIA GPU | tested on RTX 5060 Laptop 8 GB |

Paths live in [settings.json](settings.json). For per-machine changes, create `settings.local.json`
(not in git) with only the keys you want to override.

## Install into Nuke

```bat
D:\CorridorKey2\venv\Scripts\python.exe "D:\nuke plugin\install_nuke_hook.py"
```

This adds one line to `%USERPROFILE%\.nuke\init.py`. Restart Nuke and a **CorridorKey 2.0** menu
appears. To uninstall, run the same command with `--remove`.

Before relying on it, run the Gate G2 capability test once per Nuke version; see
[docs/nuke_env.md](docs/nuke_env.md).

## Using it in Nuke

**EXR/DPX sequence:** select its Read (and optionally a Roto drawn over it), then
**CorridorKey 2.0 → Key shot…**.

**Phone/camera MP4 or MOV** (Nuke NC can't read these):
1. **CorridorKey 2.0 → Prepare plate only…** and pick the file. Choose the right colour space.
2. The linear plate loads as a Read. To give a hint, draw a Roto on it (white = subject).
3. Select the plate Read and the Roto, then **Key shot…**.

Panel basics:
- **colour space**: what the camera recorded (see [docs/colour_spaces.md](docs/colour_spaces.md)).
  Never key log footage as sRGB.
- **hint**:
  - none: the model picks the subject;
  - selected node, first frame or every frame: usually a Roto;
  - matte file: a still, a sequence or a matte video.
  Set **hint quality** to 0.95 for careful roto, 0.75 for a rough matte, 0.5 for a scribble.
- **preview only**: keys the first N frames into `key/preview` to check settings quickly.
- **despill**: written as a separate `fg_despill` pass (0 = off).
- **window / low VRAM**: leave on auto unless you hit GPU memory errors.

Keying runs in the background with a progress bar; Cancel stops it. When it finishes you get, inside
a Backdrop: plate, fg (despilled), alpha → Copy → Premult → Merge over a grey BG.

## Without Nuke (command line)

Write a `job.json` (schema: [docs/job_schema.md](docs/job_schema.md)) and run:

```bat
run_job.bat "D:\CKShots\myshot\job.json"
run_queue.bat "D:\CKShots"
```

`run_queue.bat` runs every `job.json` under a folder, one after another.

## Shot folder

```
<shots folder>\<shot>\
  job.json  status.json  log.txt
  plate.json            what the plate was made from (reused if unchanged)
  plate_lin\            plate.1001.exr ...   linear Rec.709, half float, ZIP
  hint\                 hint_first.npy, seq\, nuke_render\
  key\v001\             alpha\  fg\  fg_despill\   (preview\ for preview keys)
```

Each key goes into a new version (`v001`, `v002`…); nothing is overwritten except `preview`.
**CorridorKey 2.0 → Clean up a shot…** deletes temp files, previews and older versions, and always
keeps the newest version.

## Tests

```bat
cd /d "D:\nuke plugin"
D:\CorridorKey2\venv\Scripts\python.exe -m unittest discover -s tests -v
D:\CorridorKey2\venv\Scripts\python.exe tests\e2e_gpu.py
```

- The first command runs the CPU tests: colour maths, decoding levels, sequences, hints, despill,
  job schema, and the Nuke-tool logic against a stand-in `nuke` module.
- The second keys a real clip on the GPU.

## Docs

- [PLAN.md](PLAN.md): build plan and status
- [docs/worker_api.md](docs/worker_api.md): how the engine talks to the CK2 worker
- [docs/colour_spaces.md](docs/colour_spaces.md): colour handling per footage type
- [docs/job_schema.md](docs/job_schema.md): `job.json` fields
- [docs/nuke_env.md](docs/nuke_env.md): Gate G1/G2 (Nuke version, capability test)
- [docs/performance.md](docs/performance.md): measured speed
- [docs/unsupported_formats.md](docs/unsupported_formats.md): BRAW / R3D / ARRIRAW
- [docs/upgrade_checklist.md](docs/upgrade_checklist.md): new Nuke version, engine updates
- [docs/troubleshooting.md](docs/troubleshooting.md): common errors

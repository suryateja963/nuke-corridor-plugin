# job.json (schema_version 1)

The Nuke panel writes this file to `<shot>/job.json`; you can also write it by hand and run
`run_job.bat`. Only `schema_version` and `source.path` are required; everything else has the
defaults shown (from `ck_engine/jobio.py`).

```json
{
  "schema_version": 1,
  "stage": "all",
  "shot_dir": null,
  "source": {"path": "D:/footage/greenscreen.mp4"},
  "colour": {"space": "srgb_rec709", "matrix": "auto", "range": "auto",
             "gamut": "clamp", "ocio_name": null},
  "frames": {"first": null, "last": null, "start_frame": 1001, "preview_frames": 0},
  "fps": null,
  "hint": {"mode": "none", "path": null, "invert": false, "quality": 0.95, "carry": true},
  "despill": {"amount": 0.0, "screen": "green"},
  "engine": {"window": "auto", "low_vram": false}
}
```

| Field | Values | Meaning |
|---|---|---|
| `stage` | `all`, `prepare` | `prepare` makes the plate only (so you can Roto on it in Nuke) |
| `shot_dir` | path | Where everything is written; default = folder of job.json |
| `source.path` | path | Video file; image sequence as `name.####.exr`, `name.%04d.exr`, a folder, or any one frame of it |
| `colour.space` | see [colour_spaces.md](colour_spaces.md) | Source colour space |
| `colour.matrix` | `auto` `bt709` `bt601` `bt2020` | YUV matrix for video (auto = file flag, else by size) |
| `colour.range` | `auto` `limited` `full` | auto = full for camera log, else the file flag |
| `colour.gamut` | `clamp` `keep` | Negative (out-of-gamut) values after conversion |
| `colour.ocio_name` | string | Colour space name when `space` is `ocio` |
| `frames.first`/`last` | int or null | Source frame numbers. Video: 1 = first frame. Sequences: file numbers |
| `frames.start_frame` | int | Plate number given to video frame 1 (sequences keep their own numbers) |
| `frames.preview_frames` | int | >0: only the first N frames of the range, into `key/preview` |
| `fps` | number or null | Override the source frame rate |
| `hint.mode` | `none` `first_frame` `sequence` | |
| `hint.path` | path | Image, sequence (pattern/folder) or matte video. Masks use alpha if it varies, else RGB average; white = subject |
| `hint.invert` | bool | Invert the mask |
| `hint.quality` | 0–1 | How much to trust the hint |
| `hint.carry` | bool | Carry the hint forward between windows (upstream default true) |
| `despill.amount` | 0–1 | 0 = no `fg_despill` pass |
| `despill.screen` | `green` `blue` | |
| `engine.window` | `auto` or 1–80 | Frames per window; auto lets upstream pick for your VRAM |
| `engine.low_vram` | bool | Force low-VRAM mode |

A sequence hint must line up with the plate. It's accepted if it is numbered like the plate, like the
source, or has exactly one frame per plate frame.

## status.json (written by the engine)

```json
{"state": "done", "progress": 1.0, "message": "key v001 done", "error": null,
 "stage": "all", "shot_dir": "...", "version": "v001", "key_dir": "...",
 "plate": {"pattern": ".../plate.####.exr", "first": 1001, "last": 1048, "count": 48,
           "width": 3840, "height": 2160, "fps": 25.0, "reused": false},
 "outputs": {"alpha": ".../alpha.####.exr", "fg": ".../fg.####.exr", "fg_despill": "..."},
 "auto_vram": "Auto VRAM: ...", "warnings": [], "started": "...", "finished": "..."}
```

`state` is `running`, `done`, `failed` (see `error`), or `cancelled`.

## Engine console output

`PROGRESS <0-1> <message>` lines (what Nuke's progress bar follows), then `DONE …`, `ERROR …` or
`CANCELLED`. Engine log lines are prefixed `  | `. Exit codes: 0 done, 1 failed, 2 cancelled,
64 bad usage.

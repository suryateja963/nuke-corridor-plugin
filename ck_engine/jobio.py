"""job.json schema: defaults, validation, and status.json writing.

Pure standard library, so the Nuke side can import it too.
"""

from __future__ import annotations

import copy
import json
import os
import time
from pathlib import Path

SCHEMA_VERSION = 1

DEFAULT_JOB = {
    "schema_version": SCHEMA_VERSION,
    "stage": "all",                # "all" = prepare + key; "prepare" = plate only
    "shot_dir": None,              # default: the folder holding job.json
    "source": {"path": None},      # video file, image-sequence pattern (#### or %04d), folder, or one frame
    "colour": {
        "space": "srgb_rec709",    # see ck_engine.colour.SPACES, "auto", or "ocio"
        "matrix": "auto",          # auto | bt709 | bt601 | bt2020
        "range": "auto",           # auto | limited | full
        "gamut": "clamp",          # clamp | keep (negative out-of-gamut values)
        "ocio_name": None,
    },
    "frames": {
        "first": None,             # source frame numbers (video: 1 = first frame)
        "last": None,
        "start_frame": 1001,       # plate number of video frame 1 (sequences keep their numbers)
        "preview_frames": 0,       # >0: key only the first N frames into key/preview
    },
    "fps": None,                   # override; default from the source
    "hint": {
        "mode": "none",            # none | first_frame | sequence
        "path": None,              # image, sequence pattern/folder, or matte video
        "invert": False,
        "quality": 0.95,           # 0.95 careful roto, 0.75 rough matte, 0.5 scribble
        "carry": True,
    },
    "despill": {
        "amount": 0.0,             # 0 = no fg_despill pass; "edges": maximum strength
        "screen": "green",
        "mode": "everywhere",      # everywhere | edges (edges + screen bounce, keeps green clothing)
    },
    "crop": {
        "mode": "off",             # off | auto (find the subject against the screen) | manual
        "margin": 64,              # pixels added around the auto box before rounding to 128
        "box": None,               # manual: [x, y, w, h] in plate pixels
    },
    "refine": {
        "preset": "off",           # off | hairfur | solid (see ck_engine.refine.PRESETS)
        "grow": 0,                 # pixels: + moves the matte edge out, - in
    },
    "engine": {"window": "auto", "low_vram": False},
}

SPACE_KEYS = ("auto", "srgb_rec709", "linear_rec709", "acescg", "slog3_sgamut3",
              "slog3_sgamut3cine", "vlog_vgamut", "applelog", "hlg_rec2020", "pq_rec2020", "ocio")


class JobError(ValueError):
    pass


def _merge(base: dict, extra: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (extra or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load_job(path: str | Path) -> dict:
    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise JobError(f"can't read job file {path}: {exc}") from exc
    job = _merge(DEFAULT_JOB, raw)
    if not job.get("shot_dir"):
        job["shot_dir"] = str(path.parent)
    validate(job)
    return job


def validate(job: dict) -> None:
    if job.get("schema_version") != SCHEMA_VERSION:
        raise JobError(f"job schema_version must be {SCHEMA_VERSION}")
    if job["stage"] not in ("all", "prepare"):
        raise JobError("stage must be 'all' or 'prepare'")
    if not job["source"].get("path"):
        raise JobError("source.path is required")
    c = job["colour"]
    if c["space"] not in SPACE_KEYS:
        raise JobError(f"unknown colour space {c['space']!r}")
    if c["matrix"] not in ("auto", "bt709", "bt601", "bt2020"):
        raise JobError("colour.matrix must be auto, bt709, bt601 or bt2020")
    if c["range"] not in ("auto", "limited", "full"):
        raise JobError("colour.range must be auto, limited or full")
    if c["gamut"] not in ("clamp", "keep"):
        raise JobError("colour.gamut must be clamp or keep")
    h = job["hint"]
    if h["mode"] not in ("none", "first_frame", "sequence"):
        raise JobError("hint.mode must be none, first_frame or sequence")
    if h["mode"] != "none" and not h.get("path"):
        raise JobError(f"hint.mode {h['mode']} needs hint.path")
    if not 0.0 <= float(h["quality"]) <= 1.0:
        raise JobError("hint.quality must be between 0 and 1")
    d = job["despill"]
    if not 0.0 <= float(d["amount"]) <= 1.0 or d["screen"] not in ("green", "blue"):
        raise JobError("despill.amount must be 0-1 and despill.screen green or blue")
    if d.get("mode", "everywhere") not in ("everywhere", "edges"):
        raise JobError("despill.mode must be everywhere or edges")
    c = _merge(DEFAULT_JOB["crop"], job.get("crop") or {})
    if c["mode"] not in ("off", "auto", "manual"):
        raise JobError("crop.mode must be off, auto or manual")
    if c["mode"] == "manual" and not (isinstance(c.get("box"), (list, tuple)) and len(c["box"]) == 4):
        raise JobError("crop.mode manual needs crop.box = [x, y, w, h]")
    if not 0 <= int(c["margin"]) <= 1024:
        raise JobError("crop.margin must be 0-1024 pixels")
    r = _merge(DEFAULT_JOB["refine"], job.get("refine") or {})
    if r["preset"] not in ("off", "hairfur", "solid"):
        raise JobError("refine.preset must be off, hairfur or solid")
    if not -50 <= int(r["grow"]) <= 50:
        raise JobError("refine.grow must be -50 to 50 pixels")
    w = job["engine"]["window"]
    if w != "auto" and not (isinstance(w, int) and 1 <= w <= 80):
        raise JobError("engine.window must be 'auto' or a number of frames (1-80)")
    f = job["frames"]
    if f["first"] is not None and f["last"] is not None and int(f["first"]) > int(f["last"]):
        raise JobError("frames.first is after frames.last")


def write_json_atomic(path: Path, data: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)


class Status:
    """status.json next to job.json: what Nuke (or you) read to know the outcome."""

    def __init__(self, job_dir: Path):
        self.path = job_dir / "status.json"
        self.data = {"state": "running", "progress": 0.0, "message": "starting",
                     "error": None, "warnings": [], "started": time.strftime("%Y-%m-%d %H:%M:%S")}
        self._last = 0.0
        self.save()

    def update(self, force: bool = False, **kw) -> None:
        self.data.update(kw)
        now = time.time()
        if force or now - self._last > 1.0:
            self._last = now
            self.save()

    def finish(self, state: str, **kw) -> None:
        self.data.update(kw, state=state, finished=time.strftime("%Y-%m-%d %H:%M:%S"))
        if state == "done":
            self.data["progress"] = 1.0
        self.save()

    def save(self) -> None:
        try:
            write_json_atomic(self.path, self.data)
        except OSError:
            pass  # a full disk must not hide the real error

"""Source -> linear Rec.709 half-float EXR plate (<shot>/plate_lin/plate.####.exr).

The plate is what the model reads and what Nuke reads, so key and plate always
line up. Video is decoded by ffmpeg at 16 bits per channel with the YUV matrix
and range set explicitly; never through an 8-bit step.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from . import colour
from .config import EngineError
from .imageio import read_image, write_exr
from .probe import Source

PLATE_DIR = "plate_lin"
PLATE_NAME = "plate.%04d.exr"

_MATRIX = {"bt709": "bt709", "bt470bg": "bt601", "smpte170m": "bt601", "bt601": "bt601",
           "bt2020nc": "bt2020", "bt2020c": "bt2020", "bt2020": "bt2020",
           "smpte240m": "smpte240m", "fcc": "fcc"}
# zimg (zscale) names. zscale is used instead of swscale because swscale's
# YUV->RGB loses ~0.4 % at the range ends (limited white decodes to 0.996).
_ZIMG_MATRIX = {"bt709": "709", "bt601": "170m", "bt2020": "2020_ncl",
                "smpte240m": "240m", "fcc": "fcc"}


@dataclass
class Plate:
    dir: str
    pattern: str            # printf pattern of the plate frames
    frames: list[int]       # plate frame numbers, in order
    width: int
    height: int
    fps: float
    fps_text: str
    reused: bool
    source_frames: list[int]
    warnings: list[str]

    @property
    def pattern_hashes(self) -> str:
        return self.pattern.replace("%04d", "####")


def select_frames(src: Source, first, last, preview: int) -> list[int]:
    frames = [f for f in src.frames
              if (first is None or f >= first) and (last is None or f <= last)]
    if not frames:
        raise EngineError(f"frame range {first}-{last} is outside the source "
                          f"({src.frames[0]}-{src.frames[-1]})")
    if preview and preview > 0:
        frames = frames[:preview]
    return frames


def decode_settings(src: Source, space_key: str, matrix: str, rng: str) -> tuple[str, str]:
    """Resolves 'auto' matrix/range. Returns (swscale matrix, 'limited'|'full')."""
    if matrix == "auto":
        matrix = _MATRIX.get(src.color_matrix, "bt709" if src.height >= 720 else "bt601")
    if rng == "auto":
        default = colour.SPACES[space_key].default_range if space_key in colour.SPACES else "probe"
        if default == "full" or src.kind == "sequence":
            rng = "full"
        else:
            rng = "full" if src.color_range == "pc" else "limited"
    if rng not in ("limited", "full"):
        raise EngineError(f"range must be auto, limited or full, not {rng!r}")
    return matrix, rng


def _prep_key(src: Source, job: dict, frames: list[int], plate_frames: list[int],
              matrix: str, rng: str) -> str:
    stat_path = src.path if src.kind == "video" else src.frame_path(frames[0])
    st = os.stat(stat_path)
    c = job["colour"]
    blob = json.dumps([src.path, st.st_size, int(st.st_mtime), c.get("space"), c.get("ocio_name"),
                       c.get("gamut", "clamp"), matrix, rng, frames, plate_frames], sort_keys=True)
    return hashlib.sha1(blob.encode()).hexdigest()


def _video_frames(src: Source, frames: list[int], matrix: str, rng: str, ffmpeg: str):
    """Yields float32 RGB code values [H,W,3] for `frames` (1-based, contiguous)."""
    first, count = frames[0], len(frames)
    vf = []
    if first > 1:
        vf.append(f"select=gte(n\\,{first - 1})")
    # Only matrix and range are converted; transfer and primaries stay as coded,
    # colour.py does those.
    vf.append(f"zscale=matrixin={_ZIMG_MATRIX[matrix]}:rangein={rng}:range=full:dither=none")
    vf.append("format=gbrpf32le")
    cmd = [ffmpeg, "-v", "error", "-nostdin", "-i", src.path, "-map", "0:v:0", "-an", "-sn",
           "-vf", ",".join(vf), "-fps_mode", "passthrough", "-frames:v", str(count),
           "-f", "rawvideo", "pipe:1"]
    w, h = src.width, src.height
    size = w * h * 3 * 4
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        for _ in range(count):
            buf = proc.stdout.read(size)
            if len(buf) < size:
                err = proc.stderr.read().decode("utf-8", "replace").strip()
                raise EngineError(f"ffmpeg stopped early decoding {src.path}: {err[-300:]}")
            g, b, r = np.frombuffer(buf, dtype=np.float32).reshape(3, h, w)  # planar G, B, R
            yield np.stack([r, g, b], axis=-1)
    finally:
        proc.stdout.close()
        proc.kill()
        proc.wait()
        proc.stderr.close()


def _dpx_frame(path: str, ffmpeg: str, w: int, h: int) -> np.ndarray:
    out = subprocess.run([ffmpeg, "-v", "error", "-nostdin", "-i", path, "-vf", "format=rgb48le",
                          "-frames:v", "1", "-f", "rawvideo", "pipe:1"],
                         capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if out.returncode != 0 or len(out.stdout) < w * h * 6:
        raise EngineError(f"could not decode {path}: {out.stderr.decode('utf-8', 'replace')[-300:]}")
    return np.frombuffer(out.stdout[:w * h * 6], dtype=np.uint16).reshape(h, w, 3)


def _sequence_frames(src: Source, frames: list[int], ffmpeg: str):
    """Yields float32 RGB code values (EXR: as stored) for each frame."""
    for f in frames:
        path = src.frame_path(f)
        if not os.path.isfile(path):
            raise EngineError(f"missing source frame {path}")
        if path.lower().endswith(".dpx"):
            yield _dpx_frame(path, ffmpeg, src.width, src.height)
        else:
            try:
                yield read_image(path)
            except RuntimeError as exc:
                raise EngineError(f"corrupt or unreadable frame: {path}") from exc


def prepare_plate(src: Source, job: dict, shot_dir: Path, ffmpeg: str,
                  progress=None, check_cancel=None) -> Plate:
    c = job.get("colour", {})
    space = c.get("space", "srgb_rec709")
    if space == "auto":
        space = colour.TRANSFER_GUESS.get(src.color_transfer, "srgb_rec709")
    f = job.get("frames", {})
    frames = select_frames(src, f.get("first"), f.get("last"), int(f.get("preview_frames") or 0))
    start = int(f.get("start_frame", 1001))
    plate_frames = ([start + (n - 1) for n in frames] if src.kind == "video" else list(frames))
    matrix, rng = decode_settings(src, space, c.get("matrix", "auto"), c.get("range", "auto"))
    fps = float(job.get("fps") or src.fps)
    fps_text = str(job["fps"]) if job.get("fps") else src.fps_text

    plate_dir = shot_dir / PLATE_DIR
    meta_path = shot_dir / "plate.json"
    key = _prep_key(src, {"colour": dict(c, space=space)}, frames, plate_frames, matrix, rng)
    pattern = str(plate_dir / PLATE_NAME)
    warnings = list(src.warnings)

    def plate_obj(reused):
        return Plate(str(plate_dir), pattern, plate_frames, src.width, src.height, fps,
                     fps_text, reused, frames, warnings)

    # The selected source *is* this shot's plate: nothing to do.
    if src.kind == "sequence" and Path(src.path).parent.resolve() == plate_dir.resolve():
        if space != "linear_rec709":
            raise EngineError("this is the shot's own linear plate: set colour space to "
                              "Linear Rec.709")
        return plate_obj(True)

    if meta_path.is_file() and plate_dir.is_dir():
        try:
            old = json.loads(meta_path.read_text(encoding="utf-8"))
        except ValueError:
            old = {}
        if old.get("prep_key") == key and all(
                os.path.isfile(pattern % n) for n in plate_frames):
            if progress:
                progress(1.0, "plate already prepared, reusing it")
            return plate_obj(True)

    if plate_dir.exists():
        shutil.rmtree(plate_dir)
    plate_dir.mkdir(parents=True)
    convert = colour.Converter(space, c.get("gamut", "clamp"), c.get("ocio_name"))

    if src.kind == "video":
        reader = _video_frames(src, frames, matrix, rng, ffmpeg)
    else:
        reader = _sequence_frames(src, frames, ffmpeg)

    total = len(frames)
    with ThreadPoolExecutor(max_workers=4) as pool:
        pending = []
        for i, raw in enumerate(reader):
            if check_cancel:
                check_cancel()
            code = raw.astype(np.float32) / 65535.0 if raw.dtype == np.uint16 else raw
            lin = convert(code)
            pending.append(pool.submit(write_exr, pattern % plate_frames[i], lin))
            if len(pending) > 8:
                pending.pop(0).result()
            if progress and (i % 4 == 0 or i == total - 1):
                progress((i + 1) / total, f"preparing plate {i + 1}/{total}")
        for fut in pending:
            fut.result()

    meta = {
        "prep_key": key,
        "source": src.path, "source_kind": src.kind,
        "source_frames": frames, "plate_frames": plate_frames,
        "width": src.width, "height": src.height, "fps": fps, "fps_text": fps_text,
        "colour_space": space, "matrix": matrix, "range": rng,
        "gamut": c.get("gamut", "clamp"), "ocio_name": c.get("ocio_name"),
        "source_probe": {k: v for k, v in asdict(src).items() if k != "frames"},
        "plate_pattern": pattern,
    }
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return plate_obj(False)

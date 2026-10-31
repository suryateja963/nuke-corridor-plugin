"""Hint preparation: what tells the model which subject to key.

first_frame -> <shot>/hint/hint_first.npy, 1 frame. The CK2 worker resizes it to
              the exact plate size (upstream rejects any other size), so a Roto
              rendered at HD by Nuke NC works on a 4K plate.
sequence    -> <shot>/hint/seq/hint_000000.png..., one 16-bit mask per plate frame,
              already at plate size.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import numpy as np

from .config import EngineError
from .imageio import read_image, resize, write_png16
from .probe import IMAGE_EXT, VIDEO_EXT, _scan_sequence, resolve_sequence


def to_mask(img: np.ndarray) -> np.ndarray:
    """RGBA/RGB/gray image -> float mask 0-1. Uses alpha when it carries the matte
    (a Roto renders white in alpha), else the RGB average."""
    if img.ndim == 2:
        mask = img
    elif img.shape[2] == 4 and float(img[..., 3].max()) - float(img[..., 3].min()) > 1e-4:
        mask = img[..., 3]
    else:
        mask = img[..., :3].mean(axis=2)
    return np.clip(mask, 0.0, 1.0).astype(np.float32)


def _video_masks(path: str, first: int, count: int, ffmpeg: str, ffprobe: str):
    """Grey frames of a matte video, 1-based `first`, as float masks."""
    probe = subprocess.run(
        [ffprobe, "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", path],
        capture_output=True, text=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        w, h = (int(v) for v in probe.stdout.strip().split(",")[:2])
    except ValueError as exc:
        raise EngineError(f"can't read matte video {path}") from exc
    # out_range=full: a limited-range matte video would otherwise top out at 0.92.
    vf = (f"select=gte(n\\,{first - 1})," if first > 1 else "") + "scale=out_range=full,format=gray16le"
    proc = subprocess.Popen([ffmpeg, "-v", "error", "-nostdin", "-i", path, "-vf", vf,
                             "-fps_mode", "passthrough", "-frames:v", str(count),
                             "-f", "rawvideo", "pipe:1"],
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        for _ in range(count):
            buf = proc.stdout.read(w * h * 2)
            if len(buf) < w * h * 2:
                raise EngineError(f"matte video {path} is shorter than the plate range")
            yield np.frombuffer(buf, dtype=np.uint16).reshape(h, w).astype(np.float32) / 65535.0
    finally:
        proc.stdout.close()
        proc.kill()
        proc.wait()


def _pick_frames(available: list[int], plate_frames: list[int], source_frames: list[int]) -> list[int]:
    """Which hint frames line up with the plate. Accepts hints numbered like the
    plate (rendered in Nuke on the plate), like the source, or exactly one per frame."""
    have = set(available)
    if all(f in have for f in plate_frames):
        return plate_frames
    if all(f in have for f in source_frames):
        return source_frames
    if len(available) == len(plate_frames):
        return available
    raise EngineError(
        f"hint sequence has {len(available)} frame(s) ({available[0]}-{available[-1]}) but the "
        f"plate needs {len(plate_frames)} ({plate_frames[0]}-{plate_frames[-1]}). Render the hint "
        "over the same frame range as the plate.")


# Share of a hint's white area that is open screen in the plate (SHOT-113's
# rough box: 0.79; careful rotos: 0.003-0.011; a careful roto around green
# clothes on green: 0.60, because the clothes look like screen).
SCREEN_WARN, SCREEN_LOWER = 0.3, 0.7
ROUGH_QUALITY = 0.75


def screen_share(hint: dict, plate) -> float | None:
    """Share of the first-frame hint (white > 0.5) that is screen-coloured in the
    first plate frame, or None if there is no hint or no clear screen."""
    if hint.get("hint_npy"):
        mask = np.load(hint["hint_npy"])[0]
    elif hint.get("hint_path"):
        files = sorted(Path(hint["hint_path"]).glob("hint_*.png"))
        if not files:
            return None
        mask = read_image(str(files[0]))[..., 0]
    else:
        return None
    rgb = np.power(np.clip(read_image(plate.pattern % plate.frames[0]), 0.0, 1.0), 1.0 / 2.2)
    m = resize(mask.astype(np.float32), rgb.shape[1], rgb.shape[0]) > 0.5
    if not m.any():
        return None
    border = np.concatenate([rgb[:8].reshape(-1, 3), rgb[-8:].reshape(-1, 3),
                             rgb[:, :8].reshape(-1, 3), rgb[:, -8:].reshape(-1, 3)])
    screen = np.median(border, axis=0)
    c = int(np.argmax(screen))
    if c == 0:
        return None
    others = [i for i in range(3) if i != c]
    screen_key = float(screen[c] - screen[others].max())
    if screen_key < 0.08:
        return None
    is_screen = (rgb[..., c] - rgb[..., others].max(axis=-1)) > 0.5 * screen_key
    return float((m & is_screen).sum() / m.sum())


def prepare_hint(job: dict, plate, shot_dir: Path, ffmpeg: str, ffprobe: str,
                 check_cancel=None) -> dict:
    """Returns the hint fields for the CK2 worker job ({} for no hint)."""
    h = job["hint"]
    mode = h["mode"]
    if mode == "none":
        return {}
    path = h["path"]
    out_dir = shot_dir / "hint"
    out_dir.mkdir(parents=True, exist_ok=True)
    is_video = os.path.isfile(path) and Path(path).suffix.lower() in VIDEO_EXT
    invert = bool(h.get("invert"))

    def finish(mask):
        return 1.0 - mask if invert else mask

    if mode == "first_frame":
        if is_video:
            mask = next(_video_masks(path, plate.source_frames[0], 1, ffmpeg, ffprobe))
        elif os.path.isfile(path) and not any(c in path for c in "#%"):
            mask = to_mask(read_image(path, keep_alpha=True))
        else:
            pattern = resolve_sequence(path)
            avail = _scan_sequence(pattern)
            if not avail:
                raise EngineError(f"no hint frames match {path}")
            pick = next((f for f in (plate.frames[0], plate.source_frames[0]) if f in avail), avail[0])
            mask = to_mask(read_image(pattern % pick, keep_alpha=True))
        mask = finish(mask)
        if float(mask.max()) < 0.01:
            raise EngineError("the first-frame hint is empty (all black). Check the Roto shape, "
                              "or the Invert option.")
        npy = out_dir / "hint_first.npy"
        np.save(str(npy), mask[None].astype(np.float32))
        return {"hint_npy": str(npy), "hint_mode": "first_frame"}

    # sequence
    seq_dir = out_dir / "seq"
    if seq_dir.exists():
        shutil.rmtree(seq_dir)
    seq_dir.mkdir(parents=True)
    n = len(plate.frames)
    if is_video:
        masks = _video_masks(path, plate.source_frames[0], n, ffmpeg, ffprobe)
    else:
        pattern = resolve_sequence(path)
        if Path(pattern % 0).suffix.lower() not in IMAGE_EXT:
            raise EngineError(f"unsupported hint file type: {path}")
        avail = _scan_sequence(pattern)
        if not avail:
            raise EngineError(f"no hint frames match {path}")
        picks = _pick_frames(avail, plate.frames, plate.source_frames)
        masks = (to_mask(read_image(pattern % f, keep_alpha=True)) for f in picks)
    for i, mask in enumerate(masks):
        if check_cancel:
            check_cancel()
        write_png16(str(seq_dir / f"hint_{i:06d}.png"),
                    resize(finish(mask), plate.width, plate.height))
    return {"hint_path": str(seq_dir)}

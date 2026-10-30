"""Auto-crop: key only the box around the subject, then paste the result back.

One box for the whole shot (stage 1's temporal windows need fixed geometry),
rounded out to multiples of 128 so upstream pads nothing. The model then sees the
subject at a higher effective resolution, and a smaller frame lets auto-VRAM pick
longer windows. Ported from the ComfyUI pack's ck2/crop.py (numpy + OpenCV here,
no torch, so it runs on linear EXR plates).

job["crop"]: {"mode": "off" | "auto" | "manual", "margin": 64, "box": [x, y, w, h]}
"auto" finds the subject against the green/blue screen on every 4th frame, unions
in the hint's box when there is one, and keys the full frame when it can't tell.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from .config import EngineError
from .imageio import read_image, resize, write_exr, write_png16  # sets the EXR switch before cv2

import cv2  # noqa: E402  (after imageio)

MODES = ("off", "auto", "manual")
QUANTUM = 128
FULL_FRAME_FRACTION = 0.85   # a box covering more than this of the frame isn't worth it
DOWNSCALE = 4                # detection runs at 1/4 resolution
FRAME_STEP = 4               # ...on every 4th frame


def _display(lin: np.ndarray) -> np.ndarray:
    """Linear plate -> roughly display-referred, where the screen thresholds were tuned."""
    return np.power(np.clip(lin, 0.0, 1.0), 1.0 / 2.2)


def _drop_small_blobs(mask: np.ndarray, min_fraction: float = 0.001) -> np.ndarray:
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    if n <= 1:
        return mask
    keep = stats[:, cv2.CC_STAT_AREA] >= max(1, int(min_fraction * mask.size))
    keep[0] = False
    return keep[labels]


def _drop_edge_strips(mask: np.ndarray, depth: int = 16, frac: float = 0.6,
                      slack: int = 8) -> np.ndarray:
    """Clear strips along the frame edges (a lit floor seam, the cyc's bottom edge)
    that would stretch the box to the full width. A subject crossing the edge stays:
    only columns with no subject just inside the band are cleared."""
    m = mask.copy()
    for k in range(4):
        v = np.rot90(m, k)  # view: the band examined is always v's last rows
        if v.shape[0] <= 2 * depth:
            continue
        band = v[-depth:]
        if band.mean(axis=1).max() <= frac:
            continue
        inside = v[-2 * depth:-depth].any(axis=0).astype(np.float32)
        support = np.convolve(inside, np.ones(2 * slack + 1), mode="same") > 0
        band[:, ~support] = False
    return m


def _bbox(mask: np.ndarray):
    """(x0, y0, x1, y1) with exclusive ends; None if empty."""
    ys, xs = np.nonzero(mask)
    if ys.size == 0:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def _union(a, b):
    if a is None:
        return b
    if b is None:
        return a
    return min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])


def box_from_frames(frames: list[np.ndarray], scale: int = DOWNSCALE):
    """Subject bbox from display-referred RGB frames that are 1/scale of full size.
    Returns (box in full-size pixels or None, how)."""
    sample = np.stack(frames).astype(np.float32)               # [t,h,w,3]
    border = np.concatenate([sample[:, :4].reshape(-1, 3), sample[:, -4:].reshape(-1, 3),
                             sample[:, :, :4].reshape(-1, 3), sample[:, :, -4:].reshape(-1, 3)])
    screen = np.median(border, axis=0)
    c = int(np.argmax(screen))
    if c == 0:
        return None, "screen isn't green or blue"
    others = [i for i in range(3) if i != c]
    screen_key = float(screen[c] - screen[others].max())
    if screen_key < 0.08:
        return None, "no clear screen colour at the frame border"
    kernel5 = np.ones((5, 5), np.uint8)
    kernel31 = np.ones((31, 31), np.uint8)
    box = None
    for f in sample:
        key = f[..., c] - f[..., others].max(axis=-1)
        # Solid subject: far below the screen's key. Thin hair: clearly below the
        # *local* screen level, which tolerates uneven screen lighting.
        local = cv2.dilate(key, kernel31)
        subject = (key < 0.5 * screen_key) | ((key < 0.8 * local) & (local > 0.5 * screen_key))
        subject = cv2.dilate(subject.astype(np.uint8), kernel5) > 0
        box = _union(box, _bbox(_drop_small_blobs(_drop_edge_strips(subject))))
    if box is None:
        return None, "no subject found against the screen"
    channel = "green" if c == 1 else "blue"
    return tuple(v * scale for v in box), f"auto ({channel} screen)"


def box_from_mask(mask: np.ndarray, threshold: float = 0.05):
    return _bbox(mask > threshold)


def _fit_axis(lo: int, hi: int, size: int, margin: int) -> tuple[int, int]:
    lo, hi = max(0, lo - margin), min(size, hi + margin)
    length = min(size, int(math.ceil((hi - lo) / QUANTUM)) * QUANTUM)
    start = (lo + hi - length) // 2
    start = min(max(0, start), size - length)
    return start, length


def finalize(box, width: int, height: int, margin: int):
    """Margin, round out to multiples of 128, shift into the frame -> (x, y, w, h)."""
    x0, y0, x1, y1 = box
    x, w = _fit_axis(x0, x1, width, margin)
    y, h = _fit_axis(y0, y1, height, margin)
    return x, y, w, h


def _hint_box(hint: dict, width: int, height: int):
    if hint.get("hint_npy"):
        mask = np.load(hint["hint_npy"])[0]
        return box_from_mask(resize(mask, width, height))
    if hint.get("hint_path"):
        box = None
        files = sorted(Path(hint["hint_path"]).glob("hint_*.png"))
        for f in files[::FRAME_STEP] + files[-1:]:
            box = _union(box, box_from_mask(read_image(str(f))[..., 0]))
        return box
    return None


def resolve(job: dict, plate, hint: dict):
    """Returns (crop (x, y, w, h) or None, message)."""
    c = job["crop"]
    W, H = plate.width, plate.height
    if c["mode"] == "off":
        return None, "crop off"
    if c["mode"] == "manual":
        x, y, w, h = (int(v) for v in c["box"])
        x, y = max(0, x), max(0, y)
        w, h = min(w, W - x), min(h, H - y)
        if w < 64 or h < 64:
            raise EngineError(f"crop box {c['box']} is outside the {W}x{H} plate or too small")
        return (x, y, w, h), f"manual: keying {w}x{h} at ({x},{y}) of {W}x{H}"

    frames = plate.frames
    idx = sorted(set(range(0, len(frames), FRAME_STEP)) | {len(frames) - 1})
    small = [cv2.resize(_display(read_image(plate.pattern % frames[i])),
                        (max(1, W // DOWNSCALE), max(1, H // DOWNSCALE)),
                        interpolation=cv2.INTER_AREA) for i in idx]
    box, how = box_from_frames(small)
    if box is None:
        return None, f"{how}; keying the full frame"
    hbox = _hint_box(hint, W, H)
    if hbox is not None:
        box, how = _union(box, hbox), how + " + hint"
    x, y, w, h = finalize(box, W, H, int(c["margin"]))
    if w * h > FULL_FRAME_FRACTION * W * H:
        return None, f"{how}: subject spans most of the frame; keying the full frame"
    return (x, y, w, h), f"{how}: keying {w}x{h} at ({x},{y}) of {W}x{H}"


def write_input(plate, crop, dest: Path, check_cancel=None) -> Path:
    """Cropped copies of the plate frames for the worker (frame_000000.exr ...)."""
    x, y, w, h = crop
    dest.mkdir(parents=True)
    for i, f in enumerate(plate.frames):
        if check_cancel:
            check_cancel()
        write_exr(str(dest / f"frame_{i:06d}.exr"), read_image(plate.pattern % f)[y:y + h, x:x + w])
    return dest


def crop_hint(hint: dict, crop, plate, work: Path) -> dict:
    """Hint fields for the worker, cut to the crop box (hints are plate-sized or
    get scaled to the plate first)."""
    x, y, w, h = crop
    if hint.get("hint_npy"):
        mask = resize(np.load(hint["hint_npy"])[0], plate.width, plate.height)
        npy = work / "hint_first_crop.npy"
        np.save(str(npy), np.ascontiguousarray(mask[y:y + h, x:x + w])[None].astype(np.float32))
        return {**hint, "hint_npy": str(npy)}
    if hint.get("hint_path"):
        dest = work / "hint_crop"
        dest.mkdir()
        for f in sorted(Path(hint["hint_path"]).glob("hint_*.png")):
            write_png16(str(dest / f.name), read_image(str(f))[y:y + h, x:x + w, 0])
        return {"hint_path": str(dest)}
    return hint


def paste_file(path: Path, crop, width: int, height: int) -> float:
    """Put a cropped EXR back into a zero full-size frame, in place. Returns the
    share of crop-border pixels (on sides that aren't the frame edge) above 0.5,
    so the caller can warn when the subject may have been cut off."""
    x, y, w, h = crop
    img = read_image(str(path))
    if img.shape[:2] != (h, w):
        raise EngineError(f"{path.name} is {img.shape[1]}x{img.shape[0]}, expected the crop {w}x{h}")
    a = img[..., 0]
    ring = []
    if y > 0:
        ring.append(a[:2].ravel())
    if y + h < height:
        ring.append(a[-2:].ravel())
    if x > 0:
        ring.append(a[:, :2].ravel())
    if x + w < width:
        ring.append(a[:, -2:].ravel())
    edge = float((np.concatenate(ring) > 0.5).mean()) if ring else 0.0
    full = np.zeros((height, width, 3), np.float32)
    full[y:y + h, x:x + w] = img
    write_exr(str(path), full)
    return edge

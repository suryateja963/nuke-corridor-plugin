"""Optional matte refinement on the keyed alpha, after the crop is pasted back.

Ported from the ComfyUI pack's ck2/matte.py (numpy + OpenCV here, one frame at a
time plus a small rolling window, so 4K shots don't need the clip in RAM).

job["refine"]: {"preset": "off" | "hairfur" | "solid", "grow": 0, ...overrides}
Steps run in this order, each skipped at its neutral value:
  clean     min_speck: drop isolated specks whose total alpha is below N pixels
            min_hole:  fill enclosed holes smaller than N pixels (never touches
                       regions connected to the frame border)
  levels    black / white / gamma remap (gamma > 1 lifts mid-greys)
  grow      move the edge out (+px) or in (-px), keeping its soft profile
  temporal  blend each frame toward a triangle-weighted average of t +- radius,
            only where the frames agree (|a - avg| < threshold): steadies
            flickering edges without ghosting moving hair
"""

from __future__ import annotations

import copy
import os

import numpy as np

from .imageio import read_image, write_exr

import cv2  # noqa: E402  (after imageio sets the EXR switch)

NEUTRAL = {"min_speck": 0, "min_hole": 0, "black": 0.0, "white": 1.0, "gamma": 1.0,
           "grow": 0, "temporal_radius": 0, "temporal_threshold": 0.1}
PRESETS = {
    "off": {},
    # Keeps every soft strand; only steadies edge flicker and drops stray specks.
    "hairfur": {"min_speck": 40, "temporal_radius": 1, "temporal_threshold": 0.08},
    # Hard-edged subjects (people in clothes, props): cleaner core, firmer edge.
    "solid": {"min_speck": 200, "min_hole": 400, "black": 0.02, "white": 0.95,
              "temporal_radius": 1, "temporal_threshold": 0.1},
}


def settings(job_refine: dict | None) -> dict:
    r = dict(job_refine or {})
    preset = r.pop("preset", "off")
    if preset not in PRESETS:
        raise ValueError(f"refine.preset must be one of {sorted(PRESETS)}, not {preset!r}")
    out = copy.deepcopy(NEUTRAL)
    out.update(PRESETS[preset])
    out.update({k: v for k, v in r.items() if k in NEUTRAL and v is not None})
    return out


def active(s: dict) -> bool:
    return any(s[k] != NEUTRAL[k] for k in NEUTRAL if k != "temporal_threshold")


def clean(a: np.ndarray, min_speck: int, min_hole: int) -> np.ndarray:
    a = a.copy()
    if min_speck > 0:
        n, labels = cv2.connectedComponents((a > 0.02).astype(np.uint8), connectivity=8)
        if n > 1:
            mass = np.bincount(labels.ravel(), weights=a.ravel(), minlength=n)
            small = mass < min_speck
            small[0] = False
            a[small[labels]] = 0.0
    if min_hole > 0:
        n, labels, stats, _ = cv2.connectedComponentsWithStats((a < 0.5).astype(np.uint8), connectivity=4)
        if n > 1:
            fill = stats[:, cv2.CC_STAT_AREA] < min_hole
            fill[0] = False
            border = np.unique(np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]]))
            fill[border] = False
            a[fill[labels]] = 1.0
    return a


def levels(a: np.ndarray, black: float, white: float, gamma: float) -> np.ndarray:
    a = np.clip((a - black) / max(white - black, 1e-6), 0.0, 1.0)
    return a if gamma == 1.0 else np.power(a, 1.0 / gamma)


def grow(a: np.ndarray, px: int) -> np.ndarray:
    if px == 0:
        return a
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * abs(px) + 1, 2 * abs(px) + 1))
    return cv2.dilate(a, k) if px > 0 else cv2.erode(a, k)


def spatial(a: np.ndarray, s: dict) -> np.ndarray:
    a = clean(a, int(s["min_speck"]), int(s["min_hole"]))
    a = levels(a, float(s["black"]), float(s["white"]), float(s["gamma"]))
    return np.clip(grow(a, int(s["grow"])), 0.0, 1.0).astype(np.float32)


def temporal(window: list[np.ndarray], centre: int, radius: int, threshold: float) -> np.ndarray:
    """window holds the frames centre-radius..centre+radius that exist (clamped)."""
    acc = np.zeros_like(window[centre])
    wsum = 0.0
    for i, f in enumerate(window):
        w = float(radius + 1 - abs(i - centre))
        acc += w * f
        wsum += w
    avg = acc / wsum
    a = window[centre]
    agree = np.clip(1.0 - np.abs(a - avg) / max(threshold, 1e-6), 0.0, 1.0)
    return (a + (avg - a) * agree).astype(np.float32)


def refine_sequence(paths: list[str], s: dict, check_cancel=None, progress=None) -> None:
    """Refines alpha EXRs in place. Spatial steps first, then temporal on the
    spatially refined frames (a rolling window of 2 * radius + 1 frames).
    Results go to <name>.refine.exr and replace the originals only at the end,
    so neighbours are always read unrefined and a cancel leaves the key intact."""
    r = int(s["temporal_radius"])
    n = len(paths)
    cache: dict[int, np.ndarray] = {}

    def get(i):
        if i not in cache:
            cache[i] = spatial(read_image(paths[i])[..., 0], s)
        return cache[i]

    tmp = [p[:-4] + ".refine.exr" for p in paths]
    try:
        for i in range(n):
            if check_cancel:
                check_cancel()
            if r > 0:
                lo, hi = max(0, i - r), min(n - 1, i + r)
                out = temporal([get(j) for j in range(lo, hi + 1)], i - lo, r, float(s["temporal_threshold"]))
            else:
                out = get(i)
            for j in [j for j in cache if j < i - r + 1]:
                del cache[j]
            write_exr(tmp[i], np.repeat(out[..., None], 3, axis=2))
            if progress and i % 8 == 0:
                progress((i + 1) / n)
        for t, p in zip(tmp, paths):
            os.replace(t, p)
    finally:
        for t in tmp:
            if os.path.exists(t):
                os.remove(t)

"""Spill removal on the model's fg (which upstream leaves un-despilled).

Average-limit method in linear light, the same family as upstream's own cutout
despill: green may not exceed the average of red and blue (blue screen: blue may
not exceed red/green).

mode "everywhere": `amount` blends every pixel from untouched (0) to fully limited (1).
mode "edges": per-pixel strength, `amount` is the maximum:
  - transparent edges get it: weight 2 * (1 - alpha), full below alpha 0.5;
  - screen bounce gets it: a pixel whose green excess is small next to its own
    brightness (ratio = spill / max(r, g, b) below 0.5) is a neutral or warm
    colour tinted by the screen, e.g. white fur lit by green, or shadowed screen
    the matte held as solid (rabbit leg gap, ratio ~0.46);
  - saturated screen-coloured objects keep their colour (fading out by 0.65),
    e.g. green clothing on a green screen.
  Measured on the hair/fur clips: fur bounce ratio p99 0.43-0.56, green outfit
  p50 0.78, which keeps 98% of its green (docs/quality_hairfur.md).
"""

from __future__ import annotations

import numpy as np

MODES = ("edges", "everywhere")
BOUNCE_LO, BOUNCE_HI = 0.5, 0.65


def _smoothstep(lo: float, hi: float, x: np.ndarray) -> np.ndarray:
    t = np.clip((x - lo) / (hi - lo), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def _channels(screen: str):
    if screen == "green":
        return 1, (0, 2)
    if screen == "blue":
        return 2, (0, 1)
    raise ValueError(f"screen must be green or blue, not {screen!r}")


def weight(rgb: np.ndarray, alpha: np.ndarray, screen: str = "green") -> np.ndarray:
    """Per-pixel despill strength 0-1 for mode "edges"."""
    c, (o1, o2) = _channels(screen)
    spill = np.maximum(rgb[..., c] - (rgb[..., o1] + rgb[..., o2]) * 0.5, 0.0)
    ratio = spill / np.maximum(rgb[..., :3].max(axis=-1), 1e-4)
    edge = np.clip(2.0 * (1.0 - alpha), 0.0, 1.0)
    bounce = 1.0 - _smoothstep(BOUNCE_LO, BOUNCE_HI, ratio)
    return np.maximum(edge, bounce).astype(np.float32)


def despill(rgb: np.ndarray, amount: float, screen: str = "green", *,
            alpha: np.ndarray | None = None, mode: str = "everywhere") -> np.ndarray:
    if amount <= 0.0:
        return rgb
    c, (o1, o2) = _channels(screen)
    if mode == "edges":
        if alpha is None:
            raise ValueError("despill mode 'edges' needs the alpha")
        strength = amount * weight(rgb, alpha, screen)
    elif mode == "everywhere":
        strength = amount
    else:
        raise ValueError(f"despill mode must be one of {MODES}, not {mode!r}")
    out = rgb.copy()
    spill = np.maximum(rgb[..., c] - (rgb[..., o1] + rgb[..., o2]) * 0.5, 0.0)
    out[..., c] = rgb[..., c] - strength * spill
    return out

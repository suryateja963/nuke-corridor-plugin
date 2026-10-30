"""Spill removal on the model's fg (which upstream leaves un-despilled).

Average-limit method in linear light, the same family as upstream's own cutout
despill: green may not exceed the average of red and blue (blue screen: blue may
not exceed red/green). `amount` blends from untouched (0) to fully limited (1).
"""

from __future__ import annotations

import numpy as np


def despill(rgb: np.ndarray, amount: float, screen: str = "green") -> np.ndarray:
    if amount <= 0.0:
        return rgb
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    out = rgb.copy()
    if screen == "green":
        spill = np.maximum(g - (r + b) * 0.5, 0.0)
        out[..., 1] = g - amount * spill
    elif screen == "blue":
        spill = np.maximum(b - (r + g) * 0.5, 0.0)
        out[..., 2] = b - amount * spill
    else:
        raise ValueError(f"screen must be green or blue, not {screen!r}")
    return out

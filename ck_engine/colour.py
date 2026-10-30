"""Source colour space -> scene-linear Rec.709 (sRGB primaries, D65).

CorridorKey 2.0 only understands display sRGB or scene-linear Rec.709. Every
source is converted here before keying. The curves are the camera makers'
published formulas; gamut matrices are derived from each gamut's published
primaries, so there is no hand-copied matrix to get wrong. OpenColorIO is used
only for the "ocio" space (any named space in an OCIO config), and only if
PyOpenColorIO is installed.

All functions take and return float32 arrays [..., 3] in RGB order.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# --- gamuts -------------------------------------------------------------------

D65 = (0.3127, 0.3290)
ACES_WHITE = (0.32168, 0.33767)

PRIMARIES = {
    "rec709": ((0.640, 0.330), (0.300, 0.600), (0.150, 0.060), D65),
    "rec2020": ((0.708, 0.292), (0.170, 0.797), (0.131, 0.046), D65),
    "sgamut3": ((0.730, 0.280), (0.140, 0.855), (0.100, -0.050), D65),
    "sgamut3cine": ((0.766, 0.275), (0.225, 0.800), (0.089, -0.087), D65),
    "vgamut": ((0.730, 0.280), (0.165, 0.840), (0.100, -0.030), D65),
    "ap1": ((0.713, 0.293), (0.165, 0.830), (0.128, 0.044), ACES_WHITE),
}

_BRADFORD = np.array([[0.8951, 0.2664, -0.1614],
                      [-0.7502, 1.7135, 0.0367],
                      [0.0389, -0.0685, 1.0296]])


def _xyz(xy) -> np.ndarray:
    x, y = xy
    return np.array([x / y, 1.0, (1.0 - x - y) / y])


def rgb_to_xyz(gamut: str) -> np.ndarray:
    r, g, b, w = PRIMARIES[gamut]
    m = np.stack([_xyz(r), _xyz(g), _xyz(b)], axis=1)
    s = np.linalg.solve(m, _xyz(w))
    return m * s


def _adapt(src_white, dst_white) -> np.ndarray:
    """Bradford chromatic adaptation matrix (XYZ -> XYZ)."""
    if src_white == dst_white:
        return np.eye(3)
    src = _BRADFORD @ _xyz(src_white)
    dst = _BRADFORD @ _xyz(dst_white)
    return np.linalg.inv(_BRADFORD) @ np.diag(dst / src) @ _BRADFORD


def gamut_matrix(src: str, dst: str = "rec709") -> np.ndarray:
    """3x3 matrix taking linear RGB in `src` primaries to linear RGB in `dst`."""
    adapt = _adapt(PRIMARIES[src][3], PRIMARIES[dst][3])
    return np.linalg.inv(rgb_to_xyz(dst)) @ adapt @ rgb_to_xyz(src)


def apply_matrix(rgb: np.ndarray, m: np.ndarray) -> np.ndarray:
    return np.einsum("...c,rc->...r", rgb, m.astype(np.float32), optimize=True)


# --- transfer functions (code value 0-1 -> scene linear) -----------------------

def srgb_to_linear(x: np.ndarray) -> np.ndarray:
    """IEC 61966-2-1, mirrored for negatives: the same maths as upstream
    corridorkey.color_utils.srgb_to_linear, so plates match the official CLI."""
    a = np.abs(x)
    lin = np.where(a <= 0.04045, a / 12.92, ((a + 0.055) / 1.055) ** 2.4)
    return np.sign(x) * lin


def slog3_to_linear(x: np.ndarray) -> np.ndarray:
    """Sony S-Log3 (Sony technical summary). x = 10-bit code value / 1023."""
    cv = x * 1023.0
    return np.where(cv >= 171.2102946929,
                    np.power(10.0, (cv - 420.0) / 261.5) * (0.18 + 0.01) - 0.01,
                    (cv - 95.0) * 0.01125000 / (171.2102946929 - 95.0))


def vlog_to_linear(x: np.ndarray) -> np.ndarray:
    """Panasonic V-Log (V-Log/V-Gamut reference manual). x = code value / 1023."""
    b, c, d = 0.00873, 0.241514, 0.598206
    return np.where(x < 0.181, (x - 0.125) / 5.6, np.power(10.0, (x - d) / c) - b)


_AL_R0, _AL_RT, _AL_C = -0.05641088, 0.01, 47.28711236
_AL_BETA, _AL_GAMMA, _AL_DELTA = 0.00964052, 0.08550479, 0.69336945
_AL_PT = _AL_C * (_AL_RT - _AL_R0) ** 2


def applelog_to_linear(x: np.ndarray) -> np.ndarray:
    """Apple Log (Apple Log profile white paper), inverse of its encoding curve."""
    log_part = np.power(2.0, (x - _AL_DELTA) / _AL_GAMMA) - _AL_BETA
    sqrt_part = np.sqrt(np.clip(x, 0.0, None) / _AL_C) + _AL_R0
    return np.where(x >= _AL_PT, log_part, np.where(x >= 0.0, sqrt_part, _AL_R0))


_HLG_A = 0.17883277
_HLG_B = 1.0 - 4.0 * _HLG_A
_HLG_C = 0.5 - _HLG_A * np.log(4.0 * _HLG_A)


def _hlg_inverse_oetf(x):
    x = np.clip(x, 0.0, None)
    return np.where(x <= 0.5, x * x / 3.0, (np.exp((x - _HLG_C) / _HLG_A) + _HLG_B) / 12.0)


# HLG reference white (75 % signal) is scaled to 1.0, which puts 18 % grey
# (about 38 % signal) at about 0.18, matching the other scene-linear spaces.
_HLG_SCALE = 1.0 / float(_hlg_inverse_oetf(np.float64(0.75)))


def hlg_to_linear(x: np.ndarray) -> np.ndarray:
    """BT.2100 HLG inverse OETF (scene light), reference white -> 1.0."""
    return _hlg_inverse_oetf(x) * _HLG_SCALE


def pq_to_linear(x: np.ndarray) -> np.ndarray:
    """SMPTE ST 2084 (PQ) to nits, then 203 nits (BT.2408 reference white) -> 1.0."""
    m1, m2 = 2610 / 16384, 2523 / 4096 * 128
    c1, c2, c3 = 3424 / 4096, 2413 / 4096 * 32, 2392 / 4096 * 32
    e = np.power(np.clip(x, 0.0, 1.0), 1.0 / m2)
    nits = 10000.0 * np.power(np.maximum(e - c1, 0.0) / (c2 - c3 * e), 1.0 / m1)
    return nits / 203.0


def identity(x: np.ndarray) -> np.ndarray:
    return x


# --- colour space registry -------------------------------------------------------

@dataclass(frozen=True)
class ColourSpace:
    key: str
    label: str
    curve: object          # code value -> linear
    gamut: str
    default_range: str     # "probe": trust the file's range flag; "full": raw code values
    tested: bool           # checked against real footage yet


# Camera log curves are defined on raw code values (S-Log3 black = 95/1023,
# V-Log black = 128/1023), so their default is "full": no legal->full expansion.
# Apple Log's range convention is not confirmed yet; it follows the file's flag.
SPACES = {s.key: s for s in (
    ColourSpace("srgb_rec709", "sRGB / Rec.709 video", srgb_to_linear, "rec709", "probe", True),
    ColourSpace("linear_rec709", "Linear Rec.709 (sRGB primaries)", identity, "rec709", "full", True),
    ColourSpace("acescg", "ACEScg (linear AP1)", identity, "ap1", "full", False),
    ColourSpace("slog3_sgamut3", "Sony S-Log3 / S-Gamut3", slog3_to_linear, "sgamut3", "full", False),
    ColourSpace("slog3_sgamut3cine", "Sony S-Log3 / S-Gamut3.Cine", slog3_to_linear, "sgamut3cine", "full", False),
    ColourSpace("vlog_vgamut", "Panasonic V-Log / V-Gamut", vlog_to_linear, "vgamut", "full", False),
    ColourSpace("applelog", "Apple Log (BT.2020)", applelog_to_linear, "rec2020", "probe", False),
    ColourSpace("hlg_rec2020", "HLG / BT.2020 (HDR phone video)", hlg_to_linear, "rec2020", "probe", False),
    ColourSpace("pq_rec2020", "PQ / BT.2020 (HDR10, Dolby Vision base)", pq_to_linear, "rec2020", "probe", False),
)}
OCIO_KEY = "ocio"  # any space by name from an OCIO config (needs PyOpenColorIO)

# Guess from ffprobe's color_transfer when the job says "auto".
TRANSFER_GUESS = {"arib-std-b67": "hlg_rec2020", "smpte2084": "pq_rec2020"}


class Converter:
    """Callable: code values [..., 3] -> scene-linear Rec.709 float32."""

    def __init__(self, space: str, gamut_policy: str = "clamp", ocio_name: str | None = None):
        if gamut_policy not in ("clamp", "keep"):
            raise ValueError(f"gamut policy must be 'clamp' or 'keep', not {gamut_policy!r}")
        self.gamut_policy = gamut_policy
        self._ocio = None
        if space == OCIO_KEY:
            self._ocio = _ocio_processor(ocio_name)
            self.space = None
            self._m = None
        else:
            if space not in SPACES:
                raise ValueError(f"unknown colour space {space!r}; choose one of "
                                 f"{', '.join(SPACES)} or {OCIO_KEY!r}")
            self.space = SPACES[space]
            g = self.space.gamut
            self._m = None if g == "rec709" else gamut_matrix(g)

    def __call__(self, rgb: np.ndarray) -> np.ndarray:
        if self._ocio is not None:
            out = np.ascontiguousarray(rgb, dtype=np.float32).copy()
            self._ocio.applyRGB(out)
        else:
            out = self.space.curve(rgb.astype(np.float32, copy=False)).astype(np.float32)
            if self._m is not None:
                out = apply_matrix(out, self._m)
        if self.gamut_policy == "clamp":
            # Out-of-gamut colours land below zero in Rec.709; the model was
            # trained on display-range data, so negatives are cut by default.
            np.maximum(out, 0.0, out=out)
        return out


def _ocio_processor(name: str | None):
    if not name:
        raise ValueError("colour space 'ocio' needs ocio_name (a colour space name in the config)")
    try:
        import PyOpenColorIO as ocio
    except ImportError as exc:
        raise RuntimeError("colour space 'ocio' needs PyOpenColorIO: pip install opencolorio "
                           "in the CorridorKey venv") from exc
    import os
    config = (ocio.Config.CreateFromEnv() if os.environ.get("OCIO")
              else ocio.Config.CreateFromFile("ocio://studio-config-latest"))
    dst = next((n for n in ("Linear Rec.709 (sRGB)", "lin_rec709", "linear")
                if config.getColorSpace(n) is not None), None)
    if dst is None:
        raise RuntimeError("OCIO config has no Linear Rec.709 colour space")
    return config.getProcessor(name, dst).getDefaultCPUProcessor()

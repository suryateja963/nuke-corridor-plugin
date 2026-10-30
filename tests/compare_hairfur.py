r"""Before/after close-ups of two hair_fur_batch runs, same edge region in both.

    D:\CorridorKey2\venv\Scripts\python.exe tests\compare_hairfur.py hairfur hairfur_crop

Writes _e2e_out\compare_<a>_vs_<b>.png: one row per clip, alpha and comp-on-dark
close-ups plus the whole frame on neutral grey (shows green tint) of run A then run B, plus the metric table in compare_<a>_vs_<b>.md.
"""

import json
import os
import sys
from pathlib import Path

os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from ck_engine.imageio import read_image  # noqa: E402
from hair_fur_batch import DARK, busiest_edge, label, to8  # noqa: E402

GREY = np.array([0.18, 0.18, 0.18], np.float32)

E2E = REPO / "_e2e_out"


def latest_key(run: str, clip: str):
    st = json.loads((E2E / run / "shots" / clip / "status.json").read_text())
    p, out = st["plate"], st["outputs"]
    mid = (p["first"] + p["last"] + 1) // 2
    frame = lambda pat: read_image(pat.replace("####", f"{mid:04d}"))  # noqa: E731
    return frame(out["alpha"])[..., 0], frame(out["fg_despill"])


def static_flicker(run: str, clip: str) -> float:
    """Mean |alpha(t) - alpha(t-1)| on soft-edge pixels where the plate itself
    barely changed (max |plate(t) - plate(t-1)| < 0.01): flicker, not motion."""
    st = json.loads((E2E / run / "shots" / clip / "status.json").read_text())
    p, out = st["plate"], st["outputs"]
    vals, prev = [], None
    for f in range(p["first"], p["last"] + 1):
        a = read_image(out["alpha"].replace("####", f"{f:04d}"))[..., 0]
        pl = read_image(p["pattern"].replace("####", f"{f:04d}"))
        if prev is not None:
            m = (a > 0.05) & (a < 0.95) & (np.abs(pl - prev[1]).max(-1) < 0.01)
            if m.any():
                vals.append(float(np.abs(a - prev[0])[m].mean()))
        prev = (a, pl)
    return round(float(np.mean(vals)), 4) if vals else float("nan")


def main():
    a_run, b_run = sys.argv[1:3]
    ma = json.loads((E2E / a_run / "metrics.json").read_text())
    mb = json.loads((E2E / b_run / "metrics.json").read_text())
    rows = []
    lines = [f"| clip | soft edge % ({a_run} -> {b_run}) | flicker | static flicker | spill | s | crop box |",
             "|---|---|---|---|---|---|---|"]
    for clip in ma:
        if clip not in mb or "error" in ma[clip] or "error" in mb[clip]:
            continue
        a1, f1 = latest_key(a_run, clip)
        a2, f2 = latest_key(b_run, clip)
        size = min(270, a1.shape[0] // 3)
        x, y = busiest_edge(a1, size)
        tiles = []
        for tag, a, fg in ((a_run, a1, f1), (b_run, a2, f2)):
            a3 = a[..., None]
            dark = fg * a3 + DARK * (1 - a3)
            for name, img in (("alpha", np.repeat(a3, 3, 2)), ("comp", dark)):
                t = cv2.resize(to8(img[y:y + size, x:x + size]), (360, 360), interpolation=cv2.INTER_NEAREST)
                tiles.append(label(t, f"{clip} {tag} {name}"))
            grey = fg * a3 + GREY * (1 - a3)
            tiles.append(label(cv2.resize(to8(grey), (640, 360), interpolation=cv2.INTER_AREA), f"{tag} on grey"))
        rows.append(np.hstack(tiles))
        A, B = ma[clip], mb[clip]
        lines.append(f"| {clip} | {A['soft_edge_pct']} -> {B['soft_edge_pct']} | {A['flicker']} -> {B['flicker']} "
                     f"| {static_flicker(a_run, clip)} -> {static_flicker(b_run, clip)} | {A['spill']} -> {B['spill']} | {A['seconds']} -> {B['seconds']} | {B.get('crop')} |")
    name = f"compare_{a_run}_vs_{b_run}"
    cv2.imwrite(str(E2E / f"{name}.png"), np.vstack(rows))
    (E2E / f"{name}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()

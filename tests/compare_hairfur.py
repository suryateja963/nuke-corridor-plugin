r"""Before/after close-ups of two hair_fur_batch runs, same edge region in both.

    D:\CorridorKey2\venv\Scripts\python.exe tests\compare_hairfur.py hairfur hairfur_crop

Writes _e2e_out\compare_<a>_vs_<b>.png: one row per clip, alpha and comp-on-dark
close-ups of run A then run B, plus the metric table in compare_<a>_vs_<b>.md.
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

E2E = REPO / "_e2e_out"


def latest_key(run: str, clip: str):
    st = json.loads((E2E / run / "shots" / clip / "status.json").read_text())
    p, out = st["plate"], st["outputs"]
    mid = (p["first"] + p["last"] + 1) // 2
    frame = lambda pat: read_image(pat.replace("####", f"{mid:04d}"))  # noqa: E731
    return frame(out["alpha"])[..., 0], frame(out["fg_despill"])


def main():
    a_run, b_run = sys.argv[1:3]
    ma = json.loads((E2E / a_run / "metrics.json").read_text())
    mb = json.loads((E2E / b_run / "metrics.json").read_text())
    rows = []
    lines = [f"| clip | soft edge % ({a_run} -> {b_run}) | flicker | spill | s | crop box |",
             "|---|---|---|---|---|---|"]
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
        rows.append(np.hstack(tiles))
        A, B = ma[clip], mb[clip]
        lines.append(f"| {clip} | {A['soft_edge_pct']} -> {B['soft_edge_pct']} | {A['flicker']} -> {B['flicker']} "
                     f"| {A['spill']} -> {B['spill']} | {A['seconds']} -> {B['seconds']} | {B.get('crop')} |")
    name = f"compare_{a_run}_vs_{b_run}"
    cv2.imwrite(str(E2E / f"{name}.png"), np.vstack(rows))
    (E2E / f"{name}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()

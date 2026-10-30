r"""Hair and fur quality batch: key real clips, build review sheets and edge metrics.

    D:\CorridorKey2\venv\Scripts\python.exe tests\hair_fur_batch.py [--frames 16] [--first 31] [--only cat,manhair]
        [--crop auto] [--despill edges] [--out hairfur_crop]

For every clip in D:\CorridorKey2\test_clips\{hair,animals}\raw it runs the
engine (same as the Nuke panel), then writes to _e2e_out\<--out>\ (default hairfur):
  <clip>_sheet.png   plate | alpha | comp on dark | comp on bright, plus a 2x close-up
                     of the busiest soft edge (alpha, comp)
  overview.png       one row per clip
  metrics.json/.md   per clip: soft-edge share, edge flicker, leftover spill, timing

Metrics (computed only where the key matters, the soft edge 0.05 < alpha < 0.95):
  soft_edge_pct  share of the frame that is soft edge (more = more hair detail kept)
  flicker        mean |alpha(t) - alpha(t-1)| on edge pixels (lower = steadier)
  spill          mean max(g - (r+b)/2, 0) of despilled fg on edge pixels (lower = cleaner)
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from ck_engine.imageio import read_image  # noqa: E402

CLIPS = Path(r"D:\CorridorKey2\test_clips")
OUT = REPO / "_e2e_out" / "hairfur"
DARK = np.array([0.02, 0.03, 0.08], np.float32)
BRIGHT = np.array([0.85, 0.80, 0.70], np.float32)


def to8(x):
    x = np.clip(x, 0, 1)
    x = np.where(x <= 0.0031308, x * 12.92, 1.055 * np.power(x, 1 / 2.4) - 0.055)
    return (x * 255 + 0.5).astype(np.uint8)[..., ::-1]


def label(img, text):
    cv2.rectangle(img, (0, 0), (img.shape[1], 26), (0, 0, 0), -1)
    cv2.putText(img, text, (6, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
    return img


DESPILL = {"amount": 0.5}  # --despill edges -> {"amount": 1.0, "mode": "edges"}


def key_clip(clip: Path, first: int, frames: int, crop: str):
    shot = OUT / "shots" / clip.stem
    shot.mkdir(parents=True, exist_ok=True)
    job = {"schema_version": 1, "source": {"path": str(clip)}, "colour": {"space": "srgb_rec709"},
           "frames": {"first": first, "last": first + frames - 1}, "despill": DESPILL, "crop": {"mode": crop}}
    (shot / "job.json").write_text(json.dumps(job, indent=2))
    t = time.time()
    r = subprocess.run([sys.executable, "-m", "ck_engine.run", str(shot / "job.json")], cwd=REPO,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    status = json.loads((shot / "status.json").read_text())
    status["seconds"] = round(time.time() - t)
    if r.returncode != 0:
        status.setdefault("error", r.stdout[-500:])
    return status


def busiest_edge(alpha, size):
    """Top-left of the size x size window with the most soft-edge pixels."""
    soft = ((alpha > 0.05) & (alpha < 0.95)).astype(np.float32)
    k = cv2.boxFilter(soft, -1, (size, size), normalize=False, borderType=cv2.BORDER_CONSTANT)
    h, w = alpha.shape
    half = size // 2
    k[:half, :] = k[h - half:, :] = 0
    k[:, :half] = k[:, w - half:] = 0
    y, x = np.unravel_index(np.argmax(k), k.shape)
    return max(0, x - half), max(0, y - half)


def review(clip, status):
    p, out = status["plate"], status["outputs"]
    frames = list(range(p["first"], p["last"] + 1))
    mid = frames[len(frames) // 2]
    plate = read_image(p["pattern"].replace("####", f"{mid:04d}"))
    alphas = [read_image(out["alpha"].replace("####", f"{f:04d}"))[..., 0] for f in frames]
    a = alphas[len(frames) // 2]
    fg = read_image(out["fg_despill"].replace("####", f"{mid:04d}"))
    soft = (a > 0.05) & (a < 0.95)
    flick = [float(np.abs(alphas[i] - alphas[i - 1])[soft].mean()) for i in range(1, len(alphas)) if soft.any()]
    spill = np.maximum(fg[..., 1] - (fg[..., 0] + fg[..., 2]) * 0.5, 0)
    metrics = {
        "soft_edge_pct": round(100 * float(soft.mean()), 2),
        "flicker": round(float(np.mean(flick)), 4) if flick else None,
        "spill": round(float(spill[soft].mean()), 4) if soft.any() else None,
        "alpha_mean": round(float(a.mean()), 3),
        "seconds": status["seconds"],
        "frames": len(frames),
        "auto_vram": (status.get("auto_vram") or "").replace("Auto VRAM: ", ""),
        "crop": status.get("crop"),
    }

    a3 = a[..., None]
    dark = fg * a3 + DARK * (1 - a3)
    bright = fg * a3 + BRIGHT * (1 - a3)
    tw, th = 480, 270
    tiles = [label(cv2.resize(to8(plate), (tw, th), interpolation=cv2.INTER_AREA), f"{clip.stem}: plate"),
             label(cv2.resize(to8(np.repeat(a3, 3, 2)), (tw, th), interpolation=cv2.INTER_AREA), "alpha"),
             label(cv2.resize(to8(dark), (tw, th), interpolation=cv2.INTER_AREA), "comp on dark"),
             label(cv2.resize(to8(bright), (tw, th), interpolation=cv2.INTER_AREA), "comp on bright")]
    size = min(270, a.shape[0] // 3)
    x, y = busiest_edge(a, size)
    zoom = lambda img: cv2.resize(img[y:y + size, x:x + size], (480, 480), interpolation=cv2.INTER_NEAREST)  # noqa: E731
    z1 = label(zoom(to8(np.repeat(a3, 3, 2))), f"edge close-up alpha (x{480 / size:.1f})")
    z2 = label(zoom(to8(dark)), "edge close-up comp on dark")
    z3 = label(zoom(to8(bright)), "edge close-up comp on bright")
    top = np.hstack([np.vstack(tiles[:2]), np.vstack(tiles[2:])])          # 960 x 540
    bottom = np.hstack([z1, z2, z3])                                         # 1440 x 480
    top = cv2.copyMakeBorder(top, 0, 0, 0, 1440 - top.shape[1], cv2.BORDER_CONSTANT)
    cv2.putText(top, "soft edge {soft_edge_pct}%  flicker {flicker}  spill {spill}".format(**metrics),
                (975, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)
    cv2.rectangle(top, (x * tw // a.shape[1] + tw, y * th // a.shape[0]),
                  ((x + size) * tw // a.shape[1] + tw, (y + size) * th // a.shape[0]), (0, 200, 255), 1)
    sheet = np.vstack([top, bottom])
    cv2.imwrite(str(OUT / f"{clip.stem}_sheet.png"), sheet)
    row = np.hstack([tiles[0], tiles[1], tiles[2], cv2.resize(z2, (th, th))])
    return metrics, row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", type=int, default=16)
    ap.add_argument("--first", type=int, default=31)
    ap.add_argument("--only", default="")
    ap.add_argument("--crop", default="off", choices=["off", "auto"])
    ap.add_argument("--out", default="hairfur")
    ap.add_argument("--despill", default="everywhere", choices=["everywhere", "edges"])
    args = ap.parse_args()
    global OUT, DESPILL
    if args.despill == "edges":
        DESPILL = {"amount": 1.0, "mode": "edges"}
    OUT = REPO / "_e2e_out" / args.out
    OUT.mkdir(parents=True, exist_ok=True)
    clips = sorted((CLIPS / "hair" / "raw").glob("*.mp4")) + sorted((CLIPS / "animals" / "raw").glob("*.mp4"))
    if args.only:
        want = set(args.only.split(","))
        clips = [c for c in clips if c.stem in want]
    results, rows = {}, []
    for clip in clips:
        print(f"keying {clip.stem} ...", flush=True)
        st = key_clip(clip, args.first, args.frames, args.crop)
        if st.get("state") != "done":
            results[clip.stem] = {"error": st.get("error")}
            print(f"  FAILED: {st.get('error')}", flush=True)
            continue
        m, row = review(clip, st)
        results[clip.stem] = m
        rows.append(row)
        print("  {}s  soft edge {}%  flicker {}  spill {}".format(
            m["seconds"], m["soft_edge_pct"], m["flicker"], m["spill"]), flush=True)
        (OUT / "metrics.json").write_text(json.dumps(results, indent=2))
    if rows:
        width = max(r.shape[1] for r in rows)
        rows = [cv2.copyMakeBorder(r, 0, 0, 0, width - r.shape[1], cv2.BORDER_CONSTANT) for r in rows]
        cv2.imwrite(str(OUT / "overview.png"), np.vstack(rows))
    lines = ["| clip | soft edge % | flicker | spill | s | crop | window |", "|---|---|---|---|---|---|---|"]
    for k, m in results.items():
        if "error" in m:
            lines.append(f"| {k} | failed | | | | | {m['error']} |")
        else:
            lines.append(f"| {k} | {m['soft_edge_pct']} | {m['flicker']} | {m['spill']} | {m['seconds']} | {m.get('crop')} | {m['auto_vram']} |")
    (OUT / "metrics.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()

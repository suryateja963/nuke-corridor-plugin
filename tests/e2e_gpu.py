"""End-to-end GPU test: real CorridorKey keys through the command-line engine.

    D:\\CorridorKey2\\venv\\Scripts\\python.exe tests\\e2e_gpu.py [clip.mp4]

1. preview key (6 frames) with despill, no hint
2. full key of 12 frames into v001 with a first-frame hint (made from run 1's alpha)
3. cancel during a key: status 'cancelled', lock and temp files gone
Outputs go to _e2e_out\\ (not in git).
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from ck_engine.imageio import read_image  # noqa: E402

PY = sys.executable
CLIP = sys.argv[1] if len(sys.argv) > 1 else r"D:\CorridorKey2\test_clips\raw\pail.mp4"
OUT = REPO / "_e2e_out"


def write_job(shot: Path, **extra) -> Path:
    shot.mkdir(parents=True, exist_ok=True)
    job = {"schema_version": 1, "source": {"path": CLIP},
           "colour": {"space": "srgb_rec709"}, **extra}
    p = shot / "job.json"
    p.write_text(json.dumps(job, indent=2))
    return p


def run(job: Path):
    t = time.time()
    r = subprocess.run([PY, "-m", "ck_engine.run", str(job)], cwd=REPO,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    status = json.loads((job.parent / "status.json").read_text())
    return r.returncode, status, time.time() - t, r.stdout


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        raise SystemExit(1)


def main():
    shot = OUT / "pail"
    print(f"clip: {CLIP}")

    print("1. preview, 6 frames, despill 0.5")
    job = write_job(shot, frames={"preview_frames": 6}, despill={"amount": 0.5})
    rc, st, secs, out = run(job)
    print(f"   {secs:.0f}s  {st.get('auto_vram', '')}")
    if rc != 0:
        print(out[-3000:])
    check(rc == 0 and st["state"] == "done", f"finished ({st.get('error')})")
    check(st["version"] == "preview", "went to key/preview")
    alpha = Path(st["outputs"]["alpha"].replace("####", "1001"))
    check(alpha.is_file(), f"renamed to plate numbers: {alpha.name}")
    a = read_image(str(alpha))
    check(0.0 <= a.min() and a.max() <= 1.0 and a.max() > 0.5, f"alpha range {a.min():.3f}-{a.max():.3f}")
    fg = read_image(st["outputs"]["fg"].replace("####", "1001"))
    fd = read_image(st["outputs"]["fg_despill"].replace("####", "1001"))
    check(fd[..., 1].mean() <= fg[..., 1].mean(), "despill lowered green")
    n = len(os.listdir(Path(st["outputs"]["alpha"]).parent))
    check(n == 6, f"{n} alpha frames")
    check("PROGRESS" in out, "progress lines printed")
    check(not (shot / ".running").exists() and not any((shot / "work").glob("*")), "lock and temp cleaned")
    print(f"   seconds/frame incl. model load: {secs / 6:.1f}")

    print("2. 12 frames into v001, first-frame hint from run 1's alpha")
    job = write_job(shot, frames={"first": 1, "last": 12},
                    hint={"mode": "first_frame", "path": str(alpha), "quality": 0.9})
    rc, st, secs, out = run(job)
    print(f"   {secs:.0f}s  {st.get('auto_vram', '')}")
    if rc != 0:
        print(out[-3000:])
    check(rc == 0 and st["state"] == "done", f"finished ({st.get('error')})")
    check(st["version"] == "v001", f"version {st['version']}")
    check(st["plate"]["first"] == 1001 and st["plate"]["last"] == 1012, "plate 1001-1012")
    a2 = read_image(st["outputs"]["alpha"].replace("####", "1001"))
    diff = float(abs(a2[..., 0] - a[..., 0]).mean())
    check(diff < 0.05, f"hinted key agrees with unhinted key (mean diff {diff:.4f})")
    print(f"   seconds/frame incl. model load: {secs / 12:.1f}")

    print("3. cancel after 60 s (during keying)")
    job = write_job(shot, frames={"first": 1, "last": 60})
    p = subprocess.Popen([PY, "-m", "ck_engine.run", str(job)], cwd=REPO,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(60)
    (shot / "CANCEL").touch()
    t = time.time()
    p.wait(timeout=120)
    st = json.loads((shot / "status.json").read_text())
    check(st["state"] == "cancelled", f"state {st['state']} after {time.time() - t:.0f}s")
    check(not (shot / ".running").exists() and not any((shot / "work").glob("*")), "lock and temp cleaned")
    check(not (shot / "key" / "v002").exists(), "no half-written v002 left behind")
    print("ALL PASSED")


if __name__ == "__main__":
    main()

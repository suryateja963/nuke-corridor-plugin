r"""Automatic real-Nuke test of auto-crop, edge-aware despill and matte refine, on hair/fur clips.

    powershell -ExecutionPolicy Bypass -File tests\run_nuke_auto.ps1 -Module nuke_crop_despill_test -ReportName nuke_crop_despill_report.txt

Keys rabbit.mp4 (white fur with green bounce) and greenoutfit.mp4 (green clothes
on green) through the panel with its defaults, then checks: the panel defaults
are crop auto / despill 1.0 edges; the job sent crop + edges; the crop box was
used and pasted back to the full plate size; the comp in Nuke is full size with
alpha on the subject and none in the corner; and, measured on the EXRs the key
wrote, that the rabbit's bright fur lost its green while the outfit kept it.
Comps are rendered to _g2_out\nuke_comp_<clip>.png.
"""

import json
import os
import subprocess
import traceback

import nuke

import nuke_auto_test as base
from nuke_auto_test import OUT, check, rec

base.REPORT = os.path.join(OUT, "nuke_crop_despill_report.txt")
CLIPS = r"D:\CorridorKey2\test_clips"
SHOTS = base.SHOTS
QUEUE = [("rabbit", CLIPS + r"\animals\raw\rabbit.mp4"),
         ("greenoutfit", CLIPS + r"\hair\raw\greenoutfit.mp4")]

# Run on the key's own EXRs in the engine python (Nuke's python has no numpy).
MEASURE = r"""
import json, os, sys
os.environ["OPENCV_IO_ENABLE_OPENEXR"] = "1"
sys.path.insert(0, r"D:\nuke plugin")
import numpy as np
from ck_engine.imageio import read_image
st = json.load(open(sys.argv[1]))
o, p = st["outputs"], st["plate"]
f = (p["first"] + p["last"] + 1) // 2
a = read_image(o["alpha"].replace("####", "%04d" % f))[..., 0]
fg = read_image(o["fg"].replace("####", "%04d" % f))
ds = read_image(o["fg_despill"].replace("####", "%04d" % f))
spill = lambda x: np.maximum(x[..., 1] - (x[..., 0] + x[..., 2]) / 2, 0)
ratio = spill(fg) / np.maximum(fg.max(-1), 1e-4)
solid = a > 0.95
bright = solid & (fg.max(-1) > 0.3) & (ratio < 0.45) & (spill(fg) > 0.01)
cloth = solid & (ratio > 0.65)
print(json.dumps({"shape": list(a.shape),
                  "bounce_px": int(bright.sum()),
                  "bounce_spill_before": float(spill(fg)[bright].mean()) if bright.any() else None,
                  "bounce_spill_after": float(spill(ds)[bright].mean()) if bright.any() else None,
                  "cloth_px": int(cloth.sum()),
                  "cloth_green_kept": float((ds[..., 1][cloth] / np.maximum(fg[..., 1][cloth], 1e-4)).mean()) if cloth.any() else None}))
"""


def c_defaults():
    from ck2nuke import panel
    p = panel.KeyPanel(None, None, False)
    got = (p.k["crop"].value(), int(p.k["crop_margin"].value()), float(p.k["despill"].value()),
           p.k["despill_mode"].value(), p.k["refine"].value(), int(p.k["refine_grow"].value()))
    ok = got == ("auto", 64, 1.0, "edges + bounce", "hair/fur", 0)
    return ("PASS" if ok else "FAIL"), "crop {} margin {}, despill {} {}, refine {} grow {}".format(*got)


def _measure(status_path):
    from ck2nuke import runner, settings
    out = subprocess.run([settings()["engine_python"], "-c", MEASURE, status_path], capture_output=True,
                         text=True, timeout=300, env=runner._clean_env(), creationflags=runner.CREATE_NO_WINDOW)
    if out.returncode != 0:
        raise RuntimeError(out.stderr[-400:])
    return json.loads(out.stdout.strip().splitlines()[-1])


def _check(clip, status):
    from ck2nuke import nc
    label = "Key {}: panel defaults (crop auto, despill edges)".format(clip)
    if status.get("state") != "done":
        rec(label, "FAIL", "{}: {}".format(status.get("state"), status.get("error")))
        return
    shot = os.path.join(SHOTS, clip)
    job = json.load(open(os.path.join(shot, "job.json")))
    p, crop = status["plate"], status.get("crop")
    W, H = p["width"], p["height"]
    tag = "CK2_{}_{}".format(clip, status.get("version"))
    names = {k: tag + "_" + k for k in ("alpha", "fg", "premult", "over")}
    missing = [n for n in names.values() if not nc.exists(n)]
    job_ok = job["crop"]["mode"] == "auto" and job["despill"] == {"amount": 1.0, "screen": "green", "mode": "edges"}         and job["refine"] == {"preset": "hairfur", "grow": 0} and "refine: hairfur" in open(
            os.path.join(shot, "log.txt"), encoding="utf-8").read()
    # A subject filling most of the frame (greenoutfit) correctly keys the full frame.
    log = open(os.path.join(shot, "log.txt"), encoding="utf-8").read()
    how = next((l[6:] for l in log.splitlines()[::-1] if l.startswith("crop: ")), "?")
    crop_ok = bool(crop) or "keying the full frame" in how
    rec(label, "PASS" if job_ok and crop_ok and not missing else "FAIL",
        "{} {}x{}; job crop={} despill={} refine={}; crop: {}; {}".format(
            status.get("version"), W, H, job["crop"]["mode"], job["despill"], job["refine"], how,
            "comp nodes ok" if not missing else "missing " + str(missing)))
    if missing:
        return

    def comp():
        aw, ah = nc.size(names["alpha"])
        premult = nuke.toNode(names["premult"])  # 1 of NC's 10 Node objects
        nuke.frame(p["first"] + len(range(p["first"], p["last"] + 1)) // 2)
        x, y, w, h = crop or (0, 0, W, H)
        inside = max(nuke.sample(premult, "rgba.alpha", x + w * i / 6.0, H - (y + h * j / 6.0))
                     for i in range(1, 6) for j in range(1, 6))
        corner = nuke.sample(premult, "rgba.alpha", 5, 5)
        ok = (aw, ah) == (W, H) and inside > 0.9 and corner < 0.05
        return ("PASS" if ok else "FAIL"), "alpha Read {}x{} (plate {}x{}); alpha subject={:.3f} corner={:.3f}".format(
            aw, ah, W, H, inside, corner)
    check("  {}: crop pasted back full size in Nuke".format(clip), comp)

    def despill():
        m = _measure(os.path.join(shot, "status.json"))
        if clip == "rabbit":
            b0, b1 = m["bounce_spill_before"], m["bounce_spill_after"]
            ok = m["bounce_px"] > 1000 and b1 < 0.25 * b0
            return ("PASS" if ok else "FAIL"), "green bounce on fur: {:.4f} -> {:.4f} over {} px".format(
                b0, b1, m["bounce_px"])
        kept = m["cloth_green_kept"]
        ok = m["cloth_px"] > 10000 and kept > 0.95
        return ("PASS" if ok else "FAIL"), "green clothing keeps {:.1%} of its green over {} px".format(kept, m["cloth_px"])
    check("  {}: edge despill".format(clip), despill)
    check("  {}: render comp in Nuke".format(clip),
          lambda: base._render_comp(names["over"], "nuke_comp_{}.png".format(clip)))


def _next(i):
    if i >= len(QUEUE):
        return base.finish()
    clip, path = QUEUE[i]
    from ck2nuke import nc

    @base._guarded
    def done(status):
        _check(clip, status)
        _next(i + 1)
    done.__name__ = "key_" + clip
    nc.deselect_all()
    base._key({"src_mode": "File on disk", "src_file": path, "shot_name": clip, "shot_root": SHOTS,
               "preview": True, "preview_frames": 16}, done)


def run():
    os.makedirs(OUT, exist_ok=True)
    rec("start", "INFO", "crop + despill test running in Nuke")
    for name, fn in (("Environment", base.c_env), ("ck2nuke import + settings", base.c_import),
                     ("Panel defaults", c_defaults)):
        check(name, fn)
    try:
        _next(0)
    except Exception as exc:
        traceback.print_exc()
        rec("keys", "FAIL", "{}: {}".format(type(exc).__name__, exc))
        base.finish()

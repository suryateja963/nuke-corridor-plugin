r"""Real-Nuke regression test: a Roto hint drawn over a plate whose size differs
from the project format must land on the same plate pixels.

    powershell -ExecutionPolicy Bypass -File tests\run_nuke_auto.ps1 -Module nuke_hint_format_test -ReportName nuke_hint_format_report.txt

Recreates the reported case: project format 2K Super 35 (2048x1556, Nuke's
default), a 1280x720 plate Read, and an unconnected Roto with a box drawn in plate
pixels. Renders the hint the old way (Roto's own format) and the fixed way
(plate_size), and measures where the box lands in each PNG.
"""

import json
import os
import subprocess

import nuke

import nuke_auto_test as base
from nuke_auto_test import OUT, SHOTS, check, rec

base.REPORT = os.path.join(OUT, "nuke_hint_format_report.txt")
PLATE_DIR = os.path.join(SHOTS, "_hint_plate").replace("\\", "/")
W, H = 1280, 720
BOX = (300, 100, 900, 600)   # Nuke coordinates (y up): x0, y0, x1, y1

MEASURE = r"""
import json, os, sys
os.environ["OPENCV_IO_ENABLE_OPENEXR"] = "1"
sys.path.insert(0, r"D:\nuke plugin")
import numpy as np
from ck_engine.imageio import read_image
from ck_engine.hints import to_mask
m = to_mask(read_image(sys.argv[1], keep_alpha=True))
ys, xs = np.nonzero(m > 0.5)
print(json.dumps({"w": m.shape[1], "h": m.shape[0], "x0": int(xs.min()), "x1": int(xs.max()) + 1,
                  "top": int(ys.min()), "bottom": int(ys.max()) + 1}))
"""

MAKE_PLATE = r"""
import os, sys
os.environ["OPENCV_IO_ENABLE_OPENEXR"] = "1"
sys.path.insert(0, r"D:\nuke plugin")
import numpy as np
from ck_engine.imageio import write_exr
os.makedirs(sys.argv[1], exist_ok=True)
img = np.zeros((720, 1280, 3), np.float32); img[:] = (0.05, 0.45, 0.06)
write_exr(os.path.join(sys.argv[1], "plate.1001.exr"), img)
"""


def _py(code, *args):
    from ck2nuke import runner, settings
    out = subprocess.run([settings()["engine_python"], "-c", code] + list(args), capture_output=True, text=True,
                         timeout=120, env=runner._clean_env(), creationflags=runner.CREATE_NO_WINDOW)
    if out.returncode != 0:
        raise RuntimeError(out.stderr[-400:])
    return out.stdout.strip()


def run():
    from ck2nuke import nc, panel
    os.makedirs(OUT, exist_ok=True)
    rec("start", "INFO", "hint format test running in Nuke")
    _py(MAKE_PLATE, PLATE_DIR)
    nuke.tcl('knob root.format "2K_Super_35(full-ap)"')
    check("Project format", lambda: "{}x{}".format(int(nuke.expression("root.width")), int(nuke.expression("root.height"))))
    read = nc.unique("CK2_test_plate720")
    nc.deselect_all()
    nc.paste('Read {{\n inputs 0\n file_type exr\n file {}\n format "1280 720 0 0 1280 720 1 CK2_720"\n'
             ' first 1001\n last 1001\n origfirst 1001\n origlast 1001\n name {}\n}}\n'.format(
                 nc.q(PLATE_DIR + "/plate.####.exr"), read))
    check("Plate Read", lambda: "{} {}x{}".format(read, *nc.size(read)))
    roto = base._roto("2K_Super_35(full-ap)", BOX, "CK2_test_unconnected_roto")  # what an unconnected Roto gets
    nuke.frame(1001)
    check("Roto format (unconnected)", lambda: "{}x{}".format(*nc.size(roto)))
    expect = {"w": W, "h": H, "x0": BOX[0], "x1": BOX[2], "top": H - BOX[3], "bottom": H - BOX[1]}

    def old():
        pat = panel._render_hint(roto, SHOTS + "/_hint_old", 1001, 1001, "first_frame")
        m = json.loads(_py(MEASURE, pat.replace("####", "1001")))
        return "INFO", "old render (Roto format): {}x{}, box x {}-{} top {}-{} -> stretched onto {}x{} it misses".format(
            m["w"], m["h"], m["x0"], m["x1"], m["top"], m["bottom"], W, H)
    check("Hint render, old behaviour", old)

    def new():
        pat = panel._render_hint(roto, SHOTS + "/_hint_new", 1001, 1001, "first_frame", (W, H))
        m = json.loads(_py(MEASURE, pat.replace("####", "1001")))
        ok = (m["w"], m["h"]) == (W, H) and all(abs(m[k] - expect[k]) <= 2 for k in ("x0", "x1", "top", "bottom"))
        left = [n for n in ("CK2_hintBox", "CK2_hintReformat", "CK2_hintWrite") if nc.exists(n)]
        return ("PASS" if ok and not left else "FAIL"), "{}x{}, box x {}-{} top {}-{} (expected x {}-{} top {}-{}){}".format(
            m["w"], m["h"], m["x0"], m["x1"], m["top"], m["bottom"], expect["x0"], expect["x1"], expect["top"],
            expect["bottom"], "; leftover " + str(left) if left else "")
    check("Hint render in plate pixels (fixed)", new)
    base.finish()

r"""Probe: load an already-finished key into Nuke step by step (no keying).
Writes _g2_out\load_probe.txt; the pasted .nk text goes to _g2_out\load_probe.nk."""

import json
import threading
import time
import traceback

import nuke

OUT = r"D:\nuke plugin\_g2_out\load_probe.txt"
K = "D:/nuke plugin/_e2e_out/pail/"
# A finished key from tests/e2e_gpu.py (v001, frames 1001-1012).
STATUS = {"state": "done", "stage": "all", "shot_dir": K, "version": "v001",
          "plate": {"pattern": K + "plate_lin/plate.####.exr", "first": 1001, "last": 1012,
                    "width": 3840, "height": 2160, "fps": 25.0},
          "outputs": {"alpha": K + "key/v001/alpha/alpha.####.exr", "fg": K + "key/v001/fg/fg.####.exr"}}
lines = []


def log(msg):
    lines.append("[%s] %s" % (time.strftime("%H:%M:%S"), msg))
    with open(OUT, "w") as f:
        f.write("\n".join(lines) + "\n")


def run():
    from ck2nuke import loader, nc
    nuke.message = lambda m: log("nuke.message: " + str(m).replace("\n", " | "))
    status = STATUS
    log("status %s %s" % (status["state"], status.get("version")))
    try:
        cs = nc.linear_colorspace()
        log("linear colorspace name: %r" % cs)
        names = {"tag": "T"}
        for part in ("backdrop", "plate", "fg", "alpha", "copy", "premult", "bg", "over"):
            names[part] = "T_" + part
        text = loader.comp_nk(status, names, 0, 0, cs)
        open(r"D:\nuke plugin\_g2_out\load_probe.nk", "w").write(text)
        log("nk text written (%d chars)" % len(text))
        # A watchdog: if paste blocks (modal error dialog), say so.
        done = {"v": False}
        threading.Timer(10, lambda: done["v"] or log("STILL BLOCKED in paste after 10s (modal dialog?)")).start()
        log("pasting...")
        nc.paste(text)
        done["v"] = True
        log("paste returned")
        for part in ("plate", "fg", "alpha", "copy", "premult", "bg", "over", "backdrop"):
            log("exists T_%s: %s" % (part, nc.exists("T_" + part)))
        log("copy inputs: %s, %s" % (nuke.tcl("value [input T_copy 0].name"), nuke.tcl("value [input T_copy 1].name")))
        log("merge inputs: %s, %s" % (nuke.tcl("value [input T_over 0].name"), nuke.tcl("value [input T_over 1].name")))
        log("plate colorspace: %s" % nc.value("T_plate", "colorspace"))
        done2 = {"v": False}
        threading.Timer(15, lambda: done2["v"] or log("STILL BLOCKED in nuke.sample after 15s")).start()
        node = nuke.toNode("T_premult")
        log("toNode premult: %s" % (node is not None))
        v = nuke.sample(node, "rgba.alpha", 3300, 900, 1, 1, 1001)
        done2["v"] = True
        log("sample alpha person: %.3f" % v)
    except Exception as exc:
        log("ERROR %s: %s\n%s" % (type(exc).__name__, exc, traceback.format_exc()))
    log("DONE")

r"""Gate G2: can Nuke Non-commercial host the CorridorKey 2.0 tool?

Run it from Nuke's Script Editor (paste this line and press Ctrl+Enter):

    exec(open(r"D:\nuke plugin\nuke\tests\g2_capability_test.py").read())

Each check prints PASS / WARN / FAIL in the Script Editor. Three dialogs open
on the way (file browser, two panels): click through them, any answer is fine.
A background check then runs a progress bar; when it ends, a summary box appears
and the full report is written to REPORT_PATH.

Uses only nuke + the standard library, and no PySide, so it runs on any Nuke 13+.
"""

import os
import struct
import subprocess
import sys
import threading
import time
import traceback

import nuke

ENGINE_PY = r"D:\CorridorKey2\venv\Scripts\python.exe"
OUT_DIR = r"D:\nuke plugin\_g2_out"
REPORT_PATH = os.path.join(OUT_DIR, "g2_report.txt")
PLATE_4K = os.path.join(OUT_DIR, "plate_4k", "plate.####.exr").replace("\\", "/")

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)

_results = []


def _record(name, status, detail=""):
    _results.append((name, status, detail))
    print("[G2] {:<4} {}{}".format(status, name, "  - " + detail if detail else ""))


def _run(name, fn):
    """fn returns a detail string (PASS) or a (status, detail) tuple."""
    try:
        out = fn()
        status, detail = out if isinstance(out, tuple) else ("PASS", out or "")
    except Exception as exc:
        status, detail = "FAIL", "{}: {}".format(type(exc).__name__, exc)
        traceback.print_exc()
    _record(name, status, detail)


def _clean_env():
    # Nuke sets PYTHONPATH/PYTHONHOME for its own Python. A venv python that
    # inherits them loads Nuke's stdlib, so the real tool must strip them too.
    env = {k: v for k, v in os.environ.items()
           if k.upper() not in ("PYTHONPATH", "PYTHONHOME")}
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


# --- checks that run on the main thread -------------------------------------

def check_env():
    try:
        nc = bool(nuke.env["nc"])
    except Exception:
        nc = "unknown"
    return "Nuke {}, non-commercial={}, Python {}".format(
        nuke.NUKE_VERSION_STRING, nc, sys.version.split()[0])


def check_menu():
    menu = nuke.menu("Nuke").addMenu("CorridorKey 2.0")
    menu.addCommand("G2 test item", "nuke.message('CorridorKey 2.0 menu works')")
    if nuke.menu("Nuke").findItem("CorridorKey 2.0/G2 test item") is None:
        raise RuntimeError("menu item not found after adding it")
    return "added CorridorKey 2.0 > G2 test item"


def check_get_filename():
    path = nuke.getFilename("G2: pick any file (or Cancel)")
    return "returned {!r}".format(path)


def check_panel():
    p = nuke.Panel("G2: nuke.Panel test")
    p.addEnumerationPulldown("Colour space", "sRGB Linear S-Log3")
    p.addFilenameSearch("Matte file", "")
    p.addButton("Cancel")
    p.addButton("OK")
    result = p.show()
    return "show() returned {}, colour space={!r}".format(result, p.value("Colour space"))


class _TestPythonPanel(nuke.PythonPanel):
    def __init__(self):
        nuke.PythonPanel.__init__(self, "G2: PythonPanel test")
        self.colour = nuke.Enumeration_Knob(
            "colour", "Colour space", ["sRGB / Rec.709", "Linear Rec.709", "S-Log3"])
        self.matte = nuke.File_Knob("matte", "Matte file")
        self.quality = nuke.Double_Knob("quality", "Hint quality")
        self.quality.setRange(0.0, 1.0)
        self.quality.setValue(0.95)
        for knob in (self.colour, self.matte, self.quality):
            self.addKnob(knob)


def check_python_panel():
    panel = _TestPythonPanel()
    ok = panel.showModalDialog()
    return "showModalDialog() returned {}, colour={!r}, quality={}".format(
        ok, panel.colour.value(), panel.quality.value())


def check_subprocess_echo():
    out = subprocess.run(["cmd", "/c", "echo ok"], capture_output=True, text=True,
                         timeout=30, creationflags=CREATE_NO_WINDOW)
    if out.stdout.strip() != "ok":
        raise RuntimeError("unexpected output {!r} (code {})".format(out.stdout, out.returncode))
    return "cmd /c echo ok -> 'ok'"


# Runs in the engine venv: proves Nuke can launch it with a clean env, that the
# child sees the GPU, and writes the 4K half-float plate that NC can't render itself.
_CHILD = r'''
import os, sys
os.environ["OPENCV_IO_ENABLE_OPENEXR"] = "1"
import numpy as np, cv2, torch
out = sys.argv[1]
os.makedirs(out, exist_ok=True)
h, w = 2160, 3840
ramp = np.linspace(0.0, 2.0, w, dtype=np.float32)  # >1.0 on the right: float must survive
img = np.empty((h, w, 3), np.float32)
img[...] = ramp[None, :, None]
img[..., 0] *= 0.5  # blue (BGR order) at half, so channels are distinguishable
for f in (1001, 1002, 1003):
    path = os.path.join(out, "plate.%04d.exr" % f)
    if not cv2.imwrite(path, img, [cv2.IMWRITE_EXR_TYPE, cv2.IMWRITE_EXR_TYPE_HALF]):
        raise SystemExit("cv2.imwrite failed: " + path)
gpu = torch.cuda.get_device_name(0) if torch.cuda.is_available() else "none"
print("CUDA", torch.cuda.is_available(), gpu)
print("WROTE", out)
'''


def check_engine_python():
    if not os.path.isfile(ENGINE_PY):
        raise RuntimeError("engine python not found: " + ENGINE_PY)
    child = os.path.join(OUT_DIR, "g2_child.py")
    with open(child, "w") as f:
        f.write(_CHILD)
    out = subprocess.run([ENGINE_PY, "-u", child, os.path.dirname(PLATE_4K)],
                         capture_output=True, text=True, timeout=300,
                         env=_clean_env(), creationflags=CREATE_NO_WINDOW)
    text = (out.stdout + out.stderr).strip()
    if out.returncode != 0 or "WROTE" not in out.stdout:
        raise RuntimeError("code {}: {}".format(out.returncode, text[-400:]))
    cuda = [l for l in out.stdout.splitlines() if l.startswith("CUDA")]
    cuda = cuda[0] if cuda else "CUDA ?"
    status = "PASS" if cuda.startswith("CUDA True") else "WARN"
    return status, "venv python ran with clean env; {}; wrote 3 frames of 4K half EXR".format(cuda)


def check_roto_render():
    roto = nuke.nodes.Roto()
    roto["format"].setValue("HD_1080")
    shape_note = "square shape"
    try:
        import nuke.rotopaint as rp
        curves = roto["curves"]
        shape = rp.Shape(curves)
        for x, y in ((660, 240), (1260, 240), (1260, 840), (660, 840)):
            shape.append([x, y])
        curves.rootLayer.append(shape)
    except Exception as exc:
        shape_note = "EMPTY roto, shape API failed ({}: {})".format(type(exc).__name__, exc)

    write = nuke.nodes.Write(inputs=[roto])
    pattern = os.path.join(OUT_DIR, "roto", "hint.####.png").replace("\\", "/")
    os.makedirs(os.path.join(OUT_DIR, "roto"), exist_ok=True)
    write["file"].setValue(pattern)
    write["file_type"].setValue("png")
    write["datatype"].setValue("16 bit")
    write["channels"].setValue("rgba")
    try:
        nuke.execute(write, 1, 1)
    finally:
        nuke.delete(write)
        nuke.delete(roto)

    png = pattern.replace("####", "0001")
    with open(png, "rb") as f:
        head = f.read(26)
    width, height = struct.unpack(">II", head[16:24])
    depth = head[24]
    detail = "{}x{} {}-bit PNG, {}".format(width, height, depth, shape_note)
    if (width, height, depth) != (1920, 1080, 16):
        raise RuntimeError("wrong output: " + detail)
    return ("WARN" if shape_note.startswith("EMPTY") else "PASS"), detail


# --- background thread, then back on the main thread ---------------------------

def _background():
    status, detail = "FAIL", ""
    try:
        task = nuke.ProgressTask("G2: background progress test")
        for i in range(101):
            if task.isCancelled():
                status, detail = "WARN", "worked, but you cancelled at {}%".format(i)
                break
            task.setProgress(i)
            task.setMessage("step {}/100".format(i))
            time.sleep(0.03)
        else:
            status, detail = "PASS", "100 updates from a background thread"
        del task
    except Exception as exc:
        detail = "{}: {}".format(type(exc).__name__, exc)
    # If this call is blocked, the summary never appears: that itself is the failure.
    nuke.executeInMainThread(_finish_on_main, (status, detail))


def _finish_on_main(progress_status, progress_detail):
    _record("ProgressTask from a background thread", progress_status, progress_detail)
    _record("executeInMainThread from a background thread", "PASS",
            "this summary is running on the main thread")
    _run("Read 4K half-float EXR sequence", check_read_4k)
    _write_report()


def check_read_4k():
    if not os.path.isfile(PLATE_4K.replace("####", "1001")):
        raise RuntimeError("no 4K plate on disk (engine python check failed)")
    read = nuke.nodes.Read(file=PLATE_4K, first=1001, last=1003, name="CK2_G2_4k")
    read["origfirst"].setValue(1001)
    read["origlast"].setValue(1003)
    try:
        read["colorspace"].setValue("linear")
    except Exception:
        pass  # name differs in some OCIO configs; the raw values are checked below
    if read.hasError():
        raise RuntimeError("Read node reports an error")
    w, h = read.width(), read.height()
    red = nuke.sample(read, "rgba.red", 3800, 1080)
    detail = "{}x{}, red at x=3800 is {:.3f} (expect ~1.98)".format(w, h, red)
    if (w, h) != (3840, 2160) or red < 1.0:
        raise RuntimeError(detail)
    return detail + ". Node CK2_G2_4k left in the script for you to view"


def _write_report():
    counts = {s: sum(1 for _, st, _ in _results if st == s) for s in ("PASS", "WARN", "FAIL")}
    lines = ["CorridorKey 2.0 - Gate G2 report",
             time.strftime("%Y-%m-%d %H:%M:%S"), ""]
    lines += ["{:<4}  {:<46} {}".format(s, n, d) for n, s, d in _results]
    lines += ["",
              "Manual checks (write the result in docs/nuke_env.md):",
              "  M1  Open CK2_G2_4k in the Viewer: a grey-to-bright ramp, frames 1001-1003.",
              "  M2  Startup menu test: see docs/nuke_env.md, section 'Startup test'."]
    text = "\n".join(lines)
    try:
        with open(REPORT_PATH, "w") as f:
            f.write(text + "\n")
        where = "Report: " + REPORT_PATH
    except Exception as exc:
        where = "Could not write report: {}".format(exc)
    print(text)
    nuke.message("G2 finished: {PASS} pass, {WARN} warn, {FAIL} fail.\n\n".format(**counts)
                 + where + "\n\nPaste the report back to Claude.")


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    del _results[:]
    for name, fn in (
            ("Environment", check_env),
            ("Menu item", check_menu),
            ("nuke.getFilename", check_get_filename),
            ("nuke.Panel", check_panel),
            ("nuke.PythonPanel (knob panel)", check_python_panel),
            ("subprocess: cmd /c echo", check_subprocess_echo),
            ("subprocess: engine venv python + GPU", check_engine_python),
            ("Render Roto -> Write 16-bit PNG 1920x1080", check_roto_render)):
        _run(name, fn)
    threading.Thread(target=_background, name="CK2-G2", daemon=True).start()
    print("[G2] background check running; a summary box appears when it finishes")


main()

r"""Automatic test inside real Nuke: no clicks needed.

    powershell -ExecutionPolicy Bypass -File tests\run_nuke_auto.ps1

The runner starts Nuke NC with NUKE_PATH = nuke\tests\auto_startup, whose menu.py
calls run(). Every result is written to _g2_out\nuke_auto_report.txt as it
happens; the last line is DONE.

Nuke NC hands Python only 10 Node objects per session, so this test, like the
tool, works by node name (ck2nuke.nc). It uses 5 objects itself: 3 Rotos and
2 nodes to sample.
"""

import os
import struct
import subprocess
import time
import traceback

import nuke

REPO = r"D:\nuke plugin"
OUT = os.path.join(REPO, "_g2_out")
REPORT = os.path.join(OUT, "nuke_auto_report.txt")
SHOTS = os.path.join(REPO, "_nuke_test", "shots").replace("\\", "/")
CLIP = r"D:\CorridorKey2\test_clips\raw\pail.mp4"

_results = []
_messages = []
_t0 = time.time()


def _write(final=None):
    lines = ["CorridorKey 2.0 - automatic Nuke test", time.strftime("%Y-%m-%d %H:%M:%S"), ""]
    lines += ["{:<4}  {:<46} {}".format(s, n, d) for n, s, d in _results]
    if _messages:
        lines += ["", "nuke.message calls:"] + ["  " + m.replace("\n", " | ") for m in _messages]
    if final:
        lines.append(final)
    with open(REPORT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def rec(name, status, detail=""):
    _results.append((name, status, "{}  [{:.0f}s]".format(detail, time.time() - _t0)))
    print("[CK2 AUTO] {} {} {}".format(status, name, detail))
    _write()


def check(name, fn):
    try:
        out = fn()
        status, detail = out if isinstance(out, tuple) else ("PASS", out or "")
    except Exception as exc:
        status, detail = "FAIL", "{}: {}".format(type(exc).__name__, exc)
        traceback.print_exc()
    rec(name, status, detail)
    return status


def finish():
    passed = sum(1 for _, s, _ in _results if s == "PASS")
    failed = sum(1 for _, s, _ in _results if s == "FAIL")
    _write("DONE  {} passed, {} failed".format(passed, failed))


# Modal dialogs would stall an unattended run: record them instead.
nuke.message = lambda m: _messages.append(str(m))
nuke.ask = lambda m: True


def _png_info(path):
    with open(path, "rb") as f:
        head = f.read(26)
    w, h = struct.unpack(">II", head[16:24])
    return w, h, head[24]


def _roto(fmt, box, name):
    """One Roto with a box shape (uses 1 of NC's 10 Node objects). Returns its name."""
    roto = nuke.nodes.Roto(name=name)
    roto["format"].setValue(fmt)
    import nuke.rotopaint as rp
    curves = roto["curves"]
    shape = rp.Shape(curves)
    x0, y0, x1, y1 = box
    for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
        shape.append([x, y])
    curves.rootLayer.append(shape)
    return roto.name()


# ---- quick checks ----------------------------------------------------------------

def c_env():
    try:
        nc_mode = bool(nuke.env["nc"])
    except Exception:
        nc_mode = "unknown"
    return "Nuke {}, non-commercial={}".format(nuke.NUKE_VERSION_STRING, nc_mode)


def c_menu():
    if nuke.menu("Nuke").findItem("CorridorKey 2.0/Key shot...") is None:
        raise RuntimeError("CorridorKey 2.0 menu not found - hook in .nuke/init.py not loaded?")
    return "CorridorKey 2.0 > Key shot... present"


def c_import():
    import ck2nuke
    cfg = ck2nuke.settings()
    missing = [k for k in ("engine_python", "upstream_root", "worker_script") if not os.path.exists(cfg[k])]
    if missing:
        raise RuntimeError("paths missing: {}".format(missing))
    return "ck2nuke {} from {}".format(ck2nuke.VERSION, ck2nuke.REPO_ROOT)


def c_panel():
    from ck2nuke import panel
    p = panel.KeyPanel(None, None, False)
    return "{} knobs, colour default {}".format(len(p.k), p.colour_key())


def c_engine():
    from ck2nuke import runner, settings
    out = subprocess.run([settings()["engine_python"], "-c",
                          "import torch;print('CUDA', torch.cuda.is_available(), torch.cuda.get_device_name(0))"],
                         capture_output=True, text=True, timeout=300, env=runner._clean_env(),
                         creationflags=runner.CREATE_NO_WINDOW)
    if out.returncode != 0:
        raise RuntimeError(out.stdout[-200:] + out.stderr[-300:])
    return out.stdout.strip()


def c_render(fmt, expect):
    def fn():
        from ck2nuke import nc, panel
        name = _roto(fmt, (400, 300, 1400, 900), "CK2_test_roto_" + fmt)
        try:
            pattern = panel._render_hint(name, SHOTS + "/_render_test_" + fmt, 1, 1, "first_frame")
        finally:
            nc.delete(name)
        info = _png_info(pattern.replace("####", "0001"))
        if info != expect:
            raise RuntimeError("got {}x{} {}-bit, expected {}".format(*(info + (expect,))))
        leftovers = [n for n in ("CK2_hintWrite", "CK2_hintReformat") if nc.exists(n)]
        return ("FAIL" if leftovers else "PASS"), "{}: {}x{} {}-bit PNG{}".format(
            fmt, info[0], info[1], info[2], "; leftover " + str(leftovers) if leftovers else "")
    return fn


# ---- real keys through the panel ---------------------------------------------------

_values = {}


def _auto_dialog(self):
    for k, v in _values.items():
        self.k[k].setValue(v)
    self._refresh()
    return True


def _key(values, then):
    """Runs panel.key_shot() with preset values; `then(status)` gets the result."""
    from ck2nuke import panel, runner
    _values.clear()
    _values.update(values)
    panel.KeyPanel.showModalDialog = _auto_dialog
    orig = runner._finish

    def fin(status, job_path):
        runner._finish = orig
        try:
            orig(status, job_path)
        finally:
            then(status)

    runner._finish = fin
    n_msgs = len(_messages)
    panel.key_shot()
    if len(_messages) > n_msgs:  # the panel refused before starting
        runner._finish = orig
        then({"state": "failed", "error": _messages[-1]})


def k1():
    from ck2nuke import nc
    nc.deselect_all()
    _key({"src_mode": "File on disk", "src_file": CLIP, "shot_name": "pail_nuke",
          "shot_root": SHOTS, "preview": True, "preview_frames": 6, "despill": 0.5}, k1_done)


def _check_key(tag, status, label):
    from ck2nuke import nc
    if status.get("state") != "done":
        rec(label, "FAIL", "{}: {}".format(status.get("state"), status.get("error")))
        return None
    names = {part: tag + "_" + part for part in ("plate", "fg", "alpha", "copy", "premult", "bg", "over", "backdrop")}
    missing = [n for n in names.values() if not nc.exists(n)]
    if missing:
        rec(label, "FAIL", "comp nodes missing: {}".format(missing))
        return None
    wiring = {
        "copy B=fg": nuke.tcl("value [input {} 0].name".format(names["copy"])) == names["fg"],
        "copy A=alpha": nuke.tcl("value [input {} 1].name".format(names["copy"])) == names["alpha"],
        "merge B=bg": nuke.tcl("value [input {} 0].name".format(names["over"])) == names["bg"],
        "merge A=premult": nuke.tcl("value [input {} 1].name".format(names["over"])) == names["premult"],
    }
    cs = nc.value(names["plate"], "colorspace")
    premult = nuke.toNode(names["premult"])  # 1 Node object, only to sample pixels
    nuke.frame(1001)  # Nuke 17's sample() has no frame argument: it samples the current frame
    inside = nuke.sample(premult, "rgba.alpha", 3300, 900)
    outside = nuke.sample(premult, "rgba.alpha", 300, 1900)
    p = status["plate"]
    ok = all(wiring.values()) and inside > 0.9 and outside < 0.1
    rec(label, "PASS" if ok else "FAIL",
        "{} {}x{} {}-{}; wiring {}; colorspace {}; alpha person={:.3f} bg={:.3f}; {}".format(
            status.get("version"), p["width"], p["height"], p["first"], p["last"],
            "ok" if all(wiring.values()) else wiring, cs, inside, outside,
            (status.get("auto_vram") or "").replace("Auto VRAM: ", "").strip()))
    return names["over"]


def _render_comp(merge, name):
    from ck2nuke import nc
    path = os.path.join(OUT, name).replace("\\", "/")
    ref, wr = nc.unique("CK2_test_compReformat"), nc.unique("CK2_test_compWrite")
    nc.deselect_all()
    nc.select(merge)
    nc.paste('Reformat {{\n format "1920 1080 0 0 1920 1080 1 HD_1080"\n name {}\n}}\n'
             'Write {{\n file {}\n file_type png\n channels rgb\n name {}\n}}\n'.format(ref, nc.q(path), wr))
    try:
        nc.execute(wr, 1001, 1001)
    finally:
        nc.delete(wr)
        nc.delete(ref)
    w, h, d = _png_info(path)
    return "{} {}x{}".format(name, w, h)


def _guarded(fn):
    """Callbacks run from the runner: record any error instead of silently stalling."""
    def wrapped(status):
        try:
            fn(status)
        except Exception as exc:
            traceback.print_exc()
            rec(fn.__name__, "FAIL", "{}: {}".format(type(exc).__name__, exc))
            finish()
    return wrapped


@_guarded
def k1_done(status):
    merge = _check_key("CK2_pail_nuke_preview", status, "Key 1: MP4 via panel (preview 6, despill)")
    if merge:
        check("Render comp 1 in Nuke (HD PNG)", lambda: _render_comp(merge, "nuke_comp_key1.png"))
    run_k2()


def run_k2():
    from ck2nuke import nc, panel
    try:
        plate = "CK2_pail_nuke_preview_plate"
        if not nc.exists(plate):
            rec("Key 2: plate Read + Roto hint", "FAIL", "no plate Read from key 1")
            return finish()
        # Roto around the person on the right (Nuke y is up).
        roto = _roto("UHD_4K", (2850, 0, 3840, 2160), "CK2_test_hint_roto")
        nc.deselect_all()
        nc.select(plate)
        nc.select(roto)
        sel = panel._selection()
        check("Selection by name (TCL)", lambda: ("PASS" if sel == (plate, roto) else "FAIL", str(sel)))
        _key({"preview": False}, k2_done)
    except Exception as exc:
        traceback.print_exc()
        rec("Key 2: plate Read + Roto hint", "FAIL", "{}: {}".format(type(exc).__name__, exc))
        finish()


@_guarded
def k2_done(status):
    merge = _check_key("CK2_pail_nuke_" + str(status.get("version")), status,
                       "Key 2: plate Read + Roto first-frame hint")
    if merge:
        check("Render comp 2 in Nuke (HD PNG)", lambda: _render_comp(merge, "nuke_comp_key2.png"))
    finish()


def run():
    os.makedirs(OUT, exist_ok=True)
    rec("start", "INFO", "automatic test running in Nuke")
    for name, fn in (("Environment", c_env), ("CorridorKey menu from hook", c_menu),
                     ("ck2nuke import + settings", c_import), ("Key panel builds", c_panel),
                     ("Engine python + GPU from Nuke", c_engine),
                     ("Roto hint render, HD plate", c_render("HD_1080", (1920, 1080, 16))),
                     ("Roto hint render, 4K plate (NC scale)", c_render("UHD_4K", (1920, 1080, 16)))):
        check(name, fn)
    try:
        k1()
    except Exception as exc:
        traceback.print_exc()
        rec("Key 1: MP4 via panel", "FAIL", "{}: {}".format(type(exc).__name__, exc))
        finish()

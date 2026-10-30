"""Loads engine results into the script: Reads (linear) plus a comp in a Backdrop.

Comp: fg (straight colour) + alpha copied in -> Premult -> Merge over a background.
"""

import json
import os
import time

import nuke

# Colourspace names that mean "linear Rec.709" across Nuke's default and ACES/OCIO configs.
_LINEAR_NAMES = ("linear", "scene_linear", "linear rec.709 (srgb)", "lin_rec709",
                 "utility - linear - srgb", "lin_srgb")


def _set_linear(read):
    knob = read.knob("colorspace")
    if knob is None:
        return False
    try:
        values = knob.values()
    except Exception:
        values = []
    for want in _LINEAR_NAMES:
        for v in values:
            name = v.split("/")[-1].split("\t")[0].strip().lower()
            if name == want:
                knob.setValue(v)
                return True
    try:
        knob.setValue("linear")
        return True
    except Exception:
        return False


def _read(pattern, first, last, name, x, y):
    r = nuke.nodes.Read(name=name)
    r["file"].fromUserText("{} {}-{}".format(pattern.replace("\\", "/"), first, last))
    for knob, val in (("first", first), ("last", last), ("origfirst", first), ("origlast", last)):
        r[knob].setValue(int(val))
    r["on_error"].setValue("black")
    _set_linear(r)
    r.setXYpos(x, y)
    return r


def _unique(base):
    name, i = base, 1
    while nuke.toNode(name) is not None:
        i += 1
        name = "{}{}".format(base, i)
    return name


def _origin():
    try:
        sel = nuke.selectedNodes()
    except Exception:
        sel = []
    if sel:
        return sel[0].xpos() + 300, sel[0].ypos()
    return 0, 0


def load_plate(status):
    p = status["plate"]
    x, y = _origin()
    shot = os.path.basename(status.get("shot_dir", "shot").rstrip("/\\"))
    r = _read(p["pattern"], p["first"], p["last"], _unique("CK2_{}_plate".format(shot)), x, y)
    nuke.message("CorridorKey 2.0: plate ready ({}x{}, {:.3f} fps).\n\nDraw a Roto on {} if you "
                 "want a hint, select the plate and the Roto, then Key shot.".format(
                     p["width"], p["height"], p["fps"], r.name()))
    return r


def load_result(status):
    if status.get("stage") == "prepare" or "outputs" not in status:
        return load_plate(status)
    p, out = status["plate"], status["outputs"]
    shot = os.path.basename(status.get("shot_dir", "shot").rstrip("/\\"))
    tag = "CK2_{}_{}".format(shot, status.get("version", "key"))
    x0, y0 = _origin()
    first, last = p["first"], p["last"]
    dx, dy = 130, 110

    plate = _read(p["pattern"], first, last, _unique(tag + "_plate"), x0, y0)
    fg_pattern = out.get("fg_despill") or out["fg"]
    fg = _read(fg_pattern, first, last, _unique(tag + "_fg"), x0 + dx, y0)
    alpha = _read(out["alpha"], first, last, _unique(tag + "_alpha"), x0 + 2 * dx, y0)

    # The alpha EXR is single-channel; Nuke shows it in red (and rgb).
    copy = nuke.nodes.Copy(inputs=[fg, alpha], from0="rgba.red", to0="rgba.alpha",
                           name=_unique(tag + "_copyAlpha"))
    copy.setXYpos(x0 + dx, y0 + dy)
    premult = nuke.nodes.Premult(inputs=[copy], name=_unique(tag + "_premult"))
    premult.setXYpos(x0 + dx, y0 + 2 * dy)

    fmt_name = "CK2_{}x{}".format(p["width"], p["height"])
    if not any(f.name() == fmt_name for f in nuke.formats()):
        nuke.addFormat("{} {} 1.0 {}".format(p["width"], p["height"], fmt_name))
    bg = nuke.nodes.Constant(name=_unique(tag + "_BG"))
    bg["format"].setValue(fmt_name)
    bg["color"].setValue([0.18, 0.18, 0.18, 1.0])
    bg.setXYpos(x0 - dx, y0 + 2 * dy)
    merge = nuke.nodes.Merge2(inputs=[bg, premult], operation="over", name=_unique(tag + "_over"))
    merge.setXYpos(x0 + dx, y0 + 3 * dy)

    label = "<b>{}</b>\n{} - {}x{} - {:.3f} fps - frames {}-{}\n{}".format(
        tag, time.strftime("%Y-%m-%d %H:%M"), p["width"], p["height"], p["fps"], first, last,
        "despilled fg" if out.get("fg_despill") else "fg (no despill)")
    bd = nuke.nodes.BackdropNode(xpos=x0 - dx - 40, ypos=y0 - 90,
                                 bdwidth=4 * dx + 120, bdheight=3 * dy + 180,
                                 label=label, note_font_size=14, tile_color=0x3D5A45FF)
    bd["name"].setValue(_unique(tag + "_backdrop"))
    try:
        nuke.connectViewer(0, merge)
    except Exception:
        pass
    if abs(nuke.root()["fps"].value() - p["fps"]) > 0.001:
        print("[CorridorKey 2.0] note: script fps {} differs from the shot's {:.3f}".format(
            nuke.root()["fps"].value(), p["fps"]))
    return merge


def load_from_folder():
    """Menu: pick a shot folder, load its newest finished key (or its plate)."""
    folder = nuke.getFilename("CorridorKey 2.0: pick a shot folder (contains job.json)")
    if not folder:
        return
    folder = folder if os.path.isdir(folder) else os.path.dirname(folder)
    status_path = os.path.join(folder, "status.json")
    if not os.path.isfile(status_path):
        nuke.message("No status.json in {}. Is this a CorridorKey shot folder?".format(folder))
        return
    with open(status_path, encoding="utf-8") as f:
        status = json.load(f)
    if status.get("state") != "done":
        nuke.message("The last run of this shot did not finish ({}):\n{}".format(
            status.get("state"), status.get("error") or ""))
        return
    load_result(status)

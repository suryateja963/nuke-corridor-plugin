"""Loads engine results into the script: Reads (linear) plus a comp in a Backdrop.

Comp: fg (straight colour) + alpha copied in -> Premult -> Merge over a background.
Built as .nk text and pasted (nc.paste), so it uses none of Nuke NC's 10 Python
Node objects. In .nk text the node on top of the stack becomes input 0, so for
Copy/Merge input 1 (A) is pushed first, then input 0 (B).
"""

import json
import os
import time

import nuke

from . import nc

DX, DY = 130, 110


def _origin():
    try:
        sel = nc.selected()
    except Exception:
        sel = []
    if sel:
        x, y = nc.pos(sel[0])
        return x + 300, y
    return 0, 0


def _fmt(p):
    return '"{w} {h} 0 0 {w} {h} 1 CK2_{w}x{h}"'.format(w=p["width"], h=p["height"])


def _read_nk(pattern, p, name, x, y, cs):
    first, last = p["first"], p["last"]
    return ("Read {{\n inputs 0\n file_type exr\n file {file}\n format {fmt}\n"
            " first {f}\n last {l}\n origfirst {f}\n origlast {l}\n origset true\n"
            " colorspace {cs}\n on_error black\n name {name}\n xpos {x}\n ypos {y}\n}}\n").format(
        file=nc.q(pattern), fmt=_fmt(p), f=first, l=last, cs=nc.q(cs), name=name, x=x, y=y)


def load_plate(status):
    p = status["plate"]
    x, y = _origin()
    shot = os.path.basename(status.get("shot_dir", "shot").rstrip("/\\"))
    name = nc.unique("CK2_{}_plate".format(shot))
    nc.deselect_all()
    nc.paste(_read_nk(p["pattern"], p, name, x, y, nc.linear_colorspace()))
    nuke.message("CorridorKey 2.0: plate ready ({}x{}, {:.3f} fps).\n\nDraw a Roto on {} if you "
                 "want a hint, select the plate and the Roto, then Key shot.".format(
                     p["width"], p["height"], p["fps"], name))
    return name


def comp_nk(status, names, x0, y0, cs):
    """The .nk text for plate, fg, alpha, Copy, Premult, BG, Merge and a Backdrop."""
    p, out = status["plate"], status["outputs"]
    fg_pattern = out.get("fg_despill") or out["fg"]
    label = "<b>{}</b>\\n{} - {}x{} - {:.3f} fps - frames {}-{}\\n{}".format(
        names["tag"], time.strftime("%Y-%m-%d %H:%M"), p["width"], p["height"], p["fps"],
        p["first"], p["last"], "despilled fg" if out.get("fg_despill") else "fg (no despill)")
    nk = ("BackdropNode {{\n inputs 0\n name {bd}\n label \"{label}\"\n note_font_size 14\n"
          " tile_color 0x3d5a45ff\n xpos {bx}\n ypos {by}\n bdwidth {bw}\n bdheight {bh}\n}}\n").format(
        bd=names["backdrop"], label=label, bx=x0 - DX - 40, by=y0 - 90, bw=4 * DX + 120, bh=3 * DY + 180)
    nk += _read_nk(p["pattern"], p, names["plate"], x0, y0, cs)
    nk += _read_nk(out["alpha"], p, names["alpha"], x0 + 2 * DX, y0, cs)
    nk += "set N_alpha [stack 0]\n"
    nk += _read_nk(fg_pattern, p, names["fg"], x0 + DX, y0, cs)
    nk += "set N_fg [stack 0]\n"
    # Copy: input 0 (B) = fg, input 1 (A) = alpha. The alpha EXR is single-channel,
    # which Nuke reads into red.
    nk += "push $N_alpha\npush $N_fg\n"
    nk += ("Copy {{\n inputs 2\n from0 rgba.red\n to0 rgba.alpha\n name {}\n xpos {}\n ypos {}\n}}\n"
           "Premult {{\n name {}\n xpos {}\n ypos {}\n}}\nset N_premult [stack 0]\n").format(
        names["copy"], x0 + DX, y0 + DY, names["premult"], x0 + DX, y0 + 2 * DY)
    nk += ("Constant {{\n inputs 0\n channels rgb\n color {{0.18 0.18 0.18 1}}\n format {fmt}\n"
           " name {bg}\n xpos {x}\n ypos {y}\n}}\nset N_bg [stack 0]\n").format(
        fmt=_fmt(p), bg=names["bg"], x=x0 - DX, y=y0 + 2 * DY)
    # Merge: input 0 (B) = background, input 1 (A) = premultiplied subject.
    nk += "push $N_premult\npush $N_bg\n"
    nk += "Merge2 {{\n inputs 2\n operation over\n name {}\n xpos {}\n ypos {}\n}}\n".format(
        names["over"], x0 + DX, y0 + 3 * DY)
    return nk


def load_result(status):
    if status.get("stage") == "prepare" or "outputs" not in status:
        return load_plate(status)
    shot = os.path.basename(status.get("shot_dir", "shot").rstrip("/\\"))
    tag = "CK2_{}_{}".format(shot, status.get("version", "key"))
    names = {"tag": tag}
    for part in ("backdrop", "plate", "fg", "alpha", "copy", "premult", "bg", "over"):
        names[part] = nc.unique("{}_{}".format(tag, part))
    x0, y0 = _origin()
    nc.deselect_all()
    nc.paste(comp_nk(status, names, x0, y0, nc.linear_colorspace()))
    p = status["plate"]
    try:
        fps = nuke.root()["fps"].value()
        if abs(fps - p["fps"]) > 0.001:
            print("[CorridorKey 2.0] note: script fps {} differs from the shot's {:.3f}".format(fps, p["fps"]))
    except Exception:
        pass
    return names["over"]


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

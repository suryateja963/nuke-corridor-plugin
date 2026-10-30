"""The Key shot panel: collects settings, renders a Roto hint if asked, writes job.json, starts the run."""

import json
import os
import re

import nuke

from . import settings
from . import runner

# (label shown in the panel, ck_engine colour key)
COLOUR_SPACES = [
    ("sRGB / Rec.709 video (phone, most cameras)", "srgb_rec709"),
    ("Linear Rec.709 (EXR plates)", "linear_rec709"),
    ("ACEScg (linear AP1 EXR)", "acescg"),
    ("Sony S-Log3 / S-Gamut3", "slog3_sgamut3"),
    ("Sony S-Log3 / S-Gamut3.Cine", "slog3_sgamut3cine"),
    ("Panasonic V-Log / V-Gamut", "vlog_vgamut"),
    ("Apple Log", "applelog"),
    ("HLG HDR phone video", "hlg_rec2020"),
    ("PQ HDR (HDR10 / Dolby Vision base)", "pq_rec2020"),
    ("Auto (HDR from file, else sRGB)", "auto"),
    ("Other: OCIO colour space by name", "ocio"),
]
HINT_MODES = [
    ("None (model picks the subject)", "none", None),
    ("Selected node, first frame (e.g. Roto)", "first_frame", "node"),
    ("Selected node, every frame", "sequence", "node"),
    ("Matte file, first frame", "first_frame", "file"),
    ("Matte file / sequence, every frame", "sequence", "file"),
]
WINDOWS = ["auto", "24", "16", "8", "4"]
NC_MAX_W, NC_MAX_H = 1920, 1080


def _selection():
    """(read, hint_node) from the selection. Uses selectedNodes only (NC-safe)."""
    try:
        nodes = nuke.selectedNodes()
    except Exception:
        nodes = []
    read = next((n for n in nodes if n.Class() == "Read"), None)
    hint = next((n for n in nodes if n is not read and n.Class() not in ("Viewer", "BackdropNode")), None)
    return read, hint


def _guess_shot(path):
    norm = path.replace("\\", "/")
    m = re.search(r"/([^/]+)/plate_lin/", norm)
    if m:
        return m.group(1), os.path.dirname(norm.split("/plate_lin/")[0])
    base = os.path.basename(norm)
    name = re.sub(r"[._]?(#+|%0?\d*d|\d+)?\.[^.]+$", "", base) or "shot"
    return re.sub(r"[^A-Za-z0-9_-]+", "_", name).strip("_") or "shot", None


class KeyPanel(nuke.PythonPanel):
    def __init__(self, read, hint_node, prepare_only):
        nuke.PythonPanel.__init__(self, "CorridorKey 2.0 - Key shot", "uk.co.ck2.keyshot")
        cfg = settings()
        self.read = read
        k = self.k = {}

        def add(knob, newline=True):
            if newline:
                knob.setFlag(nuke.STARTLINE)
            self.addKnob(knob)
            k[knob.name()] = knob
            return knob

        add(nuke.Text_Knob("h_src", "<b>Source</b>", ""))
        add(nuke.Enumeration_Knob("src_mode", "source", ["Selected Read", "File on disk"]))
        add(nuke.File_Knob("src_file", "file"))
        add(nuke.Text_Knob("src_info", "", ""))

        add(nuke.Text_Knob("h_shot", "<b>Shot</b>", ""))
        add(nuke.String_Knob("shot_name", "shot name"))
        add(nuke.File_Knob("shot_root", "shots folder"))
        k["shot_root"].setValue(cfg["shot_root"])

        add(nuke.Text_Knob("h_col", "<b>Colour</b>", ""))
        add(nuke.Enumeration_Knob("colour", "colour space", [c[0] for c in COLOUR_SPACES]))
        add(nuke.String_Knob("ocio_name", "OCIO name"))
        add(nuke.Enumeration_Knob("matrix", "YUV matrix", ["auto", "bt709", "bt601", "bt2020"]))
        add(nuke.Enumeration_Knob("range", "range", ["auto", "limited", "full"]), newline=False)
        add(nuke.Enumeration_Knob("gamut", "out-of-gamut", ["clamp", "keep"]), newline=False)

        add(nuke.Text_Knob("h_frames", "<b>Frames</b>", ""))
        add(nuke.Int_Knob("first", "first"))
        add(nuke.Int_Knob("last", "last"), newline=False)
        add(nuke.Text_Knob("frames_note", "", "0 / 0 = whole clip"), newline=False)
        add(nuke.Int_Knob("start_frame", "plate starts at"))
        k["start_frame"].setValue(1001)
        add(nuke.Boolean_Knob("preview", "preview only"))
        add(nuke.Int_Knob("preview_frames", "frames"), newline=False)
        k["preview_frames"].setValue(24)

        add(nuke.Text_Knob("h_hint", "<b>Hint</b>", ""))
        add(nuke.Enumeration_Knob("hint_mode", "hint", [h[0] for h in HINT_MODES]))
        add(nuke.String_Knob("hint_node", "node"))
        add(nuke.File_Knob("hint_file", "matte file"))
        add(nuke.Boolean_Knob("hint_invert", "invert"))
        add(nuke.Double_Knob("hint_quality", "hint quality"))
        k["hint_quality"].setRange(0.0, 1.0)
        k["hint_quality"].setValue(0.95)
        add(nuke.Text_Knob("q_note", "", "0.95 careful roto - 0.75 rough matte - 0.5 scribble"))

        add(nuke.Text_Knob("h_out", "<b>Output</b>", ""))
        add(nuke.Double_Knob("despill", "despill"))
        k["despill"].setRange(0.0, 1.0)
        k["despill"].setValue(0.5)
        add(nuke.Enumeration_Knob("screen", "screen", ["green", "blue"]), newline=False)
        add(nuke.Enumeration_Knob("window", "window", WINDOWS))
        add(nuke.Boolean_Knob("low_vram", "low VRAM"), newline=False)
        add(nuke.Boolean_Knob("prepare_only", "prepare plate only (then draw a Roto on it)"))
        k["prepare_only"].setValue(bool(prepare_only))

        if read is not None:
            path = read["file"].value()
            k["src_info"].setValue("{}  ({}-{}, {}x{})".format(
                os.path.basename(path), int(read["first"].value()), int(read["last"].value()),
                read.width(), read.height()))
            k["first"].setValue(int(read["first"].value()))
            k["last"].setValue(int(read["last"].value()))
            if path.lower().endswith(".exr"):
                k["colour"].setValue(COLOUR_SPACES[1][0])
            name, root = _guess_shot(path)
            k["shot_name"].setValue(name)
            if root:
                k["shot_root"].setValue(root)
        else:
            k["src_mode"].setValue("File on disk")
            k["src_info"].setValue("No Read selected. MP4/MOV: pick the file here (NC can't read it).")
        if hint_node is not None:
            k["hint_node"].setValue(hint_node.name())
            k["hint_mode"].setValue(HINT_MODES[1][0])
        self._refresh()

    def knobChanged(self, knob):
        if knob.name() == "src_file" and not self.k["shot_name"].value():
            self.k["shot_name"].setValue(_guess_shot(knob.value())[0])
        self._refresh()

    def _refresh(self):
        k = self.k
        from_file = k["src_mode"].value() == "File on disk" or self.read is None
        k["src_file"].setVisible(from_file)
        k["ocio_name"].setVisible(self.colour_key() == "ocio")
        src = self.hint_source()
        k["hint_node"].setVisible(src == "node")
        k["hint_file"].setVisible(src == "file")
        k["hint_invert"].setVisible(src is not None)
        k["hint_quality"].setVisible(src is not None)
        k["preview_frames"].setEnabled(k["preview"].value())

    def colour_key(self):
        label = self.k["colour"].value()
        return next(key for lab, key in COLOUR_SPACES if lab == label)

    def hint_entry(self):
        label = self.k["hint_mode"].value()
        return next(h for h in HINT_MODES if h[0] == label)

    def hint_source(self):
        return self.hint_entry()[2]


def _source_path(panel):
    k = panel.k
    if k["src_mode"].value() == "Selected Read" and panel.read is not None:
        raw = panel.read["file"].value()
        # A path with TCL/Python expressions: hand the engine one evaluated
        # frame; it finds the rest of the sequence from it.
        return panel.read["file"].evaluate() if "[" in raw else raw
    return k["src_file"].value()


def _render_hint(node, shot_dir, first, last, mode):
    """Renders `node` (white = subject) to 16-bit PNGs. NC renders at most
    1920x1080, so larger plates are scaled down here and back up by the engine."""
    out_dir = os.path.join(shot_dir, "hint", "nuke_render").replace("\\", "/")
    if not os.path.isdir(out_dir):
        os.makedirs(out_dir)
    for f in os.listdir(out_dir):
        os.remove(os.path.join(out_dir, f))
    created = []
    try:
        src = node
        w, h = node.width(), node.height()
        if w > NC_MAX_W or h > NC_MAX_H:
            scale = min(float(NC_MAX_W) / w, float(NC_MAX_H) / h)
            ref = nuke.nodes.Reformat(inputs=[node])
            ref["type"].setValue("scale")
            ref["scale"].setValue(scale)
            ref["filter"].setValue("Cubic")
            created.append(ref)
            src = ref
        write = nuke.nodes.Write(inputs=[src])
        created.append(write)
        pattern = out_dir + "/hint.####.png"
        write["file"].setValue(pattern)
        write["file_type"].setValue("png")
        write["datatype"].setValue("16 bit")
        write["channels"].setValue("rgba")
        if mode == "first_frame":
            nuke.execute(write, first, first)
        else:
            nuke.execute(write, first, last)
        return pattern
    finally:
        for n in created:
            nuke.delete(n)


def key_shot(prepare_only=False):
    read, hint_node = _selection()
    panel = KeyPanel(read, hint_node, prepare_only)
    if not panel.showModalDialog():
        return
    k = panel.k
    try:
        src_path = _source_path(panel)
        if not src_path:
            raise ValueError("Pick a source: select a Read node or choose a file.")
        shot_name = k["shot_name"].value() or _guess_shot(src_path)[0]
        shot_name = re.sub(r"[^A-Za-z0-9_-]+", "_", shot_name).strip("_")
        if not shot_name:
            raise ValueError("Enter a shot name.")
        root = k["shot_root"].value().rstrip("/\\")
        if not root:
            raise ValueError("Choose a shots folder.")
        shot_dir = os.path.join(root, shot_name).replace("\\", "/")
        if not os.path.isdir(shot_dir):
            os.makedirs(shot_dir)

        first, last = int(k["first"].value()), int(k["last"].value())
        use_range = not (first == 0 and last == 0)
        if use_range and first > last:
            raise ValueError("First frame is after the last frame.")
        preview = int(k["preview_frames"].value()) if k["preview"].value() else 0

        mode, src_kind = panel.hint_entry()[1], panel.hint_entry()[2]
        hint_path = None
        stage = "prepare" if k["prepare_only"].value() else "all"
        if stage == "all" and src_kind == "node":
            node = nuke.toNode(k["hint_node"].value())
            if node is None:
                raise ValueError("Hint node '{}' not found.".format(k["hint_node"].value()))
            if not use_range:
                raise ValueError("Set the frame range (first/last) to render the hint over.")
            r_last = last if not preview else min(last, first + preview - 1)
            hint_path = _render_hint(node, shot_dir, first, r_last, mode)
        elif stage == "all" and src_kind == "file":
            hint_path = k["hint_file"].value()
            if not hint_path:
                raise ValueError("Choose a matte file for the hint.")

        job = {
            "schema_version": 1,
            "stage": stage,
            "shot_dir": shot_dir,
            "source": {"path": src_path},
            "colour": {"space": panel.colour_key(), "matrix": k["matrix"].value(),
                       "range": k["range"].value(), "gamut": k["gamut"].value(),
                       "ocio_name": k["ocio_name"].value() or None},
            "frames": {"first": first if use_range else None, "last": last if use_range else None,
                       "start_frame": int(k["start_frame"].value()), "preview_frames": preview},
            "hint": {"mode": mode if (stage == "all" and hint_path) else "none", "path": hint_path,
                     "invert": bool(k["hint_invert"].value()),
                     "quality": float(k["hint_quality"].value()), "carry": True},
            "despill": {"amount": float(k["despill"].value()), "screen": k["screen"].value()},
            "engine": {"window": "auto" if k["window"].value() == "auto" else int(k["window"].value()),
                       "low_vram": bool(k["low_vram"].value())},
        }
        from ck_engine.jobio import validate
        validate(json.loads(json.dumps(job)))
    except Exception as exc:
        nuke.message("CorridorKey 2.0: {}".format(exc))
        return

    job_path = os.path.join(shot_dir, "job.json")
    for stale in ("status.json", "CANCEL"):
        p = os.path.join(shot_dir, stale)
        if os.path.exists(p):
            os.remove(p)
    with open(job_path, "w", encoding="utf-8") as f:
        json.dump(job, f, indent=2)
    runner.start(job_path, title="CorridorKey 2.0 - {}".format(shot_name))

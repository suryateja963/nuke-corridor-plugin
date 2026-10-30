"""Node access that works within Nuke Non-commercial's Python limit.

NC hands Python at most 10 Node objects per session, ever: the 11th
nuke.nodes.X() / nuke.toNode() / nuke.selectedNodes() entry comes back as None,
and dropping references doesn't free any (measured in Nuke 17.1v2, see
docs/nuke_env.md). So this tool never holds Node objects. It works with node
names through TCL, nuke.exists() and nuke.expression(), and creates nodes by
pasting .nk text with nuke.nodePaste(), none of which count.
"""

import os
import tempfile

import nuke


def exists(name):
    return bool(name) and nuke.exists(name)


def value(name, knob):
    return nuke.tcl("value {}.{}".format(name, knob))


def node_class(name):
    return nuke.tcl("class {}".format(name))


def size(name):
    return int(nuke.expression(name + ".width")), int(nuke.expression(name + ".height"))


def pos(name):
    return int(float(value(name, "xpos"))), int(float(value(name, "ypos")))


def _selected_ids():
    # TCL raises "No nodes selected" instead of returning an empty list.
    try:
        return nuke.tcl("selected_nodes").split()
    except RuntimeError:
        return []


def selected():
    """Names of the selected nodes (TCL returns internal ids; resolve each to its name)."""
    names = []
    for ident in _selected_ids():
        try:
            names.append(nuke.tcl("value {}.name".format(ident)))
        except Exception:
            pass
    return names


def deselect_all():
    for ident in _selected_ids():
        nuke.tcl("knob {}.selected false".format(ident))


def select(name):
    nuke.tcl("knob {}.selected true".format(name))


def delete(name):
    if exists(name):
        nuke.tcl("delete {}".format(name))


def execute(name, first, last):
    nuke.tcl("execute {} {}-{}".format(name, int(first), int(last)))


def unique(base):
    name, i = base, 1
    while exists(name):
        i += 1
        name = "{}{}".format(base, i)
    return name


def q(text):
    """Quote a string for .nk text: forward slashes, and escape characters TCL would expand."""
    s = str(text).replace("\\", "/")
    for ch in ('"', "[", "]", "$"):
        s = s.replace(ch, "\\" + ch)
    return '"' + s.replace("\n", "\\n") + '"'


def paste(nk_text):
    """Creates nodes from .nk text. Nodes with an open input connect to the selected node."""
    fd, path = tempfile.mkstemp(prefix="ck2_", suffix=".nk")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(nk_text)
    try:
        nuke.nodePaste(path)
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def linear_colorspace():
    """Name of linear Rec.709 in the script's colour management."""
    try:
        root = nuke.root()
        cm = root["colorManagement"].value()
        config = root["OCIO_config"].value()
    except Exception:
        return "linear"
    if cm == "Nuke" or config == "nuke-default":
        return "linear"
    return "Linear Rec.709 (sRGB)"

r"""Probe: how does Nuke NC's "10-node limit for Node objects accessible in Python" count?
Writes _g2_out\nc_probe.txt. Run via tests\run_nuke_auto.ps1 -Module nc_limit_probe."""

import gc
import os

import nuke

OUT = r"D:\nuke plugin\_g2_out\nc_probe.txt"
lines = []


def log(msg):
    lines.append(msg)
    with open(OUT, "w") as f:
        f.write("\n".join(lines) + "\n")


def run():
    # A: create nodes, drop the Python reference each time.
    got = []
    for i in range(12):
        n = nuke.nodes.NoOp(name="probeA%d" % i)
        got.append(n is not None)
        del n
        gc.collect()
    log("A create+drop ref x12: %s" % got)

    # B: are nodes pasted from a .nk file counted? (paste 12, no Python objects)
    nk = os.path.join(os.path.dirname(OUT), "probe_paste.nk")
    with open(nk, "w") as f:
        for i in range(12):
            f.write("NoOp {\n inputs 0\n name probeB%d\n xpos %d\n ypos 300\n}\n" % (i, i * 110))
    try:
        r = nuke.nodePaste(nk)
        log("B nodePaste 12 nodes: ok, returned %r" % (type(r).__name__,))
    except Exception as exc:
        log("B nodePaste failed: %s" % exc)

    # C: after that, can we still get a node object? (toNode of a pasted node, selectedNodes)
    t = nuke.toNode("probeB0")
    log("C toNode after paste: %s" % (t is not None))
    try:
        sel = nuke.selectedNodes()
        log("C selectedNodes count after paste: %d (Nones: %d)" % (len(sel), sum(1 for s in sel if s is None)))
    except Exception as exc:
        log("C selectedNodes failed: %s" % exc)

    # D: nuke.tcl / knob access without node objects
    try:
        v = nuke.tcl("value probeB3.name")
        log("D tcl value of a pasted node: %r" % v)
    except Exception as exc:
        log("D tcl failed: %s" % exc)
    try:
        nuke.tcl("knob probeB3.label hello")
        log("D tcl set knob: %r" % nuke.tcl("value probeB3.label"))
    except Exception as exc:
        log("D tcl set failed: %s" % exc)

    # E: root and colour management (needed to name the linear colourspace)
    try:
        root = nuke.root()
        log("E root ok=%s colorManagement=%r OCIO_config=%r" % (
            root is not None, root["colorManagement"].value(), root["OCIO_config"].value()))
    except Exception as exc:
        log("E root failed: %s" % exc)
    log("DONE")

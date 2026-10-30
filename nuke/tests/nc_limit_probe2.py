r"""Probe 2: TCL / name-based calls the tool needs, run AFTER using up NC's 10 node objects.
Writes _g2_out\nc_probe2.txt."""

import os

import nuke

OUT = r"D:\nuke plugin\_g2_out\nc_probe2.txt"
DIR = os.path.dirname(OUT).replace("\\", "/")
lines = []


def log(msg):
    lines.append(str(msg))
    with open(OUT, "w") as f:
        f.write("\n".join(lines) + "\n")


def step(name, fn):
    try:
        log("%s: %r" % (name, fn()))
    except Exception as exc:
        log("%s: FAILED %s: %s" % (name, type(exc).__name__, exc))


def paste(text):
    path = DIR + "/probe2_paste.nk"
    with open(path, "w") as f:
        f.write(text)
    return nuke.nodePaste(path)


def run():
    for i in range(10):
        nuke.nodes.NoOp(name="burn%d" % i)
    log("burned 10 node objects; toNode now: %r" % (nuke.toNode("burn0") is not None))

    step("paste Constant 4K", lambda: paste(
        'Constant {\n inputs 0\n channels rgb\n color {1 0 0 1}\n format "3840 2160 0 0 3840 2160 1 UHD_4K"\n'
        ' name src\n xpos 0\n ypos 0\n}\n'))
    step("nuke.exists('src')", lambda: nuke.exists("src"))
    step("nuke.expression('src.width')", lambda: nuke.expression("src.width"))
    step("tcl class src", lambda: nuke.tcl("class src"))
    step("tcl value src.xpos", lambda: nuke.tcl("value src.xpos"))
    step("deselect all (tcl)", lambda: nuke.tcl("selectAll; selectNone") if False else nuke.selectAll() or nuke.invertSelection())
    step("tcl knob src.selected true", lambda: nuke.tcl("knob src.selected true"))
    step("tcl selected_nodes", lambda: nuke.tcl("selected_nodes"))
    step("nuke.selectedNodes len", lambda: len(nuke.selectedNodes()))

    png = DIR + "/probe2.####.png"
    step("paste Reformat+Write onto selected src", lambda: paste(
        'Reformat {\n type scale\n scale 0.5\n name pr\n}\n'
        'Write {\n file "%s"\n file_type png\n datatype "16 bit"\n channels rgba\n name pw\n}\n' % png))
    step("tcl input of pw", lambda: nuke.tcl("value [input pw 0].name"))
    step("tcl input of pr", lambda: nuke.tcl("value [input pr 0].name"))
    step("tcl execute pw 1-1", lambda: nuke.tcl("execute pw 1-1"))
    step("png written (tcl)", lambda: os.path.isfile(png.replace("####", "0001")))
    if not os.path.isfile(png.replace("####", "0001")):
        step("nuke.execute('pw',1,1)", lambda: nuke.execute("pw", 1, 1))
        step("png written (nuke.execute)", lambda: os.path.isfile(png.replace("####", "0001")))
    if os.path.isfile(png.replace("####", "0001")):
        with open(png.replace("####", "0001"), "rb") as f:
            h = f.read(26)
        import struct
        log("png size/depth: %r" % (struct.unpack(">II", h[16:24]) + (h[24],)))
    step("tcl delete pw pr", lambda: nuke.tcl("delete pw; delete pr"))
    step("exists pw after delete", lambda: nuke.exists("pw"))
    step("nuke.sample by name", lambda: nuke.sample("src", "rgba.red", 10, 10))
    log("DONE")

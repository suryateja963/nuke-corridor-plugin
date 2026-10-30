"""A small stand-in for Nuke's `nuke` module, enough to run ck2nuke's logic
outside Nuke. It records what the tool does; it says nothing about whether real
Nuke (NC) allows it - that is Gate G2's job."""

import os
import sys
import types

STARTLINE = 0x1000
messages = []
asks = []
created = []
deleted = []
executed = []
_formats = []
_by_name = {}
selected = []
panel_ok = True
panel_hook = None  # fn(panel) called before showModalDialog returns


class Knob:
    def __init__(self, name="", label="", values=None, *a):
        self._name = name
        self._value = None
        self._values = list(values) if isinstance(values, (list, tuple)) else []
        if self._values:
            self._value = self._values[0]
        self.visible = True

    def name(self):
        return self._name

    def value(self):
        return self._value

    def setValue(self, v):
        self._value = v

    def values(self):
        return self._values

    def evaluate(self):
        return self._value

    def fromUserText(self, text):
        self._value = text.rsplit(" ", 1)[0]

    def setVisible(self, v):
        self.visible = v

    def setEnabled(self, v):
        pass

    def setFlag(self, f):
        pass

    def setRange(self, a, b):
        pass


class Enumeration_Knob(Knob):
    pass


def _with_default(default):
    class K(Knob):
        def __init__(self, name="", label="", *a):
            Knob.__init__(self, name, label)
            self._value = default
    return K


# Nuke's own defaults: empty strings, 0, False.
File_Knob = String_Knob = _with_default("")
Int_Knob = _with_default(0)
Double_Knob = _with_default(0.0)
Boolean_Knob = _with_default(False)


class Text_Knob(Knob):
    def __init__(self, name="", label="", text=""):
        Knob.__init__(self, name, label)
        self._value = text


class Node:
    def __init__(self, cls, inputs=None, **kw):
        self._cls = cls
        self.inputs = inputs or []
        self.knobs = {}
        self.w, self.h = kw.pop("_size", (1920, 1080))
        for k, v in kw.items():
            self[k].setValue(v)
        if cls == "Read":
            self["colorspace"]._values = ["default", "Utility/linear", "sRGB"]
        if "name" not in kw:
            n = 1
            while f"{cls}{n}" in _by_name:
                n += 1
            self["name"].setValue(f"{cls}{n}")
        _by_name[self["name"].value()] = self
        created.append(self)

    def __getitem__(self, k):
        return self.knobs.setdefault(k, Knob(k))

    def knob(self, k):
        return self[k]

    def name(self):
        return self["name"].value()

    def Class(self):
        return self._cls

    def width(self):
        return self.w

    def height(self):
        return self.h

    def setXYpos(self, x, y):
        self.xy = (x, y)

    def xpos(self):
        return getattr(self, "xy", (0, 0))[0]

    def ypos(self):
        return getattr(self, "xy", (0, 0))[1]


class _Nodes:
    def __getattr__(self, cls):
        return lambda inputs=None, **kw: Node(cls, inputs, **kw)


nodes = _Nodes()


class PythonPanel:
    def __init__(self, title="", id=""):
        self._knobs = []

    def addKnob(self, k):
        self._knobs.append(k)

    def showModalDialog(self):
        if panel_hook:
            panel_hook(self)
        return panel_ok


class ProgressTask:
    log = []

    def __init__(self, title):
        ProgressTask.log.append(("title", title))
        self.cancel_after = None

    def isCancelled(self):
        return False

    def setProgress(self, p):
        ProgressTask.log.append(("progress", p))

    def setMessage(self, m):
        ProgressTask.log.append(("message", m))


class _Format:
    def __init__(self, spec):
        self._name = spec.split()[-1]

    def name(self):
        return self._name


def addFormat(spec):
    _formats.append(_Format(spec))


def formats():
    return list(_formats)


def message(m):
    messages.append(m)


def ask(m):
    asks.append(m)
    return True


def toNode(name):
    return _by_name.get(name)


def selectedNodes():
    return list(selected)


def delete(n):
    deleted.append(n)
    _by_name.pop(n.name(), None)


def execute(node, first, last, incr=1):
    """Write nodes: render a white square mask (alpha) as 16-bit PNG per frame."""
    executed.append((node.name(), first, last))
    import numpy as np
    import cv2
    pattern = node["file"].value()
    src = node.inputs[0]
    w, h = src.width(), src.height()
    scale = float(src["scale"].value()) if src.Class() == "Reformat" else 1.0
    if src.Class() == "Reformat":
        w, h = round(src.inputs[0].width() * scale), round(src.inputs[0].height() * scale)
    for f in range(first, last + 1):
        img = np.zeros((h, w, 4), np.uint16)
        img[h // 4: 3 * h // 4, w // 4: 3 * w // 4] = 65535
        cv2.imwrite(pattern.replace("####", f"{f:04d}"), img)


def executeInMainThread(fn, args=(), kwargs=None):
    fn(*args, **(kwargs or {}))


def connectViewer(i, n):
    pass


class _Root:
    def __getitem__(self, k):
        kn = Knob(k)
        kn.setValue(24.0)
        return kn


def root():
    return _Root()


def getFilename(msg, *a, **kw):
    return None


def install():
    sys.modules["nuke"] = sys.modules[__name__]

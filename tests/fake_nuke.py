"""A small stand-in for Nuke's `nuke` and `nukescripts` modules, enough to run
ck2nuke's logic outside Nuke. It records what the tool does; it says nothing
about whether real Nuke (NC) allows it. tests\run_nuke_auto.ps1 tests that in
real Nuke.

Emulates the name-based API the tool uses because of NC's 10-Node-object limit:
nuke.exists, nuke.expression("X.width"), a few TCL commands, and nuke.nodePaste
of .nk text (stack rule: the node on top of the stack becomes input 0).
"""

import re
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
selected = []          # node names
panel_ok = True
panel_hook = None      # fn(panel) called before showModalDialog returns
root_settings = {"colorManagement": "Nuke", "OCIO_config": "nuke-default", "fps": 24.0}


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
        self.inputs = list(inputs or [])
        self.knobs = {}
        self.w, self.h = kw.pop("_size", (1920, 1080))
        for k, v in kw.items():
            self[k].setValue(v)
        if "name" not in kw:
            n = 1
            while f"{cls}{n}" in _by_name:
                n += 1
            self["name"].setValue(f"{cls}{n}")
        _by_name[self.name()] = self
        created.append(self)

    def __getitem__(self, k):
        return self.knobs.setdefault(k, Knob(k))

    def name(self):
        return self["name"].value()

    def Class(self):
        return self._cls

    def width(self):
        return self.w

    def height(self):
        return self.h


class _Nodes:
    def __getattr__(self, cls):
        return lambda inputs=None, **kw: Node(cls, inputs, **kw)


nodes = _Nodes()


# Real Nuke has no nuke.PythonPanel; it is nukescripts.PythonPanel (see install).
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

    def isCancelled(self):
        return False

    def setProgress(self, p):
        ProgressTask.log.append(("progress", p))

    def setMessage(self, m):
        ProgressTask.log.append(("message", m))


def message(m):
    messages.append(m)


def ask(m):
    asks.append(m)
    return True


def exists(name):
    return name in _by_name


def expression(expr):
    name, attr = expr.split(".")
    n = _by_name[name]
    return float(n.w if attr == "width" else n.h)


def _input_name(name, i):
    n = _by_name[name]
    return n.inputs[i].name() if i < len(n.inputs) and n.inputs[i] else ""


def tcl(cmd):
    cmd = cmd.strip()
    m = re.fullmatch(r"value \[input (\S+) (\d+)\]\.name", cmd)
    if m:
        return _input_name(m.group(1), int(m.group(2)))
    if cmd == "selected_nodes":
        if not selected:
            raise RuntimeError("No nodes selected")  # what real Nuke's TCL does
        return " ".join(selected)
    m = re.fullmatch(r"value (\S+?)\.(\w+)", cmd)
    if m:
        name, k = m.groups()
        if k == "name":
            return name
        return str(_by_name[name][k].value())
    m = re.fullmatch(r"class (\S+)", cmd)
    if m:
        return _by_name[m.group(1)].Class()
    m = re.fullmatch(r"knob (\S+?)\.selected (true|false)", cmd)
    if m:
        name, on = m.groups()
        if on == "true" and name not in selected:
            selected.append(name)
        if on == "false" and name in selected:
            selected.remove(name)
        return ""
    m = re.fullmatch(r"delete (\S+)", cmd)
    if m:
        n = _by_name.pop(m.group(1))
        deleted.append(n)
        if n.name() in selected:
            selected.remove(n.name())
        return ""
    m = re.fullmatch(r"execute (\S+) (-?\d+)-(-?\d+)", cmd)
    if m:
        execute(_by_name[m.group(1)], int(m.group(2)), int(m.group(3)))
        return ""
    m = re.fullmatch(r"filename (\S+)", cmd)
    if m:
        return str(_by_name[m.group(1)]["file"].value())
    raise NotImplementedError("fake tcl: " + cmd)


def _unquote(v):
    v = v.strip()
    if v.startswith('"') and v.endswith('"'):
        v = v[1:-1]
        v = re.sub(r"\\(.)", lambda m: "\n" if m.group(1) == "n" else m.group(1), v)
    return v


def nodePaste(path):
    """Parses the .nk subset the tool writes; connects an open first input to the
    selected node, like Nuke's paste."""
    with open(path, encoding="utf-8") as f:
        text = f.read()
    stack, vars_ = [], {}
    first_node = True
    pos = 0
    block = re.compile(r"(\w+) \{\n(.*?)\n\}\n", re.S)
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        m = re.fullmatch(r"set (\w+) \[stack 0\]", line)
        if m:
            vars_[m.group(1)] = stack[-1]
            i += 1
            continue
        m = re.fullmatch(r"push \$(\w+)", line)
        if m:
            stack.append(vars_[m.group(1)])
            i += 1
            continue
        m = re.fullmatch(r"(\w+) \{", line)
        if not m:
            raise ValueError("fake nodePaste can't parse: " + line)
        cls = m.group(1)
        knobs = {}
        i += 1
        while lines[i] != "}":
            k, _, v = lines[i].strip().partition(" ")
            knobs[k] = _unquote(v)
            i += 1
        i += 1
        n_inputs = int(knobs.pop("inputs", "1"))
        if cls == "BackdropNode":
            n_inputs = 0
        inputs = []
        if n_inputs and not stack and first_node and selected:
            inputs = [_by_name[selected[0]]]
        else:
            for _ in range(n_inputs):
                inputs.append(stack.pop() if stack else None)
        node = Node(cls, inputs)
        _by_name.pop(node.name())
        for k, v in knobs.items():
            node[k].setValue(v)
        _by_name[node.name()] = node
        if cls != "BackdropNode":
            stack.append(node)
        first_node = False
    return None


def execute(node, first, last, incr=1):
    """Write nodes: render a white square mask (alpha) as 16-bit PNG per frame."""
    import numpy as np
    import cv2
    executed.append((node.name(), first, last))
    src = node.inputs[0]
    if src.Class() == "Reformat":
        scale = float(src["scale"].value())
        w, h = round(src.inputs[0].width() * scale), round(src.inputs[0].height() * scale)
    else:
        w, h = src.width(), src.height()
    pattern = node["file"].value()
    for f in range(first, last + 1):
        img = np.zeros((h, w, 4), np.uint16)
        img[h // 4: 3 * h // 4, w // 4: 3 * w // 4] = 65535
        cv2.imwrite(pattern.replace("####", f"{f:04d}"), img)


def executeInMainThread(fn, args=(), kwargs=None):
    fn(*args, **(kwargs or {}))


class _Root:
    def __getitem__(self, k):
        kn = Knob(k)
        kn.setValue(root_settings.get(k, ""))
        return kn


def root():
    return _Root()


def getFilename(msg, *a, **kw):
    return None


def install():
    sys.modules["nuke"] = sys.modules[__name__]
    mod = types.ModuleType("nukescripts")
    mod.PythonPanel = PythonPanel
    sys.modules["nukescripts"] = mod

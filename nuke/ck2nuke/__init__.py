"""CorridorKey 2.0 inside Nuke (Non-commercial friendly).

Nuke never loads PyTorch or the model: this package writes a job.json, starts
the engine (ck_engine, in the CorridorKey venv) as a separate process, follows
its progress, and loads the resulting EXRs as Read nodes with a comp.

Only knob panels are used (no PySide), and only nodes the user selected or the
tool created are touched (NC limits how many nodes Python may retrieve).
"""

import json
import os
import sys

NUKE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(NUKE_DIR)
if REPO_ROOT not in sys.path:
    sys.path.append(REPO_ROOT)  # for ck_engine.jobio (standard library only)

VERSION = "0.1.0"


def settings():
    from ck_engine.config import DEFAULTS
    cfg = dict(DEFAULTS)
    for name in ("settings.json", "settings.local.json"):
        path = os.path.join(REPO_ROOT, name)
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as f:
                cfg.update(json.load(f))
    return cfg


def about():
    import nuke
    cfg = settings()
    nuke.message("CorridorKey 2.0 for Nuke {}\n\nTool folder: {}\nEngine python: {}\n"
                 "Shots folder: {}\n\nSettings: {}".format(
                     VERSION, REPO_ROOT, cfg["engine_python"], cfg["shot_root"],
                     os.path.join(REPO_ROOT, "settings.json")))

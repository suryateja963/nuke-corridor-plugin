"""Settings (engine paths) and the clean child-process environment."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SETTINGS_PATH = REPO_ROOT / "settings.json"
LOCAL_SETTINGS_PATH = REPO_ROOT / "settings.local.json"  # per-machine overrides, not in git

DEFAULTS = {
    "engine_python": "D:/CorridorKey2/venv/Scripts/python.exe",
    "upstream_root": "D:/CorridorKey2/upstream",
    "worker_script": "D:/CorridorKey2/ComfyUI-CorridorKey2/ck2/worker.py",
    "ffmpeg": "ffmpeg",
    "ffprobe": "ffprobe",
    "shot_root": "D:/CKShots",
    "nuke_blocking_run": False,
}


class EngineError(RuntimeError):
    """An error with a message meant for the artist, shown as-is in Nuke."""


def load_settings() -> dict:
    cfg = dict(DEFAULTS)
    for path in (SETTINGS_PATH, LOCAL_SETTINGS_PATH):
        if path.is_file():
            cfg.update(json.loads(path.read_text(encoding="utf-8")))
    return cfg


def find_tool(name: str) -> str:
    """Resolves ffmpeg/ffprobe from settings, then PATH."""
    path = shutil.which(name)
    if path is None:
        raise EngineError(f"{name} not found. Install ffmpeg (with ffprobe) or set its full "
                          f"path in {SETTINGS_PATH.name}.")
    return path


def check_engine(cfg: dict) -> None:
    """Same checks as the CK2 bridge, so a broken install fails before any work."""
    upstream = Path(cfg["upstream_root"])
    if not Path(cfg["engine_python"]).is_file():
        raise EngineError(f"CorridorKey venv python not found: {cfg['engine_python']}")
    if not (upstream / "corridorkey" / "runtime.py").is_file():
        raise EngineError(f"CorridorKey 2.0 upstream not found at {upstream}")
    if not (upstream / "weights" / "corridorkey_v2.safetensors").is_file():
        raise EngineError(f"CorridorKey weights missing; run scripts/download_weights.py in {upstream}")
    if not Path(cfg["worker_script"]).is_file():
        raise EngineError(f"CK2 worker not found: {cfg['worker_script']}")


def clean_env() -> dict:
    # Nuke (and some installers) set PYTHONPATH/PYTHONHOME; a venv python that
    # inherits them loads the wrong standard library.
    env = {k: v for k, v in os.environ.items() if k.upper() not in ("PYTHONPATH", "PYTHONHOME")}
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env

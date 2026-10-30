r"""Checks that this PC can run the CorridorKey 2.0 Nuke tool. Run it with the engine python:

    D:\CorridorKey2\venv\Scripts\python.exe "D:\nuke plugin\tools\check_setup.py"

Prints one PASS/FAIL line per check and exits 1 if anything failed. Reads the
same settings.json + settings.local.json as the tool.
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from ck_engine.config import clean_env, load_settings  # noqa: E402

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
results = []


def check(name, fn):
    try:
        ok, detail = fn()
    except Exception as exc:  # noqa: BLE001
        ok, detail = False, f"{type(exc).__name__}: {exc}"
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name:<34} {detail}")


cfg = load_settings()


def paths():
    up = Path(cfg["upstream_root"])
    need = {
        "engine python": Path(cfg["engine_python"]),
        "upstream code": up / "corridorkey" / "runtime.py",
        "CorridorKey weights": up / "weights" / "corridorkey_v2.safetensors",
        "foundation stats": up / "weights" / "foundation_stats.safetensors",
        "foundation models": up / "vfms",
        "CK2 worker": Path(cfg["worker_script"]),
    }
    missing = [f"{k} ({v})" for k, v in need.items() if not v.exists()]
    return not missing, "all present" if not missing else "missing: " + "; ".join(missing)


def ffmpeg():
    out = []
    for key in ("ffmpeg", "ffprobe"):
        r = subprocess.run([cfg[key], "-version"], capture_output=True, text=True, creationflags=NO_WINDOW)
        if r.returncode != 0:
            return False, f"{key} not runnable: {cfg[key]}"
        out.append(r.stdout.split("\n", 1)[0].split(" Copyright")[0])
    filters = subprocess.run([cfg["ffmpeg"], "-hide_banner", "-filters"], capture_output=True, text=True,
                             creationflags=NO_WINDOW).stdout
    if " zscale " not in filters:
        return False, out[0] + " - has no zscale filter; use a 'full' build (gyan.dev)"
    return True, out[0] + " (zscale ok)"


def gpu():
    code = ("import torch, sys;"
            "ok = torch.cuda.is_available();"
            "print(torch.__version__, torch.version.cuda, ok);"
            "p = torch.cuda.get_device_properties(0) if ok else None;"
            "print(p.name if p else '-', round(p.total_memory / 2**30, 1) if p else 0);"
            "x = torch.randn(1024, 1024, device='cuda') if ok else None;"
            "print(float((x @ x).sum()) if ok else 'no cuda')")
    r = subprocess.run([cfg["engine_python"], "-c", code], capture_output=True, text=True, timeout=300,
                       env=clean_env(), creationflags=NO_WINDOW)
    if r.returncode != 0:
        return False, (r.stderr.strip().splitlines() or ["torch failed"])[-1]
    ver, name = r.stdout.strip().splitlines()[:2]
    torch_v, cuda_v, ok = ver.split()
    if ok != "True":
        return False, f"torch {torch_v} (CUDA {cuda_v}) sees no GPU: update the NVIDIA driver (570 or newer)"
    gname, vram = name.rsplit(" ", 1)
    warn = "" if float(vram) >= 7.5 else "  - under 8 GB: tick Low VRAM, use window 8 or 4"
    return True, f"{gname}, {vram} GB, torch {torch_v} CUDA {cuda_v}{warn}"


def driver():
    r = subprocess.run(["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"],
                       capture_output=True, text=True, creationflags=NO_WINDOW)
    if r.returncode != 0:
        return False, "nvidia-smi not found: install the NVIDIA driver"
    v = r.stdout.strip().splitlines()[0]
    major = int(v.split(".")[0])
    return major >= 570, f"driver {v}" + ("" if major >= 570 else " - CUDA 12.8 needs 570 or newer")


def shots():
    root = Path(cfg["shot_root"])
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=root, delete=True):
        pass
    import shutil
    gb = shutil.disk_usage(root).free / 2**30
    return gb > 20, f"{root} writable, {gb:.0f} GB free" + ("" if gb > 20 else " - keep 20+ GB free for EXR plates")


def nuke_hook():
    init = Path(os.environ.get("USERPROFILE", "~")) / ".nuke" / "init.py"
    want = (REPO / "nuke").as_posix()
    text = init.read_text(encoding="utf-8") if init.is_file() else ""
    line = next((l for l in text.splitlines() if "CorridorKey 2.0 tool" in l), "")
    if not line:
        return False, f"not installed: run  \"{cfg['engine_python']}\" \"{REPO / 'install_nuke_hook.py'}\""
    return want in line, f"{init}" + ("" if want in line else f" points elsewhere: {line.strip()}")


print(f"CorridorKey 2.0 Nuke tool - setup check ({REPO})\n")
check("engine files", paths)
check("ffmpeg / ffprobe", ffmpeg)
check("NVIDIA driver", driver)
check("GPU from the engine python", gpu)
check("shots folder", shots)
check("Nuke menu hook", nuke_hook)
print("\nAll good - start Nuke and look for the CorridorKey 2.0 menu." if all(results)
      else "\nFix the FAIL lines above, then run this again.")
sys.exit(0 if all(results) else 1)

"""Starts the engine for a job.json and follows it with a Nuke progress bar.

Default: a background thread reads the engine's `PROGRESS <0-1> <msg>` lines and
drives nuke.ProgressTask, so Nuke stays usable; results load back on the main
thread via nuke.executeInMainThread. If Gate G2 showed background threads don't
work, set "nuke_blocking_run": true in settings.json: the same loop then runs on
the main thread (Nuke is busy until the key finishes, but Cancel still works).
"""

import json
import os
import queue
import subprocess
import sys
import threading
import time

import nuke

from . import REPO_ROOT, settings

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
_running = {}  # job_path -> Popen, so the same shot isn't started twice from one Nuke


def _clean_env():
    # Nuke's PYTHONPATH/PYTHONHOME must not leak into the venv python.
    env = {k: v for k, v in os.environ.items() if k.upper() not in ("PYTHONPATH", "PYTHONHOME")}
    # Nuke puts its own folder on PATH; its older msvcp140/OpenMP DLLs can then be picked up by
    # torch's fallback DLL search and fail with WinError 1114 (seen with Nuke 13.1).
    nuke_dir = os.path.normcase(os.path.dirname(os.path.abspath(sys.executable)))
    keys = [k for k in env if k.upper() == "PATH"]
    for k in keys:
        parts = [p for p in env[k].split(os.pathsep)
                 if p and not os.path.normcase(os.path.abspath(p)).startswith(nuke_dir)]
        env[k] = os.pathsep.join(parts)
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _spawn(job_path):
    cfg = settings()
    py = cfg["engine_python"]
    if not os.path.isfile(py):
        raise RuntimeError("CorridorKey venv python not found: {}\nFix engine_python in {}".format(
            py, os.path.join(REPO_ROOT, "settings.json")))
    return subprocess.Popen([py, "-u", "-m", "ck_engine.run", job_path], cwd=REPO_ROOT,
                            env=_clean_env(), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                            creationflags=CREATE_NO_WINDOW)


def _follow(proc, job_path, title):
    """Reads engine output, updates a ProgressTask, writes CANCEL on Cancel.
    Returns the final status dict."""
    q = queue.Queue()

    def pump():
        for line in proc.stdout:
            q.put(line.rstrip())
        q.put(None)

    threading.Thread(target=pump, daemon=True).start()
    task = nuke.ProgressTask(title)
    task.setMessage("starting engine")
    cancel_sent = False
    tail = []
    while True:
        if task.isCancelled() and not cancel_sent:
            open(os.path.join(os.path.dirname(job_path), "CANCEL"), "w").close()
            cancel_sent = True
            task.setMessage("cancelling...")
        try:
            line = q.get(timeout=0.2)
        except queue.Empty:
            continue
        if line is None:
            break
        tail.append(line)
        del tail[:-30]
        if line.startswith("PROGRESS "):
            parts = line.split(" ", 2)
            try:
                task.setProgress(int(float(parts[1]) * 100))
            except ValueError:
                pass
            if not cancel_sent and len(parts) > 2:
                task.setMessage(parts[2])
    proc.wait()
    proc.stdout.close()
    del task
    status_path = os.path.join(os.path.dirname(job_path), "status.json")
    try:
        with open(status_path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"state": "failed", "error": "engine ended without a status.json (code {}).\n{}".format(
            proc.returncode, "\n".join(tail[-8:]))}


def _finish(status, job_path):
    """Main thread: load results or explain what went wrong."""
    _running.pop(job_path, None)
    from . import loader
    state = status.get("state")
    log = os.path.join(os.path.dirname(job_path), "log.txt")
    if state == "done":
        try:
            loader.load_result(status)
        except Exception as exc:
            import traceback
            traceback.print_exc()
            nuke.message("CorridorKey 2.0: key finished, but loading it failed:\n{}".format(exc))
        warnings = status.get("warnings") or []
        if warnings:
            print("[CorridorKey 2.0] warnings:\n  " + "\n  ".join(warnings))
            nuke.message("CorridorKey 2.0: key {} finished, with notes:\n\n- {}".format(
                status.get("version", ""), "\n\n- ".join(warnings)))
    elif state == "cancelled":
        nuke.message("CorridorKey 2.0: cancelled.")
    else:
        nuke.message("CorridorKey 2.0 failed:\n\n{}\n\nFull log: {}".format(
            status.get("error") or "unknown error", log))


def start(job_path, title="CorridorKey 2.0"):
    job_path = os.path.abspath(job_path).replace("\\", "/")
    if job_path in _running and _running[job_path].poll() is None:
        nuke.message("CorridorKey 2.0: this shot is already keying.")
        return
    try:
        proc = _spawn(job_path)
    except Exception as exc:
        nuke.message("CorridorKey 2.0: could not start the engine:\n{}".format(exc))
        return
    _running[job_path] = proc

    if settings().get("nuke_blocking_run"):
        _finish(_follow(proc, job_path, title), job_path)
        return

    def worker():
        try:
            status = _follow(proc, job_path, title)
        except Exception as exc:  # never leave Nuke without an answer
            status = {"state": "failed", "error": "progress thread failed: {}".format(exc)}
        nuke.executeInMainThread(_finish, (status, job_path))

    threading.Thread(target=worker, name="CK2-run", daemon=True).start()
    print("[CorridorKey 2.0] keying in the background: {}".format(job_path))

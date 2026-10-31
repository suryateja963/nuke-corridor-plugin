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


# Variables Nuke (or its Python/Qt/OpenMP libraries) sets that the engine must not inherit.
_NUKE_VAR_PREFIXES = ("PYTHON", "NUKE", "FOUNDRY", "FN_", "QT_", "KMP_", "OMP_", "MKL_", "TCL_", "TK_",
                      "__COMPAT_LAYER")


def _windows_path():
    """PATH as a fresh shell gets it: the system PATH then the user PATH, from the registry."""
    import winreg
    parts = []
    for root, key in ((winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
                      (winreg.HKEY_CURRENT_USER, "Environment")):
        try:
            with winreg.OpenKey(root, key) as k:
                value = winreg.QueryValueEx(k, "Path")[0]
        except OSError:
            continue
        parts += [winreg.ExpandEnvironmentStrings(p) for p in value.split(";") if p.strip()]
    return ";".join(parts)


def _clean_env():
    # The engine runs as if started from a fresh shell. Inside Nuke 13.1, Nuke's own folders on PATH and
    # its library variables made torch fail to load (WinError 1114 on c10.dll) although the same python
    # worked from PowerShell.
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith(_NUKE_VAR_PREFIXES)}
    if os.name == "nt":
        try:
            fresh = _windows_path()
        except Exception:  # noqa: BLE001
            fresh = ""
        nuke_dir = os.path.normcase(os.path.dirname(os.path.abspath(sys.executable)))
        for k in [k for k in env if k.upper() == "PATH"]:
            del env[k]
        env["PATH"] = fresh or os.pathsep.join(
            p for p in os.environ.get("PATH", "").split(os.pathsep)
            if p and not os.path.normcase(os.path.abspath(p)).startswith(nuke_dir))
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _spawn(job_path):
    cfg = settings()
    py = cfg["engine_python"]
    if not os.path.isfile(py):
        raise RuntimeError("CorridorKey venv python not found: {}\nFix engine_python in {}".format(
            py, os.path.join(REPO_ROOT, "settings.json")))
    env = _clean_env()
    try:  # for diagnosing engine start-up problems on another PC
        with open(os.path.join(os.path.dirname(job_path), "engine_env.txt"), "w", encoding="utf-8") as f:
            f.write("nuke: {}\n".format(sys.executable))
            f.write("".join("{}={}\n".format(k, env[k]) for k in sorted(env)))
    except OSError:
        pass
    return subprocess.Popen([py, "-u", "-m", "ck_engine.run", job_path], cwd=REPO_ROOT,
                            env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
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

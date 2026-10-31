"""Run one keying job: python -m ck_engine.run <job.json>

prepare plate -> hint -> CK2 worker (upstream CorridorKey 2.0) -> rename outputs
-> despill -> status.json. Prints `PROGRESS <0-1> <message>` lines for Nuke's
progress bar; everything is also written to log.txt next to job.json. Cancel by
creating a file named CANCEL next to job.json (or Ctrl+C in the console).
"""

from __future__ import annotations

import ctypes
import glob
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path

from . import __version__
from .config import EngineError, check_engine, clean_env, find_tool, load_settings
from .jobio import JobError, Status, load_job, write_json_atomic

CANCEL_GRACE_S = 30
_WINDOW = re.compile(r"window (\d+)/(\d+)")

# Progress bands for each stage (start, end).
P_PREPARE = (0.0, 0.15)
P_HINT = (0.15, 0.17)
P_LOAD = (0.17, 0.20)
P_STAGE1 = (0.20, 0.60)
P_STAGE2 = (0.60, 0.95)


class Cancelled(Exception):
    pass


class GpuOutOfMemory(EngineError):
    pass


_CHUNK = re.compile(r"hann_chunk=(\d+)")
# Running out of memory shows up in several forms on Windows (seen on SHOT-113):
# torch's OutOfMemoryError, "fatal : Memory allocation failure" + "bad allocation",
# and a hard crash with an access violation.
_MEM_ERROR = re.compile(r"OutOfMemoryError|CUDA out of memory|bad allocation|Memory allocation failure|"
                        r"cudaErrorMemoryAllocation")
ACCESS_VIOLATION = (3221225477, -1073741819)  # 0xC0000005
_OOM_NUMBERS = re.compile(r"total capacity of ([\d.]+) GiB of which ([\d.]+) (GiB|MiB) is free.*?"
                          r"([\d.]+) GiB is allocated by PyTorch")


class Log:
    """Prints to the console (read by Nuke) and appends to log.txt."""

    def __init__(self, path: Path):
        self.f = open(path, "a", encoding="utf-8")

    def __call__(self, msg: str) -> None:
        print(msg, flush=True)
        self.f.write(msg + "\n")
        self.f.flush()

    def close(self) -> None:
        self.f.close()


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
    if not handle:
        return False
    code = ctypes.c_ulong()
    ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
    ctypes.windll.kernel32.CloseHandle(handle)
    return code.value == 259  # STILL_ACTIVE


def kill_tree(pid: int) -> None:
    subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], capture_output=True,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def next_version(key_dir: Path) -> str:
    nums = [int(m.group(1)) for p in key_dir.glob("v*") if (m := re.fullmatch(r"v(\d{3,})", p.name))]
    return f"v{(max(nums) + 1 if nums else 1):03d}"


class Runner:
    def __init__(self, job_path: Path):
        self.job_path = job_path.resolve()
        self.job_dir = self.job_path.parent
        self.cancel_file = self.job_dir / "CANCEL"
        self.log = Log(self.job_dir / "log.txt")
        self.status = Status(self.job_dir)
        self._hint_rough = False
        self._mem = None  # Windows memory headroom measured before keying

    # -- helpers ------------------------------------------------------------
    def progress(self, band, frac: float, msg: str) -> None:
        p = band[0] + (band[1] - band[0]) * max(0.0, min(1.0, frac))
        self.log(f"PROGRESS {p:.3f} {msg}")
        self.status.update(progress=round(p, 3), message=msg)

    def check_cancel(self) -> None:
        if self.cancel_file.exists():
            raise Cancelled()

    # -- main ---------------------------------------------------------------
    def run(self) -> int:
        self.log(f"=== CorridorKey 2.0 Nuke engine {__version__} - {time.strftime('%Y-%m-%d %H:%M:%S')}")
        self.log(f"job: {self.job_path}")
        if self.cancel_file.exists():
            self.cancel_file.unlink()
        lock = None
        work = None
        out = None  # key version folder; removed unless the key finishes
        try:
            job = load_job(self.job_path)
            shot = Path(job["shot_dir"]).resolve()
            shot.mkdir(parents=True, exist_ok=True)
            lock = self._lock(shot)
            cfg = load_settings()
            check_engine(cfg)
            ffmpeg, ffprobe = find_tool(cfg["ffmpeg"]), find_tool(cfg["ffprobe"])
            self.status.update(force=True, shot_dir=str(shot), stage=job["stage"])

            from .prepare import prepare_plate
            from .probe import probe
            self.progress(P_PREPARE, 0.0, "probing source")
            src = probe(job["source"]["path"], ffprobe)
            for w in src.warnings:
                self.log(f"WARNING {w}")
            self.log(f"source: {src.kind} {src.width}x{src.height} {src.fps:.3f} fps, "
                     f"{len(src.frames)} frames, {src.pix_fmt} {src.bit_depth}-bit, "
                     f"range={src.color_range or '?'} matrix={src.color_matrix or '?'} "
                     f"transfer={src.color_transfer or '?'}")
            plate = prepare_plate(src, job, shot, ffmpeg,
                                  progress=lambda f, m: self.progress(P_PREPARE, f, m),
                                  check_cancel=self.check_cancel)
            plate_info = {"pattern": plate.pattern_hashes, "first": plate.frames[0],
                          "last": plate.frames[-1], "count": len(plate.frames),
                          "width": plate.width, "height": plate.height, "fps": plate.fps,
                          "reused": plate.reused}
            self.status.update(force=True, plate=plate_info, warnings=plate.warnings)
            self.log(f"plate: {plate.pattern_hashes} {plate.frames[0]}-{plate.frames[-1]}"
                     f"{' (reused)' if plate.reused else ''}")
            if job["stage"] == "prepare":
                self.status.finish("done", message="plate ready")
                self.log("DONE plate ready")
                return 0

            preview = int(job["frames"].get("preview_frames") or 0) > 0
            key_dir = shot / "key"
            version = "preview" if preview else next_version(key_dir)
            out = key_dir / version
            if out.exists():
                shutil.rmtree(out)
            out.mkdir(parents=True)
            work = shot / "work" / f"job_{int(time.time())}"
            work.mkdir(parents=True)

            from .hints import prepare_hint
            self.progress(P_HINT, 0.0, "preparing hint")
            hint = prepare_hint(job, plate, shot, ffmpeg, ffprobe, check_cancel=self.check_cancel)
            self.check_cancel()
            self._check_hint(job, hint, plate)

            from . import crop as cropmod
            # A rough hint (mostly screen) would only widen the box and cost GPU memory.
            crop, how = cropmod.resolve(job, plate, {} if self._hint_rough else hint)
            self.log(f"crop: {how}")
            self.status.update(force=True, crop=list(crop) if crop else None)
            if crop:
                input_dir = cropmod.write_input(plate, crop, work / "input", self.check_cancel)
                hint = cropmod.crop_hint(hint, crop, plate, work)
                size = [crop[2], crop[3]]
            else:
                input_dir = self._link_plate(plate, work / "input")
                size = [plate.width, plate.height]
            raw_dir = out / "_raw"
            wjob = {
                "upstream_root": cfg["upstream_root"],
                "work_dir": str(work), "output_dir": str(raw_dir),
                "input_path": str(input_dir), "expected_frames": len(plate.frames),
                "frame_size": size,
                "keep_exr": True, "return_arrays": False,
                "settings": {
                    "window": job["engine"]["window"], "low_vram": bool(job["engine"]["low_vram"]),
                    "carry_hint": bool(job["hint"]["carry"]),
                    "hint_quality": float(job["hint"]["quality"]),
                    "max_frames": -1, "fps": plate.fps, "input_is_linear": True,
                },
                **hint,
            }
            self._check_memory()
            self._key_with_retries(cfg, job, wjob, work, raw_dir, len(plate.frames))

            outputs = self._collect(raw_dir, out, plate.frames)
            if crop:
                self._paste(out, plate, crop)
            from . import refine
            rs = refine.settings(job.get("refine"))
            if refine.active(rs):
                self.log(f"refine: {job['refine'].get('preset', 'off')} {rs}")
                refine.refine_sequence(
                    [str(out / "alpha" / f"alpha.{f:04d}.exr") for f in plate.frames], rs,
                    check_cancel=self.check_cancel,
                    progress=lambda fr: self.progress((0.97, 0.98), fr, "refining matte"))
            d = job["despill"]
            if float(d["amount"]) > 0:
                outputs["fg_despill"] = self._despill(out, plate.frames, float(d["amount"]), d["screen"],
                                                     d.get("mode", "everywhere"))
            shutil.rmtree(raw_dir, ignore_errors=True)
            shutil.rmtree(work, ignore_errors=True)
            work = None
            self.status.finish("done", message=f"key {version} done", version=version,
                               key_dir=str(out), outputs=outputs)
            self.log(f"DONE {version} -> {out}")
            out = None
            return 0
        except Cancelled:
            self.status.finish("cancelled", message="cancelled", error="Cancelled by user")
            self.log("CANCELLED")
            return 2
        except KeyboardInterrupt:
            self.status.finish("cancelled", message="cancelled", error="Cancelled (Ctrl+C)")
            self.log("CANCELLED (Ctrl+C)")
            return 2
        except (EngineError, JobError) as exc:
            self.status.finish("failed", message="failed", error=str(exc))
            self.log(f"ERROR {exc}")
            return 1
        except Exception as exc:  # noqa: BLE001
            self.log(traceback.format_exc())
            msg = f"{type(exc).__name__}: {exc}"
            if isinstance(exc, OSError) and getattr(exc, "errno", None) == 28:
                msg = "Disk full. Free space on the shot drive and try again."
            self.status.finish("failed", message="failed", error=msg)
            self.log(f"ERROR {msg}")
            return 1
        finally:
            if work is not None:
                shutil.rmtree(work, ignore_errors=True)
            if out is not None:  # cancelled or failed: don't leave a half-written version
                shutil.rmtree(out, ignore_errors=True)
            if lock is not None:
                lock.unlink(missing_ok=True)
            if self.cancel_file.exists():
                self.cancel_file.unlink(missing_ok=True)
            self.log.close()

    # -- steps ---------------------------------------------------------------
    def _lock(self, shot: Path) -> Path:
        lock = shot / ".running"
        if lock.exists():
            try:
                pid = int(lock.read_text().strip() or 0)
            except ValueError:
                pid = 0
            if _pid_alive(pid) and pid != os.getpid():
                raise EngineError(f"this shot is already being keyed (process {pid}). Cancel it "
                                  "or wait for it to finish.")
        lock.write_text(str(os.getpid()))
        return lock

    def _link_plate(self, plate, dest: Path) -> Path:
        """The worker keys every frame in its input folder, so give it exactly the
        selected plate frames (hard links: instant, no extra disk on the same drive)."""
        dest.mkdir(parents=True)
        for i, f in enumerate(plate.frames):
            src = plate.pattern % f
            dst = dest / f"frame_{i:06d}.exr"
            try:
                os.link(src, dst)
            except OSError:
                shutil.copy2(src, dst)
        return dest

    def _run_worker(self, cfg: dict, wjob_path: Path, work: Path, total: int) -> None:
        self.progress(P_LOAD, 0.0, "loading CorridorKey model")
        proc = subprocess.Popen(
            [cfg["engine_python"], "-u", cfg["worker_script"], str(wjob_path)],
            cwd=cfg["upstream_root"], env=clean_env(),
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        q: queue.Queue = queue.Queue()

        def pump():
            for line in proc.stdout:
                q.put(line.rstrip())
            q.put(None)

        threading.Thread(target=pump, daemon=True).start()
        tail: list[str] = []
        done = False
        cancel_at = None
        mem_lines: list[str] = []
        try:
            while True:
                try:
                    line = q.get(timeout=0.25)
                except queue.Empty:
                    if cancel_at is None and self.cancel_file.exists():
                        (work / "CANCEL").touch()
                        cancel_at = time.time()
                        self.log("cancelling (waiting for the engine to stop)...")
                    elif cancel_at is not None and time.time() - cancel_at > CANCEL_GRACE_S:
                        kill_tree(proc.pid)
                    continue
                if line is None:
                    break
                tail.append(line)
                del tail[:-60]
                if _MEM_ERROR.search(line):
                    mem_lines.append(line)
                if line.startswith("CK2_PROGRESS"):
                    _, n, _t = line.split()
                    self.progress(P_STAGE2, int(n) / max(total, 1), f"writing frames {n}/{total}")
                    continue
                if line.startswith("CK2_DONE"):
                    done = True
                self.log(f"  | {line}")
                m = _WINDOW.search(line)
                if m:
                    i, n = int(m.group(1)), int(m.group(2))
                    self.progress(P_STAGE1, i / max(n, 1), f"keying window {i}/{n}")
                elif "Auto VRAM" in line:
                    self.status.update(force=True, auto_vram=line.strip())
        except KeyboardInterrupt:
            (work / "CANCEL").touch()
            kill_tree(proc.pid)
            raise
        proc.wait()
        if cancel_at is not None:
            raise Cancelled()
        if proc.returncode != 0 or not done:
            text = "\n".join(tail)
            if mem_lines or proc.returncode in ACCESS_VIOLATION:
                m = _OOM_NUMBERS.search("\n".join(mem_lines))
                detail = ""
                if m:
                    total_gb, free = float(m.group(1)), float(m.group(2)) / (1024 if m.group(3) == "MiB" else 1)
                    mine = float(m.group(4))
                    others = max(0.0, total_gb - free - mine)
                    detail = (f" The card has {total_gb:.1f} GB; CorridorKey had {mine:.1f} GB and other "
                              f"programs about {others:.1f} GB.")
                raise GpuOutOfMemory("The GPU ran out of memory." + detail + " Close other GPU programs "
                                     "(other Nuke windows, cineSync/players, browsers, Resolve, games; set "
                                     "Nuke's viewer to a small frame), tick Low VRAM, or pick window 4 or 2, "
                                     "then key again.")
            last = next((l for l in reversed(tail) if l.strip()), "no output")
            raise EngineError(f"CorridorKey engine failed (code {proc.returncode}): {last[-300:]}. "
                              "Full output in log.txt.")

    def _collect(self, raw_dir: Path, out: Path, frames: list[int]) -> dict:
        """<clip>_alpha_exr/alpha_000000.exr -> alpha/alpha.1001.exr (plate numbers)."""
        outputs = {}
        for name in ("alpha", "fg"):
            dirs = glob.glob(str(raw_dir / "exr" / f"*_{name}_exr"))
            if not dirs:
                raise EngineError(f"engine wrote no {name} EXRs")
            files = sorted(glob.glob(os.path.join(dirs[0], f"{name}_*.exr")))
            if len(files) != len(frames):
                raise EngineError(f"engine wrote {len(files)} {name} frames, expected {len(frames)}")
            dest = out / name
            dest.mkdir()
            for f, frame in zip(files, frames):
                os.replace(f, dest / f"{name}.{frame:04d}.exr")
            outputs[name] = str(dest / f"{name}.####.exr")
        return outputs

    def _key_with_retries(self, cfg: dict, job: dict, wjob: dict, work: Path, raw_dir: Path,
                          total: int) -> None:
        """Runs the worker. If the GPU runs out of memory (other programs took some
        while it ran), retries with low VRAM and a smaller window: 4 -> 2 -> 1."""
        window, low_vram = job["engine"]["window"], bool(job["engine"]["low_vram"])
        tried = []
        for attempt in range(3):
            wdir = work if attempt == 0 else work / f"retry{attempt}"
            wdir.mkdir(exist_ok=True)
            wjob["work_dir"] = str(wdir)
            wjob["settings"]["window"], wjob["settings"]["low_vram"] = window, low_vram
            wjob_path = wdir / "job.json"
            write_json_atomic(wjob_path, wjob)
            try:
                self._run_worker(cfg, wjob_path, wdir, total)
            except GpuOutOfMemory as exc:
                from .sysmem import ENGINE_COMMIT_GB, advice
                if self._mem and self._mem["usable_gb"] < ENGINE_COMMIT_GB:
                    # Windows itself was short of memory: a smaller window won't help.
                    raise EngineError("The key ran out of Windows memory (it shows up as a GPU error, but the "
                                      "GPU had room). " + advice(self._mem)) from None
                used = window
                if used == "auto":
                    m = _CHUNK.search(self.status.data.get("auto_vram") or "")
                    used = int(m.group(1)) if m else 4
                tried.append(int(used))
                if used <= 1 or attempt == 2:
                    raise GpuOutOfMemory(f"{exc} Tried window {', '.join(map(str, tried))} with low VRAM.") from None
                window, low_vram = max(1, int(used) // 2), True
                self.log(f"GPU out of memory with window {used}; retrying with window {window} + low VRAM")
                self.progress(P_LOAD, 0.0, f"out of GPU memory - retrying with window {window}")
                shutil.rmtree(raw_dir, ignore_errors=True)
                continue
            if tried:
                self._warn(f"The GPU ran out of memory with window {tried[0]} (other programs were using it), "
                           f"so the key was redone with window {window} and low VRAM: slower, with slightly "
                           "less smoothing between frames. Close other GPU programs before big 4K keys.")
            return

    def _check_memory(self) -> None:
        from .sysmem import ENGINE_COMMIT_GB, advice, headroom
        try:
            self._mem = h = headroom()
        except Exception as exc:  # noqa: BLE001
            self.log(f"memory check skipped: {exc}")
            return
        self.log(f"memory: Windows can commit {h['usable_gb']:.1f} GB more (available {h['available_gb']:.1f} GB "
                 f"+ page file growth {h['growth_gb']:.1f} GB on {', '.join(h['drives']) or '?'}); "
                 f"the engine needs about {ENGINE_COMMIT_GB:.0f} GB")
        if h["usable_gb"] < 10.0:
            raise EngineError("Not enough Windows memory to key. " + advice(h))
        if h["usable_gb"] < ENGINE_COMMIT_GB:
            self.log("WARNING memory is tight; the key may fail part-way. " + advice(h))

    def _warn(self, msg: str) -> None:
        self.log(f"WARNING {msg}")
        self.status.update(force=True, warnings=self.status.data.get("warnings", []) + [msg])

    def _check_hint(self, job: dict, hint: dict, plate) -> None:
        """A rough Roto at high hint quality makes the model keep the screen inside
        the shape as subject. Lower the quality when the hint is mostly screen."""
        from .hints import ROUGH_QUALITY, SCREEN_LOWER, SCREEN_WARN, screen_share
        share = screen_share(hint, plate)
        self._hint_rough = share is not None and share > SCREEN_LOWER
        q = float(job["hint"]["quality"])
        if share is None or q <= ROUGH_QUALITY:
            return
        self.log(f"hint: {share:.0%} of the hint's area is open screen")
        if share > SCREEN_LOWER:
            job["hint"]["quality"] = ROUGH_QUALITY
            self._warn(f"{share:.0%} of the hint shape is green/blue screen, so it looks like a rough shape. "
                       f"Hint quality was lowered from {q:g} to {ROUGH_QUALITY:g} so the screen inside it is "
                       "keyed out. For a careful roto, draw it tight around the subject.")
        elif share > SCREEN_WARN:
            self._warn(f"{share:.0%} of the hint shape is green/blue screen. If the Roto is rough, key again "
                       f"with hint quality {ROUGH_QUALITY:g}; if the subject wears screen-coloured clothes, "
                       "ignore this.")

    def _paste(self, out: Path, plate, crop) -> None:
        """Cropped alpha/fg -> full plate size, zero outside the box."""
        from .crop import paste_file
        edge = 0.0
        for i, frame in enumerate(plate.frames):
            self.check_cancel()
            edge = max(edge, paste_file(out / "alpha" / f"alpha.{frame:04d}.exr", crop,
                                        plate.width, plate.height))
            paste_file(out / "fg" / f"fg.{frame:04d}.exr", crop, plate.width, plate.height)
            if i % 8 == 0:
                self.progress((0.95, 0.97), (i + 1) / len(plate.frames),
                              f"placing crop {i + 1}/{len(plate.frames)}")
        if edge > 0.02:
            self._warn(f"the subject touches the crop box edge ({edge:.0%} of the border); part of it "
                       "may be cut off. Raise the crop margin or set crop to off.")

    def _despill(self, out: Path, frames: list[int], amount: float, screen: str,
                 mode: str = "everywhere") -> str:
        from .despill import despill
        from .imageio import read_image, write_exr
        dest = out / "fg_despill"
        dest.mkdir()
        for i, frame in enumerate(frames):
            self.check_cancel()
            fg = read_image(str(out / "fg" / f"fg.{frame:04d}.exr"))
            alpha = read_image(str(out / "alpha" / f"alpha.{frame:04d}.exr"))[..., 0] if mode == "edges" else None
            write_exr(str(dest / f"fg_despill.{frame:04d}.exr"),
                      despill(fg, amount, screen, alpha=alpha, mode=mode))
            if i % 8 == 0:
                self.progress((0.95, 1.0), (i + 1) / len(frames), f"despill {i + 1}/{len(frames)}")
        return str(dest / "fg_despill.####.exr")


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print("usage: python -m ck_engine.run <job.json>")
        return 64
    path = Path(argv[0])
    if not path.is_file():
        print(f"ERROR job file not found: {path}")
        return 64
    return Runner(path).run()


if __name__ == "__main__":
    sys.exit(main())

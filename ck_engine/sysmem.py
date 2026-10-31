"""Windows memory headroom: can the engine get the ~15 GB it commits?

Measured peak commit of the engine (parent + CK2 worker), 2026-10-31: 14.8 GB
for an 8-frame 1080p key, 13.9 GB for 8 frames at 4K, 13.7 GB for 37 frames at
4K. It is mostly the models, so it hardly depends on resolution or length. When
Windows can't commit it (small page file on a full C: drive), the key dies
part-way as "CUDA out of memory", "bad allocation" or an access violation, even
though the GPU itself has room. Checking first turns that into a clear message.
"""

from __future__ import annotations

import ctypes
import json
import shutil
import subprocess

ENGINE_COMMIT_GB = 15.0
GB = 2 ** 30


class _MemStatus(ctypes.Structure):
    _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]


def _status() -> _MemStatus:
    s = _MemStatus()
    s.dwLength = ctypes.sizeof(_MemStatus)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(s))
    return s


def _pagefiles() -> tuple[bool, list[str]]:
    """(automatically managed?, page file drive letters)."""
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "@{auto=(Get-CimInstance Win32_ComputerSystem).AutomaticManagedPagefile;"
             "files=@(Get-CimInstance Win32_PageFileUsage | ForEach-Object Name)} | ConvertTo-Json"],
            capture_output=True, text=True, timeout=30, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        d = json.loads(out.stdout)
        files = d.get("files") or []
        files = [files] if isinstance(files, str) else files
        return bool(d.get("auto")), sorted({f[0].upper() for f in files if f})
    except Exception:  # noqa: BLE001
        return False, []


def headroom() -> dict:
    """Commit available now, plus what an auto-managed page file can still grow by."""
    s = _status()
    auto, drives = _pagefiles()
    growth = 0.0
    if auto:
        for d in drives:
            try:
                growth += max(0.0, shutil.disk_usage(f"{d}:\\").free / GB - 2.0)
            except OSError:
                pass
        # Windows caps an automatic page file at 3x RAM.
        growth = min(growth, max(0.0, 3 * s.ullTotalPhys / GB - (s.ullTotalPageFile - s.ullTotalPhys) / GB))
    return {"ram_gb": s.ullTotalPhys / GB, "limit_gb": s.ullTotalPageFile / GB,
            "available_gb": s.ullAvailPageFile / GB, "growth_gb": growth,
            "usable_gb": s.ullAvailPageFile / GB + growth, "auto": auto, "drives": drives}


def advice(h: dict) -> str:
    where = ", ".join(f"{d}:" for d in h["drives"]) or "?"
    return (f"Windows can give programs about {h['usable_gb']:.1f} GB more memory (RAM {h['ram_gb']:.0f} GB + page file "
            f"on {where}); CorridorKey needs about {ENGINE_COMMIT_GB:.0f} GB. Fix: put the page file on a drive with "
            "space (Start > 'Adjust the appearance and performance of Windows' > Advanced > Virtual memory > Change: "
            "untick 'Automatically manage', pick D:, 'System managed size', Set, OK, restart), or free space on "
            f"{where}, and close programs you don't need.")

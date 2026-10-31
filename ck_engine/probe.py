"""What is the source? Video file, image sequence (pattern, folder or one frame of it)."""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path

from .config import EngineError

VIDEO_EXT = {".mp4", ".mov", ".mxf", ".mkv", ".avi", ".m4v", ".webm", ".mts", ".m2ts"}
IMAGE_EXT = {".exr", ".dpx", ".tif", ".tiff", ".png", ".jpg", ".jpeg"}
RAW_EXT = {".braw", ".r3d", ".ari", ".arx", ".crm", ".nev"}

_HASHES = re.compile(r"#+")
_PRINTF = re.compile(r"%0?(\d*)d")
_TRAILING_NUM = re.compile(r"^(.*?)(\d+)(\.[^.]+)$")
# Nuke's file browser appends the frame range: "plate.####.exr 1001-1100".
_NUKE_RANGE = re.compile(r"\s+-?\d+-\d+$")


def strip_range(path: str) -> str:
    return _NUKE_RANGE.sub("", path.strip())


@dataclass
class Source:
    kind: str                      # "video" or "sequence"
    path: str                      # video file, or sequence pattern with %0Nd
    width: int = 0
    height: int = 0
    fps: float = 24.0
    fps_text: str = "24/1"
    frames: list[int] = field(default_factory=list)  # video: 1..N; sequence: file frame numbers
    pix_fmt: str = ""
    bit_depth: int = 0
    color_range: str = ""          # "tv" / "pc" / ""
    color_matrix: str = ""         # ffprobe color_space, e.g. bt709 / bt2020nc
    color_transfer: str = ""
    color_primaries: str = ""
    timecode: str = ""
    warnings: list[str] = field(default_factory=list)

    def frame_path(self, frame: int) -> str:
        return self.path % frame

    @property
    def is_hdr(self) -> bool:
        return self.color_transfer in ("arib-std-b67", "smpte2084")


def _ffprobe(ffprobe: str, args: list[str]) -> dict:
    out = subprocess.run([ffprobe, "-v", "error", "-of", "json", *args],
                         capture_output=True, text=True, encoding="utf-8", errors="replace",
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if out.returncode != 0:
        raise EngineError(f"ffprobe could not read the source: {out.stderr.strip()[-300:]}")
    return json.loads(out.stdout or "{}")


def _bit_depth(stream: dict) -> int:
    for key in ("bits_per_raw_sample", "bits_per_sample"):
        try:
            if int(stream.get(key) or 0) > 0:
                return int(stream[key])
        except ValueError:
            pass
    pf = stream.get("pix_fmt", "")
    m = re.search(r"p(\d{2})(le|be)?$", pf)
    return int(m.group(1)) if m else 8


def to_printf(pattern: str) -> str:
    """'a.####.exr' / 'a.%04d.exr' / 'a.%d.exr' -> printf pattern."""
    if _HASHES.search(pattern):
        return _HASHES.sub(lambda m: f"%0{len(m.group(0))}d", pattern)
    m = _PRINTF.search(pattern)
    if m:
        return pattern
    raise EngineError(f"not a sequence pattern: {pattern}")


def _scan_sequence(printf: str) -> list[int]:
    folder, name = os.path.split(printf)
    m = _PRINTF.search(name)
    pad = m.group(1)
    head, tail = name[:m.start()], name[m.end():]
    num = rf"(\d{{{int(pad)},}})" if pad else r"(\d+)"
    rx = re.compile("^" + re.escape(head) + num + re.escape(tail) + "$", re.IGNORECASE)
    frames = []
    for entry in os.listdir(folder or "."):
        mm = rx.match(entry)
        if mm:
            frames.append(int(mm.group(1)))
    return sorted(frames)


def resolve_sequence(path: str) -> str:
    """Folder, pattern, or one frame of a sequence -> printf pattern."""
    path = strip_range(path)
    p = Path(path)
    if p.is_dir():
        images = sorted(f for f in os.listdir(p) if Path(f).suffix.lower() in IMAGE_EXT)
        if not images:
            raise EngineError(f"no image frames (.exr/.dpx/.tif/.png) in {p}")
        m = _TRAILING_NUM.match(images[0])
        if not m:
            raise EngineError(f"can't find a frame number in {images[0]}")
        return str(p / f"{m.group(1)}%0{len(m.group(2))}d{m.group(3)}")
    if _HASHES.search(p.name) or _PRINTF.search(p.name):
        return str(p.parent / to_printf(p.name))
    m = _TRAILING_NUM.match(p.name)
    if m:
        printf = str(p.parent / f"{m.group(1)}%0{len(m.group(2))}d{m.group(3)}")
        # One frame of a sequence, even one outside its range (an expression in a
        # Read evaluated at frame 1 gives plate.0001.exr for a 1001-1100 plate).
        if p.is_file() or _scan_sequence(printf):
            return printf
    raise EngineError(f"source not found: {path}")


def probe(path: str, ffprobe: str) -> Source:
    path = strip_range(path)
    ext = Path(path.replace("#", "0")).suffix.lower()
    if ext in RAW_EXT:
        raise EngineError(f"{ext} camera raw can't be decoded here. Export EXR or ProRes from "
                          "DaVinci Resolve first (see docs/unsupported_formats.md).")
    if Path(path).is_file() and ext in VIDEO_EXT:
        return _probe_video(path, ffprobe)
    return _probe_sequence(resolve_sequence(path), ffprobe)


def _probe_video(path: str, ffprobe: str) -> Source:
    info = _ffprobe(ffprobe, ["-select_streams", "v:0", "-show_streams", "-show_format", path])
    if not info.get("streams"):
        raise EngineError(f"no video stream in {path}")
    s = info["streams"][0]
    rate = s.get("avg_frame_rate") if s.get("avg_frame_rate", "0/0") != "0/0" else s.get("r_frame_rate", "24/1")
    fps = float(Fraction(rate)) if rate and rate != "0/0" else 24.0
    n = int(s.get("nb_frames") or 0)
    if n <= 0:
        # Some containers don't store a frame count: count packets (slower, exact).
        cnt = _ffprobe(ffprobe, ["-select_streams", "v:0", "-count_packets",
                                 "-show_entries", "stream=nb_read_packets", path])
        n = int(cnt["streams"][0].get("nb_read_packets") or 0)
    if n <= 0:
        raise EngineError(f"could not count frames in {path}")
    src = Source(
        kind="video", path=path, width=int(s["width"]), height=int(s["height"]),
        fps=fps, fps_text=rate, frames=list(range(1, n + 1)),
        pix_fmt=s.get("pix_fmt", ""), bit_depth=_bit_depth(s),
        color_range=s.get("color_range", ""), color_matrix=s.get("color_space", ""),
        color_transfer=s.get("color_transfer", ""), color_primaries=s.get("color_primaries", ""),
        timecode=(s.get("tags") or {}).get("timecode", "")
        or (info.get("format", {}).get("tags") or {}).get("timecode", ""))
    rot = (s.get("tags") or {}).get("rotate") or next(
        (str(d.get("rotation")) for d in s.get("side_data_list", []) if "rotation" in d), "")
    if rot and rot not in ("0", "0.0"):
        src.warnings.append(f"video has rotation metadata ({rot} deg); frames are keyed as stored")
    if src.is_hdr:
        src.warnings.append("HDR video (HLG/PQ). Choose the matching HDR colour space; for green "
                            "screen, shooting with HDR off is safer.")
    if src.bit_depth <= 8 and src.color_transfer not in ("bt709", "iec61966-2-1", "", "unknown"):
        src.warnings.append("8-bit source with a non-Rec.709 curve: expect banding in the key")
    return src


def _probe_sequence(printf: str, ffprobe: str) -> Source:
    frames = _scan_sequence(printf)
    if not frames:
        raise EngineError(f"no frames match {printf}")
    missing = sorted(set(range(frames[0], frames[-1] + 1)) - set(frames))
    src = Source(kind="sequence", path=printf, frames=frames)
    if missing:
        src.warnings.append(f"{len(missing)} frame(s) missing in the sequence, e.g. {missing[:5]}")
    first = printf % frames[0]
    ext = Path(first).suffix.lower()
    if ext == ".exr":
        from .imageio import read_image
        img = read_image(first)
        src.height, src.width = img.shape[:2]
        src.bit_depth = 16
        src.pix_fmt = "exr"
    else:
        info = _ffprobe(ffprobe, ["-show_streams", first])
        s = info["streams"][0]
        src.width, src.height = int(s["width"]), int(s["height"])
        src.pix_fmt = s.get("pix_fmt", "")
        src.bit_depth = _bit_depth(s)
        src.color_range = "pc"
    return src

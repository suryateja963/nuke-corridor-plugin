# Test matrix (PLAN Phase 4)

Fill in as you test. Mark ✅ pass, ❌ fail (+ note), — not applicable / no footage.

| Source | Res | No hint | Roto first frame | Roto every frame | Matte file | s/frame | Window (Auto VRAM line) | Notes |
|---|---|---|---|---|---|---|---|---|
| pail.mp4 (sRGB H.264) | 4K | ✅ engine + ✅ Nuke panel | ✅ Nuke Roto (box; use quality ~0.75 for rough boxes) | | | ~4.5 | chunk 4, low VRAM | Keyed from real Nuke 17.1v2 NC 2026-10-30 |
| Phone SDR MP4 | HD | | | | | | | |
| Phone HDR (HLG) | | | | | | | | |
| Sony S-Log3 | | | | | | | | |
| Panasonic V-Log | | | | | | | | |
| Apple Log | | | | | | | | |
| EXR sequence | | | | | | | | |
| Two-person shot | | | | | | | | Hint must pick the right person |

## Failure tests

| Case | Expected message | Result |
|---|---|---|
| Weights missing (rename the weights file) | "CorridorKey weights missing…" | |
| Full disk (small USB stick as shots folder) | "Disk full…" | |
| Cancel mid-key | "cancelled", no `.running`, no `work\` left, no half version | ✅ engine test |
| Corrupt frame in an EXR sequence | "corrupt or unreadable frame: …" | |
| Hint with the wrong frame count | "hint sequence has N frame(s)…" | ✅ unit test |
| GPU out of memory (heavy app open, window 24 at 4K) | "The GPU ran out of memory…" | |

## Quality baseline

Composite a known image with alpha over flat green, key it, and diff the alpha. Save the inputs,
outputs and the mean difference in `docs/quality_baseline/`, and re-run after any engine update.

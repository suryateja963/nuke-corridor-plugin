# Performance (RTX 5060 Laptop, 8 GB)

## Measured

| Date | Clip | Resolution | Frames | Wall time | Notes |
|---|---|---|---|---|---|
| 2026-10-28 | synthetic (ComfyUI pack) | 1920×1080 | 48 | ~150 s | auto-VRAM: `hann_chunk=8`, low VRAM |
| 2026-10-30 | `pail.mp4` (real, 8-bit H.264) | 3840×2160 | 6 (preview) | 121 s | auto-VRAM: `6.9 GB available at 3840x2176 -> hann_chunk=4, hann_stride=2, low_vram=True (estimated peak 5.3 GB)` |
| 2026-10-30 | `pail.mp4` | 3840×2160 | 12 | 148 s | same window; first-frame hint |

Each run includes plate prep, loading the model in a fresh process, keying, and writing EXRs.

## What that means at 4K

From the two 4K runs: **about 95 s fixed per run** (model load plus start-up) **plus about 4.5 s per
frame**.

| Shot length (4K) | Estimate |
|---|---|
| 24-frame preview | about 3.5 min |
| 100 frames | about 9 min |
| 300 frames | about 24 min |

At 1080p, upstream picks an 8-frame window (4 at 4K), and per-frame cost should be roughly a third of
4K. Measure with `tests\e2e_gpu.py <1080p clip>` once you have one.

## Disk

Half-float EXR with ZIP compression. 4K: plate, fg and fg_despill are about 20–30 MB per frame each,
and alpha is about 5–10 MB. So a 300-frame 4K shot with all passes is roughly 25 GB. Old versions add
up; use **Clean up a shot…**.

## Ideas if it's too slow

- Preview first (24 frames) to settle colour and hint, then key the full range.
- The fixed ~95 s is mostly model load. The CK2 worker has a persistent mode (`--serve`) that keeps
  the model loaded between keys. Using it from Nuke would cut repeat keys to about prep + 4.5 s per
  frame. Not built yet (PLAN follow-up).
- Auto-crop (CK2 pack feature) keys only a box around the subject. Under ~1.5 MP, 8 GB auto-VRAM picks
  bigger windows and runs about a third faster. Not exposed in the Nuke tool yet.

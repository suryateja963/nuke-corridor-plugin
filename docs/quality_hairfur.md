# Hair and fur quality: baseline (2026-10-30)

`tests\hair_fur_batch.py`: 10 real 1080p clips (5 hair, 5 fur), 16 frames each (source frames
31–46), no hint, despill 0.5, colour sRGB/Rec.709. Run on the RTX 5060 Laptop 8 GB through the
same engine the Nuke panel uses. Sheets and the overview are in `_e2e_out\hairfur\` (not in git).

| clip | subject | soft edge % | flicker | spill | time (16 fr) | window |
|---|---|---|---|---|---|---|
| girlhair | hair, chair, mirror | 1.88 | 0.020 | 0.001 | 70 s | 80, low VRAM |
| greenoutfit | green clothes on green | 0.64 | 0.057 | 0.035* | 77 s | 8 (2048 wide) |
| manhair | flying hair | 1.89 | 0.101 | 0.000 | 69 s | 80 |
| womanblue | blue screen, long hair | 0.97 | 0.086 | 0.001 | 72 s | 80 |
| womangreen | long hair | 1.02 | 0.016 | 0.008 | 70 s | 80 |
| cat | long fur | 2.46 | 0.022 | 0.001 | 70 s | 80 |
| fluffykitten | fluffy fur | 2.31 | 0.014 | 0.020 | 74 s | 80 |
| gingerkitten | fur, close to camera | 5.51 | 0.064 | 0.007 | 65 s | 80 |
| lyingkitten | fur | 4.02 | 0.065 | 0.030 | 72 s | 80 |
| rabbit | black/white fur, soft footage | 0.96 | 0.062 | 0.035 | 73 s | 80 |

Metrics are computed on soft-edge pixels only (0.05 < alpha < 0.95) of the middle frame:
- **soft edge %:** how much of the frame is partial alpha. More means more hair and fur detail is
  kept.
- **flicker:** mean |Δalpha| between frames on the edge. It also counts real motion, so manhair's
  0.10 is mostly flying hair. Compare a clip with itself across versions, not clips with each other.
- **spill:** leftover green in the despilled fg on the edge. *greenoutfit's value is the outfit
  itself, which is correctly green.

## What looks good
- Every subject is separated cleanly, with no holes inside faces or bodies.
- The green outfit on a green screen is kept whole and stays green.
- Foreground objects are kept (girlhair's chair and mirror; the pail clip's camera and tripod).
- Flying hair (manhair) keeps separate strands.
- Speed at 1080p: whole 16-frame shots fit one 80-frame window, about 70 s per clip including
  model load.

## Weaknesses (where to improve)
1. **Fur edges are soft and smooth, not strand-level** (cat, gingerkitten). The alpha is a soft
   gradient where the real fur has separate tips.
2. **Green bounce inside the subject:** the rabbit's white chest fur stays green-tinted. Despill
   0.5 limits green on the fg, but this is light reflected from the screen, and 0.5 is too weak for
   white fur. Raising it everywhere would grey out green clothing (greenoutfit).
3. **Contact areas:** the gaps between the rabbit's paws are soft blobs, not clean.
4. **No temporal-stability measure** that separates real motion from flicker.

## Improvement candidates (ranked by expected gain for hair/fur)
1. **Auto-crop to the subject before keying.** The CK2 worker already supports a `crop` box. Keying
   only the subject's box lets the model see the fur at a higher effective resolution, and under
   ~1.5 MP auto-VRAM also picks bigger windows. The ComfyUI pack measured about a third faster.
   Expected: sharper fur tips. Needs a `crop` job option, then pasting results back full-frame.
2. **Edge-aware despill:** strength scales with (1 − alpha) plus a screen-colour distance mask. Edges
   and bounce on light fur get full despill, while solid green clothing is left alone. Expose it as
   "despill: edges only / everywhere".
3. **Matte refinement pass** (already written in the CK2 pack: Levels, Edge, Temporal Smooth),
   offered as optional engine steps with presets for hair and fur.
4. **Hint quality presets in the panel:** a rough box at 0.95 over-trusts the box (see
   `nuke_env.md` / Key 2). Show "rough box → 0.75" next to the setting.
5. **Better flicker metric:** compare alpha only where the plate itself didn't change (|Δplate| small).

Re-run `tests\hair_fur_batch.py` after each change and compare it with this table.

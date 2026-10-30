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

## Run 2: auto-crop (2026-10-30)

`tests\hair_fur_batch.py --crop auto --out hairfur_crop`, same 10 clips and settings, compared with
`tests\compare_hairfur.py hairfur hairfur_crop` (same edge close-up from both runs).

| clip | crop box (x, y, w, h) | soft edge % | flicker | spill | time | est. VRAM peak |
|---|---|---|---|---|---|---|
| girlhair | full frame (no clear screen at border) | 1.88 → 1.88 | .020 → .020 | .001 → .001 | 70 → 86 s | 5.9 GB |
| greenoutfit | full frame (subject fills it) | 0.64 → 0.64 | .057 → .057 | .035 → .035 | 77 → 78 s | 4.2 GB |
| manhair | 462,56,1152,1024 | 1.89 → 1.89 | .101 → .101 | .000 → .000 | 69 → 60 s | 5.9 → 4.2 GB |
| womanblue | 324,0,1024,1080 | 0.97 → 0.98 | .086 → .086 | .001 → .001 | 72 → 60 s | 5.9 → 4.2 GB |
| womangreen | 512,0,1408,1080 | 1.02 → 1.01 | .016 → .016 | .008 → .009 | 70 → 76 s | 5.9 → 4.9 GB |
| cat | 492,184,896,896 | 2.46 → 2.50 | .022 → .022 | .001 → .001 | 70 → 51 s | 5.9 → 3.9 GB |
| fluffykitten | 450,100,1024,896 | 2.31 → 2.36 | .014 → .013 | .020 → .019 | 74 → 56 s | 5.9 → 3.9 GB |
| gingerkitten | 0,56,1280,1024 | 5.51 → 5.51 | .064 → .063 | .007 → .007 | 65 → 64 s | 5.9 → 4.4 GB |
| lyingkitten | full frame (subject fills it) | 4.02 → 4.02 | .065 → .065 | .030 → .030 | 72 → 74 s | 5.9 GB |
| rabbit | 258,184,1280,896 | 0.96 → 0.99 | .062 → .061 | .035 → .034 | 73 → 67 s | 5.9 → 4.2 GB |

**Result:** no visible quality change at 1080p. The close-ups are the same, and the metrics move by
at most 0.05 points. Upstream keys at the input's own resolution (its internal downscales are fixed
fractions of the input size), so a crop doesn't show it more pixels of fur, and the "sharper tips"
expectation was wrong. What crop does give is speed (up to 27% faster on the cat) and a lower VRAM
peak (5.9 → 3.9–4.9 GB). That headroom matters most at 4K, where full frames are limited to window 4.
The 4K check is still to do. Every crop kept the whole subject: no clip raised the crop-edge warning.

**Decision:** keep it as the panel default ("crop to subject: auto"). It falls back to the full frame
by itself when there's no clear screen or the subject fills the frame. The job schema default stays
"off", so older job files behave as before.

**Next for hair/fur quality:** edge-aware despill (candidate 2) is now the top item. Fur-tip softness
needs a model-side or refinement change (candidate 3), not a crop.

## Run 3: edge-aware despill (2026-10-30)

`tests\hair_fur_batch.py --crop auto --despill edges --out hairfur_despill` (despill amount 1.0,
mode `edges`) against run 2 (crop auto, despill 0.5 everywhere).
`tests\compare_hairfur.py hairfur_crop hairfur_despill` adds a whole-frame view on neutral grey.

Before choosing the rule, I measured the green excess divided by the pixel's brightest channel
(ratio) on solid pixels:
- Fur with green bounce: p99 0.43 (rabbit), 0.53–0.56 (kittens).
- The green outfit: p50 0.78, with 98% above 0.5.

So `edges` gives full strength below ratio 0.45, fades out by 0.6, and adds 2 × (1 − alpha) on
transparent edges.

| clip | edge spill run 2 → run 3 |
|---|---|
| girlhair | .001 → .000 |
| greenoutfit | .035 → .020 (outfit itself stays green, see grey view) |
| manhair | .000 → .000 |
| womanblue | .001 → .000 |
| womangreen | .009 → .003 |
| cat | .001 → .000 |
| fluffykitten | .019 → .003 |
| gingerkitten | .007 → .000 |
| lyingkitten | .030 → .005 |
| rabbit | .034 → .003 |

Alpha, soft edge % and flicker are identical, because despill only touches `fg_despill`. In the grey
view the rabbit's white chest and paws lose the green tint, while the green outfit and beret keep
their colour. The cost is about 0.12 s per 1080p frame (it reads the alpha). Total clip times in this
run were 15–30 s higher, but that came from the machine state: the despill step itself is 2 s per clip.

**Decision:** the panel defaults to despill 1.0, "edges + bounce". The job schema default stays mode
`everywhere`, so older jobs behave as before.

**Still open for hair/fur:** soft fur tips (needs refinement or the model, candidate 3), and a flicker
metric that ignores real motion (candidate 5).

## Real-Nuke check (2026-10-31)

`tests\run_nuke_auto.ps1 -Module nuke_crop_despill_test -ReportName nuke_crop_despill_report.txt`
keys rabbit and greenoutfit (16 frames each) through the panel's own defaults in Nuke 17.1v2 NC:
**11/11 pass.**
- The panel defaults are crop auto with margin 64, and despill 1.0 "edges + bounce". The job.json
  the panel writes carries both settings.
- rabbit: keyed a 1024×1024 crop at (396,56). The comp's alpha Read is the full 1920×1080, with alpha
  1.000 on the rabbit and 0.000 in the corner. Green bounce on bright fur went from 0.111 to 0.000
  over 51k px.
- greenoutfit: correctly fell back to the full frame ("subject spans most of the frame"). The green
  clothing keeps 99.9% of its green over 291k px.
- Both comps render from Nuke (`_g2_out\nuke_comp_rabbit.png`, `nuke_comp_greenoutfit.png`).

**Known limit:** where the matte wrongly marks screen as solid (alpha 1), such as the gap between the
rabbit's front legs and a few dark neck spots, the screen shows as bright green and edge despill
leaves it, because it can't tell it apart from a green object. The fix belongs in the matte: a hint
(Roto), or the refinement pass (candidate 3). "despill where: everywhere" at 1.0 also removes it,
but it greys green clothing.

## Run 4: matte refinement + despill tuning (2026-10-31)

`tests\hair_fur_batch.py --crop auto --despill edges --refine hairfur --out hairfur_refine`, compared
with run 3 by `tests\compare_hairfur.py hairfur_despill hairfur_refine`. The comparison now also
reports **static flicker**: edge flicker counted only where the plate itself barely changed (max
|Δplate| < 0.01), so real hair motion doesn't count. This is candidate 5.

**What the rabbit's green patches turned out to be:** shadowed screen seen between the legs and
through dark neck spots, which the matte held as solid. They are darker and duller than the open
screen (ratio about 0.46), so they sat inside the old fade zone (0.45–0.6) and got only about half
despilled. The pack's refinement ops (clean, levels, grow, temporal smoothing) can't fix this: they
see alpha = 1, which looks like the subject. I moved the despill fade zone to **0.5–0.65** instead.
On real frames that cuts these patches by ~60%, and the green outfit still keeps 98% of its green.
0.55–0.7 would cut them by ~85%, but the outfit drops to 94.6%.

Green patch pixels inside the rabbit matte (alpha > 0.5, green ratio > 0.3), frames 1031 / 1039 / 1046:
run 2: 2034 / 1671 / 2613 → run 3: 1215 / 1349 / 1980 → run 4: **726 / 804 / 1297**.

**New: `ck_engine/refine.py`**, ported from the ComfyUI pack. It works per frame with a rolling
window and swaps the results in only at the end, so a cancel leaves the key intact. The steps run in
this order: clean specks and holes → levels → grow/shrink → temporal smoothing (only where frames
agree). Presets:
- `hairfur`: specks under 40 px removed, plus temporal radius 1 at threshold 0.08.
- `solid`: also fills holes and firms the edges with levels.

| clip | flicker run 3 → 4 | static flicker | soft edge % | spill |
|---|---|---|---|---|
| girlhair | .0202 → .0177 | .0143 → .0121 | 1.88 → 1.88 | .000 → .000 |
| greenoutfit | .0572 → .0561 | .0547 → .0541 | 0.64 → 0.67 | .020 → .018 |
| manhair | .1007 → .0973 | .0101 → .0153 | 1.89 → 1.91 | .000 → .000 |
| womanblue | .0861 → .0835 | .0152 → .0176 | 0.98 → 1.01 | .000 → .000 |
| womangreen | .0159 → .0137 | .0068 → .0069 | 1.01 → 1.00 | .003 → .002 |
| cat | .0216 → .0193 | .0049 → .0054 | 2.50 → 2.50 | .000 → .000 |
| fluffykitten | .0134 → .0113 | .0053 → .0047 | 2.36 → 2.36 | .003 → .002 |
| gingerkitten | .0631 → .0608 | .0158 → .0177 | 5.51 → 5.49 | .000 → .000 |
| lyingkitten | .0652 → .0617 | .0137 → .0148 | 4.02 → 4.03 | .005 → .003 |
| rabbit | .0611 → .0584 | .0196 → .0168 | 0.99 → 0.98 | .003 → .002 |

**Result:** overall edge flicker drops 3–16% on every clip, and soft-edge detail is kept (no strands
lost; no ghosting on manhair's flying hair in the close-ups). Static flicker is mixed (4 down, 5 up,
1 flat), so the steadying effect of radius 1 is small. The model's own temporal windows already do
most of that work. Fur-tip softness is unchanged: that needs the model, not a post-process.

**Real Nuke (2026-10-31):** `nuke_crop_despill_test` passes **11/11**. Panel defaults are crop auto,
despill 1.0 edges + bounce, and refine hair/fur grow 0. The job and log show `refine: hairfur`. Green
bounce on fur goes from 0.111 to 0.000, and the outfit keeps 99.9% of its green. In Nuke's own comp,
the rabbit's leg gap is now dark with only a faint green trace.

**Panel default:** refine "hair/fur" (gentle: it only touches specks and frame-to-frame jitter).
"solid" is for hard-edged subjects, and "grow/shrink px" moves the edge. The job schema default stays
`off`.

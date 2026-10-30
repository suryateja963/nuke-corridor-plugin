# Colour handling

CorridorKey 2.0 only accepts display sRGB/Rec.709 or **scene-linear Rec.709**. It doesn't read
colour metadata or convert log/HDR itself. So the engine converts every source to linear Rec.709
(sRGB primaries, D65) half-float EXR first (`ck_engine/colour.py`). Nuke reads that same plate, set
to linear.

## How a frame is converted

1. **Decode** (video and DPX) with ffmpeg + **zscale** to 32-bit float RGB. Only the YUV matrix and
   range are applied here; transfer and gamut stay as recorded.
   - We use zscale, not swscale, because swscale's YUV→RGB loses about 0.4 % at the range ends
     (limited-range white came out as 0.996). zscale is exact; covered by `tests/test_engine.py`.
2. **Curve:** code value → scene linear, using the camera maker's published formula.
3. **Gamut:** a 3×3 matrix to Rec.709. The matrices are derived in code from each gamut's published
   primaries (Bradford adaptation for ACES white), not copied by hand. Tests check them against known
   values.
4. **Out of gamut:** wide-gamut sources produce negatives in Rec.709. `clamp` (default) cuts them to
   0; `keep` leaves them. Which keys better is an open test (PLAN task 1.5).

## Spaces

| Panel choice | Key | Curve | Gamut | Range default | Tested on real footage |
|---|---|---|---|---|---|
| sRGB / Rec.709 video | `srgb_rec709` | IEC 61966-2-1 (same maths as upstream's `srgb_to_linear`) | Rec.709 | from file flag | yes (4K phone-style MP4) |
| Linear Rec.709 | `linear_rec709` | none | Rec.709 | — | yes (EXR) |
| ACEScg | `acescg` | none | AP1 → Rec.709 (Bradford) | — | no |
| Sony S-Log3 / S-Gamut3 | `slog3_sgamut3` | Sony S-Log3 | S-Gamut3 | **full** (raw code values) | no |
| Sony S-Log3 / S-Gamut3.Cine | `slog3_sgamut3cine` | Sony S-Log3 | S-Gamut3.Cine | **full** | no |
| Panasonic V-Log / V-Gamut | `vlog_vgamut` | Panasonic V-Log | V-Gamut | **full** | no |
| Apple Log | `applelog` | Apple Log profile | BT.2020 | from file flag (**unconfirmed**) | no |
| HLG HDR phone video | `hlg_rec2020` | BT.2100 HLG inverse OETF, 75 % → 1.0 | BT.2020 | from file flag | no |
| PQ HDR | `pq_rec2020` | ST 2084, 203 nits → 1.0 | BT.2020 | from file flag | no |
| Auto | `auto` | HLG/PQ if the file says so, else sRGB | | | |
| Other (OCIO) | `ocio` | any named space in `$OCIO`, or OCIO's built-in studio config | | | needs `pip install opencolorio` in the venv |

**Why log curves default to full range:** Sony's and Panasonic's formulas are defined on the stored
10-bit code values (S-Log3 black = 95/1023, 18 % grey = 420/1023; V-Log black = 128/1023). Expanding
legal range to full first would shift every value. If a log clip looks wrong, try `range: limited` in
the panel, and tell Claude which looked right.

**Apple Log:** whether iPhone files store it in legal or full range isn't confirmed yet. It follows
the file's flag for now. Check with a grey card the first time.

**HLG/PQ scaling:** reference white (HLG 75 %, PQ 203 nits) maps to 1.0, which puts 18 % grey at about
0.18, matching the other spaces.

## Rules

1. **Never key in log.** Pick the camera's space; the model misreads the screen colour otherwise.
2. **Keep 16-bit or float throughout.** Decoding is 32-bit float; plates are half float.
3. **One source of truth.** Comp from the plate Read the tool creates, not the original clip.

## Checking a conversion (PLAN Phase 1 "done when")

Shoot or find a clip with a grey card or chart, then run **Prepare plate only**. In Nuke, sample the
grey card on the plate Read: an 18 % card should read about **0.18** in all three channels. If it reads
about 0.13–0.15 or 0.21–0.25, the range is probably wrong; try the other range setting.

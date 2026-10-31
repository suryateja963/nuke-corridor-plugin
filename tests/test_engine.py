"""CPU tests for ck_engine. Run in the CorridorKey venv from the repo root:

    D:\\CorridorKey2\\venv\\Scripts\\python.exe -m unittest discover -s tests -v
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from ck_engine import colour, crop, despill, hints, jobio, prepare, probe, refine  # noqa: E402
from ck_engine.config import EngineError, find_tool, load_settings  # noqa: E402
from ck_engine.imageio import read_image, write_exr, write_png16  # noqa: E402
from ck_engine.run import next_version  # noqa: E402

CFG = load_settings()
FFMPEG = find_tool(CFG["ffmpeg"])
FFPROBE = find_tool(CFG["ffprobe"])


class ColourTests(unittest.TestCase):
    def test_slog3_mid_grey(self):
        self.assertAlmostEqual(float(colour.slog3_to_linear(np.float64(420 / 1023))), 0.18, places=4)
        self.assertAlmostEqual(float(colour.slog3_to_linear(np.float64(95 / 1023))), 0.0, places=6)

    def test_vlog_mid_grey(self):
        self.assertAlmostEqual(float(colour.vlog_to_linear(np.float64(0.423))), 0.18, delta=0.002)
        self.assertAlmostEqual(float(colour.vlog_to_linear(np.float64(0.125))), 0.0, places=6)

    def test_applelog_round_trip(self):
        # forward curve from the Apple Log profile, to check the inverse
        def encode(r):
            if r >= colour._AL_RT:
                return colour._AL_GAMMA * np.log2(r + colour._AL_BETA) + colour._AL_DELTA
            if r >= colour._AL_R0:
                return colour._AL_C * (r - colour._AL_R0) ** 2
            return 0.0
        for r in (0.0, 0.005, 0.01, 0.18, 1.0, 8.0):
            self.assertAlmostEqual(float(colour.applelog_to_linear(np.float64(encode(r)))), r, places=5)

    def test_hlg_reference_white_and_grey(self):
        self.assertAlmostEqual(float(colour.hlg_to_linear(np.float64(0.75))), 1.0, places=5)
        self.assertAlmostEqual(float(colour.hlg_to_linear(np.float64(0.38))), 0.18, delta=0.01)

    def test_pq_reference_white(self):
        self.assertAlmostEqual(float(colour.pq_to_linear(np.float64(0.5807))), 1.0, delta=0.02)

    def test_srgb_matches_upstream(self):
        sys.path.insert(0, CFG["upstream_root"])
        from corridorkey.color_utils import srgb_to_linear as upstream
        x = np.linspace(-0.2, 1.2, 1001, dtype=np.float32)
        np.testing.assert_allclose(colour.srgb_to_linear(x), upstream(x), atol=1e-6)

    def test_gamut_matrices_keep_white(self):
        for g in colour.PRIMARIES:
            np.testing.assert_allclose(colour.gamut_matrix(g) @ np.ones(3), np.ones(3), atol=1e-4)

    def test_known_matrices(self):
        np.testing.assert_allclose(colour.gamut_matrix("rec2020")[0],
                                   [1.6605, -0.5876, -0.0728], atol=2e-3)
        np.testing.assert_allclose(colour.gamut_matrix("ap1")[0],
                                   [1.7051, -0.6218, -0.0833], atol=2e-3)

    def test_converter_clamps_negatives(self):
        sat = np.array([[[0.0, 1.0, 0.0]]], np.float32)  # pure BT.2020 green
        keep = colour.Converter("applelog", "keep")(sat)
        clamp = colour.Converter("applelog", "clamp")(sat)
        self.assertLess(float(keep.min()), 0.0)
        self.assertGreaterEqual(float(clamp.min()), 0.0)

    def test_unknown_space(self):
        with self.assertRaises(ValueError):
            colour.Converter("nope")


def _make_video(path, w=64, h=36, frames=5, y_lo=64, y_hi=940, rng="tv"):
    """10-bit 4:2:2 video, left half Y=y_lo, right half Y=y_hi, neutral chroma."""
    y = np.full((h, w), y_lo, np.uint16)
    y[:, w // 2:] = y_hi
    uv = np.full((h, w // 2), 512, np.uint16)
    frame = np.concatenate([y.ravel(), uv.ravel(), uv.ravel()]).astype("<u2").tobytes()
    cmd = [FFMPEG, "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "yuv422p10le",
           "-s", f"{w}x{h}", "-r", "25", "-i", "pipe:0", "-c:v", "ffv1",
           "-color_range", rng, "-colorspace", "bt709", "-color_trc", "bt709",
           "-color_primaries", "bt709", path]
    subprocess.run(cmd, input=frame * frames, check=True)


class DecodeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.video = os.path.join(self.tmp.name, "ramp.mkv")
        _make_video(self.video)

    def tearDown(self):
        self.tmp.cleanup()

    def test_probe(self):
        src = probe.probe(self.video, FFPROBE)
        self.assertEqual((src.kind, src.width, src.height, len(src.frames)), ("video", 64, 36, 5))
        self.assertEqual((src.color_range, src.bit_depth), ("tv", 10))

    def _first(self, rng, first=1):
        src = probe.probe(self.video, FFPROBE)
        frames = src.frames[first - 1:]
        return next(prepare._video_frames(src, frames, "bt709", rng, FFMPEG))

    def test_limited_range_expands_to_0_1(self):
        f = self._first("limited")
        self.assertAlmostEqual(float(f[18, 5, 1]), 0.0, delta=1e-4)
        self.assertAlmostEqual(float(f[18, 60, 1]), 1.0, delta=1e-4)

    def test_full_range_keeps_code_values(self):
        f = self._first("full")
        self.assertAlmostEqual(float(f[18, 5, 1]), 64 / 1023, delta=1e-4)
        self.assertAlmostEqual(float(f[18, 60, 1]), 940 / 1023, delta=1e-4)

    def test_decode_from_later_frame(self):
        f = self._first("limited", first=3)
        self.assertEqual(f.shape, (36, 64, 3))

    def test_camera_log_defaults_to_full_range(self):
        src = probe.probe(self.video, FFPROBE)
        self.assertEqual(prepare.decode_settings(src, "slog3_sgamut3", "auto", "auto"), ("bt709", "full"))
        self.assertEqual(prepare.decode_settings(src, "srgb_rec709", "auto", "auto"), ("bt709", "limited"))

    def test_prepare_plate_and_reuse(self):
        shot = Path(self.tmp.name) / "shot"
        job = jobio._merge(jobio.DEFAULT_JOB, {"source": {"path": self.video},
                                               "frames": {"first": 2, "last": 4}})
        plate = prepare.prepare_plate(probe.probe(self.video, FFPROBE), job, shot, FFMPEG)
        self.assertEqual(plate.frames, [1002, 1003, 1004])
        self.assertFalse(plate.reused)
        img = read_image(plate.pattern % 1002)
        self.assertAlmostEqual(float(img[18, 60, 0]), 1.0, delta=0.005)   # sRGB 1.0 -> linear 1.0
        self.assertAlmostEqual(float(img[18, 5, 0]), 0.0, delta=0.002)
        meta = json.loads((shot / "plate.json").read_text())
        self.assertEqual(meta["range"], "limited")
        again = prepare.prepare_plate(probe.probe(self.video, FFPROBE), job, shot, FFMPEG)
        self.assertTrue(again.reused)

    def test_out_of_range_frames(self):
        src = probe.probe(self.video, FFPROBE)
        with self.assertRaises(EngineError):
            prepare.select_frames(src, 50, 60, 0)

    def test_preview_limits_frames(self):
        src = probe.probe(self.video, FFPROBE)
        self.assertEqual(prepare.select_frames(src, None, None, 2), [1, 2])


class SequenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name) / "seq"
        self.dir.mkdir()
        for f in (1001, 1002, 1003):
            write_exr(str(self.dir / f"shot.{f:04d}.exr"), np.full((8, 16, 3), 0.5, np.float32))

    def tearDown(self):
        self.tmp.cleanup()

    def test_resolve_forms(self):
        want = str(self.dir / "shot.%04d.exr")
        self.assertEqual(probe.resolve_sequence(str(self.dir / "shot.####.exr")), want)
        self.assertEqual(probe.resolve_sequence(str(self.dir / "shot.%04d.exr")), want)
        self.assertEqual(probe.resolve_sequence(str(self.dir)), want)
        self.assertEqual(probe.resolve_sequence(str(self.dir / "shot.1002.exr")), want)

    def test_probe_sequence(self):
        src = probe.probe(str(self.dir / "shot.####.exr"), FFPROBE)
        self.assertEqual((src.kind, src.frames, src.width, src.height), ("sequence", [1001, 1002, 1003], 16, 8))

    def test_linear_passthrough_keeps_numbers(self):
        shot = Path(self.tmp.name) / "shot"
        job = jobio._merge(jobio.DEFAULT_JOB, {"source": {"path": str(self.dir)},
                                               "colour": {"space": "linear_rec709"}})
        plate = prepare.prepare_plate(probe.probe(str(self.dir), FFPROBE), job, shot, FFMPEG)
        self.assertEqual(plate.frames, [1001, 1002, 1003])
        self.assertAlmostEqual(float(read_image(plate.pattern % 1001)[0, 0, 0]), 0.5, places=3)

    def test_raw_rejected(self):
        with self.assertRaises(EngineError):
            probe.probe(str(self.dir / "clip.braw"), FFPROBE)


class _Plate:
    def __init__(self, frames, source_frames, w=16, h=8):
        self.frames, self.source_frames, self.width, self.height = frames, source_frames, w, h


class HintTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_pick_frames(self):
        self.assertEqual(hints._pick_frames([1001, 1002], [1001, 1002], [1, 2]), [1001, 1002])
        self.assertEqual(hints._pick_frames([1, 2, 3], [1001, 1002], [1, 2]), [1, 2])
        self.assertEqual(hints._pick_frames([5, 6], [1001, 1002], [1, 2]), [5, 6])
        with self.assertRaises(EngineError):
            hints._pick_frames([5, 6, 7], [1001, 1002], [1, 2])

    def test_mask_prefers_alpha(self):
        rgba = np.zeros((4, 4, 4), np.float32)
        rgba[..., :3] = 1.0
        rgba[1:3, 1:3, 3] = 1.0
        self.assertEqual(float(hints.to_mask(rgba).sum()), 4.0)
        self.assertEqual(float(hints.to_mask(rgba[..., :3]).sum()), 16.0)

    def _job(self, mode, path, invert=False):
        return jobio._merge(jobio.DEFAULT_JOB, {"source": {"path": "x"},
                                                "hint": {"mode": mode, "path": path, "invert": invert}})

    def test_first_frame_npy(self):
        m = np.zeros((4, 8), np.float32)
        m[:, :4] = 1.0
        write_png16(str(self.root / "roto.png"), m)
        out = hints.prepare_hint(self._job("first_frame", str(self.root / "roto.png")),
                                 _Plate([1001], [1]), self.root, FFMPEG, FFPROBE)
        arr = np.load(out["hint_npy"])
        self.assertEqual((arr.shape, out["hint_mode"]), ((1, 4, 8), "first_frame"))
        self.assertAlmostEqual(float(arr[0, 0, 0]), 1.0, places=3)

    def test_empty_hint_rejected(self):
        write_png16(str(self.root / "black.png"), np.zeros((4, 8), np.float32))
        with self.assertRaises(EngineError):
            hints.prepare_hint(self._job("first_frame", str(self.root / "black.png")),
                               _Plate([1001], [1]), self.root, FFMPEG, FFPROBE)

    def test_sequence_inverted_and_resized(self):
        (self.root / "m").mkdir()
        for f in (1001, 1002):
            write_png16(str(self.root / "m" / f"matte.{f}.png"), np.zeros((4, 8), np.float32))
        out = hints.prepare_hint(self._job("sequence", str(self.root / "m" / "matte.####.png"), True),
                                 _Plate([1001, 1002], [1, 2], w=16, h=8), self.root, FFMPEG, FFPROBE)
        files = sorted(os.listdir(out["hint_path"]))
        self.assertEqual(files, ["hint_000000.png", "hint_000001.png"])
        img = read_image(os.path.join(out["hint_path"], files[0]))
        self.assertEqual(img.shape[:2], (8, 16))
        self.assertAlmostEqual(float(img.min()), 1.0, places=3)


class _CropPlate:
    def __init__(self, d, frames, w, h):
        self.pattern, self.frames, self.width, self.height = str(Path(d) / "p.%04d.exr"), frames, w, h


def _green_plate(d, w=1024, h=512, box=(400, 150, 520, 400), n=5):
    """Linear green screen with a grey subject at box (x0, y0, x1, y1)."""
    plate = _CropPlate(d, list(range(1001, 1001 + n)), w, h)
    for f in plate.frames:
        img = np.empty((h, w, 3), np.float32)
        img[:] = (0.05, 0.45, 0.06)
        img[box[1]:box[3], box[0]:box[2]] = (0.3, 0.25, 0.2)
        write_exr(plate.pattern % f, img)
    return plate


class CropTests(unittest.TestCase):
    def job(self, **c):
        return {"crop": {"mode": "auto", "margin": 64, "box": None, **c}}

    def test_finalize_rounds_to_128_and_stays_inside(self):
        self.assertEqual(crop.finalize((400, 150, 520, 400), 1024, 512, 64), (332, 83, 256, 384))
        x, y, w, h = crop.finalize((0, 0, 30, 30), 1920, 1080, 64)
        self.assertEqual((x, y, w % 128, h % 128), (0, 0, 0, 0))

    def test_auto_finds_subject_on_green(self):
        with tempfile.TemporaryDirectory() as d:
            plate = _green_plate(d)
            box, how = crop.resolve(self.job(), plate, {})
            self.assertIn("green screen", how)
            x, y, w, h = box
            self.assertTrue(x <= 400 and x + w >= 520 and y <= 150 and y + h >= 400, box)
            self.assertLess(w, 1024)

    def test_auto_falls_back_without_screen(self):
        with tempfile.TemporaryDirectory() as d:
            plate = _CropPlate(d, [1001], 512, 256)
            write_exr(plate.pattern % 1001, np.full((256, 512, 3), 0.3, np.float32))
            box, how = crop.resolve(self.job(), plate, {})
            self.assertIsNone(box)
            self.assertIn("full frame", how)

    def test_off_and_manual(self):
        plate = _CropPlate("x", [1], 1920, 1080)
        self.assertEqual(crop.resolve(self.job(mode="off"), plate, {})[0], None)
        box, _ = crop.resolve(self.job(mode="manual", box=[1800, 1000, 512, 512]), plate, {})
        self.assertEqual(box, (1800, 1000, 120, 80))

    def test_hint_and_paste_back(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            plate = _green_plate(d)
            mask = np.zeros((256, 512), np.float32)     # half-size first-frame hint
            mask[75:200, 200:260] = 1.0
            np.save(str(d / "h.npy"), mask[None])
            box, how = crop.resolve(self.job(), plate, {"hint_npy": str(d / "h.npy")})
            self.assertIn("hint", how)
            cut = crop.crop_hint({"hint_npy": str(d / "h.npy"), "hint_mode": "first_frame"}, box, plate, d)
            hm = np.load(cut["hint_npy"])
            self.assertEqual(hm.shape, (1, box[3], box[2]))
            x, y, w, h = box
            alpha = np.zeros((h, w, 3), np.float32)
            alpha[10:20, 10:20] = 1.0
            write_exr(str(d / "a.exr"), alpha)
            edge = crop.paste_file(d / "a.exr", box, 1024, 512)
            full = read_image(str(d / "a.exr"))
            self.assertEqual(full.shape[:2], (512, 1024))
            self.assertEqual(float(full[y + 15, x + 15, 0]), 1.0)
            self.assertEqual(float(full.sum()), 300.0)
            self.assertEqual(edge, 0.0)

    def test_job_validation(self):
        jobio.validate({**jobio.DEFAULT_JOB, "source": {"path": "a"}, "crop": {"mode": "auto"}})
        with self.assertRaises(jobio.JobError):
            jobio.validate({**jobio.DEFAULT_JOB, "source": {"path": "a"}, "crop": {"mode": "manual"}})


class RefineTests(unittest.TestCase):
    def test_presets_and_overrides(self):
        self.assertFalse(refine.active(refine.settings({"preset": "off"})))
        s = refine.settings({"preset": "hairfur", "grow": -2})
        self.assertTrue(refine.active(s))
        self.assertEqual((s["temporal_radius"], s["grow"], s["black"]), (1, -2, 0.0))
        with self.assertRaises(ValueError):
            refine.settings({"preset": "bogus"})

    def test_clean_specks_and_holes(self):
        a = np.zeros((64, 64), np.float32)
        a[10:40, 10:40] = 1.0
        a[20:23, 20:23] = 0.0          # 9 px hole inside the subject
        a[55:57, 55:57] = 1.0          # 4 px speck
        out = refine.clean(a, min_speck=10, min_hole=20)
        self.assertEqual(float(out[21, 21]), 1.0)
        self.assertEqual(float(out[55:57, 55:57].sum()), 0.0)
        self.assertEqual(float(out[0, 0]), 0.0)   # background touching the border stays

    def test_grow_and_levels(self):
        a = np.zeros((32, 32), np.float32)
        a[10:20, 10:20] = 1.0
        self.assertEqual(float(refine.grow(a, 2)[8, 15]), 1.0)
        self.assertEqual(float(refine.grow(a, -2)[11, 15]), 0.0)
        np.testing.assert_allclose(refine.levels(np.array([0.02, 0.5, 0.95], np.float32), 0.02, 0.95, 1.0),
                                   [0.0, 0.516, 1.0], atol=1e-3)

    def test_temporal_steadies_flicker_not_motion(self):
        with tempfile.TemporaryDirectory() as d:
            paths = []
            for i in range(5):
                a = np.zeros((8, 8), np.float32)
                a[:, :4] = 0.5 + (0.04 if i % 2 else -0.04)   # flickering soft edge
                a[:, 6 if i < 2 else 7] = 1.0                    # real motion: big change
                p = os.path.join(d, f"a.{i:04d}.exr")
                write_exr(p, np.repeat(a[..., None], 3, 2))
                paths.append(p)
            refine.refine_sequence(paths, refine.settings({"preset": "off", "temporal_radius": 1,
                                                           "temporal_threshold": 0.1}))
            mid = [read_image(p)[..., 0] for p in paths]
            self.assertLess(abs(float(mid[2][0, 0]) - 0.5), 0.03)    # flicker damped
            self.assertGreater(float(mid[3][0, 7]), 0.95)            # moving edge kept
            self.assertFalse([f for f in os.listdir(d) if "refine" in f])


class NukePathTests(unittest.TestCase):
    def test_nuke_range_suffix_and_out_of_range_frame(self):
        with tempfile.TemporaryDirectory() as d:
            for f in (1001, 1002, 1003):
                write_exr(os.path.join(d, f"plate.{f}.exr"), np.zeros((4, 4, 3), np.float32))
            want = os.path.join(d, "plate.%04d.exr")
            self.assertEqual(probe.resolve_sequence(d + "/plate.####.exr 1001-1003"), want)
            # an expression evaluated at frame 1 names a frame the plate doesn't have
            self.assertEqual(probe.resolve_sequence(d + "/plate.0001.exr"), want)
            src = probe.probe(d + "/plate.####.exr 1001-1003", FFPROBE)
            self.assertEqual(src.frames, [1001, 1002, 1003])
            with self.assertRaises(EngineError):
                probe.resolve_sequence(d + "/other.0001.exr")


class HintScreenShareTests(unittest.TestCase):
    def test_rough_box_vs_tight_roto(self):
        with tempfile.TemporaryDirectory() as d:
            plate = _green_plate(d)                      # subject box x 400-520, y 150-400
            tight = np.zeros((512, 1024), np.float32)
            tight[150:400, 400:520] = 1.0
            rough = np.zeros((512, 1024), np.float32)
            rough[:, 300:1024] = 1.0
            for name, m in (("tight", tight), ("rough", rough)):
                np.save(os.path.join(d, name + ".npy"), m[None])
            s_tight = hints.screen_share({"hint_npy": os.path.join(d, "tight.npy")}, plate)
            s_rough = hints.screen_share({"hint_npy": os.path.join(d, "rough.npy")}, plate)
            self.assertLess(s_tight, 0.05)
            self.assertGreater(s_rough, hints.SCREEN_LOWER)
            self.assertIsNone(hints.screen_share({}, plate))


class MiscTests(unittest.TestCase):
    def test_despill(self):
        px = np.array([[[0.2, 0.8, 0.2]]], np.float32)
        self.assertAlmostEqual(float(despill.despill(px, 1.0)[0, 0, 1]), 0.2, places=5)
        self.assertAlmostEqual(float(despill.despill(px, 0.5)[0, 0, 1]), 0.5, places=5)
        grey = np.full((1, 1, 3), 0.4, np.float32)
        np.testing.assert_allclose(despill.despill(grey, 1.0), grey)
        blue = np.array([[[0.1, 0.1, 0.9]]], np.float32)
        self.assertAlmostEqual(float(despill.despill(blue, 1.0, "blue")[0, 0, 2]), 0.1, places=5)

    def test_despill_edges_keeps_green_clothing(self):
        px = np.array([[[0.05, 0.40, 0.06],     # saturated green cloth, solid
                        [0.70, 0.80, 0.70],     # white fur with green bounce, solid
                        [0.20, 0.50, 0.20]]],   # half-transparent edge
                      np.float32)
        alpha = np.array([[1.0, 1.0, 0.3]], np.float32)
        out = despill.despill(px, 1.0, alpha=alpha, mode="edges")
        self.assertAlmostEqual(float(out[0, 0, 1]), 0.40, places=5)   # cloth untouched
        self.assertAlmostEqual(float(out[0, 1, 1]), 0.70, places=5)   # bounce removed
        self.assertAlmostEqual(float(out[0, 2, 1]), 0.20, places=5)   # edge fully limited
        with self.assertRaises(ValueError):
            despill.despill(px, 1.0, mode="edges")

    def test_job_defaults_and_validation(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "job.json"
            p.write_text(json.dumps({"schema_version": 1, "source": {"path": "a.mp4"}}))
            job = jobio.load_job(p)
            self.assertEqual(job["shot_dir"], d)
            self.assertEqual(job["frames"]["start_frame"], 1001)
            p.write_text(json.dumps({"schema_version": 1, "source": {"path": "a.mp4"},
                                     "hint": {"mode": "sequence"}}))
            with self.assertRaises(jobio.JobError):
                jobio.load_job(p)

    def test_next_version(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(next_version(Path(d)), "v001")
            (Path(d) / "v001").mkdir()
            (Path(d) / "v007").mkdir()
            (Path(d) / "preview").mkdir()
            self.assertEqual(next_version(Path(d)), "v008")


if __name__ == "__main__":
    unittest.main()

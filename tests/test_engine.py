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

from ck_engine import colour, despill, hints, jobio, prepare, probe  # noqa: E402
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


class MiscTests(unittest.TestCase):
    def test_despill(self):
        px = np.array([[[0.2, 0.8, 0.2]]], np.float32)
        self.assertAlmostEqual(float(despill.despill(px, 1.0)[0, 0, 1]), 0.2, places=5)
        self.assertAlmostEqual(float(despill.despill(px, 0.5)[0, 0, 1]), 0.5, places=5)
        grey = np.full((1, 1, 3), 0.4, np.float32)
        np.testing.assert_allclose(despill.despill(grey, 1.0), grey)
        blue = np.array([[[0.1, 0.1, 0.9]]], np.float32)
        self.assertAlmostEqual(float(despill.despill(blue, 1.0, "blue")[0, 0, 2]), 0.1, places=5)

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

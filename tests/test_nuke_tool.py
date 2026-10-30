"""ck2nuke logic with a stand-in `nuke` module (tests/fake_nuke.py) and the real engine.

    D:\\CorridorKey2\\venv\\Scripts\\python.exe -m unittest tests.test_nuke_tool -v

Covers: panel -> job.json, hint render path for a 4K plate (NC 1920x1080 limit),
runner following a real engine run (plate prepare, CPU), loader's pasted comp.
Real-Nuke behaviour is tested by tests\run_nuke_auto.ps1.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests"))
sys.path.insert(0, str(REPO / "nuke"))
sys.path.insert(0, str(REPO))

import fake_nuke  # noqa: E402

fake_nuke.install()
from ck2nuke import loader, panel, runner  # noqa: E402
from test_engine import _make_video  # noqa: E402


def set_panel(**values):
    def hook(p):
        for k, v in values.items():
            p.k[k].setValue(v)
        p._refresh()
    fake_nuke.panel_hook = hook


def reset():
    fake_nuke.messages.clear()
    fake_nuke.selected.clear()
    fake_nuke._by_name.clear()
    fake_nuke.panel_hook = None


class NukeToolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        reset()
        self.started = []
        self._orig_start = runner.start
        panel.runner.start = lambda job_path, title="": self.started.append(job_path)

    def tearDown(self):
        panel.runner.start = self._orig_start
        self.tmp.cleanup()

    def _job(self):
        self.assertEqual(fake_nuke.messages, [], fake_nuke.messages)
        self.assertEqual(len(self.started), 1)
        return json.loads(Path(self.started[0]).read_text())

    def test_file_source_job(self):
        video = str(self.root / "clip.mp4")
        set_panel(src_file=video, shot_root=str(self.root / "shots"),
                  colour="Sony S-Log3 / S-Gamut3.Cine", preview=True, preview_frames=12,
                  despill=0.3)
        panel.key_shot()
        job = self._job()
        self.assertEqual(job["source"]["path"], video)
        self.assertEqual(job["shot_dir"], (self.root / "shots" / "clip").as_posix())
        self.assertEqual(job["colour"]["space"], "slog3_sgamut3cine")
        self.assertEqual(job["frames"]["preview_frames"], 12)
        self.assertEqual(job["frames"]["first"], None)
        self.assertEqual(job["hint"]["mode"], "none")
        self.assertEqual(job["despill"]["amount"], 0.3)

    def test_read_with_roto_hint_on_4k_plate(self):
        shot = self.root / "shots" / "s010"
        read = fake_nuke.Node("Read", _size=(3840, 2160), name="Read1")
        read["file"].setValue((shot / "plate_lin" / "plate.####.exr").as_posix())
        read["first"].setValue(1001)
        read["last"].setValue(1010)
        fake_nuke.Node("Roto", _size=(3840, 2160), name="Roto1")
        fake_nuke.selected.extend(["Read1", "Roto1"])
        set_panel()
        panel.key_shot()
        job = self._job()
        self.assertEqual(job["shot_dir"], shot.as_posix())
        self.assertEqual(job["colour"]["space"], "linear_rec709")
        self.assertEqual((job["frames"]["first"], job["frames"]["last"]), (1001, 1010))
        self.assertEqual(job["hint"]["mode"], "first_frame")
        import cv2
        img = cv2.imread(job["hint"]["path"].replace("####", "1001"), cv2.IMREAD_UNCHANGED)
        self.assertEqual(img.shape[:2], (1080, 1920))   # scaled down for the NC render limit
        self.assertFalse(fake_nuke.exists("CK2_hintWrite"))  # temp nodes removed
        self.assertFalse(fake_nuke.exists("CK2_hintReformat"))

    def test_missing_source_message(self):
        set_panel(shot_root=str(self.root))
        panel.key_shot()
        self.assertTrue(fake_nuke.messages and "source" in fake_nuke.messages[0].lower())
        self.assertEqual(self.started, [])


class RunnerLoaderTests(unittest.TestCase):
    def setUp(self):
        reset()

    def test_prepare_round_trip(self):
        """Runner + loader against a real engine run (stage 'prepare', CPU only)."""
        with tempfile.TemporaryDirectory() as d:
            video = os.path.join(d, "tiny.mkv")
            _make_video(video, w=64, h=36, frames=4)
            shot = Path(d) / "shot"
            shot.mkdir()
            jp = shot / "job.json"
            jp.write_text(json.dumps({"schema_version": 1, "stage": "prepare",
                                      "shot_dir": shot.as_posix(), "source": {"path": video}}))
            fake_nuke.ProgressTask.log.clear()
            status = runner._follow(runner._spawn(jp.as_posix()), jp.as_posix(), "test")
            self.assertEqual(status["state"], "done", status)
            self.assertTrue(any(k == "progress" for k, _ in fake_nuke.ProgressTask.log))
            runner._finish(status, jp.as_posix())
            self.assertTrue(fake_nuke.exists("CK2_shot_plate"))
            self.assertEqual(fake_nuke.tcl("value CK2_shot_plate.colorspace"), "linear")
            self.assertIn("plate ready", fake_nuke.messages[-1])

    def test_loader_builds_comp(self):
        status = {"state": "done", "stage": "all", "shot_dir": "D:/CKShots/s020", "version": "v003",
                  "plate": {"pattern": "D:/x/plate_lin/plate.####.exr", "first": 1001, "last": 1048,
                            "width": 3840, "height": 2160, "fps": 25.0},
                  "outputs": {"alpha": "D:/x/key/v003/alpha/alpha.####.exr",
                              "fg": "D:/x/key/v003/fg/fg.####.exr",
                              "fg_despill": "D:/x/key/v003/fg_despill/fg_despill.####.exr"}}
        merge = loader.load_result(status)
        t = "CK2_s020_v003_"
        self.assertEqual(merge, t + "over")
        inp = fake_nuke._input_name
        self.assertEqual((inp(t + "copy", 0), inp(t + "copy", 1)), (t + "fg", t + "alpha"))
        self.assertEqual(inp(t + "premult", 0), t + "copy")
        self.assertEqual((inp(t + "over", 0), inp(t + "over", 1)), (t + "bg", t + "premult"))
        self.assertIn("fg_despill", fake_nuke.tcl("value {}fg.file".format(t)))
        self.assertEqual(fake_nuke.tcl("value {}over.operation".format(t)), "over")
        # loading the same shot again gets fresh names instead of clobbering
        self.assertEqual(loader.load_result(status), t + "over2")


if __name__ == "__main__":
    unittest.main()

"""Headless GUI smoke test (Qt 'offscreen' platform). Skipped if PySide6 cannot start.

Run:  python -m unittest tests.test_ui_smoke -v
"""
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from PySide6.QtWidgets import QApplication, QMessageBox
    HAVE_QT = True
except Exception:          # pragma: no cover
    HAVE_QT = False

import numpy as np
from PIL import Image

from tests.test_processing import make_subject


def pump(cond, timeout=20.0):
    end = time.time() + timeout
    while time.time() < end:
        QApplication.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return False


@unittest.skipUnless(HAVE_QT, "PySide6 not available")
class UiSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        QMessageBox.information = staticmethod(lambda *a, **k: None)   # never block on dialogs
        QMessageBox.critical = staticmethod(lambda *a, **k: None)
        from ui.main_window import MainWindow
        cls.win = MainWindow()
        cls.win.show()
        cls.tmp = tempfile.TemporaryDirectory()
        cls.img = os.path.join(cls.tmp.name, "subject.png")
        Image.fromarray(make_subject(500, 380)).save(cls.img)

    @classmethod
    def tearDownClass(cls):
        cls.win.close()
        cls.tmp.cleanup()

    def test_full_flow(self):
        w = self.win
        w.load_path(self.img)
        self.assertTrue(pump(lambda: w.subject is not None), "image did not load")
        self.assertTrue(pump(lambda: w._last_still is not None and w._preview_worker is None), "no preview")
        first = w._last_still.copy()
        self.assertEqual(first.ndim, 3)

        # slider change re-renders the preview
        w.sliders["edge_thickness"]._slider.setValue(80)
        self.assertTrue(pump(lambda: not np.array_equal(w._last_still, first)
                             if w._last_still.shape == first.shape else True))

        # dragging moves the subject and syncs the sliders
        before = w.settings.pos_x
        w._on_subject_dragged(0.1, 0.0)
        self.assertGreater(w.settings.pos_x, before)

        # animation preview plays and stops
        w.toggle_preview_animation()
        self.assertTrue(pump(lambda: w._playing), "animation preview did not start")
        self.assertGreater(len(w._frames), 10)
        pump(lambda: False, 0.3)
        w.toggle_preview_animation()
        self.assertFalse(w._playing)

        # reset
        w.reset_settings()
        self.assertEqual(w.settings.pos_x, 50)

    def test_exports(self):
        from export.png_export import export_png
        from export.video_export import export_mp4
        w = self.win
        w.load_path(self.img)
        self.assertTrue(pump(lambda: w.subject is not None))
        s = w.settings
        s.resolution, s.duration, s.fps = 720, 3, 24
        png = os.path.join(self.tmp.name, "a.png")
        w._begin_export("export_png", export_png, png, w.subject, s, cancellable=False)
        self.assertTrue(pump(lambda: os.path.exists(png) and w._export_worker is None))

        mp4 = os.path.join(self.tmp.name, "a.mp4")
        w._begin_export("export_mp4", export_mp4, mp4, w.subject, s, cancellable=True)
        self.assertTrue(pump(lambda: os.path.exists(mp4) and w._export_worker is None, 60))
        self.assertGreater(os.path.getsize(mp4), 10_000)

        # cancelling leaves no partial file behind
        mp4b = os.path.join(self.tmp.name, "b.mp4")
        w._begin_export("export_mp4", export_mp4, mp4b, w.subject, s, cancellable=True)
        w._cancel_export()
        self.assertTrue(pump(lambda: w._export_worker is None, 30))
        self.assertFalse(os.path.exists(mp4b))
        self.assertFalse(os.path.exists(mp4b + ".part"))

    def test_transition_preview_and_export(self):
        from export.transition_export import export_transition_mp4
        w = self.win
        w.load_path(self.img)
        self.assertTrue(pump(lambda: w.subject is not None))
        w.settings.resolution, w.settings.duration, w.settings.fps = 720, 3, 24
        w.settings.bg_mode = "solid"
        self.assertEqual(w._transition_picture().shape[2], 3)      # loaded image is used

        w.toggle_preview_transition()
        self.assertTrue(pump(lambda: w._playing, 40), "transition preview did not start")
        self.assertEqual(len(w._frames), 72)
        self.assertEqual(w.btn_tpreview.text(), "Stop preview")
        self.assertFalse(w.btn_preview.isEnabled())
        w.toggle_preview_transition()
        self.assertFalse(w._playing)
        self.assertEqual(w.btn_tpreview.text(), "Preview transition")

        out = os.path.join(self.tmp.name, "t.mp4")
        w._begin_export("export_transition", export_transition_mp4, out, w._transition_picture(),
                        w.settings, cancellable=True)
        self.assertTrue(pump(lambda: os.path.exists(out) and w._export_worker is None, 90))
        self.assertGreater(os.path.getsize(out), 10_000)

        # cancel leaves nothing behind
        out2 = os.path.join(self.tmp.name, "t2.mp4")
        w._begin_export("export_transition", export_transition_mp4, out2, None,
                        w.settings, cancellable=True)
        w._cancel_export()
        self.assertTrue(pump(lambda: w._export_worker is None, 60))
        self.assertFalse(os.path.exists(out2) or os.path.exists(out2 + ".part"))

    def test_bad_file_reports_error(self):
        w = self.win
        bad = os.path.join(self.tmp.name, "bad.png")
        Path(bad).write_bytes(b"garbage")
        w.load_path(bad)
        self.assertTrue(pump(lambda: not any(x.kind == "load" for x in w._workers)))


if __name__ == "__main__":
    unittest.main()

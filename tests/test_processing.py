"""Headless tests for the processing and export code (no GUI needed).

Run from the project root:   python -m unittest discover -s tests -v
"""
import os
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cv2
import numpy as np
from PIL import Image

from export.png_export import export_png
from export.video_export import export_mp4, find_ffmpeg
from processing.animation import animation_state
from processing.errors import ExportError, ImageLoadError
from processing.loader import load_subject
from processing.mask import prepare_subject
from processing.pipeline import render_still
from processing.settings import ANIMATION_STYLES, CUTOUT_STYLES, Settings
from processing.sprite import build_sprite


def make_subject(w=420, h=300) -> np.ndarray:
    """Synthetic soft-edged ellipse with a colour gradient and a few thin 'hairs'."""
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    d = ((xx - w / 2) / (w * 0.42)) ** 2 + ((yy - h / 2) / (h * 0.40)) ** 2
    alpha = np.clip((1.0 - d) * 12, 0, 1)
    img = np.zeros((h, w, 4), np.uint8)
    img[..., 0] = 60 + 180 * xx / w
    img[..., 1] = 90 + 100 * yy / h
    img[..., 2] = 200 - 120 * xx / w
    for k in range(6):
        cv2.line(alpha, (w // 2 + 20 * k, 30), (w // 2 + 30 * k - 40, 2), 0.6, 1)
    img[..., 3] = np.clip(alpha * 255, 0, 255)
    return prepare_subject(img)


class ProcessingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.subject = make_subject()

    def test_still_each_cutout_style(self):
        for style in CUTOUT_STYLES:
            s = Settings(cutout_style=style, resolution=720)
            frame = render_still(self.subject, s, max_side=640)
            self.assertEqual(frame.dtype, np.uint8)
            self.assertEqual(frame.shape, (360, 640, 3), style)
            self.assertGreater(frame.std(), 5, style)

    def test_vertical_aspect_and_sizes(self):
        self.assertEqual(Settings(aspect="9:16", resolution=1080).frame_size(), (1080, 1920))
        self.assertEqual(Settings(aspect="16:9", resolution=720).frame_size(), (1280, 720))

    def test_fixed_seed_is_deterministic(self):
        s = Settings(resolution=720)
        a = render_still(self.subject, s, max_side=480)
        b = render_still(self.subject, s, max_side=480)
        c = render_still(self.subject, replace(s, seed=999), max_side=480)
        self.assertTrue(np.array_equal(a, b))
        self.assertFalse(np.array_equal(a, c))

    def test_transparent_background_has_alpha(self):
        s = Settings(bg_mode="transparent", resolution=720)
        frame = render_still(self.subject, s, max_side=480)
        self.assertEqual(frame.shape[2], 4)
        self.assertEqual(frame[0, 0, 3], 0)                 # corner is empty
        self.assertEqual(frame[frame.shape[0] // 2, frame.shape[1] // 2, 3], 255)

    def test_green_background(self):
        s = Settings(bg_mode="green", shadow_intensity=0, resolution=720)
        frame = render_still(self.subject, s, max_side=480)
        self.assertTrue(np.array_equal(frame[0, 0], [0, 255, 0]))

    def test_paper_edge_extends_beyond_subject(self):
        s0 = Settings(edge_thickness=0, bg_mode="transparent", shadow_intensity=0, resolution=720)
        s1 = replace(s0, edge_thickness=60)
        a0 = render_still(self.subject, s0, max_side=480)[..., 3].astype(int).sum()
        a1 = render_still(self.subject, s1, max_side=480)[..., 3].astype(int).sum()
        self.assertGreater(a1, a0 * 1.1)

    def test_animation_styles_move_and_are_static_at_zero(self):
        s = Settings(resolution=720)
        size = s.frame_size()
        n = s.fps * s.duration
        for style in ANIMATION_STYLES:
            states = [animation_state(style, i, n, s.fps, s, size) for i in range(n)]
            moved = max(abs(t.dx) + abs(t.dy) + abs(t.angle) + abs(t.sx - 1) + abs(1 - t.opacity)
                        for t in states)
            self.assertGreater(moved, 0, style)
            still = animation_state(style, 5, n, s.fps, replace(s, animation_amount=0), size)
            self.assertEqual((still.dx, still.dy, still.angle, still.sx, still.opacity), (0, 0, 0, 1, 1))

    def test_edges_identical_across_frames(self):
        """No flicker: warping with an identity transform reproduces the same pixels every time."""
        from processing.compositor import render_frame
        from processing.transform import TransformState
        s = Settings(resolution=720)
        size = s.frame_size(480)
        sprite = build_sprite(self.subject, s, size, s.seed)
        f1 = render_frame(sprite, s, size, TransformState())
        f2 = render_frame(sprite, s, size, TransformState())
        self.assertTrue(np.array_equal(f1, f2))

    def test_validation(self):
        with self.assertRaises(ValueError):
            Settings(cutout_style="nope").validate()
        with self.assertRaises(ValueError):
            Settings(duration=2).validate()
        self.assertEqual(Settings(subject_size=500).validate().subject_size, 100)


class TransitionTests(unittest.TestCase):
    def test_timeline_and_frames(self):
        from processing.crumple import TransitionRenderer, timeline, make_demo_picture
        s = Settings(resolution=720, duration=4, fps=24, bg_mode="solid")
        c0, _ = timeline(0.0)
        self.assertEqual(c0, 1.0)                           # starts as a ball
        self.assertEqual(timeline(0.5)[0], 0.0)             # flat sheet in the middle
        self.assertEqual(timeline(0.99), (1.0, 1.0))        # gone at the end
        size = s.frame_size(480)
        r = TransitionRenderer(None, s, size)
        self.assertEqual(r.n_frames, 96)
        first, mid, last = r.frame(0), r.frame(r.n_frames // 2), r.frame(r.n_frames - 1)
        self.assertEqual(first.shape, (size[1], size[0], 3))
        # stop-motion hold: frames of one pose are identical, the next pose differs
        self.assertTrue(np.array_equal(r.frame(10), r.frame(11)))
        self.assertFalse(np.array_equal(r.frame(10), r.frame(12)))
        # the picture is revealed in the middle (more colourful than the empty table) and gone at the end
        self.assertGreater(mid.astype(float).std(), first.astype(float).std())
        self.assertLess(last.astype(float).std(), mid.astype(float).std())
        self.assertTrue(np.array_equal(last, np.clip(r.bg, 0, 255).astype(np.uint8)))   # empty table

    def test_custom_picture_vertical_and_green(self):
        from processing.crumple import TransitionRenderer
        pic = np.zeros((300, 200, 3), np.uint8)
        pic[..., 0] = 220                                   # red picture
        s = Settings(aspect="9:16", resolution=720, duration=3, bg_mode="green")
        size = s.frame_size(480)
        r = TransitionRenderer(pic, s, size)
        mid = r.frame(r.n_frames // 2)
        self.assertEqual(mid.shape, (size[1], size[0], 3))
        self.assertTrue(np.array_equal(mid[0, 0], [0, 255, 0]))          # green background
        self.assertGreater(int((mid[..., 0] > 150).sum()), 1000)          # red picture visible

    def test_export_rejects_transparent(self):
        from export.transition_export import export_transition_mp4
        with self.assertRaises(ExportError):
            export_transition_mp4("/tmp/x.mp4", None, Settings(bg_mode="transparent"))


class IoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.subject = make_subject()
        cls.tmp = tempfile.TemporaryDirectory()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_load_transparent_and_opaque_and_garbage(self):
        p = os.path.join(self.tmp.name, "t.png")
        Image.fromarray(make_subject()).save(p)
        li = load_subject(p)
        self.assertTrue(li.has_alpha)
        pj = os.path.join(self.tmp.name, "o.jpg")
        Image.fromarray(make_subject()[..., :3]).save(pj)
        self.assertFalse(load_subject(pj).has_alpha)
        bad = os.path.join(self.tmp.name, "bad.png")
        Path(bad).write_bytes(b"not an image")
        with self.assertRaises(ImageLoadError):
            load_subject(bad)
        with self.assertRaises(ImageLoadError):
            load_subject(os.path.join(self.tmp.name, "missing.png"))

    def test_png_export_transparent(self):
        p = os.path.join(self.tmp.name, "out.png")
        export_png(p, self.subject, Settings(bg_mode="transparent", resolution=720))
        img = Image.open(p)
        self.assertEqual(img.mode, "RGBA")
        self.assertEqual(img.size, (1280, 720))

    def test_mp4_rejects_transparent(self):
        with self.assertRaises(ExportError):
            export_mp4(os.path.join(self.tmp.name, "x.mp4"), self.subject,
                       Settings(bg_mode="transparent"))

    def test_mp4_export(self):
        try:
            find_ffmpeg()
        except ExportError:
            self.skipTest("FFmpeg not available")
        p = os.path.join(self.tmp.name, "out.mp4")
        seen = []
        s = Settings(resolution=720, duration=3, fps=24, bg_mode="green", animation_style="bounce")
        export_mp4(p, self.subject, s, progress=seen.append)
        self.assertGreater(os.path.getsize(p), 10_000)
        self.assertEqual(seen[-1], 100)
        with open(p, "rb") as f:
            self.assertIn(b"ftyp", f.read(32))
        self.assertFalse(os.path.exists(p + ".part"))


if __name__ == "__main__":
    unittest.main()

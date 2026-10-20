#!/usr/bin/env python
"""Regenerates the project artwork in assets/ with the app's own paper engine:

    icon.png / icon.ico / icon.icns   application icon
    avatar.png                        square profile picture (GitHub avatar)
    banner.png                        1280x640 social-preview banner (GitHub "Social preview")
    demo.gif                          README animation of the unfold / crumple transition
    screenshot.png                    screenshot of the real window (needs PySide6)

Usage (from the project root):   python tools/make_assets.py [--skip-screenshot]
Fonts: Poppins if installed (Google Fonts), otherwise DejaVu Sans / Pillow's default.
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from processing.compositor import render_frame
from processing.crumple import CrumpleSheet, TransitionRenderer, make_demo_picture
from processing.mask import prepare_subject
from processing.settings import Settings
from processing.sprite import build_sprite
from processing.transform import TransformState
from processing.utils import smoothstep

ASSETS = ROOT / "assets"
FONT_DIRS = ["/usr/share/fonts/truetype/google-fonts", "/usr/share/fonts/truetype/dejavu",
             "C:/Windows/Fonts", "/Library/Fonts", "/System/Library/Fonts", os.path.expanduser("~/.fonts")]


def font(name_candidates, size):
    for d in FONT_DIRS:
        for n in name_candidates:
            p = Path(d) / n
            if p.is_file():
                return ImageFont.truetype(str(p), size)
    return ImageFont.load_default(size)


# ------------------------------------------------------------------------------ paper layers
def picture_subject(w, h, shape="rect", seed=3):
    """Sunset picture as an RGBA subject: 'rect' (rounded corners) or 'circle'."""
    pic = make_demo_picture(w, h, seed)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    if shape == "circle":
        d = np.hypot(xx - w / 2, yy - h / 2) - min(w, h) / 2
    else:
        r = 0.06 * min(w, h)
        qx, qy = np.abs(xx - w / 2) - (w / 2 - r), np.abs(yy - h / 2) - (h / 2 - r)
        d = np.hypot(np.maximum(qx, 0), np.maximum(qy, 0)) + np.minimum(np.maximum(qx, qy), 0) - r
    alpha = (np.clip(0.5 - d, 0, 1) * 255).astype(np.uint8)
    return prepare_subject(np.dstack([pic, alpha]))


def plain_subject(w, h, colour=(246, 242, 233)):
    img = np.zeros((h, w, 4), np.uint8)
    img[..., :3], img[..., 3] = colour, 255
    return prepare_subject(img)


def paper_layer(subject, frame, size, angle=0.0, dx=0.0, dy=0.0, edge=40, rough=60, style="torn",
                shadow=65, blur=45, seed=5, sx=60, sy=62):
    """Render one torn-paper cut-out onto a transparent frame of the given size (RGBA uint8)."""
    s = Settings(subject_size=size, edge_thickness=edge, edge_roughness=rough, edge_detail=60,
                 texture_intensity=45, shadow_x=sx, shadow_y=sy, shadow_blur=blur,
                 shadow_intensity=shadow, cutout_style=style, bg_mode="transparent")
    sprite = build_sprite(subject, s, frame, seed)
    return render_frame(sprite, s, frame, TransformState(angle=angle, dx=dx, dy=dy))


def over(base: Image.Image, layer: np.ndarray) -> Image.Image:
    return Image.alpha_composite(base, Image.fromarray(layer, "RGBA"))


# ------------------------------------------------------------------------------ icon / avatar
def gradient(w, h, c0, c1, c2=None):
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    t = (xx * 0.4 + yy * 0.6) / (0.4 * w + 0.6 * h)
    a, b = np.array(c0, np.float32), np.array(c1, np.float32)
    img = a + (b - a) * t[..., None]
    if c2 is not None:                                     # warm glow bottom-right
        g = np.exp(-(np.hypot(xx / w - 0.85, yy / h - 1.0) / 0.55) ** 2)[..., None]
        img = img + g * (np.array(c2, np.float32) - img) * 0.35
    return img


def make_icon(N=1024, full_bleed=False, paper_scale=1.0) -> Image.Image:
    bg = gradient(N, N, (22, 28, 66), (74, 46, 128), (255, 140, 90))
    tile = Image.fromarray(np.clip(bg, 0, 255).astype(np.uint8), "RGB").convert("RGBA")
    # a stack of two sheets: blank one behind, sunset photo in front
    back = paper_layer(plain_subject(800, 600), (N, N), 56 * paper_scale, angle=10, dx=0.03 * N, dy=0.02 * N,
                       edge=18, rough=70, shadow=60, blur=40, seed=11)
    front = paper_layer(picture_subject(800, 600), (N, N), 60 * paper_scale, angle=-6, dx=-0.01 * N,
                        dy=0.0, edge=38, rough=62, shadow=75, blur=50, seed=5)
    tile = over(over(tile, back), front)
    if full_bleed:
        return tile.convert("RGB")
    yy, xx = np.mgrid[0:N, 0:N].astype(np.float32)
    r = 0.225 * N
    qx, qy = np.abs(xx - N / 2) - (N / 2 - r), np.abs(yy - N / 2) - (N / 2 - r)
    d = np.hypot(np.maximum(qx, 0), np.maximum(qy, 0)) + np.minimum(np.maximum(qx, qy), 0) - r
    mask = np.clip(0.5 - d, 0, 1)
    rim = np.clip(1 - np.abs(d + 3) / 2.0, 0, 1) * 0.18          # thin light rim
    arr = np.array(tile, np.float32)
    arr[..., :3] = arr[..., :3] * (1 - rim[..., None]) + 255 * rim[..., None]
    arr[..., 3] = mask * 255
    return Image.fromarray(arr.astype(np.uint8), "RGBA")


def save_icons(icon: Image.Image):
    icon.save(ASSETS / "icon.png")
    icon.save(ASSETS / "icon.ico", sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
    try:
        icon.save(ASSETS / "icon.icns")
    except Exception as e:                                 # pragma: no cover
        print("  (icns skipped:", e, ")")


# ------------------------------------------------------------------------------ banner
def text_shadowed(img: Image.Image, xy, text, fnt, fill, anchor="ls", shadow=(0, 0, 0, 140), off=3, blur=4):
    sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).text((xy[0] + off, xy[1] + off), text, font=fnt, fill=shadow, anchor=anchor)
    img.alpha_composite(sh.filter(ImageFilter.GaussianBlur(blur)))
    ImageDraw.Draw(img).text(xy, text, font=fnt, fill=fill, anchor=anchor)


def make_banner(icon: Image.Image) -> Image.Image:
    W, H = 1280, 640
    bg = gradient(W, H, (14, 18, 44), (58, 36, 104), (255, 130, 90))
    rng = np.random.default_rng(1)
    bg += rng.normal(0, 1.8, bg.shape)
    img = Image.fromarray(np.clip(bg, 0, 255).astype(np.uint8), "RGB").convert("RGBA")

    # right side: unfolding sheet, torn photo, paper ball
    pic = make_demo_picture(520, 350, 3)
    sheet = CrumpleSheet(pic, 520, 350, 0.62, 7)
    cfg = Settings(bg_mode="transparent")
    r = np.random.default_rng(2)
    unfold = render_frame(sheet.render(0.42, r), cfg, (W, H),
                          TransformState(dx=345, dy=-40, sx=1.0, sy=1.0, angle=-4, lift=0.2))
    ball = render_frame(sheet.render(1.0, r), cfg, (W, H),
                        TransformState(dx=150, dy=205, sx=0.62, sy=0.62, angle=20, lift=0.5))
    torn = paper_layer(picture_subject(560, 560, "circle", 9), (W, H), 42, angle=7, dx=470, dy=150,
                       edge=32, rough=65, shadow=70, blur=42, seed=21)
    for layer in (unfold, ball, torn):
        img = over(img, layer)

    # left side: icon, title, tagline, chips
    ic = icon.resize((132, 132), Image.Resampling.LANCZOS)
    img.alpha_composite(ic, (72, 70))
    big = font(["Poppins-Bold.ttf", "DejaVuSans-Bold.ttf"], 88)
    mid = font(["Poppins-Medium.ttf", "DejaVuSans.ttf"], 34)
    small = font(["Poppins-Medium.ttf", "DejaVuSans.ttf"], 24)
    text_shadowed(img, (72, 300), "PaperCut", big, (255, 255, 255, 255))
    text_shadowed(img, (72, 392), "Studio", big, (255, 196, 140, 255))
    text_shadowed(img, (72, 462), "Torn-paper cutouts & stop-motion", mid, (232, 236, 250, 255), off=2, blur=3)
    text_shadowed(img, (72, 508), "videos from any image.", mid, (232, 236, 250, 255), off=2, blur=3)
    x = 72
    for chip in ("Python", "PySide6", "OpenCV", "100% local"):
        wtxt = int(ImageDraw.Draw(img).textlength(chip, font=small))
        pill = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ImageDraw.Draw(pill).rounded_rectangle((x, 546, x + wtxt + 34, 588), 21, fill=(255, 255, 255, 34),
                                               outline=(255, 255, 255, 70), width=1)
        img.alpha_composite(pill)
        ImageDraw.Draw(img).text((x + 17, 567), chip, font=small, fill=(255, 255, 255, 235), anchor="lm")
        x += wtxt + 34 + 12
    return img.convert("RGB")


# ------------------------------------------------------------------------------ gif / screenshot
def make_gif():
    s = Settings(resolution=720, fps=24, bg_mode="solid", bg_color=(44, 52, 84))
    size = s.frame_size(480)
    r = TransitionRenderer(None, s, size, seconds=8.5, hold=2)
    frames = []
    for i in range(0, r.n_frames, 2):                      # one frame per stop-motion pose (12 fps)
        im = Image.fromarray(r.frame(i)).convert("P", palette=Image.Palette.ADAPTIVE, colors=128,
                                                 dither=Image.Dither.NONE)
        frames.append(im)
    frames[0].save(ASSETS / "demo.gif", save_all=True, append_images=frames[1:], duration=83, loop=0,
                   disposal=1)


def make_screenshot():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        print("  (screenshot skipped: PySide6 not installed)")
        return
    app = QApplication.instance() or QApplication([])
    from ui.main_window import MainWindow
    tmp = os.path.join(tempfile.gettempdir(), "papercut_demo_subject.png")
    Image.fromarray(picture_subject(640, 640, "circle", 9)).save(tmp)
    w = MainWindow()
    w.resize(1420, 900)
    w.show()
    w.load_path(tmp)
    end = time.time() + 30
    while time.time() < end and (w._last_still is None or w._preview_worker is not None):
        app.processEvents()
        time.sleep(0.01)
    for _ in range(40):
        app.processEvents()
        time.sleep(0.01)
    w.grab().save(str(ASSETS / "screenshot.png"))
    w.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-screenshot", action="store_true")
    ap.add_argument("--skip-gif", action="store_true")
    a = ap.parse_args()
    ASSETS.mkdir(exist_ok=True)
    print("icon ...")
    icon = make_icon(1024)
    save_icons(icon)
    print("avatar ...")
    make_icon(500, full_bleed=True, paper_scale=0.80).save(ASSETS / "avatar.png")
    print("banner ...")
    make_banner(icon).save(ASSETS / "banner.png")
    if not a.skip_gif:
        print("demo.gif ...")
        make_gif()
    if not a.skip_screenshot:
        print("screenshot ...")
        make_screenshot()
    print("done ->", ASSETS)


if __name__ == "__main__":
    main()

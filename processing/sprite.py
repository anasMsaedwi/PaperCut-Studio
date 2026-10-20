"""Builds the "sprite": subject + paper edge + texture (one premultiplied layer) and its shadow.

The sprite is generated ONCE per export (seeded), then only warped per frame. That is
what keeps the edge and texture perfectly stable across frames (no flicker).
Layer order inside the final picture: background -> shadow -> paper edge -> subject.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass

import cv2
import numpy as np

from .mask import resize_rgba
from .paper_edge import RIM_STRENGTH, build_paper_alpha, edge_rim
from .settings import Settings
from .shadow import make_shadow
from .texture import paper_texture
from .utils import gaussian

PAPER_RGB = np.array([244, 240, 230], np.float32)
PAPER_WHITE = np.array([252, 251, 247], np.float32)


@dataclass
class Sprite:
    cutout: np.ndarray                  # float32 (h, w, 4): premultiplied RGB 0..255, alpha 0..1
    shadow: np.ndarray                  # float32 (h, w): shadow opacity 0..1
    shadow_offset: tuple[float, float]  # frame pixels

    @property
    def size(self) -> tuple[int, int]:
        h, w = self.shadow.shape
        return w, h

    @property
    def center(self) -> tuple[float, float]:
        w, h = self.size
        return w / 2.0, h / 2.0


def build_sprite(subject: np.ndarray, s: Settings, frame_size: tuple[int, int], seed: int) -> Sprite:
    """subject: uint8 RGBA (cropped). frame_size: output (w, h) this sprite will be used at."""
    W, H = frame_size
    unit = min(W, H) / 1000.0              # px per 1/1000 of the short side
    rng = np.random.default_rng(seed)

    # 1. scale the subject to fit the requested fraction of the frame
    frac = 0.15 + 0.80 * s.subject_size / 100.0
    sh, sw = subject.shape[:2]
    scale = min(W * frac / sw, H * frac / sh)
    nw, nh = max(8, int(round(sw * scale))), max(8, int(round(sh * scale)))
    rgb, alpha = resize_rgba(subject, (nw, nh))

    # 2. derived pixel sizes
    thickness = s.edge_thickness / 100.0 * 60.0 * unit
    rough = s.edge_roughness / 100.0
    detail = s.edge_detail / 100.0
    sigma = 0.5 * unit + s.shadow_blur / 100.0 * 40.0 * unit
    amp = rough * (0.6 * thickness + 14.0 * unit)
    pad = int(np.ceil(thickness + 1.5 * amp + 3.0 * sigma + 8))
    rgb = cv2.copyMakeBorder(rgb, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=(0, 0, 0))
    alpha = cv2.copyMakeBorder(alpha, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=0)

    # 3. paper outline + rim + texture
    paper_a = build_paper_alpha(alpha, s.cutout_style, thickness, rough, detail, unit, rng)
    rim = edge_rim(paper_a, max(2.0 * unit, 0.5 * thickness)) * RIM_STRENGTH[s.cutout_style]
    tex = paper_texture(alpha.shape, rng, unit)
    tex_amp = s.texture_intensity / 100.0 * 0.16

    paper_rgb = PAPER_RGB + (PAPER_WHITE - PAPER_RGB) * rim[..., None]
    paper_rgb = paper_rgb * (1.0 + tex_amp * tex[..., None])

    # small contact shadow of the photo on the paper border
    ox = (s.shadow_x - 50.0) / 50.0 * 0.06 * min(W, H)
    oy = (s.shadow_y - 50.0) / 50.0 * 0.06 * min(W, H)
    if thickness > 2.0 * unit:
        contact = gaussian(alpha, 2.0 * unit)
        contact = np.roll(contact, (int(np.sign(oy) * round(2 * unit)),
                                    int(np.sign(ox) * round(1.5 * unit))), axis=(0, 1))
        paper_rgb = paper_rgb * (1.0 - 0.22 * contact * (1.0 - alpha))[..., None]
    paper_rgb = np.clip(paper_rgb, 0, 255)

    subj_rgb = np.clip(rgb * (1.0 + 0.5 * tex_amp * tex[..., None]), 0, 255)

    # 4. composite paper edge, then subject (premultiplied "over")
    pa, sa = paper_a[..., None], alpha[..., None]
    cut_rgb = subj_rgb * sa + paper_rgb * pa * (1.0 - sa)
    cut_a = alpha + paper_a * (1.0 - alpha)
    cutout = np.dstack([cut_rgb, cut_a]).astype(np.float32)

    # 5. shadow on its own layer
    shadow = make_shadow(cut_a, sigma, s.shadow_intensity / 100.0 * 0.85)
    return Sprite(cutout=cutout, shadow=shadow, shadow_offset=(ox, oy))


class SpriteCache:
    """Remembers the last sprite so moving/animating the subject doesn't rebuild it."""

    def __init__(self):
        self._key = None
        self._sprite: Sprite | None = None
        self._lock = threading.Lock()

    def get(self, token: int, subject: np.ndarray, s: Settings, frame_size) -> Sprite:
        key = (token, tuple(frame_size), s.sprite_key())
        with self._lock:
            if key == self._key and self._sprite is not None:
                return self._sprite
        sprite = build_sprite(subject, s, tuple(frame_size), s.seed)
        with self._lock:
            self._key, self._sprite = key, sprite
        return sprite

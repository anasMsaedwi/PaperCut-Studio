"""Warps the sprite into a frame and composites it over the chosen background."""
from __future__ import annotations

import cv2
import numpy as np

from .settings import Settings
from .sprite import Sprite
from .transform import TransformState, affine_matrix

SHADOW_COLOR = np.array([20, 17, 15], np.float32)


def background_color(s: Settings):
    """RGB tuple, or None for a transparent background."""
    if s.bg_mode == "green":
        return (0, 255, 0)
    if s.bg_mode == "solid":
        return tuple(s.bg_color)
    return None


def render_frame(sprite: Sprite, s: Settings, frame_size: tuple[int, int],
                 state: TransformState | None = None) -> np.ndarray:
    """Return uint8 RGB (h, w, 3), or RGBA (h, w, 4) with straight alpha when the
    background mode is 'transparent'."""
    state = state or TransformState()
    W, H = frame_size
    centre = (W / 2.0 + (s.pos_x - 50.0) / 100.0 * W + state.dx,
              H / 2.0 + (s.pos_y - 50.0) / 100.0 * H + state.dy)
    M = affine_matrix(sprite.center, centre, state.sx, state.sy, state.angle)

    cut = cv2.warpAffine(sprite.cutout, M, (W, H), flags=cv2.INTER_LINEAR,
                         borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0))
    # Shadow follows the sprite's motion but keeps a fixed light direction:
    # the offset is added in frame space, after rotation/scale.
    M_sh = M.copy()
    grow = 1.0 + 0.6 * state.lift
    M_sh[0, 2] += sprite.shadow_offset[0] * grow
    M_sh[1, 2] += sprite.shadow_offset[1] * grow
    sh = cv2.warpAffine(sprite.shadow, M_sh, (W, H), flags=cv2.INTER_LINEAR,
                        borderMode=cv2.BORDER_CONSTANT, borderValue=0)

    if state.lift:
        sh *= 1.0 - 0.25 * min(1.0, max(0.0, state.lift))
    if state.opacity < 1.0:
        k = max(0.0, state.opacity)
        cut *= k
        sh *= k

    a_c = cut[..., 3]
    under = (1.0 - a_c) * sh                        # shadow visible around the cut-out
    out_a = a_c + under
    out_p = cut[..., :3] + under[..., None] * SHADOW_COLOR

    bg = background_color(s)
    if bg is None:
        rgb = out_p / np.maximum(out_a, 1e-4)[..., None]
        out = np.empty((H, W, 4), np.uint8)
        out[..., :3] = np.clip(rgb, 0, 255)
        out[..., 3] = np.clip(out_a * 255.0 + 0.5, 0, 255)
        return out
    out = out_p + (1.0 - out_a)[..., None] * np.asarray(bg, np.float32)
    return np.clip(out, 0, 255).astype(np.uint8)

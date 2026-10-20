"""Per-frame transform of the paper sprite."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class TransformState:
    dx: float = 0.0        # extra translation in frame pixels
    dy: float = 0.0
    sx: float = 1.0        # scale around the sprite centre
    sy: float = 1.0
    angle: float = 0.0     # degrees, positive = clockwise on screen
    opacity: float = 1.0   # whole cut-out incl. shadow
    lift: float = 0.0      # 0..1, how far the paper "floats" above the surface (grows the shadow)


def affine_matrix(src_center, dst_center, sx: float, sy: float, angle_deg: float) -> np.ndarray:
    """2x3 matrix: scale, then rotate about src_center, then move src_center to dst_center."""
    th = np.radians(angle_deg)
    c, s = np.cos(th), np.sin(th)
    A = np.array([[c * sx, -s * sy], [s * sx, c * sy]], np.float64)
    t = np.asarray(dst_center, np.float64) - A @ np.asarray(src_center, np.float64)
    return np.hstack([A, t[:, None]]).astype(np.float32)

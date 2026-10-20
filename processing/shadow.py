"""Soft drop shadow built from a tight contact layer plus a wide soft layer."""
from __future__ import annotations

import numpy as np

from .utils import gaussian


def make_shadow(alpha: np.ndarray, sigma: float, intensity: float) -> np.ndarray:
    """alpha: float32 silhouette (0..1). Returns shadow opacity (0..1) incl. intensity."""
    tight = gaussian(alpha, max(0.6, sigma * 0.35))
    soft = gaussian(alpha, max(1.0, sigma))
    return np.clip((0.55 * tight + 0.45 * soft) * intensity, 0.0, 1.0).astype(np.float32)

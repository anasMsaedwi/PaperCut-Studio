"""Alpha-mask clean-up and colour de-contamination (works on uint8 RGBA arrays)."""
from __future__ import annotations

import cv2
import numpy as np

from .utils import smoothstep


def has_meaningful_alpha(rgba: np.ndarray) -> bool:
    """True if the image already contains real transparency (i.e. is a cut-out)."""
    alpha = rgba[..., 3]
    return bool(alpha.max() > 0 and (alpha < 250).mean() > 0.002)


def refine_alpha(alpha: np.ndarray) -> np.ndarray:
    """Smooth jagged edges but keep soft semi-transparent detail (hair, fur).

    1. very light blur removes stair-steps
    2. an S-curve tightens the halo without hard-thresholding thin strands
    3. tiny disconnected specks are dropped
    """
    a = alpha.astype(np.float32) / 255.0
    a = cv2.GaussianBlur(a, (0, 0), 0.7)
    a = smoothstep((a - 0.08) / (0.92 - 0.08))
    binary = (a > 0.2).astype(np.uint8)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
    if n > 2:
        min_area = max(16, int(0.0003 * a.size))
        small = np.zeros(n, bool)
        small[1:] = stats[1:, cv2.CC_STAT_AREA] < min_area
        a[small[labels]] = 0.0
    return np.clip(a * 255.0 + 0.5, 0, 255).astype(np.uint8)


def decontaminate(rgb: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    """Replace colours of semi-transparent edge pixels with colours from the solid interior,
    so remnants of the old background don't show as a coloured fringe."""
    a = alpha.astype(np.float32) / 255.0
    core = (a > 0.97).astype(np.float32)
    if core.sum() < 16:
        return rgb
    f = rgb.astype(np.float32)
    num = cv2.GaussianBlur(f * core[..., None], (0, 0), 3.0)
    den = cv2.GaussianBlur(core, (0, 0), 3.0)
    est = num / np.maximum(den, 1e-4)[..., None]
    w = np.clip(1.0 - a, 0, 1) * (den > 0.02)
    out = f * (1 - w[..., None]) + est * w[..., None]
    return np.clip(out, 0, 255).astype(np.uint8)


def prepare_subject(rgba: np.ndarray) -> np.ndarray:
    """Refine the mask, clean edge colours and crop to the subject's bounding box."""
    rgba = np.ascontiguousarray(rgba)
    alpha = refine_alpha(rgba[..., 3])
    rgb = decontaminate(rgba[..., :3], alpha)
    ys, xs = np.where(alpha > 6)
    if xs.size == 0:
        raise ValueError("The subject mask is empty - nothing was detected in the image.")
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    return np.dstack([rgb[y0:y1, x0:x1], alpha[y0:y1, x0:x1]])


def resize_rgba(rgba: np.ndarray, size: tuple[int, int]) -> tuple[np.ndarray, np.ndarray]:
    """Resize with premultiplied alpha (no dark/bright fringes).
    Returns (rgb float32 0..255, alpha float32 0..1)."""
    w, h = size
    a = rgba[..., 3].astype(np.float32) / 255.0
    p = rgba[..., :3].astype(np.float32) * a[..., None]
    shrink = w * h < rgba.shape[0] * rgba.shape[1]
    interp = cv2.INTER_AREA if shrink else cv2.INTER_CUBIC
    p = cv2.resize(p, (w, h), interpolation=interp)
    a2 = np.clip(cv2.resize(a, (w, h), interpolation=interp), 0.0, 1.0)
    rgb = np.clip(p / np.maximum(a2, 1e-4)[..., None], 0, 255)
    rgb[a2 < 1e-3] = 0
    return rgb.astype(np.float32), a2.astype(np.float32)

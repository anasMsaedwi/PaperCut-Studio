"""Small numeric helpers shared by the processing modules."""
from __future__ import annotations

import cv2
import numpy as np


def gaussian(img: np.ndarray, sigma: float) -> np.ndarray:
    """Gaussian blur on float32 data; large sigmas are done on a downscaled copy for speed."""
    if sigma <= 0.05:
        return img
    if sigma <= 6.0:
        return cv2.GaussianBlur(img, (0, 0), sigma)
    h, w = img.shape[:2]
    f = max(2, int(sigma / 3.0))
    sw, sh = max(2, w // f), max(2, h // f)
    small = cv2.resize(img, (sw, sh), interpolation=cv2.INTER_AREA)
    small = cv2.GaussianBlur(small, (0, 0), sigma * sw / w)
    return cv2.resize(small, (w, h), interpolation=cv2.INTER_LINEAR)


def smoothstep(x: np.ndarray) -> np.ndarray:
    x = np.clip(x, 0.0, 1.0)
    return x * x * (3.0 - 2.0 * x)


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t

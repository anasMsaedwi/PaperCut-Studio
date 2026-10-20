"""Subtle paper texture: grain + soft mottling + short fibres."""
from __future__ import annotations

import cv2
import numpy as np

from .noise import fractal_noise


def paper_texture(shape, rng: np.random.Generator, unit: float) -> np.ndarray:
    """Zero-mean float32 texture in [-1, 1]. Generated once per sprite, so it is
    identical on every animation frame (no flicker)."""
    grain = rng.standard_normal(shape).astype(np.float32)
    grain = cv2.GaussianBlur(grain, (0, 0), max(0.5, 0.7 * unit))
    grain = grain / (grain.std() + 1e-6) * 0.35
    mottle = fractal_noise(shape, rng, 3, 4) * 0.45
    fibres = _fibres(shape, rng, unit) * 0.8
    return np.clip(grain + mottle + fibres, -1.0, 1.0).astype(np.float32)


def _fibres(shape, rng, unit):
    h, w = shape
    n = int(min(4000, h * w / (2500.0 * max(unit, 0.3) ** 2)))
    light = np.zeros(shape, np.uint8)
    dark = np.zeros(shape, np.uint8)
    cx, cy = rng.uniform(0, w, n), rng.uniform(0, h, n)
    ang = rng.uniform(0, np.pi, n)
    half = rng.uniform(6, 28, n) * unit / 2.0
    is_dark = rng.random(n) < 0.55
    for i in range(n):
        dx, dy = np.cos(ang[i]) * half[i], np.sin(ang[i]) * half[i]
        p1 = (int(cx[i] - dx), int(cy[i] - dy))
        p2 = (int(cx[i] + dx), int(cy[i] + dy))
        cv2.line(dark if is_dark[i] else light, p1, p2, 255, 1, cv2.LINE_AA)
    out = (light.astype(np.float32) - dark.astype(np.float32)) / 255.0
    return cv2.GaussianBlur(out, (0, 0), max(0.4, 0.5 * unit))

"""Multi-scale (fractal) noise built from upsampled random grids. Deterministic given an rng."""
from __future__ import annotations

import cv2
import numpy as np


def fractal_noise(shape, rng: np.random.Generator, base_cells: int = 6, octaves: int = 4,
                  persistence: float = 0.55, lacunarity: float = 2.0) -> np.ndarray:
    """Return float32 noise roughly in [-1, 1] with shape (h, w).

    base_cells: number of noise cells along the longest side in the first octave.
    """
    h, w = shape
    longest = max(h, w)
    out = np.zeros((h, w), np.float32)
    amp, cells = 1.0, float(base_cells)
    for _ in range(octaves):
        if longest / cells < 2.0:        # features below ~2 px are pointless
            break
        gw = max(2, int(np.ceil(cells * w / longest)) + 1)
        gh = max(2, int(np.ceil(cells * h / longest)) + 1)
        grid = rng.standard_normal((gh, gw)).astype(np.float32)
        out += amp * cv2.resize(grid, (w, h), interpolation=cv2.INTER_CUBIC)
        amp *= persistence
        cells *= lacunarity
    out -= out.mean()
    return np.clip(out / (2.5 * out.std() + 1e-6), -1.0, 1.0)

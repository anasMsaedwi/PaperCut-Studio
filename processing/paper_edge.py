"""Irregular paper outline around the subject mask (smooth / cut / torn)."""
from __future__ import annotations

import cv2
import numpy as np

from .noise import fractal_noise
from .utils import gaussian, lerp

# How much lighter/whiter the outer rim of the paper is, per style.
RIM_STRENGTH = {"smooth": 0.15, "cut": 0.30, "torn": 0.90}


def build_paper_alpha(subject_alpha: np.ndarray, style: str, thickness: float,
                      roughness: float, detail: float, unit: float,
                      rng: np.random.Generator) -> np.ndarray:
    """Return paper coverage (float32 0..1) around a padded subject alpha.

    thickness : border width in pixels
    roughness : 0..1 tearing / wobble strength
    detail    : 0..1 amount of fine detail along the edge
    unit      : pixels per 1/1000 of the frame's short side (resolution independence)
    The result is always >= subject_alpha so the paper never cuts into the subject.
    """
    shape = subject_alpha.shape
    # Distance (px) from every pixel to the nearest subject pixel.
    src = np.where(subject_alpha > 0.2, 0, 255).astype(np.uint8)
    dist = cv2.distanceTransform(src, cv2.DIST_L2, 5)
    field = thickness - dist - 0.5          # > 0 inside the paper outline

    if style == "smooth":
        # Blurring the distance field rounds corners and bridges narrow gaps.
        field = gaussian(field, max(1.0, thickness * 0.3))
        paper = np.clip(field + 0.5, 0.0, 1.0)

    elif style == "cut":
        paper = _scissor_cut(field, detail, roughness, unit, rng)

    else:  # torn
        amp = roughness * (0.6 * thickness + 14.0 * unit)
        cells = int(round(lerp(4, 14, detail)))
        octaves = int(round(lerp(3, 6, detail)))
        coarse = fractal_noise(shape, rng, cells, octaves)
        fine = fractal_noise(shape, rng, int(round(lerp(40, 110, detail))), 2, persistence=0.6)
        field = field + amp * coarse + (0.25 * amp + 0.8 * unit * roughness) * fine
        aa = lerp(1.0, 2.2, roughness)       # rougher paper = fuzzier fibres
        paper = np.clip(field / aa + 0.5, 0.0, 1.0)

    return np.maximum(paper, subject_alpha).astype(np.float32)


def _scissor_cut(field, detail, roughness, unit, rng):
    """Polygonal outline: fewer vertices = bolder scissor facets."""
    mask = (field > 0).astype(np.uint8)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    poly = np.zeros(mask.shape, np.uint8)
    eps = max(1.0, lerp(18.0, 1.5, detail) * unit)
    for c in contours:
        if cv2.contourArea(c) < 20:
            continue
        pts = cv2.approxPolyDP(c, eps, True).reshape(-1, 2).astype(np.float32)
        if roughness > 0:
            pts += rng.normal(0.0, roughness * 3.0 * unit, pts.shape).astype(np.float32)
        cv2.fillPoly(poly, [np.round(pts).astype(np.int32)], 255)
    return cv2.GaussianBlur(poly.astype(np.float32) / 255.0, (0, 0), 0.8)


def edge_rim(paper_alpha: np.ndarray, width_px: float) -> np.ndarray:
    """0..1 weight that is 1 on the outermost paper pixels and fades inward."""
    inside = ((paper_alpha > 0.5).astype(np.uint8)) * 255
    d = cv2.distanceTransform(inside, cv2.DIST_L2, 3)
    return np.clip(1.0 - d / max(width_px, 1.5), 0.0, 1.0)

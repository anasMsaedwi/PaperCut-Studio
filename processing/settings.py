"""All user-adjustable settings in one plain dataclass (no Qt imports)."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import ClassVar, Tuple

CUTOUT_STYLES = ("smooth", "cut", "torn")
ANIMATION_STYLES = ("jitter", "stopmotion", "floating", "bounce", "reveal")
BG_MODES = ("solid", "green", "transparent")
ASPECTS = ("16:9", "9:16")
RESOLUTIONS = (720, 1080)
FPS_CHOICES = (24, 30)
TRANSITION_SOURCES = ("image", "demo")


@dataclass
class Settings:
    # ---- sliders, all 0..100 -------------------------------------------------
    subject_size: float = 60
    pos_x: float = 50            # 50 = centred
    pos_y: float = 50            # 50 = centred
    edge_thickness: float = 35
    edge_roughness: float = 55
    edge_detail: float = 50
    texture_intensity: float = 40
    shadow_x: float = 62         # 50 = no horizontal offset
    shadow_y: float = 62         # 50 = no vertical offset
    shadow_blur: float = 40
    shadow_intensity: float = 55
    animation_amount: float = 50

    # ---- choices ---------------------------------------------------------------
    cutout_style: str = "torn"
    animation_style: str = "jitter"
    bg_mode: str = "solid"
    bg_color: Tuple[int, int, int] = (38, 52, 78)
    aspect: str = "16:9"
    resolution: int = 1080       # short side: 720 or 1080
    duration: int = 5            # seconds, 3..10
    fps: int = 30
    seed: int = 20240601         # drives edge shape, texture and jitter
    transition_source: str = "image"   # picture revealed by the unfold transition: loaded image / demo
    crumple_seed: int = 7              # crumple pattern of the transition

    SLIDER_FIELDS: ClassVar[Tuple[str, ...]] = (
        "subject_size", "pos_x", "pos_y", "edge_thickness", "edge_roughness",
        "edge_detail", "texture_intensity", "shadow_x", "shadow_y",
        "shadow_blur", "shadow_intensity", "animation_amount",
    )

    # Fields that change the pre-rendered paper "sprite" (see sprite.py).
    SPRITE_FIELDS: ClassVar[Tuple[str, ...]] = (
        "subject_size", "edge_thickness", "edge_roughness", "edge_detail",
        "texture_intensity", "shadow_x", "shadow_y", "shadow_blur",
        "shadow_intensity", "cutout_style", "seed",
    )

    def validate(self) -> "Settings":
        """Clamp numeric values and reject unknown choices. Returns self."""
        for name in self.SLIDER_FIELDS:
            value = float(getattr(self, name))
            if not math.isfinite(value):
                raise ValueError(f"{name} must be a finite number")
            setattr(self, name, min(100.0, max(0.0, value)))
        _check(self.cutout_style, CUTOUT_STYLES, "cutout style")
        _check(self.animation_style, ANIMATION_STYLES, "animation style")
        _check(self.bg_mode, BG_MODES, "background mode")
        _check(self.aspect, ASPECTS, "aspect ratio")
        _check(int(self.resolution), RESOLUTIONS, "resolution")
        _check(int(self.fps), FPS_CHOICES, "frame rate")
        _check(self.transition_source, TRANSITION_SOURCES, "transition picture")
        self.resolution, self.fps = int(self.resolution), int(self.fps)
        if not 3 <= int(self.duration) <= 10:
            raise ValueError("Duration must be between 3 and 10 seconds")
        self.duration = int(self.duration)
        self.bg_color = tuple(min(255, max(0, int(c))) for c in self.bg_color)[:3]
        self.seed = int(self.seed) & 0x7FFFFFFF
        self.crumple_seed = int(self.crumple_seed) & 0x7FFFFFFF
        return self

    def frame_size(self, max_side: int | None = None) -> tuple[int, int]:
        """Output size (w, h); optionally downscaled so the long side <= max_side."""
        short = int(self.resolution)
        long_ = short * 16 // 9
        w, h = (long_, short) if self.aspect == "16:9" else (short, long_)
        if max_side and max(w, h) > max_side:
            f = max_side / max(w, h)
            w, h = int(round(w * f / 2)) * 2, int(round(h * f / 2)) * 2
        return w, h

    def sprite_key(self) -> tuple:
        return tuple(getattr(self, n) for n in self.SPRITE_FIELDS)


def _check(value, allowed, label):
    if value not in allowed:
        raise ValueError(f"Unsupported {label}: {value!r} (allowed: {allowed})")

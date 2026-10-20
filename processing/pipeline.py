"""High-level jobs used by the UI and the exporters (no Qt imports)."""
from __future__ import annotations

from dataclasses import replace

import numpy as np

from .animation import animation_state
from .compositor import render_frame
from .errors import OperationCancelled
from .settings import Settings
from .sprite import SpriteCache, build_sprite
from .transform import TransformState


def render_still(subject: np.ndarray, settings: Settings, max_side: int | None = None) -> np.ndarray:
    """Neutral (un-animated) frame. Used for PNG export and tests."""
    s = replace(settings).validate()
    size = s.frame_size(max_side)
    sprite = build_sprite(subject, s, size, s.seed)
    return render_frame(sprite, s, size, TransformState())


def render_still_job(subject, settings, max_side, token, cache: SpriteCache) -> np.ndarray:
    """Preview still; reuses the cached sprite when only position/background changed."""
    s = replace(settings).validate()
    size = s.frame_size(max_side)
    return render_frame(cache.get(token, subject, s, size), s, size, TransformState())


def render_preview_animation(subject, settings, max_side, max_seconds, token, cache: SpriteCache,
                             progress=None, is_cancelled=None):
    """Pre-render the first `max_seconds` of the clip at reduced size. Returns (frames, fps)."""
    s = replace(settings).validate()
    size = s.frame_size(max_side)
    sprite = cache.get(token, subject, s, size)
    n_total = s.fps * s.duration
    n_play = min(n_total, int(round(max_seconds * s.fps)))
    frames = []
    for i in range(n_play):
        if is_cancelled and is_cancelled():
            raise OperationCancelled()
        state = animation_state(s.animation_style, i, n_total, s.fps, s, size)
        frames.append(render_frame(sprite, s, size, state))
        if progress:
            progress(int(100 * (i + 1) / n_play))
    return frames, s.fps

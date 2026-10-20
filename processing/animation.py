"""Animation styles -> per-frame TransformState. Everything is deterministic (seeded) and
periodic styles loop seamlessly. 'Animation amount' (0..100) scales every motion; 0 = static."""
from __future__ import annotations

import numpy as np

from .settings import Settings
from .transform import TransformState


def ease_in_out_cubic(t: float) -> float:
    t = min(1.0, max(0.0, t))
    return 4 * t ** 3 if t < 0.5 else 1 - (-2 * t + 2) ** 3 / 2


def ease_out_cubic(t: float) -> float:
    t = min(1.0, max(0.0, t))
    return 1 - (1 - t) ** 3


def ease_out_back(t: float, c1: float = 1.70158) -> float:
    t = min(1.0, max(0.0, t))
    c3 = c1 + 1
    return 1 + c3 * (t - 1) ** 3 + c1 * (t - 1) ** 2


def animation_state(style: str, frame_idx: int, n_frames: int, fps: int,
                    s: Settings, frame_size: tuple[int, int]) -> TransformState:
    a = s.animation_amount / 100.0
    if a <= 0 or n_frames <= 0:
        return TransformState()
    unit = min(frame_size) / 1000.0
    duration = n_frames / float(fps)
    u = frame_idx / float(n_frames)

    if style == "jitter":
        return _jitter(s.seed, frame_idx, max(1, round(fps / 12)), a, unit, 1.0)

    if style == "stopmotion":
        step = max(1, round(fps / 8))                 # hold each pose ~3 frames
        uq = (frame_idx // step) * step / float(n_frames)
        cycles = max(1, round(duration / 3.0))
        w = 2 * np.pi * uq * cycles
        base = TransformState(dx=np.sin(w) * 12 * unit * a,
                              dy=np.cos(w * 1.0 + 0.7) * 6 * unit * a,
                              sx=1 + 0.02 * a * np.sin(w), sy=1 + 0.02 * a * np.sin(w),
                              angle=np.sin(w + 1.0) * 2.5 * a)
        return _add(base, _jitter(s.seed, frame_idx, step, a, unit, 1.6))

    if style == "floating":
        cycles = max(1, round(duration / 2.5))
        w = 2 * np.pi * u * cycles
        sc = 1 + 0.012 * a * np.sin(w)
        return TransformState(dx=np.cos(w) * 6 * unit * a, dy=-np.sin(w) * 22 * unit * a,
                              sx=sc, sy=sc, angle=np.sin(w + 1.0) * 2.0 * a,
                              lift=0.5 + 0.5 * np.sin(w))

    if style == "bounce":
        n = max(1, round(duration / 1.0))
        ph = (u * n) % 1.0
        h = 4 * ph * (1 - ph)                          # parabola: 0 on the ground, 1 at the top
        squash = max(0.0, 1.0 - min(ph, 1 - ph) / 0.12)
        sy = 1 - 0.10 * a * squash + 0.03 * a * h
        sx = 1 + 0.08 * a * squash - 0.02 * a * h
        return TransformState(dy=-h * 60 * unit * a, sx=sx, sy=sy,
                              angle=np.sin(2 * np.pi * ph) * 1.5 * a, lift=h)

    if style == "reveal":
        end = 0.4                                      # first 40 % of the clip
        p = u / end
        c = ease_out_cubic(p)
        s0 = 1 - 0.35 * a
        scale = s0 + (1 - s0) * ease_out_back(p)
        st = TransformState(dy=(1 - c) * 80 * unit * a, sx=scale, sy=scale,
                            angle=-(1 - c) * 8.0 * a, opacity=c, lift=1 - c)
        if p >= 1.0:                                   # then breathe with a little jitter
            st = _add(st, _jitter(s.seed, frame_idx, max(1, round(fps / 12)), a, unit, 0.5))
        return st

    return TransformState()


def _jitter(seed: int, frame_idx: int, step: int, a: float, unit: float, gain: float) -> TransformState:
    """Random small pose that only changes every `step` frames (stop-motion 'boil')."""
    rng = np.random.default_rng([seed, frame_idx // step, 7])
    g = np.clip(rng.normal(0.0, 0.6, 4), -1.5, 1.5)
    return TransformState(dx=g[0] * 6 * unit * a * gain, dy=g[1] * 6 * unit * a * gain,
                          sx=1 + g[2] * 0.004 * a * gain, sy=1 + g[2] * 0.004 * a * gain,
                          angle=g[3] * 0.8 * a * gain)


def _add(a: TransformState, b: TransformState) -> TransformState:
    return TransformState(dx=a.dx + b.dx, dy=a.dy + b.dy, sx=a.sx * b.sx, sy=a.sy * b.sy,
                          angle=a.angle + b.angle, opacity=a.opacity * b.opacity,
                          lift=max(a.lift, b.lift))

"""Stop-motion paper transition engine (no Qt): a crumpled sheet unfolds to reveal a picture,
holds, then crumples back into a ball that rolls out of the frame.

One crumple parameter c (1 = ball, 0 = flat sheet) drives
  * facet lighting + crease lines (a seeded Voronoi "low-poly" crumple, plus fine wrinkles),
  * a per-facet warp of the picture and a per-facet reveal order (centre facets open first),
  * the outline (rounded rectangle -> noisy circle) and the overall scale (sheet -> ball),
  * the soft drop shadow (tighter and darker when the paper is balled up).
Reuses the paper texture, shadow and compositing code of the main app.
"""
from __future__ import annotations

import cv2
import numpy as np
from PIL import Image, ImageOps

from .animation import ease_in_out_cubic
from .compositor import render_frame
from .errors import OperationCancelled
from .noise import fractal_noise
from .settings import Settings
from .shadow import make_shadow
from .sprite import Sprite
from .texture import paper_texture
from .transform import TransformState
from .utils import gaussian, lerp, smoothstep

PAPER_FRONT = np.array([246, 242, 233], np.float32)
PAPER_BACK = np.array([234, 228, 214], np.float32)      # outside of the sheet, slightly darker
LIGHT = (-0.62, -0.78)                                  # light comes from the top-left


# ----------------------------------------------------------------------------- picture
def make_demo_picture(w: int, h: int, seed: int = 3) -> np.ndarray:
    """A small procedural sunset-over-mountains-and-lake illustration (uint8 RGB)."""
    rng = np.random.default_rng(seed)
    y = np.arange(h, dtype=np.float32)[:, None] * np.ones((1, w), np.float32)
    x = np.arange(w, dtype=np.float32)[None, :] * np.ones((h, 1), np.float32)
    hz = 0.64 * h
    top, mid, low = (np.array(c, np.float32) for c in ((38, 48, 112), (232, 112, 98), (255, 206, 128)))
    s = np.clip(y / hz, 0, 1)[..., None]
    img = np.where(s < 0.62, top + (mid - top) * smoothstep(s / 0.62),
                   mid + (low - mid) * smoothstep((s - 0.62) / 0.38))
    sx, sy, sr = 0.68 * w, 0.55 * h, 0.075 * h                       # sun, glow, disc
    d = np.hypot(x - sx, y - sy)
    img = img + np.exp(-(d / (0.30 * h)) ** 2)[..., None] * np.array([90, 60, 20], np.float32)
    img = img * (1 - smoothstep(1.5 - (d - sr) / 2.0)[..., None]) + \
        np.array([255, 244, 200], np.float32) * smoothstep(1.5 - (d - sr) / 2.0)[..., None]
    for base, amp, col in ((0.50, 0.12, (122, 96, 150)), (0.57, 0.09, (78, 66, 116)),
                           (0.64, 0.06, (34, 36, 70))):
        n = fractal_noise((1, w), rng, 5, 5)[0]
        ridge = (base - amp * (0.5 + 0.5 * n)) * h
        m = smoothstep((y - ridge[None, :]) / 2.0 + 0.5)[..., None] * (y < hz + 2)[..., None]
        img = img * (1 - m) + np.array(col, np.float32) * m
    # lake: mirrored, rippled, darker
    yh = int(hz)
    rows = np.arange(yh, h)
    src = np.clip(yh - (rows - yh) * 1.0 - 1, 0, h - 1).astype(int)
    ripple = (np.sin(rows[:, None] * 0.55 + x[0][None, :] * 0.02) * (rows[:, None] - yh) * 0.05).astype(int)
    xs = np.clip(np.arange(w)[None, :] + ripple, 0, w - 1)
    water = img[src[:, None], xs] * np.array([0.62, 0.70, 0.88], np.float32)
    water = cv2.GaussianBlur(water, (0, 0), 1.2)
    img[yh:] = water
    for k in range(5):                                                # a few birds
        bx, by = (0.18 + 0.05 * k) * w, (0.2 + 0.03 * ((k * 7) % 4)) * h
        sz = (0.012 + 0.003 * (k % 3)) * w
        pts = np.array([[bx - sz, by], [bx, by + sz * 0.45], [bx + sz, by]], np.int32)
        cv2.polylines(img, [pts], False, (40, 30, 50), max(1, int(h / 360)), cv2.LINE_AA)
    vig = 1 - 0.28 * (np.hypot((x / w - 0.5) * 1.2, (y / h - 0.5)) ** 2)[..., None]
    img = img * vig + rng.normal(0, 2.0, img.shape)
    return np.clip(img, 0, 255).astype(np.uint8)


def load_picture(path: str, size: tuple[int, int]) -> np.ndarray:
    try:
        with Image.open(path) as im:
            im = ImageOps.exif_transpose(im).convert("RGB")
            return np.array(ImageOps.fit(im, size, Image.Resampling.LANCZOS))
    except (OSError, ValueError) as e:
        sys.exit(f"Could not read the image '{path}': {e}")


# ----------------------------------------------------------------------------- sheet model
class CrumpleSheet:
    """Everything that does not change between poses is built once here (seeded)."""

    def __init__(self, picture: np.ndarray, pw: int, ph: int, unit: float, seed: int):
        rng = np.random.default_rng(seed)
        self.unit, self.pw, self.ph = unit, pw, ph
        pad = int(160 * unit)
        self.H0, self.W0 = ph + 2 * pad, pw + 2 * pad
        H0, W0 = self.H0, self.W0
        cx, cy = W0 / 2.0, H0 / 2.0
        self.cx, self.cy = cx, cy
        self.X, self.Y = np.meshgrid(np.arange(W0, dtype=np.float32), np.arange(H0, dtype=np.float32))
        shape = (H0, W0)

        # --- Voronoi facets (computed at half resolution, upsampled) --------------------
        gx_n, gy_n = (9, 6) if pw >= ph else (6, 9)
        cw, ch = pw / gx_n, ph / gy_n
        seeds = np.array([(pad + (i + rng.uniform(0.15, 0.85)) * cw, pad + (j + rng.uniform(0.15, 0.85)) * ch)
                          for i in range(gx_n) for j in range(gy_n)], np.float32)
        n = len(seeds)
        h2, w2 = H0 // 2, W0 // 2
        X2, Y2 = self.X[::2, ::2][:h2, :w2], self.Y[::2, ::2][:h2, :w2]
        d1 = np.full((h2, w2), np.inf, np.float32)
        d2 = d1.copy()
        lab = np.zeros((h2, w2), np.uint8)
        for i, (sx, sy) in enumerate(seeds):
            d = np.hypot(X2 - sx, Y2 - sy)
            closer = d < d1
            d2 = np.where(closer, d1, np.minimum(d2, d))
            lab = np.where(closer, i, lab).astype(np.uint8)
            d1 = np.where(closer, d, d1)
        self.lab = cv2.resize(lab, (W0, H0), interpolation=cv2.INTER_NEAREST)
        self.crease_dist = cv2.resize(d2 - d1, (W0, H0), interpolation=cv2.INTER_LINEAR)

        tilt = rng.normal(size=(n, 2)).astype(np.float32)
        tilt *= (rng.uniform(0.5, 1.0, (n, 1)) / np.linalg.norm(tilt, axis=1, keepdims=True)).astype(np.float32)
        off = rng.normal(size=(n, 2)).astype(np.float32) * 30 * unit
        self.tx = gaussian(tilt[self.lab, 0].astype(np.float32), 1.5 * unit)
        self.ty = gaussian(tilt[self.lab, 1].astype(np.float32), 1.5 * unit)
        offmap = gaussian(np.dstack([off[self.lab, 0], off[self.lab, 1]]).astype(np.float32), 10 * unit)
        self.ox, self.oy = offmap[..., 0].copy(), offmap[..., 1].copy()
        # centre facets unfold first, outer ones last
        r = np.hypot((seeds[:, 0] - cx) / (pw / 2), (seeds[:, 1] - cy) / (ph / 2)) / np.sqrt(2)
        thr = (0.93 - 0.55 * r + 0.10 * rng.random(n)).astype(np.float32)
        self.thr_map = thr[self.lab]

        # --- fine wrinkles: three noise fields, gradients used for lighting -------------
        self.gx, self.gy = [], []
        for _ in range(3):
            nz = gaussian(fractal_noise(shape, rng, 16, 5), 1.2 * unit)
            gx = cv2.Sobel(nz, cv2.CV_32F, 1, 0, ksize=3)
            gy = cv2.Sobel(nz, cv2.CV_32F, 0, 1, ksize=3)
            s = float(np.std(gx) + np.std(gy)) / 2 + 1e-6
            self.gx.append(gx / s * 0.35)
            self.gy.append(gy / s * 0.35)

        # --- texture, picture and paper colours ---------------------------------------
        tex = paper_texture(shape, rng, unit)
        m = int(22 * unit)                                           # white print border
        front = np.empty((H0, W0, 3), np.float32)
        front[:] = PAPER_FRONT
        pic = cv2.resize(picture, (pw - 2 * m, ph - 2 * m), interpolation=cv2.INTER_AREA).astype(np.float32)
        front[pad + m:pad + ph - m, pad + m:pad + pw - m] = pic
        inset = np.zeros(shape, np.float32)
        inset[pad + m:pad + ph - m, pad + m:pad + pw - m] = 1.0
        front *= (1.0 + (0.045 + 0.04 * (1 - inset)) * tex)[..., None]      # photo: lighter grain
        back = np.empty_like(front)
        back[:] = PAPER_BACK
        back *= (1.0 + 0.11 * tex)[..., None]
        self.front, self.back = front, back

        # --- outline model -------------------------------------------------------------
        q_x = np.abs(self.X - cx) - (pw / 2 - 10 * unit)
        q_y = np.abs(self.Y - cy) - (ph / 2 - 10 * unit)
        self.sdf_rect = (np.hypot(np.maximum(q_x, 0), np.maximum(q_y, 0))
                         + np.minimum(np.maximum(q_x, q_y), 0) - 10 * unit).astype(np.float32)
        self.R = 0.47 * min(pw, ph)
        self.dist_c = np.hypot(self.X - cx, self.Y - cy).astype(np.float32)
        self.sdf_circ = self.dist_c - self.R
        self.edge_n = fractal_noise(shape, rng, 7, 3)
        self.edge_f = fractal_noise(shape, rng, 30, 2)
        self.amp = 0.07 * min(pw, ph)

    # -------------------------------------------------------------------------------
    def render(self, c: float, rng: np.random.Generator) -> Sprite:
        u = self.unit
        # picture / paper with the facet warp, revealed facet by facet
        mx, my = self.X - self.ox * c, self.Y - self.oy * c
        front = cv2.remap(self.front, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        back = cv2.remap(self.back, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        w = np.clip((self.thr_map - c) / 0.05 + 0.5, 0, 1)[..., None]
        rgb = back + (front - back) * w

        # lighting: facets + wrinkles (slightly different wrinkles every pose = stop-motion "boil")
        wt = np.array([1.0, 0.25 * rng.normal(), 0.25 * rng.normal()])
        wt /= np.linalg.norm(wt)
        gx = wt[0] * self.gx[0] + wt[1] * self.gx[1] + wt[2] * self.gx[2]
        gy = wt[0] * self.gy[0] + wt[1] * self.gy[1] + wt[2] * self.gy[2]
        lx, ly = LIGHT
        shade = 1.0 - c * (0.50 * (lx * self.tx + ly * self.ty) + 0.55 * (lx * gx + ly * gy))
        cs = 0.10 + 0.90 * c ** 0.8                                   # flat paper keeps faint creases
        edge = np.clip(1.0 - self.crease_dist / (3.4 * u), 0, 1)
        shade = shade * (1.0 - 0.50 * cs * edge ** 1.3)
        shade = shade + 0.10 * cs * np.clip(np.roll(edge, (1, 1), (0, 1)) - edge, 0, 1)
        ball = float(smoothstep((c - 0.55) / 0.45))                   # round, self-shadowed ball
        shade = shade * (1.0 - 0.30 * ball * np.clip(self.dist_c / self.R, 0, 1.2) ** 2 + 0.14 * ball)
        rgb = np.clip(rgb * np.clip(shade, 0.30, 1.30)[..., None], 0, 255)

        # outline: clean rounded rectangle -> noisy circle
        m = float(smoothstep((c - 0.15) / 0.70))
        sdf = (1 - m) * self.sdf_rect + m * self.sdf_circ
        sdf = sdf - c * self.amp * (self.edge_n + 0.25 * self.edge_f)
        alpha = np.clip(0.5 - sdf / 1.3, 0, 1).astype(np.float32)

        sigma = (6 + 14 * c) * u
        shadow = make_shadow(alpha, sigma, 0.62)
        cut = np.dstack([rgb * alpha[..., None], alpha]).astype(np.float32)
        return Sprite(cutout=cut, shadow=shadow, shadow_offset=((7 + 9 * c) * u, (10 + 14 * c) * u))


# ----------------------------------------------------------------------------- timeline
def timeline(u: float) -> tuple[float, float]:
    """Normalised time 0..1 -> (crumple c, vanish v). 1 = ball, 0 = flat sheet."""
    if u < 0.106:
        return 1.0, 0.0                                  # ball sits on the table
    if u < 0.424:
        return 1.0 - ease_in_out_cubic((u - 0.106) / 0.318), 0.0       # unfold + reveal
    if u < 0.612:
        return 0.0, 0.0                                  # hold the picture
    if u < 0.847:
        return ease_in_out_cubic((u - 0.612) / 0.235), 0.0             # crumple
    if u < 0.929:
        return 1.0, (u - 0.847) / 0.082                  # ball shrinks and rolls away
    return 1.0, 1.0                                      # empty table


def make_background(W: int, H: int, mode: str = "solid", color=(62, 70, 86), seed: int = 11) -> np.ndarray:
    """Table surface: soft vignette + faint grain in the chosen colour, or flat chroma green."""
    if mode == "green":
        out = np.empty((H, W, 3), np.float32)
        out[:] = (0, 255, 0)
        return out
    y, x = np.mgrid[0:H, 0:W].astype(np.float32)
    r = np.hypot((x / W - 0.5) * 1.1, y / H - 0.5)
    bg = np.asarray(color, np.float32) * np.clip(1.25 - 0.85 * r ** 1.6, 0.3, 2.0)[..., None]
    rng = np.random.default_rng(seed)
    grain = cv2.GaussianBlur(rng.normal(0, 1, (H, W)).astype(np.float32), (0, 0), 1.0) * 2.2
    soft = fractal_noise((H, W), rng, 3, 3) * 3.0
    return np.clip(bg + (grain + soft)[..., None], 0, 255)


def fit_picture(rgb: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    """Cover-crop an RGB array to `size` (keeps aspect ratio, centre crop)."""
    im = Image.fromarray(np.ascontiguousarray(rgb[..., :3]))
    return np.array(ImageOps.fit(im, size, Image.Resampling.LANCZOS))


def sheet_size(W: int, H: int) -> tuple[int, int]:
    """Paper sheet size (w, h) for a frame: landscape 3:2 sheet, or a portrait sheet for 9:16."""
    if H > W:
        pw = int(0.80 * W) // 2 * 2
        return pw, int(pw * 1.30) // 2 * 2
    ph = int(0.72 * H) // 2 * 2
    return int(ph * 1.5) // 2 * 2, ph


class TransitionRenderer:
    """Renders the whole transition frame by frame (stop-motion: poses are held `hold` frames)."""

    def __init__(self, picture, settings: Settings, frame_size: tuple[int, int],
                 seconds: float | None = None, hold: int = 2):
        W, H = frame_size
        self.W, self.H, self.fps, self.hold = W, H, settings.fps, max(1, hold)
        self.seed = settings.crumple_seed
        self.n_frames = max(1, int(round((seconds or settings.duration) * settings.fps)))
        unit = min(W, H) / 1080.0
        pw, ph = sheet_size(W, H)
        m = int(22 * unit)
        pic_size = (pw - 2 * m, ph - 2 * m)
        pic = make_demo_picture(*pic_size) if picture is None else fit_picture(picture, pic_size)
        self.unit = unit
        self.sheet = CrumpleSheet(pic, pw, ph, unit, self.seed)
        self.bg = make_background(W, H, settings.bg_mode, settings.bg_color)
        self._S = Settings(bg_mode="transparent")
        self._pose, self._frame = -1, None

    def frame(self, i: int) -> np.ndarray:
        """uint8 RGB frame i (0 <= i < n_frames). Consecutive frames of a pose are identical."""
        pose = i // self.hold
        if pose != self._pose:
            self._frame, self._pose = self._render_pose(pose), pose
        return self._frame

    def _render_pose(self, pose: int) -> np.ndarray:
        u = self.unit
        rng = np.random.default_rng([self.seed, pose, 5])
        u_t = min(1.0, pose * self.hold / float(self.n_frames))
        c, v = timeline(u_t)
        c = float(np.clip(c + (rng.normal(0, 0.010) if 0 < c < 1 else 0.0), 0, 1))
        vanish = float(v ** 2.2)
        scale = (1.0 - 0.70 * float(smoothstep(c))) * (1.0 - vanish)
        if scale < 0.02:                                   # ball has left the table
            return np.clip(self.bg, 0, 255).astype(np.uint8)
        wob = c * 4.0 * np.sin(2 * np.pi * u_t * 9) * (1 - c)             # rocking while unfolding
        st = TransformState(dx=rng.normal(0, 2.5 * u) + 260 * u * vanish,
                            dy=rng.normal(0, 2.5 * u) + 120 * u * vanish,
                            sx=scale, sy=scale, angle=rng.normal(0, 0.45) + wob + 90 * vanish,
                            lift=0.5 * c)
        fr = render_frame(self.sheet.render(c, rng), self._S, (self.W, self.H), st)
        al = fr[..., 3:4].astype(np.float32) / 255.0
        return np.clip(fr[..., :3] * al + self.bg * (1 - al), 0, 255).astype(np.uint8)


def render_transition_preview(picture, settings: Settings, max_side: int, progress=None, is_cancelled=None):
    """Whole transition at reduced size for the in-app preview. Returns (frames, fps)."""
    s = settings.validate()
    size = s.frame_size(max_side)
    r = TransitionRenderer(picture, s, size)
    frames = []
    for i in range(r.n_frames):
        if is_cancelled and is_cancelled():
            raise OperationCancelled()
        frames.append(r.frame(i))
        if progress:
            progress(int(100 * (i + 1) / r.n_frames))
    return frames, s.fps

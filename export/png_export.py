"""Single-frame PNG export (RGBA with alpha when the background is 'transparent')."""
from __future__ import annotations

import os
from dataclasses import replace

from PIL import Image

from processing.compositor import render_frame
from processing.errors import ExportError
from processing.settings import Settings
from processing.sprite import build_sprite
from processing.transform import TransformState

from .utils import ensure_disk_space


def export_png(path: str, subject, settings: Settings, progress=None, is_cancelled=None) -> str:
    """Render the neutral (un-animated) pose at full output resolution and save it."""
    try:
        s = replace(settings).validate()
    except ValueError as e:
        raise ExportError(str(e)) from e
    size = s.frame_size()
    ensure_disk_space(path, size[0] * size[1] * 4 * 2 + 1_000_000)
    tmp = path + ".part"
    try:
        sprite = build_sprite(subject, s, size, s.seed)
        frame = render_frame(sprite, s, size, TransformState())
        Image.fromarray(frame).save(tmp, format="PNG")
        os.replace(tmp, path)
    except OSError as e:
        _cleanup(tmp)
        raise ExportError(f"Could not write the PNG file:\n{e}") from e
    except MemoryError:
        _cleanup(tmp)
        raise ExportError("Not enough memory to render this image. Try 720p.") from None
    return path


def _cleanup(p):
    try:
        os.remove(p)
    except OSError:
        pass

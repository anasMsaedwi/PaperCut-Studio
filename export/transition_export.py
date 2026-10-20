"""MP4 export of the unfold / crumple transition."""
from __future__ import annotations

from dataclasses import replace

from processing.crumple import TransitionRenderer
from processing.errors import ExportError, OperationCancelled
from processing.settings import Settings

from .mp4_writer import Mp4Writer
from .utils import ensure_disk_space


def export_transition_mp4(path: str, picture, settings: Settings, progress=None, is_cancelled=None) -> str:
    """picture: RGB uint8 array to reveal, or None for the built-in demo illustration.
    Uses aspect, resolution, FPS, duration, background and crumple seed from `settings`."""
    try:
        s = replace(settings).validate()
    except ValueError as e:
        raise ExportError(str(e)) from e
    if s.bg_mode == "transparent":
        raise ExportError("MP4 (H.264) cannot store transparency. Use the green background "
                          "option or a solid colour.")
    size = s.frame_size()
    ensure_disk_space(path, 25_000_000 + s.duration * 10_000_000)
    renderer = TransitionRenderer(picture, s, size)
    writer = Mp4Writer(path, size[0], size[1], s.fps)
    try:
        for i in range(renderer.n_frames):
            if is_cancelled and is_cancelled():
                raise OperationCancelled()
            writer.write(renderer.frame(i))
            if progress:
                progress(int(100 * (i + 1) / renderer.n_frames))
        writer.close()
    except BaseException:
        writer.abort()
        raise
    return path

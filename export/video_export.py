"""H.264 MP4 export. Frames are streamed to FFmpeg through a pipe (no temp frame files)."""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import replace

from processing.animation import animation_state
from processing.compositor import render_frame
from processing.errors import ExportError, OperationCancelled
from processing.settings import Settings
from processing.sprite import build_sprite

from .utils import ensure_disk_space


def find_ffmpeg() -> str:
    """Bundled binary from imageio-ffmpeg first, then any ffmpeg on PATH."""
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and os.path.isfile(exe):
            return exe
    except Exception:
        pass
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    raise ExportError("FFmpeg was not found.\n\nInstall the bundled one with:\n"
                      "    pip install imageio-ffmpeg\n"
                      "or install FFmpeg system-wide and make sure it is on your PATH "
                      "(see the README).")


def export_mp4(path: str, subject, settings: Settings, progress=None, is_cancelled=None) -> str:
    try:
        s = replace(settings).validate()
    except ValueError as e:
        raise ExportError(str(e)) from e
    if s.bg_mode == "transparent":
        raise ExportError("MP4 (H.264) cannot store transparency. Use the green background "
                          "option, or export a PNG instead.")
    ffmpeg = find_ffmpeg()
    W, H = s.frame_size()
    n_frames = s.fps * s.duration
    ensure_disk_space(path, 25_000_000 + s.duration * 8_000_000)

    sprite = build_sprite(subject, s, (W, H), s.seed)      # built once -> no edge flicker
    tmp = path + ".part"
    cmd = [ffmpeg, "-y", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(s.fps), "-i", "-",
           "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
           "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-f", "mp4", tmp]
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    err_file = tempfile.TemporaryFile()
    try:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=err_file, creationflags=flags)
    except OSError as e:
        err_file.close()
        raise ExportError(f"Could not start FFmpeg:\n{e}") from e

    def ffmpeg_message() -> str:
        err_file.seek(0)
        return err_file.read().decode("utf-8", "replace").strip()[-800:]

    try:
        for i in range(n_frames):
            if is_cancelled and is_cancelled():
                raise OperationCancelled()
            state = animation_state(s.animation_style, i, n_frames, s.fps, s, (W, H))
            frame = render_frame(sprite, s, (W, H), state)
            try:
                proc.stdin.write(frame.tobytes())
            except (BrokenPipeError, OSError):
                proc.wait()
                raise ExportError("FFmpeg stopped unexpectedly:\n" + ffmpeg_message()) from None
            if progress:
                progress(int(100 * (i + 1) / n_frames))
        proc.stdin.close()
        code = proc.wait()
        if code != 0:
            msg = ffmpeg_message()
            if "libx264" in msg:
                msg += ("\n\nThis FFmpeg build has no H.264 (libx264) encoder. Install a full "
                        "FFmpeg system-wide or reinstall imageio-ffmpeg.")
            raise ExportError("FFmpeg failed:\n" + msg)
        os.replace(tmp, path)
    except BaseException:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        _cleanup(tmp)
        raise
    finally:
        err_file.close()
        if proc.stdin and not proc.stdin.closed:
            try:
                proc.stdin.close()
            except OSError:
                pass
    return path


def _cleanup(p):
    try:
        os.remove(p)
    except OSError:
        pass

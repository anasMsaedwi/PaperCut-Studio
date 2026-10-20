"""Streams raw RGB frames to FFmpeg (H.264 MP4) and finalises the file atomically."""
from __future__ import annotations

import os
import subprocess
import tempfile

from processing.errors import ExportError

from .video_export import find_ffmpeg


class Mp4Writer:
    def __init__(self, path: str, W: int, H: int, fps: int, crf: int = 17):
        self.path, self.tmp = path, path + ".part"
        cmd = [find_ffmpeg(), "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
               "-s", f"{W}x{H}", "-r", str(fps), "-i", "-", "-an", "-c:v", "libx264", "-preset", "medium",
               "-crf", str(crf), "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-f", "mp4", self.tmp]
        self.err = tempfile.TemporaryFile()
        try:
            self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=self.err,
                                         creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        except OSError as e:
            self.err.close()
            raise ExportError(f"Could not start FFmpeg:\n{e}") from e

    def _message(self) -> str:
        self.err.seek(0)
        msg = self.err.read().decode("utf-8", "replace").strip()[-600:]
        if "libx264" in msg:
            msg += "\n\nThis FFmpeg build has no H.264 (libx264) encoder."
        return msg

    def write(self, frame) -> None:
        try:
            self.proc.stdin.write(frame.tobytes())
        except (BrokenPipeError, OSError):
            self.proc.wait()
            raise ExportError("FFmpeg stopped unexpectedly:\n" + self._message()) from None

    def close(self) -> None:
        self.proc.stdin.close()
        if self.proc.wait() != 0:
            raise ExportError("FFmpeg failed:\n" + self._message())
        self.err.close()
        os.replace(self.tmp, self.path)

    def abort(self) -> None:
        if self.proc.poll() is None:
            self.proc.kill()
        self.proc.wait()
        try:
            self.proc.stdin.close()
        except OSError:
            pass
        self.err.close()
        try:
            os.remove(self.tmp)
        except OSError:
            pass

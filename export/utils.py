"""Shared export helpers: disk-space check and atomic file naming."""
from __future__ import annotations

import os
import shutil

from processing.errors import ExportError


def ensure_disk_space(path: str, required_bytes: int) -> None:
    folder = os.path.dirname(os.path.abspath(path)) or "."
    if not os.path.isdir(folder):
        raise ExportError(f"The folder does not exist:\n{folder}")
    try:
        free = shutil.disk_usage(folder).free
    except OSError as e:
        raise ExportError(f"Could not check free disk space in {folder}: {e}") from e
    if free < required_bytes:
        need, have = required_bytes / 1e6, free / 1e6
        raise ExportError(f"Not enough free disk space in {folder}.\n"
                          f"About {need:.0f} MB are needed, {have:.0f} MB are free.")
    if not os.access(folder, os.W_OK):
        raise ExportError(f"You do not have permission to write to:\n{folder}")

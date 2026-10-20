"""Optional local background removal with rembg (nothing is uploaded anywhere).

rembg downloads its ONNX model the first time a model is used (u2net is ~170 MB) and
caches it in your home folder (~/.rembg or ~/.u2net depending on the rembg version, or
$U2NET_HOME if you set it). After that it works fully offline.
"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import numpy as np
from PIL import Image

from .errors import BackgroundRemovalError
from .mask import prepare_subject

SUPPORTED_MODELS = {
    "u2net": "u2net - general purpose (~170 MB)",
    "isnet-general-use": "isnet-general-use - sharper edges (~170 MB)",
    "u2netp": "u2netp - small and fast (~4 MB)",
    "silueta": "silueta - small (~43 MB)",
}

_sessions: dict[str, object] = {}


def is_rembg_available() -> bool:
    return importlib.util.find_spec("rembg") is not None


def model_is_cached(model: str) -> bool:
    """True if rembg already has this model on disk (so no download will happen).

    Different rembg versions use different cache layouts, so check all known locations.
    """
    roots = []
    env_home = os.environ.get("U2NET_HOME")
    if env_home:
        roots.append(Path(env_home).expanduser())
    xdg = os.environ.get("XDG_DATA_HOME")
    roots += [Path.home() / ".rembg", Path.home() / ".u2net"]
    if xdg:
        roots += [Path(xdg).expanduser() / "rembg", Path(xdg).expanduser() / ".u2net"]
    for root in roots:
        if (root / f"{model}.onnx").is_file() or (root / "models" / model / f"{model}.onnx").is_file():
            return True
    return False


def remove_background(rgba: np.ndarray, model: str = "u2net", alpha_matting: bool = False) -> np.ndarray:
    """Return a prepared (refined + cropped) uint8 RGBA subject."""
    try:
        from rembg import new_session, remove
    except ImportError as e:
        raise BackgroundRemovalError(
            "Background removal needs the optional 'rembg' package, which is not installed.\n\n"
            "Install it with:\n    pip install \"rembg[cpu]\"\n\n"
            "Meanwhile you can import an image that is already transparent (PNG/WebP), "
            "or keep using the image as-is.") from e
    except Exception as e:     # e.g. onnxruntime failing to load
        raise BackgroundRemovalError(f"rembg could not be loaded: {e}") from e

    try:
        session = _sessions.get(model)
        if session is None:
            session = _sessions[model] = new_session(model)
        pil = Image.fromarray(np.ascontiguousarray(rgba[..., :3]), "RGB")
        out = remove(pil, session=session, alpha_matting=alpha_matting,
                     alpha_matting_foreground_threshold=240,
                     alpha_matting_background_threshold=10,
                     alpha_matting_erode_size=10, post_process_mask=True)
        result = np.array(out.convert("RGBA"), dtype=np.uint8)
    except Exception as e:
        raise BackgroundRemovalError(
            f"Background removal failed: {e}\n\n"
            "If this is the first time you use this model, check your internet connection - "
            "the model file is downloaded once. You can still import a transparent PNG "
            "or use the image as-is.") from e

    coverage = float((result[..., 3] > 16).mean())
    if coverage < 0.005:
        raise BackgroundRemovalError("No subject was detected in this image. "
                                     "Try another model, or use the image as-is.")
    try:
        return prepare_subject(result)
    except ValueError as e:
        raise BackgroundRemovalError(str(e)) from e

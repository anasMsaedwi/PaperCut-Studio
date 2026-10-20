"""Image loading: keeps aspect ratio, honours EXIF rotation, caps the working size."""
from __future__ import annotations

import os
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

from .errors import ImageLoadError
from .mask import has_meaningful_alpha, prepare_subject

MAX_WORKING_SIDE = 2048          # larger images are downscaled once, on load
Image.MAX_IMAGE_PIXELS = 250_000_000


@dataclass
class LoadedImage:
    original: np.ndarray         # uint8 RGBA, <= MAX_WORKING_SIDE
    subject: np.ndarray          # uint8 RGBA, mask refined + cropped
    has_alpha: bool              # file already contained a cut-out
    source_size: tuple[int, int]


def load_image_array(path: str, max_side: int = MAX_WORKING_SIDE) -> tuple[np.ndarray, tuple[int, int]]:
    if not os.path.isfile(path):
        raise ImageLoadError(f"File not found:\n{path}")
    try:
        with Image.open(path) as img:
            source_size = img.size
            if img.format == "JPEG":                     # fast, reduced-size JPEG decode
                img.draft("RGB", (max_side, max_side))
            img = ImageOps.exif_transpose(img)
            img = img.convert("RGBA")
            img.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
            return np.array(img, dtype=np.uint8), source_size
    except (UnidentifiedImageError, Image.DecompressionBombError):
        raise ImageLoadError("This file is not a supported image (or it is corrupt / too large).\n"
                             "Try PNG, JPEG, WebP, BMP or TIFF.") from None
    except (OSError, ValueError, SyntaxError) as e:
        raise ImageLoadError(f"Could not read the image: {e}") from e


def load_subject(path: str, max_side: int = MAX_WORKING_SIDE) -> LoadedImage:
    """Load a file and prepare a usable subject straight away.

    * transparent PNG/WebP -> its alpha channel is the mask
    * otherwise            -> the whole picture is used as-is (until the user removes the background)
    """
    rgba, source_size = load_image_array(path, max_side)
    has_alpha = has_meaningful_alpha(rgba)
    if not has_alpha:
        rgba[..., 3] = 255
    try:
        subject = prepare_subject(rgba)
    except ValueError as e:
        raise ImageLoadError(str(e)) from e
    return LoadedImage(rgba, subject, has_alpha, source_size)


def subject_as_is(rgba: np.ndarray) -> np.ndarray:
    """Use the whole picture (fully opaque) as the subject - fallback when background
    removal is unavailable or fails."""
    opaque = rgba.copy()
    opaque[..., 3] = 255
    return prepare_subject(opaque)

"""Exceptions whose messages are safe to show directly to the user."""
from __future__ import annotations


class PaperCutError(Exception):
    """Base class for errors with a user-readable message."""


class ImageLoadError(PaperCutError):
    pass


class BackgroundRemovalError(PaperCutError):
    pass


class ExportError(PaperCutError):
    pass


class OperationCancelled(Exception):
    """Raised inside a long job when the user pressed Cancel."""

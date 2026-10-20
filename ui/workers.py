"""Background worker: runs any function in a QThread so the UI never freezes.

All results are delivered through signals that carry the job `kind`, so the main window can
connect them to ordinary bound methods (which Qt then delivers on the GUI thread).
"""
from __future__ import annotations

import traceback

from PySide6.QtCore import QThread, Signal

from processing.errors import OperationCancelled, PaperCutError


class FunctionWorker(QThread):
    result = Signal(str, object)     # kind, return value
    error = Signal(str, str)         # kind, message
    progress = Signal(str, int)      # kind, 0..100
    cancelled = Signal(str)
    done = Signal(object)            # the worker itself; always emitted last

    def __init__(self, kind: str, fn, args=(), kwargs=None, wants_callbacks: bool = False):
        super().__init__()
        self._kind, self._fn = kind, fn
        self._args, self._kwargs = args, dict(kwargs or {})
        self._wants_callbacks = wants_callbacks
        self._cancel = False

    @property
    def kind(self) -> str:
        return self._kind

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        try:
            kwargs = dict(self._kwargs)
            if self._wants_callbacks:
                kwargs["progress"] = lambda pct: self.progress.emit(self._kind, int(pct))
                kwargs["is_cancelled"] = lambda: self._cancel
            out = self._fn(*self._args, **kwargs)
            self.result.emit(self._kind, out)
        except OperationCancelled:
            self.cancelled.emit(self._kind)
        except PaperCutError as e:
            self.error.emit(self._kind, str(e))
        except MemoryError:
            self.error.emit(self._kind, "The computer ran out of memory. Try a smaller image or 720p.")
        except Exception as e:                      # keep the app alive, show the reason
            traceback.print_exc()
            self.error.emit(self._kind, f"Unexpected error ({type(e).__name__}): {e}")
        finally:
            self.done.emit(self)

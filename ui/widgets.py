"""Reusable widgets: image view (with drag / wheel) and a labelled 0-100 slider."""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QSlider, QVBoxLayout, QWidget


def ndarray_to_qimage(arr: np.ndarray) -> QImage:
    """uint8 RGB (h,w,3) or RGBA (h,w,4) -> QImage that owns its memory."""
    arr = np.ascontiguousarray(arr)
    h, w, c = arr.shape
    fmt = QImage.Format.Format_RGBA8888 if c == 4 else QImage.Format.Format_RGB888
    return QImage(arr.data, w, h, c * w, fmt).copy()


class ImageView(QWidget):
    """Shows an image scaled to fit. If `interactive`, dragging reports movement of the
    subject and the mouse wheel reports scaling. Transparent images get a checkerboard."""

    subjectMoved = Signal(float, float)   # drag delta as a fraction of the displayed image size
    wheelScrolled = Signal(int)           # +1 / -1
    clicked = Signal()

    def __init__(self, placeholder: str = "", interactive: bool = False, parent=None):
        super().__init__(parent)
        self._image: QImage | None = None
        self._has_alpha = False
        self._placeholder = placeholder
        self._interactive = interactive
        self._drag_from = None
        self._moved = False
        self.setMinimumSize(260, 200)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        if interactive:
            self.setCursor(Qt.CursorShape.OpenHandCursor)

    # ---- content -------------------------------------------------------------
    def set_array(self, arr: np.ndarray | None) -> None:
        if arr is None:
            self._image = None
        else:
            self._image = ndarray_to_qimage(arr)
            self._has_alpha = arr.shape[2] == 4 and bool((arr[..., 3] < 255).any())
        self.update()

    def has_image(self) -> bool:
        return self._image is not None

    def _target_rect(self) -> QRectF:
        if self._image is None:
            return QRectF()
        avail = QRectF(self.rect()).adjusted(8, 8, -8, -8)
        iw, ih = self._image.width(), self._image.height()
        k = min(avail.width() / iw, avail.height() / ih)
        w, h = iw * k, ih * k
        return QRectF(avail.center().x() - w / 2, avail.center().y() - h / 2, w, h)

    # ---- painting ------------------------------------------------------------
    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.fillRect(self.rect(), QColor("#1b1d23"))
        if self._image is None:
            p.setPen(QColor("#8a8f9c"))
            p.drawText(self.rect().adjusted(20, 20, -20, -20),
                       Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, self._placeholder)
            return
        rect = self._target_rect()
        if self._has_alpha:
            self._draw_checker(p, rect)
        p.drawImage(rect, self._image)
        p.setPen(QColor("#3a3f4b"))
        p.drawRect(rect)

    @staticmethod
    def _draw_checker(p: QPainter, rect: QRectF, size: int = 12) -> None:
        p.save()
        p.setClipRect(rect)
        light, dark = QColor("#4a4e59"), QColor("#363a44")
        y, row = rect.top(), 0
        while y < rect.bottom():
            x, col = rect.left(), 0
            while x < rect.right():
                p.fillRect(QRectF(x, y, size, size), light if (row + col) % 2 == 0 else dark)
                x += size
                col += 1
            y += size
            row += 1
        p.restore()

    # ---- mouse ---------------------------------------------------------------
    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            self._drag_from, self._moved = ev.position(), False
            if self._interactive and self._image is not None:
                self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, ev):
        if self._drag_from is None or not self._interactive or self._image is None:
            return
        rect = self._target_rect()
        if rect.width() <= 0:
            return
        d = ev.position() - self._drag_from
        self._drag_from, self._moved = ev.position(), True
        self.subjectMoved.emit(d.x() / rect.width(), d.y() / rect.height())

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            if not self._moved:
                self.clicked.emit()
            self._drag_from = None
            if self._interactive:
                self.setCursor(Qt.CursorShape.OpenHandCursor)

    def wheelEvent(self, ev):
        if self._interactive and self._image is not None:
            self.wheelScrolled.emit(1 if ev.angleDelta().y() > 0 else -1)
            ev.accept()


class SliderRow(QWidget):
    """Label + current value above a 0..100 slider."""

    valueChanged = Signal(int)

    def __init__(self, label: str, value: int = 50, tooltip: str = "", parent=None):
        super().__init__(parent)
        self._value_label = QLabel(str(value))
        self._value_label.setMinimumWidth(28)
        self._value_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setRange(0, 100)
        self._slider.setValue(value)
        top = QHBoxLayout()
        top.addWidget(QLabel(label))
        top.addStretch(1)
        top.addWidget(self._value_label)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        lay.addLayout(top)
        lay.addWidget(self._slider)
        if tooltip:
            self.setToolTip(tooltip)
        self._slider.valueChanged.connect(self._on_changed)

    def _on_changed(self, v: int):
        self._value_label.setText(str(v))
        self.valueChanged.emit(v)

    def set_value_silent(self, v: float) -> None:
        self._slider.blockSignals(True)
        self._slider.setValue(int(round(v)))
        self._slider.blockSignals(False)
        self._value_label.setText(str(self._slider.value()))

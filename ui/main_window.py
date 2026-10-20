"""Main window: wires the widgets to the processing / export code via background workers."""
from __future__ import annotations

import os
import random
from dataclasses import replace
from functools import partial

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QAction, QColor, QKeySequence
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QFileDialog, QFrame, QGroupBox,
                               QHBoxLayout, QLabel, QMainWindow, QMessageBox, QProgressBar,
                               QProgressDialog, QPushButton, QScrollArea, QSpinBox, QSplitter,
                               QVBoxLayout, QWidget)

from export.png_export import export_png
from export.transition_export import export_transition_mp4
from export.video_export import export_mp4
from processing.crumple import render_transition_preview
from processing.loader import MAX_WORKING_SIDE, LoadedImage, load_subject, subject_as_is
from processing.pipeline import render_preview_animation, render_still_job
from processing.segmentation import (SUPPORTED_MODELS, is_rembg_available, model_is_cached,
                                     remove_background)
from processing.settings import Settings
from processing.sprite import SpriteCache

from .styles import STYLESHEET
from .widgets import ImageView, SliderRow
from .workers import FunctionWorker

PREVIEW_MAX_SIDE = 960          # still preview resolution (long side)
ANIM_PREVIEW_MAX_SIDE = 480     # animation preview resolution (long side)
ANIM_PREVIEW_SECONDS = 6.0      # preview plays at most the first N seconds
TRANSITION_PREVIEW_MAX_SIDE = 560   # transition preview resolution (long side)

SLIDER_GROUPS = [
    ("Subject", [
        ("subject_size", "Subject size", "How much of the frame the cut-out fills. Mouse wheel on the result also changes it."),
        ("pos_x", "Position X", "50 = centred. You can also drag the subject in the result view."),
        ("pos_y", "Position Y", "50 = centred."),
    ]),
    ("Paper edge", [
        ("edge_thickness", "Paper-edge thickness", "Width of the white paper border around the subject."),
        ("edge_roughness", "Edge roughness / tearing", "How irregular or torn the border is."),
        ("edge_detail", "Edge detail", "Amount of fine detail along the edge (more vertices / finer fibres)."),
        ("texture_intensity", "Paper-texture intensity", "Grain and fibres. Keep low to protect image detail."),
    ]),
    ("Shadow", [
        ("shadow_x", "Shadow offset - horizontal", "50 = no offset, <50 left, >50 right."),
        ("shadow_y", "Shadow offset - vertical", "50 = no offset, <50 up, >50 down."),
        ("shadow_blur", "Shadow blur", "Softness of the shadow."),
        ("shadow_intensity", "Shadow intensity", "Darkness of the shadow."),
    ]),
    ("Animation", [
        ("animation_amount", "Animation amount", "Strength of the motion. 0 = static."),
    ]),
]

CUTOUT_ITEMS = [("Smooth edge", "smooth"), ("Cut edge (scissors)", "cut"), ("Torn edge", "torn")]
ANIM_ITEMS = [("Subtle paper jitter", "jitter"), ("Stop-motion", "stopmotion"),
              ("Floating", "floating"), ("Bounce", "bounce"), ("Gradual reveal", "reveal")]
BG_ITEMS = [("Solid colour", "solid"), ("Green chroma key", "green"), ("Transparent (PNG only)", "transparent")]
ASPECT_ITEMS = [("16:9 (landscape)", "16:9"), ("9:16 (portrait)", "9:16")]
RES_ITEMS = [("720p", 720), ("1080p", 1080)]
FPS_ITEMS = [("24 FPS", 24), ("30 FPS", 30)]
TSRC_ITEMS = [("Loaded image", "image"), ("Demo illustration", "demo")]


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PaperCut Studio")
        self.resize(1380, 880)
        self.setAcceptDrops(True)
        self.setStyleSheet(STYLESHEET)

        self.settings = Settings()
        self.original = None            # uint8 RGBA working copy of the loaded file
        self.subject = None             # uint8 RGBA, refined + cropped
        self._token = 0                 # bumps whenever self.subject changes (sprite cache key)
        self._workers: set[FunctionWorker] = set()
        self._preview_worker = None
        self._preview_dirty = False
        self._anim_worker = None
        self._export_worker = None
        self._export_dialog = None
        self._frames = None
        self._frame_idx = 0
        self._last_still = None
        self._playing = False
        self._play_source = "animation"   # which preview is playing: animation / transition
        self._still_cache, self._anim_cache = SpriteCache(), SpriteCache()

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(140)
        self._debounce.timeout.connect(self._start_preview)
        self._play_timer = QTimer(self)
        self._play_timer.timeout.connect(self._advance_frame)

        self._build_menu()
        self._build_ui()
        self._sync_widgets()
        self._update_buttons()
        self.statusBar().showMessage("Open or drop an image to begin.")

    # ======================================================================= UI
    def _build_menu(self):
        m = self.menuBar().addMenu("&File")
        act = QAction("&Open image...", self)
        act.setShortcut(QKeySequence.StandardKey.Open)
        act.triggered.connect(self.open_image_dialog)
        m.addAction(act)
        m.addSeparator()
        quit_act = QAction("&Quit", self)
        quit_act.setShortcut(QKeySequence.StandardKey.Quit)
        quit_act.triggered.connect(self.close)
        m.addAction(quit_act)
        h = self.menuBar().addMenu("&Help")
        about = QAction("&About / privacy", self)
        about.triggered.connect(self._show_about)
        h.addAction(about)

    def _build_ui(self):
        # --- left: two image views --------------------------------------------
        self.original_view = ImageView("Drop an image here\nor click to browse")
        self.original_view.clicked.connect(self._original_clicked)
        self.result_view = ImageView("The paper-cutout preview appears here", interactive=True)
        self.result_view.subjectMoved.connect(self._on_subject_dragged)
        self.result_view.wheelScrolled.connect(self._on_wheel)

        def titled(title, view, hint=""):
            box = QWidget()
            lay = QVBoxLayout(box)
            lay.setContentsMargins(4, 4, 4, 4)
            t = QLabel(title)
            t.setObjectName("viewTitle")
            lay.addWidget(t)
            lay.addWidget(view, 1)
            if hint:
                h = QLabel(hint)
                h.setObjectName("hint")
                lay.addWidget(h)
            return box

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(titled("Original", self.original_view))
        splitter.addWidget(titled("Result", self.result_view,
                                  "Drag the result to move the subject - mouse wheel to resize it."))
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)

        # --- right: settings panel ----------------------------------------------
        panel = QWidget()
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(8, 8, 8, 8)
        pl.setSpacing(8)
        pl.addWidget(self._build_image_group())
        self.sliders: dict[str, SliderRow] = {}
        for title, rows in SLIDER_GROUPS:
            box = QGroupBox(title)
            bl = QVBoxLayout(box)
            for attr, label, tip in rows:
                row = SliderRow(label, int(getattr(self.settings, attr)), tip)
                row.valueChanged.connect(partial(self._on_slider, attr))
                self.sliders[attr] = row
                bl.addWidget(row)
            if title == "Paper edge":
                self.cb_cutout = self._combo(bl, "Cutout style", CUTOUT_ITEMS, "cutout_style")
                btn = QPushButton("New random edge")
                btn.setToolTip("Pick a new random seed for the edge shape and texture.")
                btn.clicked.connect(self._new_seed)
                bl.addWidget(btn)
            if title == "Animation":
                self.cb_anim = self._combo(bl, "Animation style", ANIM_ITEMS, "animation_style")
            pl.addWidget(box)
        pl.addWidget(self._build_transition_group())
        pl.addWidget(self._build_output_group())
        pl.addWidget(self._build_action_group())
        pl.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(panel)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setMinimumWidth(400)
        scroll.setMaximumWidth(460)

        central = QWidget()
        cl = QHBoxLayout(central)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.addWidget(splitter, 1)
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        cl.addWidget(sep)
        cl.addWidget(scroll)
        self.setCentralWidget(central)

        self.busy_bar = QProgressBar()
        self.busy_bar.setRange(0, 0)
        self.busy_bar.setFixedWidth(160)
        self.busy_bar.setTextVisible(False)
        self.busy_bar.hide()
        self.statusBar().addPermanentWidget(self.busy_bar)

    def _build_image_group(self) -> QGroupBox:
        box = QGroupBox("Image")
        lay = QVBoxLayout(box)
        self.btn_open = QPushButton("Open image...")
        self.btn_open.setObjectName("primary")
        self.btn_open.clicked.connect(self.open_image_dialog)
        lay.addWidget(self.btn_open)

        self.btn_removebg = QPushButton("Remove background (local, rembg)")
        self.btn_removebg.clicked.connect(self.remove_background_clicked)
        lay.addWidget(self.btn_removebg)

        row = QHBoxLayout()
        self.cb_model = QComboBox()
        for key, label in SUPPORTED_MODELS.items():
            self.cb_model.addItem(label, key)
        self._shrinkable(self.cb_model)
        row.addWidget(QLabel("Model"))
        row.addWidget(self.cb_model, 1)
        lay.addLayout(row)
        self.chk_matting = QCheckBox("Alpha matting (finer hair, slower)")
        lay.addWidget(self.chk_matting)

        self.btn_asis = QPushButton("Use original image as-is")
        self.btn_asis.setToolTip("Skip background removal and cut out the whole picture.")
        self.btn_asis.clicked.connect(self.use_as_is_clicked)
        lay.addWidget(self.btn_asis)

        note = QLabel("Everything runs on this computer. rembg downloads its model once "
                      "on first use; images are never uploaded." if is_rembg_available() else
                      "rembg is not installed (optional): import a transparent PNG/WebP or use "
                      "the image as-is. See the README to enable background removal.")
        note.setObjectName("hint")
        note.setWordWrap(True)
        lay.addWidget(note)
        return box

    def _build_transition_group(self) -> QGroupBox:
        box = QGroupBox("Unfold / crumple transition")
        lay = QVBoxLayout(box)
        self.cb_tsrc = self._combo(lay, "Picture to reveal", TSRC_ITEMS, "transition_source")
        btn = QPushButton("New crumple pattern")
        btn.setToolTip("Pick a new random crumple (creases and unfolding order).")
        btn.clicked.connect(self._new_crumple)
        lay.addWidget(btn)
        self.btn_tpreview = QPushButton("Preview transition")
        self.btn_tpreview.clicked.connect(self.toggle_preview_transition)
        self.btn_texport = QPushButton("Export transition MP4...")
        self.btn_texport.setObjectName("primary")
        self.btn_texport.clicked.connect(self.export_transition_clicked)
        lay.addWidget(self.btn_tpreview)
        lay.addWidget(self.btn_texport)
        note = QLabel("A crumpled sheet unfolds to reveal the whole picture, holds, then crumples "
                      "into a ball and rolls away. Uses the Output settings below (aspect, "
                      "resolution, FPS, duration - 6 to 9 s looks best - and background).")
        note.setObjectName("hint")
        note.setWordWrap(True)
        lay.addWidget(note)
        return box

    def _build_output_group(self) -> QGroupBox:
        box = QGroupBox("Output")
        lay = QVBoxLayout(box)
        self.cb_bg = self._combo(lay, "Background", BG_ITEMS, "bg_mode")
        self.btn_color = QPushButton("Background colour...")
        self.btn_color.clicked.connect(self._pick_color)
        lay.addWidget(self.btn_color)
        self.cb_aspect = self._combo(lay, "Aspect ratio", ASPECT_ITEMS, "aspect")
        self.cb_res = self._combo(lay, "Resolution", RES_ITEMS, "resolution")
        self.cb_fps = self._combo(lay, "Frame rate", FPS_ITEMS, "fps")
        row = QHBoxLayout()
        row.addWidget(QLabel("Duration"))
        self.sp_duration = QSpinBox()
        self.sp_duration.setRange(3, 10)
        self.sp_duration.setSuffix(" s")
        self.sp_duration.valueChanged.connect(self._on_duration)
        row.addStretch(1)
        row.addWidget(self.sp_duration)
        lay.addLayout(row)
        return box

    def _build_action_group(self) -> QGroupBox:
        box = QGroupBox("Actions")
        lay = QVBoxLayout(box)
        self.btn_preview = QPushButton("Preview animation")
        self.btn_preview.clicked.connect(self.toggle_preview_animation)
        self.btn_reset = QPushButton("Reset settings")
        self.btn_reset.clicked.connect(self.reset_settings)
        self.btn_png = QPushButton("Export PNG...")
        self.btn_png.clicked.connect(self.export_png_clicked)
        self.btn_mp4 = QPushButton("Export MP4...")
        self.btn_mp4.setObjectName("primary")
        self.btn_mp4.clicked.connect(self.export_mp4_clicked)
        for b in (self.btn_preview, self.btn_reset, self.btn_png, self.btn_mp4):
            lay.addWidget(b)
        return box

    @staticmethod
    def _shrinkable(cb: QComboBox) -> None:
        """Let long item texts be elided instead of widening the whole settings panel."""
        cb.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        cb.setMinimumContentsLength(14)

    def _combo(self, layout, label, items, attr) -> QComboBox:
        row = QHBoxLayout()
        row.addWidget(QLabel(label))
        cb = QComboBox()
        for text, value in items:
            cb.addItem(text, value)
        self._shrinkable(cb)
        cb.currentIndexChanged.connect(partial(self._on_combo, attr, cb))
        row.addStretch(1)
        row.addWidget(cb)
        layout.addLayout(row)
        return cb

    # ======================================================== settings <-> widgets
    def _sync_widgets(self):
        """Push self.settings into every widget without triggering change handlers."""
        for attr, row in self.sliders.items():
            row.set_value_silent(getattr(self.settings, attr))
        for cb, attr in ((self.cb_cutout, "cutout_style"), (self.cb_anim, "animation_style"),
                         (self.cb_bg, "bg_mode"), (self.cb_aspect, "aspect"),
                         (self.cb_res, "resolution"), (self.cb_fps, "fps"),
                         (self.cb_tsrc, "transition_source")):
            cb.blockSignals(True)
            cb.setCurrentIndex(max(0, cb.findData(getattr(self.settings, attr))))
            cb.blockSignals(False)
        self.sp_duration.blockSignals(True)
        self.sp_duration.setValue(self.settings.duration)
        self.sp_duration.blockSignals(False)
        self._refresh_color_button()

    def _refresh_color_button(self):
        r, g, b = self.settings.bg_color
        fg = "#000" if (r * 299 + g * 587 + b * 114) / 1000 > 140 else "#fff"
        self.btn_color.setStyleSheet(f"background: rgb({r},{g},{b}); color: {fg};")
        self.btn_color.setEnabled(self.settings.bg_mode == "solid")

    def _on_slider(self, attr, value):
        setattr(self.settings, attr, float(value))
        self._settings_changed()

    def _on_combo(self, attr, cb, _index):
        setattr(self.settings, attr, cb.currentData())
        self._refresh_color_button()
        self._settings_changed()

    def _on_duration(self, v):
        self.settings.duration = int(v)
        self._settings_changed()

    def _pick_color(self):
        r, g, b = self.settings.bg_color
        c = QColorDialog.getColor(QColor(r, g, b), self, "Background colour")
        if c.isValid():
            self.settings.bg_color = (c.red(), c.green(), c.blue())
            self._refresh_color_button()
            self._settings_changed()

    def _new_seed(self):
        self.settings.seed = random.randint(1, 2**31 - 1)
        self._settings_changed()

    def _new_crumple(self):
        self.settings.crumple_seed = random.randint(1, 2**31 - 1)
        self.statusBar().showMessage("New crumple pattern picked - press 'Preview transition'.")
        self._stop_playback(restore=False)

    def reset_settings(self):
        self.settings = Settings()
        self._sync_widgets()
        self._settings_changed()

    def _settings_changed(self):
        self._stop_playback(restore=False)
        if self._anim_worker is not None:
            self._anim_worker.cancel()
        self._schedule_preview()

    # ============================================================ result view input
    def _on_subject_dragged(self, fx, fy):
        if self.subject is None:
            return
        self._stop_playback(restore=False)
        for attr, d in (("pos_x", fx), ("pos_y", fy)):
            v = min(100.0, max(0.0, getattr(self.settings, attr) + d * 100.0))
            setattr(self.settings, attr, v)
            self.sliders[attr].set_value_silent(v)
        self._settings_changed()

    def _on_wheel(self, direction):
        v = min(100.0, max(0.0, self.settings.subject_size + 3 * direction))
        self.settings.subject_size = v
        self.sliders["subject_size"].set_value_silent(v)
        self._settings_changed()

    # ====================================================================== workers
    def _start_worker(self, kind, fn, args=(), kwargs=None, wants_callbacks=False) -> FunctionWorker:
        w = FunctionWorker(kind, fn, args, kwargs, wants_callbacks)
        w.result.connect(self._on_result)
        w.error.connect(self._on_error)
        w.progress.connect(self._on_progress)
        w.cancelled.connect(self._on_cancelled)
        w.done.connect(self._on_worker_done)
        self._workers.add(w)
        w.start()
        return w

    def _set_busy(self, text: str | None):
        if text:
            self.statusBar().showMessage(text)
            self.busy_bar.show()
        else:
            self.busy_bar.hide()

    def _on_worker_done(self, w):
        w.wait()
        self._workers.discard(w)
        if w is self._preview_worker:
            self._preview_worker = None
            if self._preview_dirty:
                self._preview_dirty = False
                self._start_preview()
        if w is self._anim_worker:
            self._anim_worker = None
            if not self._playing:
                self._reset_preview_button()
        if w is self._export_worker:
            self._export_worker = None
            self._close_export_dialog()
            self._update_buttons()
        if w.kind in ("load", "removebg", "asis"):
            self._set_busy(None)
            self._update_buttons()
        w.deleteLater()

    def _on_result(self, kind, payload):
        if kind == "load":
            self._on_loaded(payload)
        elif kind in ("removebg", "asis"):
            self._set_subject(payload)
            self.statusBar().showMessage("Background removed." if kind == "removebg"
                                         else "Using the original image as-is.")
        elif kind == "preview":
            self._last_still = payload
            if not self._playing:
                self.result_view.set_array(payload)
        elif kind == "anim":
            self._start_playback(*payload)
        elif kind in ("export_png", "export_mp4", "export_transition"):
            self.statusBar().showMessage("Export finished.")
            QMessageBox.information(self, "Export complete", f"Saved to:\n{payload}")

    def _on_error(self, kind, message):
        if kind == "preview":
            self.statusBar().showMessage("Preview failed: " + message.splitlines()[0])
            return
        if kind == "removebg":
            box = QMessageBox(QMessageBox.Icon.Warning, "Background removal failed", message, parent=self)
            box.setInformativeText("The image is still available: you can import a transparent "
                                   "PNG/WebP, or continue with 'Use original image as-is'.")
            box.exec()
            return
        if kind == "anim":
            self._reset_preview_button()
        title = {"load": "Could not open the image", "asis": "Could not use the image",
                 "export_png": "PNG export failed", "export_mp4": "MP4 export failed",
                 "export_transition": "Transition export failed",
                 "anim": "Preview failed"}.get(kind, "Error")
        QMessageBox.critical(self, title, message)
        self.statusBar().showMessage(title)

    def _on_progress(self, kind, pct):
        if kind in ("export_mp4", "export_transition") and self._export_dialog is not None:
            self._export_dialog.setValue(pct)
        elif kind == "anim":
            self.statusBar().showMessage(f"Rendering preview... {pct}%")

    def _on_cancelled(self, kind):
        if kind.startswith("export"):
            self.statusBar().showMessage("Export cancelled.")
        elif kind == "anim":
            self._reset_preview_button()

    # ======================================================================= loading
    def open_image_dialog(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open image", "", "Images (*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff);;All files (*)")
        if path:
            self.load_path(path)

    def _original_clicked(self):
        if not self.original_view.has_image():
            self.open_image_dialog()

    def dragEnterEvent(self, ev):
        if ev.mimeData().hasUrls():
            ev.acceptProposedAction()

    def dropEvent(self, ev):
        urls = ev.mimeData().urls()
        if urls and urls[0].isLocalFile():
            self.load_path(urls[0].toLocalFile())

    def load_path(self, path: str):
        if any(w.kind == "load" for w in self._workers):
            return
        self._set_busy(f"Loading {os.path.basename(path)}...")
        self._start_worker("load", load_subject, args=(path,))
        self._source_name = os.path.basename(path)

    def _on_loaded(self, li: LoadedImage):
        self.original = li.original
        self.original_view.set_array(li.original if li.has_alpha else li.original[..., :3])
        self.settings.pos_x = self.settings.pos_y = 50.0
        self._sync_widgets()
        self._set_subject(li.subject)
        h, w = li.original.shape[:2]
        if li.has_alpha:
            self.statusBar().showMessage(f"{self._source_name}: transparent image - using its alpha channel as the mask.")
        else:
            self.statusBar().showMessage(f"{self._source_name} ({li.source_size[0]}x{li.source_size[1]}"
                                         f"{', scaled to ' + str(w) + 'x' + str(h) if li.source_size != (w, h) else ''}): "
                                         "using the image as-is. Click 'Remove background' to cut out the subject.")

    def _set_subject(self, subject):
        self.subject = subject
        self._token += 1
        self._update_buttons()
        self._stop_playback(restore=False)
        self._schedule_preview()

    # ============================================================ background removal
    def remove_background_clicked(self):
        if self.original is None:
            return
        if not is_rembg_available():
            QMessageBox.information(
                self, "rembg is not installed",
                "Background removal uses the optional 'rembg' package.\n\nInstall it with:\n"
                "    pip install \"rembg[cpu]\"\nthen restart the app.\n\nUntil then you can import an "
                "already-transparent PNG/WebP, or use the original image as-is.")
            return
        model = self.cb_model.currentData()
        if not model_is_cached(model):
            ans = QMessageBox.question(
                self, "One-time model download",
                f"The '{model}' model is not on this computer yet.\n\nrembg will download it once "
                "(up to ~170 MB) and keep it in your home folder. After that, background removal "
                "works offline. Your images are never uploaded.\n\nDownload and continue?")
            if ans != QMessageBox.StandardButton.Yes:
                return
        self._set_busy("Removing background (the first run may download the model)...")
        self._update_buttons(busy=True)
        self._start_worker("removebg", remove_background, args=(self.original,),
                           kwargs={"model": model, "alpha_matting": self.chk_matting.isChecked()})

    def use_as_is_clicked(self):
        if self.original is None:
            return
        self._set_busy("Preparing image...")
        self._update_buttons(busy=True)
        self._start_worker("asis", subject_as_is, args=(self.original,))

    # =========================================================================== preview
    def _schedule_preview(self):
        if self.subject is not None:
            self._debounce.start()

    def _start_preview(self):
        if self.subject is None:
            return
        if self._preview_worker is not None:      # a render is running: redo once it ends
            self._preview_dirty = True
            return
        self._preview_worker = self._start_worker(
            "preview", render_still_job,
            args=(self.subject, replace(self.settings), PREVIEW_MAX_SIDE, self._token, self._still_cache))

    def toggle_preview_animation(self):
        self._request_preview("animation")

    def toggle_preview_transition(self):
        self._request_preview("transition")

    def _request_preview(self, which: str):
        if self._playing:
            self._stop_playback()
            return
        if self._anim_worker is not None:
            return
        if which == "animation":
            if self.subject is None:
                return
            btn, fn = self.btn_preview, render_preview_animation
            args = (self.subject, replace(self.settings), ANIM_PREVIEW_MAX_SIDE, ANIM_PREVIEW_SECONDS,
                    self._token, self._anim_cache)
        else:
            btn, fn = self.btn_tpreview, render_transition_preview
            args = (self._transition_picture(), replace(self.settings), TRANSITION_PREVIEW_MAX_SIDE)
        self._play_source = which
        self.btn_preview.setEnabled(False)
        self.btn_tpreview.setEnabled(False)
        btn.setText("Rendering preview...")
        self._anim_worker = self._start_worker("anim", fn, args=args, wants_callbacks=True)

    def _transition_picture(self):
        """RGB array revealed by the transition, or None for the built-in demo illustration."""
        if self.settings.transition_source == "image":
            if self.original is not None:
                # transparent images are revealed on white paper
                a = self.original[..., 3:4].astype("float32") / 255.0
                paper = (246.0, 242.0, 233.0)
                return (self.original[..., :3] * a + paper * (1.0 - a)).clip(0, 255).astype("uint8")
            self.statusBar().showMessage("No image loaded yet - the transition uses the demo illustration.")
        return None

    def _start_playback(self, frames, fps):
        self._frames, self._frame_idx, self._playing = frames, 0, True
        active = self.btn_tpreview if self._play_source == "transition" else self.btn_preview
        other = self.btn_preview if active is self.btn_tpreview else self.btn_tpreview
        active.setText("Stop preview")
        active.setEnabled(True)
        other.setEnabled(False)
        self._play_timer.start(max(1, int(round(1000 / fps))))
        self.statusBar().showMessage(f"Playing preview ({len(frames) / fps:.0f} s, reduced resolution).")

    def _advance_frame(self):
        if not self._frames:
            return
        self.result_view.set_array(self._frames[self._frame_idx])
        self._frame_idx = (self._frame_idx + 1) % len(self._frames)

    def _stop_playback(self, restore: bool = True):
        was = self._playing
        self._play_timer.stop()
        self._playing, self._frames = False, None
        if was or self._anim_worker is None:
            self._reset_preview_button()
        if restore and was and self._last_still is not None:
            self.result_view.set_array(self._last_still)

    def _reset_preview_button(self):
        self.btn_preview.setText("Preview animation")
        self.btn_preview.setEnabled(self.subject is not None)
        self.btn_tpreview.setText("Preview transition")
        self.btn_tpreview.setEnabled(True)

    # =========================================================================== export
    def export_png_clicked(self):
        if self.subject is None:
            return
        default = os.path.splitext(getattr(self, "_source_name", "paper_cutout"))[0] + "_cutout.png"
        path, _ = QFileDialog.getSaveFileName(self, "Export PNG", default, "PNG image (*.png)")
        if not path:
            return
        if not path.lower().endswith(".png"):
            path += ".png"
        self._begin_export("export_png", export_png, path, self.subject, replace(self.settings), cancellable=False)

    def _mp4_settings(self):
        """Settings copy for an MP4 export; asks to switch Transparent -> green. None = cancelled."""
        s = replace(self.settings)
        if s.bg_mode == "transparent":
            ans = QMessageBox.question(
                self, "MP4 cannot be transparent",
                "H.264 MP4 does not support transparency.\n\nExport with a solid green (chroma-key) "
                "background instead? You can remove the green in your video editor.")
            if ans != QMessageBox.StandardButton.Yes:
                return None
            s.bg_mode = "green"
        return s

    def _ask_mp4_path(self, suffix: str):
        base = os.path.splitext(getattr(self, "_source_name", "paper_cutout"))[0]
        path, _ = QFileDialog.getSaveFileName(self, "Export MP4", base + suffix, "MP4 video (*.mp4)")
        if path and not path.lower().endswith(".mp4"):
            path += ".mp4"
        return path

    def export_mp4_clicked(self):
        if self.subject is None:
            return
        s = self._mp4_settings()
        if s is None:
            return
        path = self._ask_mp4_path("_cutout.mp4")
        if path:
            self._begin_export("export_mp4", export_mp4, path, self.subject, s, cancellable=True)

    def export_transition_clicked(self):
        s = self._mp4_settings()
        if s is None:
            return
        path = self._ask_mp4_path("_unfold.mp4")
        if path:
            self._begin_export("export_transition", export_transition_mp4, path,
                               self._transition_picture(), s, cancellable=True)

    def _begin_export(self, kind, fn, path, payload, settings, cancellable):
        self._stop_playback(restore=False)
        dlg = QProgressDialog("Rendering...", "Cancel" if cancellable else None, 0, 100, self)
        dlg.setWindowTitle("Exporting")
        dlg.setWindowModality(Qt.WindowModality.WindowModal)
        dlg.setMinimumDuration(0)
        dlg.setAutoClose(False)
        dlg.setAutoReset(False)
        if not cancellable:
            dlg.setRange(0, 0)
        else:
            dlg.canceled.connect(self._cancel_export)
        dlg.setValue(0)
        dlg.show()
        self._export_dialog = dlg
        self._update_buttons(busy=True)
        self._export_worker = self._start_worker(kind, fn, args=(path, payload, settings),
                                                 wants_callbacks=True)

    def _cancel_export(self):
        if self._export_worker is not None:
            self._export_worker.cancel()

    def _close_export_dialog(self):
        dlg, self._export_dialog = self._export_dialog, None
        if dlg is not None:
            try:
                dlg.canceled.disconnect()
            except (RuntimeError, TypeError):
                pass
            dlg.hide()
            dlg.deleteLater()

    # ============================================================================ misc
    def _update_buttons(self, busy: bool = False):
        have = self.subject is not None and not busy and self._export_worker is None
        for b in (self.btn_png, self.btn_mp4, self.btn_reset):
            b.setEnabled(have if b is not self.btn_reset else True)
        self.btn_removebg.setEnabled(self.original is not None and not busy)
        self.btn_asis.setEnabled(self.original is not None and not busy)
        idle = not busy and self._export_worker is None
        self.btn_texport.setEnabled(idle)
        if self._anim_worker is None and not self._playing:
            self.btn_preview.setEnabled(have)
            self.btn_tpreview.setEnabled(idle)

    def _show_about(self):
        QMessageBox.about(
            self, "About PaperCut Studio",
            "PaperCut Studio turns a still image into a paper-cutout / torn-paper picture or video.\n\n"
            "Privacy: all processing happens locally. No image is uploaded. The optional rembg model "
            f"is downloaded once from the internet; images larger than {MAX_WORKING_SIDE}px are "
            "downscaled when loaded.")

    def closeEvent(self, ev):
        self._debounce.stop()
        self._play_timer.stop()
        self._close_export_dialog()
        for w in list(self._workers):
            w.cancel()
        for w in list(self._workers):
            w.wait(8000)
        super().closeEvent(ev)

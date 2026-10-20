"""Application stylesheet (dark theme)."""

STYLESHEET = """
QMainWindow, QWidget { background: #23262e; color: #e6e8ee; font-size: 13px; }
QScrollArea { border: none; }
QGroupBox { border: 1px solid #3a3f4b; border-radius: 8px; margin-top: 14px; padding: 10px 8px 8px 8px; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 6px; color: #aab1c3; font-weight: 600; }
QPushButton { background: #353a47; border: 1px solid #454b5a; border-radius: 6px; padding: 7px 12px; }
QPushButton:hover { background: #404656; }
QPushButton:disabled { color: #777c89; background: #2b2e37; }
QPushButton#primary { background: #4c7dff; border-color: #4c7dff; color: white; font-weight: 600; }
QPushButton#primary:hover { background: #6490ff; }
QPushButton#primary:disabled { background: #34406a; color: #8a93b5; }
QComboBox, QSpinBox { background: #2d313c; border: 1px solid #454b5a; border-radius: 6px; padding: 4px 8px; }
QSlider::groove:horizontal { height: 4px; background: #3a3f4b; border-radius: 2px; }
QSlider::handle:horizontal { background: #4c7dff; width: 14px; height: 14px; margin: -6px 0; border-radius: 7px; }
QSlider::sub-page:horizontal { background: #4c7dff; border-radius: 2px; }
QStatusBar { background: #1b1d23; }
QLabel#hint { color: #8a8f9c; font-size: 12px; }
QLabel#viewTitle { color: #aab1c3; font-weight: 600; padding: 2px 4px; }
QProgressBar { border: 1px solid #3a3f4b; border-radius: 4px; background: #2d313c; max-height: 12px; }
QProgressBar::chunk { background: #4c7dff; }
"""

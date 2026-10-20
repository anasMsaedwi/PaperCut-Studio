"""PaperCut Studio - entry point.   Usage:  python app.py [image-file]"""
from __future__ import annotations

import sys


def main() -> int:
    if sys.version_info < (3, 11):
        sys.exit(f"PaperCut Studio needs Python 3.11 or newer (found {sys.version.split()[0]}).")
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        sys.exit("PySide6 is not installed. Run:  python -m pip install -r requirements.txt")

    from pathlib import Path

    from PySide6.QtGui import QIcon

    from ui.main_window import MainWindow

    if sys.platform == "win32":          # own taskbar icon instead of the generic Python one
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("PaperCutStudio.App")
        except Exception:
            pass

    app = QApplication(sys.argv)
    app.setApplicationName("PaperCut Studio")
    icon_path = Path(__file__).resolve().parent / "assets" / "icon.png"
    if icon_path.is_file():
        app.setWindowIcon(QIcon(str(icon_path)))
    win = MainWindow()
    win.show()
    if len(sys.argv) > 1:
        win.load_path(sys.argv[1])
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())

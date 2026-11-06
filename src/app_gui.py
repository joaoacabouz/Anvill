"""Main entry point for Anvill GUI Application (PySide6)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure src/ and repo root are in sys.path
_SRC_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SRC_DIR.parent
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from gui.app import MainWindow
from gui.icons import get_svg_icon
from logger import setup_logging


def main() -> int:
    setup_logging()

    # High-DPI support
    os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"
    os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "1"

    app = QApplication(sys.argv)
    app.setApplicationName("Anvill")
    app.setOrganizationName("AnvillProject")
    app.setWindowIcon(get_svg_icon("anvill-logo.svg", "#00E5FF", "#00E5FF", 64))

    # Set default modern UI font
    font = QFont("Segoe UI", 10)
    font.setStyleHint(QFont.SansSerif)
    app.setFont(font)

    window = MainWindow()
    window.setWindowIcon(get_svg_icon("anvill-logo.svg", "#00E5FF", "#00E5FF", 64))
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())


"""Main application window for Anvill GUI integrating titlebar, splash, wizard and player."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtGui import QCursor, QMouseEvent
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QMainWindow,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from config import load_config
from constants import CONFIG_PATH, DEFAULT_AVD_NAME
from gui.player import PlayerView
from gui.settings_dialog import SettingsDialog
from gui.setup_wizard import SetupWizard
from gui.splash import SplashScreen
from gui.theme import ThemePalette, generate_qss, get_theme
from gui.titlebar import FramelessTitleBar


class MainWindow(QMainWindow):
    """Custom frameless main application window for Anvill Android VM."""

    BORDER_MARGIN = 8

    def __init__(self, initial_theme_id: str | None = None):
        super().__init__()
        self.cfg = load_config()
        self.avd_name = self.cfg.get("vm", {}).get("avd_name", DEFAULT_AVD_NAME)
        theme_id = initial_theme_id or self.cfg.get("vm", {}).get("theme", "cyber_cyan")
        self.current_palette: ThemePalette = get_theme(theme_id)

        # Frameless window configuration
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        self.resize(1080, 720)
        self.setMinimumSize(850, 580)

        self._setup_ui()
        self.apply_theme(self.current_palette)

    def _setup_ui(self) -> None:
        self.central_container = QWidget(self)
        self.central_container.setObjectName("CentralContainer")
        self.setCentralWidget(self.central_container)

        root_layout = QVBoxLayout(self.central_container)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # 1. Title bar
        self.title_bar = FramelessTitleBar(self, self.current_palette, self.avd_name)
        self.title_bar.theme_changed.connect(self._on_theme_changed)
        self.title_bar.settings_requested.connect(self._open_settings)
        root_layout.addWidget(self.title_bar)

        # 2. Stacked Content Area
        self.stack = QStackedWidget()

        # Page 0: Splash Screen
        self.splash_screen = SplashScreen(self, self.current_palette, self.avd_name)
        self.splash_screen.splash_finished.connect(self._on_splash_finished)
        self.stack.addWidget(self.splash_screen)

        # Page 1: Setup Wizard (First-time provisioning)
        self.setup_wizard = SetupWizard(self, self.current_palette, self.avd_name)
        self.setup_wizard.setup_completed.connect(self._on_setup_completed)
        self.stack.addWidget(self.setup_wizard)

        # Page 2: Emulator Player
        self.player_view = PlayerView(self, self.current_palette, self.avd_name)
        self.player_view.status_changed.connect(self.title_bar.set_status)
        self.stack.addWidget(self.player_view)

        root_layout.addWidget(self.stack, stretch=1)
        self.setMouseTracking(True)
        self.central_container.setMouseTracking(True)

    def apply_theme(self, palette: ThemePalette) -> None:
        """Applies theme palette and updates all child widgets."""
        self.current_palette = palette
        qss = generate_qss(palette)
        qapp = QApplication.instance()
        if qapp:
            qapp.setStyleSheet(qss)

        self.title_bar.update_palette(palette)
        self.splash_screen.update_palette(palette)
        self.setup_wizard.update_palette(palette)
        self.player_view.update_palette(palette)

        self.central_container.setStyleSheet(f"""
            QWidget#CentralContainer {{
                background-color: {palette.bg_main};
                border: 1px solid {palette.border_color};
            }}
        """)

    def _on_theme_changed(self, theme_id: str) -> None:
        palette = get_theme(theme_id)
        self.apply_theme(palette)

        # Persist theme selection in config.json
        try:
            self.cfg = load_config()
            self.cfg.setdefault("vm", {})["theme"] = theme_id
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(self.cfg, f, indent=2)
        except Exception:
            pass

    def _open_settings(self) -> None:
        dlg = SettingsDialog(self, self.current_palette)
        dlg.theme_selected.connect(self._on_theme_changed)
        if dlg.exec():
            # Refresh AVD name if changed
            self.cfg = load_config()
            new_name = self.cfg.get("vm", {}).get("avd_name", DEFAULT_AVD_NAME)
            if new_name != self.avd_name:
                self.avd_name = new_name
                self.title_bar.set_avd_name(new_name)
                self.player_view.avd_name = new_name

    def _on_splash_finished(self, setup_ready: bool) -> None:
        if setup_ready:
            # Setup already done -> go directly to Player
            self.stack.setCurrentIndex(2)
            self.title_bar.set_status("offline")
        else:
            # First run -> go to Setup Wizard
            self.stack.setCurrentIndex(1)
            self.title_bar.set_status("offline")

    def _on_setup_completed(self) -> None:
        self.stack.setCurrentIndex(2)
        self.title_bar.set_status("offline")

    # Native OS Edge Resizing for Frameless Window
    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton and not self.isMaximized():
            edge, corner = self._hit_test(event.pos())
            edges = Qt.Edges()
            if corner == "top-left":
                edges = Qt.TopEdge | Qt.LeftEdge
            elif corner == "top-right":
                edges = Qt.TopEdge | Qt.RightEdge
            elif corner == "bottom-left":
                edges = Qt.BottomEdge | Qt.LeftEdge
            elif corner == "bottom-right":
                edges = Qt.BottomEdge | Qt.RightEdge
            elif edge is not None:
                edges = edge

            if edges and self.windowHandle():
                self.windowHandle().startSystemResize(edges)
                event.accept()
                return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if not self.isMaximized():
            self._update_cursor_shape(event.pos())
        super().mouseMoveEvent(event)

    def _hit_test(self, pos: QPoint) -> tuple[Optional[Qt.Edge], Optional[str]]:
        x, y = pos.x(), pos.y()
        w, h = self.width(), self.height()
        m = self.BORDER_MARGIN

        on_left = x < m
        on_right = x > w - m
        on_top = y < m
        on_bottom = y > h - m

        if on_top and on_left:
            return None, "top-left"
        if on_top and on_right:
            return None, "top-right"
        if on_bottom and on_left:
            return None, "bottom-left"
        if on_bottom and on_right:
            return None, "bottom-right"

        if on_top:
            return Qt.TopEdge, None
        if on_bottom:
            return Qt.BottomEdge, None
        if on_left:
            return Qt.LeftEdge, None
        if on_right:
            return Qt.RightEdge, None

        return None, None

    def _update_cursor_shape(self, pos: QPoint) -> None:
        edge, corner = self._hit_test(pos)
        if corner in ("top-left", "bottom-right"):
            self.setCursor(Qt.SizeFDiagCursor)
        elif corner in ("top-right", "bottom-left"):
            self.setCursor(Qt.SizeBDiagCursor)
        elif edge in (Qt.TopEdge, Qt.BottomEdge):
            self.setCursor(Qt.SizeVerCursor)
        elif edge in (Qt.LeftEdge, Qt.RightEdge):
            self.setCursor(Qt.SizeHorCursor)
        else:
            self.setCursor(Qt.ArrowCursor)

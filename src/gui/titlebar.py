"""Custom frameless title bar for Anvill GUI."""

from __future__ import annotations

from typing import Callable, Optional
from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QColor, QFont, QMouseEvent
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QWidget,
)

from gui.theme import ThemePalette, list_themes


class FramelessTitleBar(QWidget):
    """Modern custom draggable titlebar with theme selector and window controls."""

    theme_changed = Signal(str)
    settings_requested = Signal()

    def __init__(
        self,
        parent: QWidget,
        palette: ThemePalette,
        avd_name: str = "Android16_Pro",
    ):
        super().__init__(parent)
        self.parent_window = parent
        self.palette = palette
        self.avd_name = avd_name
        self._drag_pos: Optional[QPoint] = None

        self.setFixedHeight(44)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._setup_ui()
        self.update_palette(palette)

    def _setup_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 0, 8, 0)
        layout.setSpacing(10)

        # 1. Branding (Icon + Title)
        self.logo_lbl = QLabel("⚡")
        logo_font = QFont()
        logo_font.setPointSize(14)
        logo_font.setBold(True)
        self.logo_lbl.setFont(logo_font)

        self.title_lbl = QLabel("ANVILL")
        title_font = QFont()
        title_font.setPointSize(11)
        title_font.setBold(True)
        self.title_lbl.setFont(title_font)

        # AVD Pill
        self.avd_badge = QLabel(f"{self.avd_name}")
        self.avd_badge.setProperty("class", "BadgePill")

        layout.addWidget(self.logo_lbl)
        layout.addWidget(self.title_lbl)
        layout.addWidget(self.avd_badge)

        layout.addStretch()

        # 2. Center Status Badge
        self.status_badge = QLabel("⚪ Offline")
        self.status_badge.setProperty("class", "StatusOffline")
        self.status_badge.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.status_badge)

        layout.addStretch()

        # 3. Theme Selector
        self.theme_combo = QComboBox()
        self.theme_combo.setToolTip("Switch Color Theme")
        for tid, tname, accent in list_themes():
            self.theme_combo.addItem(f"🎨 {tname}", tid)
        self.theme_combo.currentIndexChanged.connect(self._on_theme_changed)
        layout.addWidget(self.theme_combo)

        # 4. Settings Button
        self.settings_btn = QPushButton("⚙")
        self.settings_btn.setToolTip("VM Settings & Hardware Profiles")
        self.settings_btn.setFixedSize(32, 32)
        self.settings_btn.clicked.connect(self.settings_requested.emit)
        layout.addWidget(self.settings_btn)

        # 5. Window Control Buttons
        self.min_btn = QPushButton("—")
        self.min_btn.setToolTip("Minimize")
        self.min_btn.setFixedSize(32, 32)
        self.min_btn.clicked.connect(self.parent_window.showMinimized)

        self.max_btn = QPushButton("🗖")
        self.max_btn.setToolTip("Maximize / Restore")
        self.max_btn.setFixedSize(32, 32)
        self.max_btn.clicked.connect(self._toggle_maximize)

        self.close_btn = QPushButton("✕")
        self.close_btn.setToolTip("Close")
        self.close_btn.setFixedSize(32, 32)
        self.close_btn.clicked.connect(self.parent_window.close)

        layout.addWidget(self.min_btn)
        layout.addWidget(self.max_btn)
        layout.addWidget(self.close_btn)

    def _toggle_maximize(self) -> None:
        if self.parent_window.isMaximized():
            self.parent_window.showNormal()
            self.max_btn.setText("🗖")
        else:
            self.parent_window.showMaximized()
            self.max_btn.setText("🗗")

    def _on_theme_changed(self, index: int) -> None:
        theme_id = self.theme_combo.itemData(index)
        if theme_id:
            self.theme_changed.emit(theme_id)

    def set_status(self, state: str) -> None:
        """Updates the status pill ('offline', 'booting', 'running')."""
        if state == "running":
            self.status_badge.setText("🟢 Running")
            self.status_badge.setProperty("class", "StatusRunning")
        elif state == "booting":
            self.status_badge.setText("🟡 Booting...")
            self.status_badge.setProperty("class", "StatusBooting")
        else:
            self.status_badge.setText("⚪ Offline")
            self.status_badge.setProperty("class", "StatusOffline")
        self.status_badge.style().unpolish(self.status_badge)
        self.status_badge.style().polish(self.status_badge)

    def set_avd_name(self, name: str) -> None:
        self.avd_name = name
        self.avd_badge.setText(name)

    def update_palette(self, palette: ThemePalette) -> None:
        """Applies theme colors to title bar elements."""
        self.palette = palette
        self.setStyleSheet(f"""
            QWidget {{
                background-color: {palette.bg_surface};
                border-bottom: 1px solid {palette.border_color};
            }}
            QLabel {{
                border-bottom: none;
            }}
            QPushButton {{
                background-color: transparent;
                border: none;
                border-radius: 6px;
                color: {palette.text_secondary};
                font-size: 13px;
                font-weight: 700;
            }}
            QPushButton:hover {{
                background-color: {palette.accent_dim};
                color: {palette.accent};
            }}
            QPushButton#close_btn:hover {{
                background-color: {palette.danger};
                color: #FFFFFF;
            }}
        """)
        self.close_btn.setObjectName("close_btn")
        self.logo_lbl.setStyleSheet(f"color: {palette.accent}; border: none;")
        self.title_lbl.setStyleSheet(f"color: {palette.text_primary}; border: none;")

        # Sync combo selection
        idx = self.theme_combo.findData(palette.id)
        if idx >= 0 and self.theme_combo.currentIndex() != idx:
            self.theme_combo.blockSignals(True)
            self.theme_combo.setCurrentIndex(idx)
            self.theme_combo.blockSignals(False)

    # Mouse drag window handlers
    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.parent_window.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if event.buttons() == Qt.LeftButton and self._drag_pos is not None:
            if self.parent_window.isMaximized():
                self.parent_window.showNormal()
                self.max_btn.setText("🗖")
            self.parent_window.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            self._toggle_maximize()
            event.accept()

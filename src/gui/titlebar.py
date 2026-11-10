"""Modern custom frameless title bar for Anvill GUI with pinned window controls and native Windows dragging."""

from __future__ import annotations

from typing import Optional
from PySide6.QtCore import QPoint, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QMouseEvent
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QWidget,
)

from constants import DEFAULT_AVD_NAME
from gui.icons import get_svg_icon, get_svg_pixmap
from gui.theme import ThemePalette, list_themes


class FramelessTitleBar(QWidget):
    """Modern custom draggable titlebar with guaranteed top-right window controls."""

    theme_changed = Signal(str)
    settings_requested = Signal()

    def __init__(
        self,
        parent: QWidget,
        palette: ThemePalette,
        avd_name: str = DEFAULT_AVD_NAME,
    ):
        super().__init__(parent)
        self.parent_window = parent
        self.palette = palette
        self.avd_name = avd_name

        self.setObjectName("TitleBarWidget")
        self.setFixedHeight(38)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._setup_ui()
        self.update_palette(palette)

    def _setup_ui(self) -> None:
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(12, 0, 0, 0)
        main_layout.setSpacing(8)

        # 1. Left Branding Section
        self.logo_lbl = QLabel()
        self.logo_lbl.setFixedSize(20, 20)
        self.logo_lbl.setScaledContents(True)
        self.logo_lbl.setPixmap(get_svg_pixmap("anvill-logo.svg", self.palette.accent, 20))

        self.title_lbl = QLabel("ANVILL")
        title_font = QFont("Segoe UI", 10, QFont.Bold)
        self.title_lbl.setFont(title_font)

        self.avd_badge = QLabel(f"{self.avd_name}")
        self.avd_badge.setProperty("class", "BadgePill")
        self.avd_badge.setFixedHeight(22)

        # Status Pill Indicator
        self.status_badge = QLabel("● Offline")
        self.status_badge.setProperty("class", "StatusOffline")
        self.status_badge.setAlignment(Qt.AlignCenter)
        self.status_badge.setFixedHeight(22)

        main_layout.addWidget(self.logo_lbl)
        main_layout.addWidget(self.title_lbl)
        main_layout.addWidget(self.avd_badge)
        main_layout.addSpacing(6)
        main_layout.addWidget(self.status_badge)

        # 2. Draggable Center Spacer (Occupies remaining horizontal room)
        main_layout.addStretch(1)

        # 3. Right Utility & Window Controls (Strictly pinned to top-right corner)
        right_container = QWidget()
        right_container.setObjectName("TitleBarRightContainer")
        right_layout = QHBoxLayout(right_container)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(2)

        # Theme Selector Dropdown
        self.theme_combo = QComboBox()
        self.theme_combo.setToolTip("Switch Color Theme")
        self.theme_combo.setFixedWidth(190)
        self.theme_combo.setFixedHeight(28)
        self.theme_combo.setIconSize(QSize(14, 14))
        for tid, tname, accent in list_themes():
            self.theme_combo.addItem(get_svg_icon("theme-svgrepo-com.svg", accent, accent, 14), f" {tname}", tid)
        self.theme_combo.currentIndexChanged.connect(self._on_theme_changed)
        right_layout.addWidget(self.theme_combo)

        # Settings Button with clean vector dots icon
        self.settings_btn = QPushButton()
        self.settings_btn.setObjectName("TitleBarSettingsBtn")
        self.settings_btn.setToolTip("Settings & Profiles")
        self.settings_btn.setFixedSize(30, 32)
        self.settings_btn.setIconSize(QSize(16, 16))
        self.settings_btn.setIcon(get_svg_icon("dots-vertical-svgrepo-com.svg", self.palette.text_secondary, self.palette.accent, 16))
        self.settings_btn.clicked.connect(self.settings_requested.emit)
        right_layout.addWidget(self.settings_btn)

        right_layout.addSpacing(4)

        # Windows Native-Style Control Buttons (—, 🗖, ✕)
        self.min_btn = QPushButton("—")
        self.min_btn.setObjectName("TitleBarMinBtn")
        self.min_btn.setToolTip("Minimize")
        self.min_btn.setFixedSize(38, 38)
        self.min_btn.clicked.connect(self.parent_window.showMinimized)

        self.max_btn = QPushButton("🗖")
        self.max_btn.setObjectName("TitleBarMaxBtn")
        self.max_btn.setToolTip("Maximize / Restore")
        self.max_btn.setFixedSize(38, 38)
        self.max_btn.clicked.connect(self._toggle_maximize)

        self.close_btn = QPushButton("✕")
        self.close_btn.setObjectName("TitleBarCloseBtn")
        self.close_btn.setToolTip("Close")
        self.close_btn.setFixedSize(44, 38)
        self.close_btn.clicked.connect(self.parent_window.close)

        right_layout.addWidget(self.min_btn)
        right_layout.addWidget(self.max_btn)
        right_layout.addWidget(self.close_btn)

        main_layout.addWidget(right_container)

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
        """Updates the status indicator ('offline', 'booting', 'running')."""
        if state == "running":
            self.status_badge.setText("● Running")
            self.status_badge.setProperty("class", "StatusRunning")
        elif state == "booting":
            self.status_badge.setText("● Booting...")
            self.status_badge.setProperty("class", "StatusBooting")
        else:
            self.status_badge.setText("● Offline")
            self.status_badge.setProperty("class", "StatusOffline")
        self.status_badge.style().unpolish(self.status_badge)
        self.status_badge.style().polish(self.status_badge)

    def set_avd_name(self, name: str) -> None:
        self.avd_name = name
        self.avd_badge.setText(name)

    def update_palette(self, palette: ThemePalette) -> None:
        """Applies theme colors without affecting global child widgets."""
        self.palette = palette
        self.setStyleSheet(f"""
            QWidget#TitleBarWidget {{
                background-color: {palette.bg_surface};
                border-bottom: 1px solid {palette.border_color};
            }}
            QPushButton#TitleBarSettingsBtn {{
                background-color: transparent;
                border: none;
                border-radius: 4px;
                color: {palette.text_secondary};
                font-size: 14px;
            }}
            QPushButton#TitleBarSettingsBtn:hover {{
                background-color: {palette.accent_dim};
                color: {palette.accent};
            }}
            QPushButton#TitleBarMinBtn, QPushButton#TitleBarMaxBtn {{
                background-color: transparent;
                border: none;
                color: {palette.text_secondary};
                font-size: 13px;
                font-weight: 600;
            }}
            QPushButton#TitleBarMinBtn:hover, QPushButton#TitleBarMaxBtn:hover {{
                background-color: rgba(255, 255, 255, 0.08);
                color: #FFFFFF;
            }}
            QPushButton#TitleBarCloseBtn {{
                background-color: transparent;
                border: none;
                color: {palette.text_secondary};
                font-size: 13px;
                font-weight: 600;
            }}
            QPushButton#TitleBarCloseBtn:hover {{
                background-color: #E81123;
                color: #FFFFFF;
            }}
        """)
        self.logo_lbl.setPixmap(get_svg_pixmap("anvill-logo.svg", palette.accent, 20))
        self.settings_btn.setIcon(get_svg_icon("dots-vertical-svgrepo-com.svg", palette.text_secondary, palette.accent, 16))
        self.logo_lbl.setStyleSheet(f"border: none;")
        self.title_lbl.setStyleSheet(f"color: {palette.text_primary}; border: none;")

        # Sync combo selection
        idx = self.theme_combo.findData(palette.id)
        if idx >= 0 and self.theme_combo.currentIndex() != idx:
            self.theme_combo.blockSignals(True)
            self.theme_combo.setCurrentIndex(idx)
            self.theme_combo.blockSignals(False)

    # Native Window Dragging & Maximizing
    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            win = self.window().windowHandle()
            if win:
                win.startSystemMove()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            self._toggle_maximize()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

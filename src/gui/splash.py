"""Modern loading / splash screen for Anvill GUI."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional
from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from constants import AVD_ROOT, DEFAULT_AVD_NAME, SDK_ROOT
from gui.icons import get_svg_pixmap
from gui.theme import ThemePalette


def is_setup_completed(
    sdk_root: Path = SDK_ROOT,
    avd_root: Path = AVD_ROOT,
    avd_name: str = DEFAULT_AVD_NAME,
) -> bool:
    """Verifies whether the portable SDK, tools and target AVD are already provisioned."""
    emu_bin = sdk_root / "emulator" / "emulator.exe"
    adb_bin = sdk_root / "platform-tools" / "adb.exe"
    avd_ini = avd_root / f"{avd_name}.ini"
    avd_cfg = avd_root / f"{avd_name}.avd" / "config.ini"

    return emu_bin.exists() and adb_bin.exists() and avd_ini.exists() and avd_cfg.exists()


class SplashScreen(QWidget):
    """Animated loading screen displayed when the application starts."""

    # Signal emits True if setup is already complete, False if first-run setup is required
    splash_finished = Signal(bool)

    def __init__(
        self,
        parent: QWidget,
        palette: ThemePalette,
        avd_name: str = DEFAULT_AVD_NAME,
        player_view: Optional[Any] = None,
    ):
        super().__init__(parent)
        self.palette = palette
        self.avd_name = avd_name
        self.player_view = player_view
        self._progress_val = 0
        self._boot_started = False

        self._setup_ui()
        self.update_palette(palette)
        self._start_timer()

    def _setup_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setAlignment(Qt.AlignCenter)
        main_layout.setContentsMargins(40, 40, 40, 40)
        main_layout.setSpacing(20)

        # Center Container Card
        card = QWidget()
        card.setProperty("class", "SurfaceCard")
        card.setFixedSize(540, 360)
        card_layout = QVBoxLayout(card)
        card_layout.setAlignment(Qt.AlignCenter)
        card_layout.setContentsMargins(30, 30, 30, 30)
        card_layout.setSpacing(16)

        # Glowing Icon (High-resolution Anvill Logo)
        self.icon_lbl = QLabel()
        self.icon_lbl.setFixedSize(68, 68)
        self.icon_lbl.setAlignment(Qt.AlignCenter)
        self.icon_lbl.setPixmap(get_svg_pixmap("anvill-logo.svg", self.palette.accent, 68))

        # Title
        self.title_lbl = QLabel("ANVILL")
        title_font = QFont()
        title_font.setPointSize(28)
        title_font.setBold(True)
        self.title_lbl.setFont(title_font)
        self.title_lbl.setAlignment(Qt.AlignCenter)

        # Subtitle
        self.sub_lbl = QLabel("Android Virtual Machine & Emulator Player")
        sub_font = QFont()
        sub_font.setPointSize(12)
        self.sub_lbl.setFont(sub_font)
        self.sub_lbl.setAlignment(Qt.AlignCenter)

        # Status description
        self.status_lbl = QLabel("Verifying environment and host acceleration...")
        status_font = QFont()
        status_font.setPointSize(11)
        self.status_lbl.setFont(status_font)
        self.status_lbl.setAlignment(Qt.AlignCenter)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(8)

        card_layout.addWidget(self.icon_lbl)
        card_layout.addWidget(self.title_lbl)
        card_layout.addWidget(self.sub_lbl)
        card_layout.addSpacing(10)
        card_layout.addWidget(self.status_lbl)
        card_layout.addWidget(self.progress_bar)

        main_layout.addWidget(card)

    def update_palette(self, palette: ThemePalette) -> None:
        self.palette = palette
        self.icon_lbl.setPixmap(get_svg_pixmap("anvill-logo.svg", palette.accent, 68))
        self.title_lbl.setStyleSheet(f"color: {palette.text_primary};")
        self.sub_lbl.setStyleSheet(f"color: {palette.text_secondary};")
        self.status_lbl.setStyleSheet(f"color: {palette.text_accent}; font-weight: 500;")

    def _start_timer(self) -> None:
        self._timer = QTimer(self)
        self._timer.setInterval(25)
        self._timer.timeout.connect(self._step)
        self._timer.start()

    def _step(self) -> None:
        ready = is_setup_completed(avd_name=self.avd_name)

        if not ready:
            # First-time setup is required -> advance to 100% and transition to Setup Wizard
            self._progress_val += 4
            self.progress_bar.setValue(min(100, self._progress_val))
            if self._progress_val >= 100:
                self._timer.stop()
                self.status_lbl.setText("First run detected. Preparing Setup Wizard...")
                QTimer.singleShot(350, lambda: self.splash_finished.emit(False))
            return

        # Setup is already complete -> advance progress and transition to Player Dashboard
        self._progress_val += 5
        self.progress_bar.setValue(min(100, self._progress_val))
        if self._progress_val >= 100:
            self._timer.stop()
            self.status_lbl.setText("✓ Ready! Loading Player Dashboard...")
            QTimer.singleShot(250, lambda: self.splash_finished.emit(True))

    def _on_boot_status(self, text: str) -> None:
        """Dynamically increments the progress bar according to real boot milestones."""
        self.status_lbl.setText(text)
        low = text.lower()
        if "hardware" in low or "resolving" in low:
            self._progress_val = max(self._progress_val, 25)
        elif "tablet" in low or "configuring" in low:
            self._progress_val = max(self._progress_val, 40)
        elif "launching" in low or "qemu" in low:
            self._progress_val = max(self._progress_val, 55)
        elif "connection" in low or "adb" in low:
            self._progress_val = max(self._progress_val, 72)
        elif "boot" in low or "waiting" in low:
            self._progress_val = max(self._progress_val, 86)
        elif "anti-detection" in low or "spoofing" in low or "docking" in low:
            self._progress_val = max(self._progress_val, 95)
        elif "ready" in low or "running" in low:
            self._progress_val = 100
        self.progress_bar.setValue(self._progress_val)

    def _on_boot_finished(self, success: bool, err_msg: str) -> None:
        if self._timer and self._timer.isActive():
            self._timer.stop()
        if success:
            self.progress_bar.setValue(100)
            self.status_lbl.setText("✓ Android Tablet ready and running!")
            QTimer.singleShot(300, lambda: self.splash_finished.emit(True))
        else:
            self.status_lbl.setText(f"Boot error: {err_msg}")
            QTimer.singleShot(500, lambda: self.splash_finished.emit(True))


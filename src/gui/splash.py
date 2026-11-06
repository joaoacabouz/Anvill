"""Modern loading / splash screen for Anvill GUI."""

from __future__ import annotations

from pathlib import Path
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

    def __init__(self, parent: QWidget, palette: ThemePalette, avd_name: str = DEFAULT_AVD_NAME):
        super().__init__(parent)
        self.palette = palette
        self.avd_name = avd_name
        self._progress_val = 0

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

        # Glowing Icon
        self.icon_lbl = QLabel("⚡")
        icon_font = QFont()
        icon_font.setPointSize(48)
        icon_font.setBold(True)
        self.icon_lbl.setFont(icon_font)
        self.icon_lbl.setAlignment(Qt.AlignCenter)

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
        self.icon_lbl.setStyleSheet(f"color: {palette.accent};")
        self.title_lbl.setStyleSheet(f"color: {palette.text_primary};")
        self.sub_lbl.setStyleSheet(f"color: {palette.text_secondary};")
        self.status_lbl.setStyleSheet(f"color: {palette.text_accent}; font-weight: 500;")

    def _start_timer(self) -> None:
        self._timer = QTimer(self)
        self._timer.setInterval(25)
        self._timer.timeout.connect(self._step)
        self._timer.start()

    def _step(self) -> None:
        self._progress_val += 2
        self.progress_bar.setValue(min(100, self._progress_val))

        if self._progress_val == 30:
            self.status_lbl.setText("Checking WHPX / hardware virtualization...")
        elif self._progress_val == 60:
            self.status_lbl.setText("Scanning local SDK & AVD profiles...")
        elif self._progress_val >= 100:
            self._timer.stop()
            ready = is_setup_completed(avd_name=self.avd_name)
            if ready:
                self.status_lbl.setText("✓ Ready! Loading Player...")
            else:
                self.status_lbl.setText("First run detected. Preparing Setup Wizard...")
            QTimer.singleShot(400, lambda: self.splash_finished.emit(ready))

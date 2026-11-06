"""First-time setup wizard with real-time progress and background QThread worker."""

from __future__ import annotations

from pathlib import Path
from typing import List, Tuple
from PySide6.QtCore import QObject, QThread, Qt, Signal
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from constants import AVD_ROOT, DEFAULT_AVD_NAME, JDK_ROOT, SDK_ROOT, USER_HOME
from gui.theme import ThemePalette
from provisioner import bootstrap


class SetupWorker(QThread):
    """Executes the automated bootstrap, AVD creation, and first-boot root on a background thread."""

    progress_signal = Signal(int, str)
    log_signal = Signal(str)
    finished_signal = Signal(bool, str)

    def __init__(
        self,
        sdk_root: Path = SDK_ROOT,
        avd_root: Path = AVD_ROOT,
        user_home: Path = USER_HOME,
        avd_name: str = DEFAULT_AVD_NAME,
        jdk_root: Path = JDK_ROOT,
    ):
        super().__init__()
        self.sdk_root = sdk_root
        self.avd_root = avd_root
        self.user_home = user_home
        self.avd_name = avd_name
        self.jdk_root = jdk_root

    def run(self) -> None:
        try:
            self.progress_signal.emit(10, "Verifying hardware acceleration and environment...")
            self.log_signal.emit("[SETUP] Starting Portable Android SDK Bootstrap...")

            # Run full automated bootstrap
            self.progress_signal.emit(30, "Checking portable OpenJDK 17 and SDK tools...")
            res = bootstrap(
                sdk_root=self.sdk_root,
                avd_root=self.avd_root,
                user_home=self.user_home,
                avd_name=self.avd_name,
                jdk_root=self.jdk_root,
                auto_root=True,
            )
            self.progress_signal.emit(100, "Setup, Magisk Root and Hardening completed successfully!")
            self.log_signal.emit(f"[SETUP] Complete! Virtual device ready: {res.avd_name}")
            self.finished_signal.emit(True, "")
        except Exception as exc:
            self.log_signal.emit(f"[ERROR] Setup failed: {exc}")
            self.finished_signal.emit(False, str(exc))


class SetupWizard(QWidget):
    """Visual setup wizard displayed on first run."""

    setup_completed = Signal()

    def __init__(
        self,
        parent: QWidget,
        palette: ThemePalette,
        avd_name: str = DEFAULT_AVD_NAME,
    ):
        super().__init__(parent)
        self.palette = palette
        self.avd_name = avd_name
        self.worker: SetupWorker | None = None

        self._setup_ui()
        self.update_palette(palette)

    def _setup_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(40, 30, 40, 30)
        main_layout.setSpacing(20)

        # Header Card
        header_card = QWidget()
        header_card.setProperty("class", "SurfaceCard")
        h_layout = QVBoxLayout(header_card)
        h_layout.setContentsMargins(24, 20, 24, 20)
        h_layout.setSpacing(8)

        self.title_lbl = QLabel("First-Time Setup & Device Provisioning")
        title_font = QFont()
        title_font.setPointSize(18)
        title_font.setBold(True)
        self.title_lbl.setFont(title_font)

        self.desc_lbl = QLabel(
            "Anvill will download the portable Android SDK, create your virtual device, "
            "and automatically apply Magisk root, debloat non-essentials and real-device anti-detection hardening."
        )
        self.desc_lbl.setWordWrap(True)

        h_layout.addWidget(self.title_lbl)
        h_layout.addWidget(self.desc_lbl)
        main_layout.addWidget(header_card)

        # Steps Overview Card
        steps_card = QWidget()
        steps_card.setProperty("class", "ElevatedCard")
        s_layout = QVBoxLayout(steps_card)
        s_layout.setContentsMargins(20, 16, 20, 16)
        s_layout.setSpacing(10)

        steps_title = QLabel("Automated Setup Pipeline:")
        steps_title.setStyleSheet("font-weight: 700; font-size: 13px;")
        s_layout.addWidget(steps_title)

        self.step_labels: List[QLabel] = []
        steps_text = [
            "1. Hardware Acceleration (WHPX / Hypervisor check)",
            "2. Portable OpenJDK 17 Runtime",
            "3. Android Command-line Tools & Licenses",
            "4. Android System Image & Emulator Engine",
            "5. Portable AVD Creation with Sensor Emulation",
            "6. First-Boot Automated Root, Debloat & Hardening",
        ]
        for st in steps_text:
            lbl = QLabel(f"⚪  {st}")
            lbl.setStyleSheet("font-size: 12px; color: #8B949E;")
            self.step_labels.append(lbl)
            s_layout.addWidget(lbl)

        main_layout.addWidget(steps_card)

        # Progress Section
        prog_card = QWidget()
        prog_card.setProperty("class", "SurfaceCard")
        p_layout = QVBoxLayout(prog_card)
        p_layout.setContentsMargins(20, 16, 20, 16)
        p_layout.setSpacing(10)

        self.status_lbl = QLabel("Ready to initialize setup.")
        self.status_lbl.setStyleSheet("font-weight: 600; font-size: 13px;")

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(12)

        # Console Log Box
        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setFixedHeight(140)
        self.log_box.setFont(QFont("Consolas", 10))
        self.log_box.setStyleSheet("background-color: #0A0D14; border: 1px solid #1E2B3D; border-radius: 8px;")

        p_layout.addWidget(self.status_lbl)
        p_layout.addWidget(self.progress_bar)
        p_layout.addWidget(self.log_box)
        main_layout.addWidget(prog_card)

        # Bottom Actions Bar
        actions_bar = QHBoxLayout()
        actions_bar.setSpacing(12)

        self.start_btn = QPushButton("🚀 Start Full Setup")
        self.start_btn.setProperty("class", "PrimaryButton")
        self.start_btn.setMinimumHeight(42)
        self.start_btn.clicked.connect(self._start_setup)

        self.continue_btn = QPushButton("Proceed to Android Player ▶")
        self.continue_btn.setProperty("class", "PrimaryButton")
        self.continue_btn.setMinimumHeight(42)
        self.continue_btn.setVisible(False)
        self.continue_btn.clicked.connect(self.setup_completed.emit)

        actions_bar.addStretch()
        actions_bar.addWidget(self.start_btn)
        actions_bar.addWidget(self.continue_btn)
        main_layout.addLayout(actions_bar)

    def update_palette(self, palette: ThemePalette) -> None:
        self.palette = palette
        self.title_lbl.setStyleSheet(f"color: {palette.accent}; font-weight: 700;")
        self.desc_lbl.setStyleSheet(f"color: {palette.text_secondary};")
        self.status_lbl.setStyleSheet(f"color: {palette.text_accent};")

    def _start_setup(self) -> None:
        self.start_btn.setEnabled(False)
        self.start_btn.setText("Setting up...")
        self.status_lbl.setText("Running automated setup pipeline...")

        self.worker = SetupWorker(avd_name=self.avd_name)
        self.worker.progress_signal.connect(self._on_progress)
        self.worker.log_signal.connect(self._append_log)
        self.worker.finished_signal.connect(self._on_finished)
        self.worker.start()

    def _on_progress(self, percent: int, msg: str) -> None:
        self.progress_bar.setValue(percent)
        self.status_lbl.setText(msg)

        # Highlight step labels based on progress
        step_thresholds = [10, 25, 45, 65, 85, 100]
        for i, thresh in enumerate(step_thresholds):
            if percent >= thresh:
                self.step_labels[i].setText(f"🟢  {self.step_labels[i].text()[4:]}")
                self.step_labels[i].setStyleSheet(f"font-size: 12px; color: {self.palette.success}; font-weight: 600;")
            elif percent >= (thresh - 15):
                self.step_labels[i].setText(f"🟡  {self.step_labels[i].text()[4:]}")
                self.step_labels[i].setStyleSheet(f"font-size: 12px; color: {self.palette.warning}; font-weight: 600;")

    def _append_log(self, text: str) -> None:
        self.log_box.append(text)
        self.log_box.moveCursor(QTextCursor.End)

    def _on_finished(self, success: bool, err_msg: str) -> None:
        if success:
            self.status_lbl.setText("✓ Setup Completed! Your Android device is ready.")
            self.status_lbl.setStyleSheet(f"color: {self.palette.success}; font-weight: 700;")
            self.start_btn.setVisible(False)
            self.continue_btn.setVisible(True)
        else:
            self.status_lbl.setText(f"Setup encountered an issue: {err_msg}")
            self.status_lbl.setStyleSheet(f"color: {self.palette.danger}; font-weight: 700;")
            self.start_btn.setEnabled(True)
            self.start_btn.setText("Retry Setup")

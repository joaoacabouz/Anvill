"""Android Emulator Player widget with window embedding and side toolbar controls."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
import platform
import subprocess
import time
from pathlib import Path
from typing import List, Optional, Tuple

from PySide6.QtCore import QPoint, QSize, QThread, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QDragEnterEvent, QDropEvent, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from adb import AdbManager
from config import load_config
from constants import AVD_ROOT, DEFAULT_AVD_NAME, REPO_ROOT, SDK_ROOT
from gui.theme import ThemePalette
from inspector import HostInspector
from launcher import EmulatorLauncher, LaunchFlags, pick_gpu_mode
from profiles import get_hardware_profile, get_spoof_profile, load_profiles


# Win32 user32 imports for window embedding
if platform.system() == "Windows":
    user32 = ctypes.windll.user32
    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
else:
    user32 = None


def find_emulator_window(avd_name: str) -> Optional[int]:
    """Finds the HWND of the running Android Emulator on Windows."""
    if not user32:
        return None

    matches: List[Tuple[int, str]] = []

    def enum_windows_callback(hwnd: int, lparam: int) -> bool:
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                title = buf.value
                # Match "Android Emulator" or avd_name or "qemu"
                if ("android emulator" in title.lower()) or (avd_name.lower() in title.lower()):
                    matches.append((hwnd, title))
        return True

    cb = WNDENUMPROC(enum_windows_callback)
    user32.EnumWindows(cb, 0)

    if matches:
        return matches[0][0]
    return None


class EmulatorBootWorker(QThread):
    """Starts the emulator process and awaits boot completion in background."""

    status_signal = Signal(str)
    booted_signal = Signal(bool, str)

    def __init__(
        self,
        avd_name: str,
        hw_profile: str,
        spoof_profile: str,
        cold_boot: bool = False,
        safe_gpu: bool = False,
    ):
        super().__init__()
        self.avd_name = avd_name
        self.hw_profile = hw_profile
        self.spoof_profile = spoof_profile
        self.cold_boot = cold_boot
        self.safe_gpu = safe_gpu
        self.adb = AdbManager()
        self.launcher: Optional[EmulatorLauncher] = None
        self.proc: Optional[subprocess.Popen] = None

    def run(self) -> None:
        try:
            self.status_signal.emit("Resolving hardware & spoofing profiles...")
            profiles_data = load_profiles()
            inspector = HostInspector.detect()
            profile = get_hardware_profile(profiles_data, self.hw_profile, inspector=inspector)
            gpu_mode = pick_gpu_mode(inspector, safe_gpu=self.safe_gpu)
            spoof = get_spoof_profile(profiles_data, self.spoof_profile)

            cfg = load_config()
            avd_cfg = AVD_ROOT / f"{self.avd_name}.avd" / "config.ini"

            flags = LaunchFlags(
                profile=profile,
                gpu_mode=gpu_mode,
                avd_name=self.avd_name,
                scrcpy=False,
                safe_gpu=self.safe_gpu,
                cold_boot=self.cold_boot,
            )

            emu_bin = SDK_ROOT / "emulator" / ("emulator.exe" if platform.system() == "Windows" else "emulator")
            from provisioner import get_portable_env
            env = get_portable_env(SDK_ROOT)

            self.launcher = EmulatorLauncher(emu_bin, flags, self.adb, env)
            self.status_signal.emit("Launching QEMU Emulator Engine...")
            self.proc = self.launcher.launch()

            self.status_signal.emit("Waiting for device connection (ADB)...")
            if not self.adb.wait_for_device(timeout=90):
                self.booted_signal.emit(False, "Device connection timed out.")
                return

            self.status_signal.emit("Waiting for Android to complete boot...")
            if not self.adb.wait_for_boot_completed(timeout=120):
                self.booted_signal.emit(False, "Android boot timed out.")
                return

            self.status_signal.emit("Injecting device spoofing & anti-detection...")
            self.adb.apply_spoof(spoof)

            self.status_signal.emit("✓ Emulator running and ready!")
            self.booted_signal.emit(True, "")
        except Exception as exc:
            self.booted_signal.emit(False, str(exc))


class PlayerView(QWidget):
    """Main Android Player container with embedded emulator viewport and side control bar."""

    status_changed = Signal(str)

    def __init__(
        self,
        parent: QWidget,
        palette: ThemePalette,
        avd_name: str = DEFAULT_AVD_NAME,
    ):
        super().__init__(parent)
        self.palette = palette
        self.avd_name = avd_name
        self.adb = AdbManager()
        self.boot_worker: Optional[EmulatorBootWorker] = None
        self.embedded_hwnd: Optional[int] = None
        self._embed_timer: Optional[QTimer] = None

        self.setAcceptDrops(True)
        self._setup_ui()
        self.update_palette(palette)

    def _setup_ui(self) -> None:
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(12)

        # 1. Central Viewport Area (Stacked: Dashboard -> Booting -> Embedded Container)
        self.stack = QStackedWidget()

        # Page 0: Idle Dashboard
        self.dashboard_page = self._create_dashboard_page()
        self.stack.addWidget(self.dashboard_page)

        # Page 1: Booting Page
        self.booting_page = self._create_booting_page()
        self.stack.addWidget(self.booting_page)

        # Page 2: Active Player Container
        self.player_page = self._create_player_container_page()
        self.stack.addWidget(self.player_page)

        main_layout.addWidget(self.stack, stretch=1)

        # 2. Side Toolbar Controls (Like Emulator Side Bar)
        self.toolbar = self._create_side_toolbar()
        main_layout.addWidget(self.toolbar)

    def _create_dashboard_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(16)

        card = QWidget()
        card.setProperty("class", "SurfaceCard")
        card.setFixedSize(620, 440)
        c_layout = QVBoxLayout(card)
        c_layout.setContentsMargins(36, 30, 36, 30)
        c_layout.setSpacing(14)

        # Icon & Title
        title_box = QHBoxLayout()
        icon = QLabel("📱")
        icon.setFont(QFont("Segoe UI Emoji", 32))
        title = QLabel(f"Android Virtual Machine")
        title.setFont(QFont("Segoe UI", 18, QFont.Bold))
        title_box.addWidget(icon)
        title_box.addWidget(title)
        title_box.addStretch()
        c_layout.addLayout(title_box)

        desc = QLabel("Ready to start emulator session with real-device hardware emulation.")
        desc.setStyleSheet("color: #8B949E; font-size: 13px;")
        c_layout.addWidget(desc)

        c_layout.addSpacing(10)

        # Options Box
        opts_box = QVBoxLayout()
        opts_box.setSpacing(8)

        # Hardware Profile Row
        row1 = QHBoxLayout()
        row1_lbl = QLabel("Hardware Profile:")
        row1_lbl.setStyleSheet("font-weight: 600;")
        self.hw_combo = QComboBox()
        self.hw_combo.addItems(["auto", "ultra", "high", "balanced", "low"])
        self.hw_combo.setCurrentText("auto")
        row1.addWidget(row1_lbl)
        row1.addWidget(self.hw_combo, stretch=1)
        opts_box.addLayout(row1)

        # Spoofing Profile Row
        row2 = QHBoxLayout()
        row2_lbl = QLabel("Device Spoofing:")
        row2_lbl.setStyleSheet("font-weight: 600;")
        self.spoof_combo = QComboBox()
        self.spoof_combo.addItems(["s23_ultra", "rog_phone_7", "stock"])
        self.spoof_combo.setCurrentText("s23_ultra")
        row2.addWidget(row2_lbl)
        row2.addWidget(self.spoof_combo, stretch=1)
        opts_box.addLayout(row2)

        c_layout.addLayout(opts_box)
        c_layout.addSpacing(16)

        # Big Launch Button
        self.launch_btn = QPushButton("▶ Launch Android Emulator")
        self.launch_btn.setProperty("class", "PrimaryButton")
        self.launch_btn.setMinimumHeight(48)
        self.launch_btn.clicked.connect(self._start_emulator)
        c_layout.addWidget(self.launch_btn)

        layout.addWidget(card)
        return page

    def _create_booting_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(16)

        card = QWidget()
        card.setProperty("class", "SurfaceCard")
        card.setFixedSize(500, 280)
        c_layout = QVBoxLayout(card)
        c_layout.setAlignment(Qt.AlignCenter)
        c_layout.setContentsMargins(30, 30, 30, 30)
        c_layout.setSpacing(12)

        spinner_lbl = QLabel("⚡")
        spinner_lbl.setFont(QFont("Segoe UI Emoji", 36))
        spinner_lbl.setAlignment(Qt.AlignCenter)

        boot_title = QLabel("Booting Android Emulator...")
        boot_title.setFont(QFont("Segoe UI", 16, QFont.Bold))
        boot_title.setAlignment(Qt.AlignCenter)

        self.boot_status_lbl = QLabel("Starting QEMU virtualization...")
        self.boot_status_lbl.setStyleSheet("color: #00E5FF; font-weight: 600; font-size: 13px;")
        self.boot_status_lbl.setAlignment(Qt.AlignCenter)

        c_layout.addWidget(spinner_lbl)
        c_layout.addWidget(boot_title)
        c_layout.addWidget(self.boot_status_lbl)

        layout.addWidget(card)
        return page

    def _create_player_container_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Viewport Frame
        self.viewport_frame = QWidget()
        self.viewport_frame.setProperty("class", "SurfaceCard")
        self.viewport_frame.setStyleSheet("background-color: #000000; border-radius: 10px;")

        # Active placeholder banner inside viewport
        vf_layout = QVBoxLayout(self.viewport_frame)
        vf_layout.setAlignment(Qt.AlignCenter)
        self.embed_notice = QLabel("📱 Android Emulator Active\n\n(Window Hooked / Controlled)")
        self.embed_notice.setFont(QFont("Segoe UI", 14, QFont.Bold))
        self.embed_notice.setStyleSheet("color: #8B949E; text-align: center;")
        self.embed_notice.setAlignment(Qt.AlignCenter)
        vf_layout.addWidget(self.embed_notice)

        layout.addWidget(self.viewport_frame)
        return page

    def _create_side_toolbar(self) -> QWidget:
        toolbar = QWidget()
        toolbar.setProperty("class", "ElevatedCard")
        toolbar.setFixedWidth(52)
        t_layout = QVBoxLayout(toolbar)
        t_layout.setContentsMargins(6, 12, 6, 12)
        t_layout.setSpacing(8)

        # Standard Android Emulator Control Buttons
        self.power_btn = self._make_tool_btn("⏻", "Power Button (Lock / Unlock)", self._on_power)
        self.vol_up_btn = self._make_tool_btn("🔊", "Volume Up", self._on_vol_up)
        self.vol_down_btn = self._make_tool_btn("🔉", "Volume Down", self._on_vol_down)
        self.rotate_btn = self._make_tool_btn("🔄", "Rotate Screen", self._on_rotate)
        self.shot_btn = self._make_tool_btn("📸", "Take Screenshot", self._on_screenshot)
        self.apk_btn = self._make_tool_btn("📦", "Install APK File", self._on_install_apk)

        t_layout.addWidget(self.power_btn)
        t_layout.addWidget(self.vol_up_btn)
        t_layout.addWidget(self.vol_down_btn)
        t_layout.addWidget(self.rotate_btn)
        t_layout.addWidget(self.shot_btn)
        t_layout.addWidget(self.apk_btn)

        t_layout.addStretch()

        # Android Navigation Buttons
        self.back_btn = self._make_tool_btn("◀", "Back", self._on_back)
        self.home_btn = self._make_tool_btn("⚪", "Home", self._on_home)
        self.recents_btn = self._make_tool_btn("⏹", "Recent Apps", self._on_recents)

        t_layout.addWidget(self.back_btn)
        t_layout.addWidget(self.home_btn)
        t_layout.addWidget(self.recents_btn)

        t_layout.addStretch()

        # Stop VM Button
        self.stop_btn = QPushButton("✕")
        self.stop_btn.setProperty("class", "ToolButton")
        self.stop_btn.setToolTip("Shutdown Emulator")
        self.stop_btn.setStyleSheet("background-color: rgba(239, 68, 68, 0.15); color: #EF4444; border-color: #EF4444;")
        self.stop_btn.clicked.connect(self._stop_emulator)
        t_layout.addWidget(self.stop_btn)

        return toolbar

    def _make_tool_btn(self, icon_text: str, tooltip: str, callback) -> QPushButton:
        btn = QPushButton(icon_text)
        btn.setProperty("class", "ToolButton")
        btn.setToolTip(tooltip)
        btn.clicked.connect(callback)
        return btn

    def update_palette(self, palette: ThemePalette) -> None:
        self.palette = palette

    def _start_emulator(self) -> None:
        self.stack.setCurrentIndex(1)  # Booting
        self.status_changed.emit("booting")

        hw = self.hw_combo.currentText()
        spoof = self.spoof_combo.currentText()

        self.boot_worker = EmulatorBootWorker(
            avd_name=self.avd_name,
            hw_profile=hw,
            spoof_profile=spoof,
        )
        self.boot_worker.status_signal.connect(self.boot_status_lbl.setText)
        self.boot_worker.booted_signal.connect(self._on_boot_result)
        self.boot_worker.start()

        # Start background timer looking for the emulator window to embed
        self._start_window_embedding_poll()

    def _on_boot_result(self, success: bool, err_msg: str) -> None:
        if success:
            self.stack.setCurrentIndex(2)  # Active Player
            self.status_changed.emit("running")
        else:
            QMessageBox.critical(self, "Emulator Error", f"Failed to start emulator:\n{err_msg}")
            self.stack.setCurrentIndex(0)
            self.status_changed.emit("offline")

    def _start_window_embedding_poll(self) -> None:
        self._embed_timer = QTimer(self)
        self._embed_timer.setInterval(1000)
        self._embed_timer.timeout.connect(self._try_embed_window)
        self._embed_timer.start()

    def _try_embed_window(self) -> None:
        if not user32 or self.embedded_hwnd:
            return

        hwnd = find_emulator_window(self.avd_name)
        if hwnd:
            self.embedded_hwnd = hwnd
            if self._embed_timer:
                self._embed_timer.stop()

            # Embed into container viewport
            container_id = int(self.viewport_frame.winId())
            user32.SetParent(hwnd, container_id)

            # Resize emulator window to fit container
            rect = self.viewport_frame.rect()
            user32.MoveWindow(hwnd, 0, 0, rect.width(), rect.height(), True)
            self.embed_notice.setVisible(False)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        # Keep embedded window sized to viewport
        if user32 and self.embedded_hwnd:
            rect = self.viewport_frame.rect()
            user32.MoveWindow(self.embedded_hwnd, 0, 0, rect.width(), rect.height(), True)

    def _stop_emulator(self) -> None:
        reply = QMessageBox.question(
            self,
            "Shutdown",
            "Are you sure you want to shut down the Android emulator?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self.adb.run("emu", "kill")
            if self.boot_worker and self.boot_worker.proc:
                try:
                    self.boot_worker.proc.terminate()
                except Exception:
                    pass
            self.embedded_hwnd = None
            self.stack.setCurrentIndex(0)
            self.status_changed.emit("offline")

    # Android Key Controls
    def _on_power(self) -> None:
        self.adb.run("shell", "input", "keyevent", "26")

    def _on_vol_up(self) -> None:
        self.adb.run("shell", "input", "keyevent", "24")

    def _on_vol_down(self) -> None:
        self.adb.run("shell", "input", "keyevent", "25")

    def _on_rotate(self) -> None:
        # Toggle user rotation between 0 and 1
        res = self.adb.run("shell", "settings", "get", "system", "user_rotation")
        curr = res.stdout.strip()
        new_rot = "1" if curr == "0" else "0"
        self.adb.run("shell", "settings", "put", "system", "accelerometer_rotation", "0")
        self.adb.run("shell", "settings", "put", "system", "user_rotation", new_rot)

    def _on_back(self) -> None:
        self.adb.run("shell", "input", "keyevent", "4")

    def _on_home(self) -> None:
        self.adb.run("shell", "input", "keyevent", "3")

    def _on_recents(self) -> None:
        self.adb.run("shell", "input", "keyevent", "187")

    def _on_screenshot(self) -> None:
        out_dir = REPO_ROOT / "screenshots"
        out_dir.mkdir(parents=True, exist_ok=True)
        filename = f"screenshot_{int(time.time())}.png"
        filepath = out_dir / filename

        # Grab screenshot through adb
        try:
            with open(filepath, "wb") as f:
                subprocess.run(
                    [str(self.adb.adb_path), "-e", "exec-out", "screencap", "-p"],
                    stdout=f,
                    timeout=15,
                    check=True,
                )
            QMessageBox.information(self, "Screenshot Saved", f"Screenshot saved to:\n{filepath}")
        except Exception as exc:
            QMessageBox.warning(self, "Screenshot Error", f"Failed to capture screenshot:\n{exc}")

    def _on_install_apk(self) -> None:
        apk_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select APK to Install",
            "",
            "Android Package (*.apk);;All Files (*.*)",
        )
        if apk_path:
            self._install_apk(Path(apk_path))

    def _install_apk(self, apk: Path) -> None:
        if not apk.exists():
            return
        res = self.adb.run("install", "-r", str(apk), timeout=120)
        if res.returncode == 0:
            QMessageBox.information(self, "APK Installed", f"Successfully installed:\n{apk.name}")
        else:
            QMessageBox.warning(self, "Installation Failed", f"Could not install {apk.name}:\n{res.stderr.strip() or res.stdout.strip()}")

    # Drag & Drop APK support
    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.toLocalFile().lower().endswith(".apk"):
                    event.acceptProposedAction()
                    return
        super().dragEnterEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        for url in event.mimeData().urls():
            local_path = Path(url.toLocalFile())
            if local_path.suffix.lower() == ".apk":
                self._install_apk(local_path)
                event.acceptProposedAction()
                return
        super().dropEvent(event)

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

from PySide6.QtCore import QPoint, QRect, QSize, QThread, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QDragEnterEvent, QDropEvent, QFont, QIcon, QPainter, QPixmap, QWindow
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
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


# ---------------------------------------------------------------------------
# Win32 Native Helpers for External Window Reparenting & Embedding
# ---------------------------------------------------------------------------

if platform.system() == "Windows":
    user32 = ctypes.windll.user32
    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

    # Setup 64-bit safe prototypes to avoid ctypes OverflowError
    SetWindowLongPtr = getattr(user32, "SetWindowLongPtrW", user32.SetWindowLongW)
    SetWindowLongPtr.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
    SetWindowLongPtr.restype = ctypes.c_ssize_t

    GetWindowLongPtr = getattr(user32, "GetWindowLongPtrW", user32.GetWindowLongW)
    GetWindowLongPtr.argtypes = [wintypes.HWND, ctypes.c_int]
    GetWindowLongPtr.restype = ctypes.c_ssize_t

    # Win32 style constants
    GWL_STYLE = -16
    WS_POPUP = 0x80000000
    WS_CAPTION = 0x00C00000
    WS_THICKFRAME = 0x00040000
    WS_MINIMIZEBOX = 0x00020000
    WS_MAXIMIZEBOX = 0x00010000
    WS_SYSMENU = 0x00080000
    WS_CHILD = 0x40000000
    WS_VISIBLE = 0x10000000

    SWP_NOZORDER = 0x0004
    SWP_FRAMECHANGED = 0x0020
    SWP_SHOWWINDOW = 0x0040
    SWP_NOACTIVATE = 0x0010
else:
    user32 = None


def find_emulator_window(avd_name: str, target_pid: Optional[int] = None) -> Optional[int]:
    """Finds the HWND of the running Android Emulator window on Windows.

    Filters out Anvill's own process and hidden/helper windows.
    Matches window title patterns like 'Android Emulator - Android16_Pro:5554'.
    """
    if not user32:
        return None

    my_pid = os.getpid()
    matches: List[Tuple[int, str, int]] = []

    def enum_windows_callback(hwnd: int, lparam: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True

        # Never match Anvill itself
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == my_pid:
            return True

        length = user32.GetWindowTextLengthW(hwnd)
        if length > 0:
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            title = buf.value.strip()
            title_lower = title.lower()

            # Must have non-trivial size (ignore 0x0 or offscreen dummy windows)
            rect = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            w = rect.right - rect.left
            h = rect.bottom - rect.top
            if w < 100 or h < 100:
                return True

            # Match criteria
            if target_pid and pid.value == target_pid:
                matches.append((hwnd, title, 100))
            elif "android emulator" in title_lower:
                priority = 90 if avd_name.lower() in title_lower else 75
                matches.append((hwnd, title, priority))
            elif avd_name.lower() in title_lower and "anvill" not in title_lower:
                matches.append((hwnd, title, 60))

        return True

    cb = WNDENUMPROC(enum_windows_callback)
    user32.EnumWindows(cb, 0)

    if matches:
        matches.sort(key=lambda x: x[2], reverse=True)
        return matches[0][0]
    return None


def strip_and_embed_window(child_hwnd: int, parent_widget: QWidget) -> Optional[QWidget]:
    """Strips outer OS window titlebar/borders and wraps HWND inside a PySide6 QWidget container."""
    if not user32 or not child_hwnd:
        return None

    try:
        # Strip top-level borders, caption and popups
        style = GetWindowLongPtr(child_hwnd, GWL_STYLE)
        style &= ~(WS_POPUP | WS_CAPTION | WS_THICKFRAME | WS_MINIMIZEBOX | WS_MAXIMIZEBOX | WS_SYSMENU)
        style |= (WS_CHILD | WS_VISIBLE)
        SetWindowLongPtr(child_hwnd, GWL_STYLE, ctypes.c_ssize_t(style).value)

        # Wrap HWND into Qt's native window abstraction
        qwin = QWindow.fromWinId(child_hwnd)
        container = QWidget.createWindowContainer(qwin, parent_widget)
        container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        # Reparent and inform Windows of style change
        w = max(100, parent_widget.width())
        h = max(100, parent_widget.height())
        user32.SetWindowPos(
            child_hwnd,
            0,
            0,
            0,
            w,
            h,
            SWP_NOZORDER | SWP_FRAMECHANGED | SWP_SHOWWINDOW,
        )
        return container
    except Exception as exc:
        print(f"[Anvill] Error embedding window {child_hwnd}: {exc}")
        return None


# ---------------------------------------------------------------------------
# Background Boot Worker
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Player View (Main VM Container & Controller)
# ---------------------------------------------------------------------------

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
        self.embedded_container: Optional[QWidget] = None
        self._embed_timer: Optional[QTimer] = None
        self._detect_timer: Optional[QTimer] = None

        self.setAcceptDrops(True)
        self._setup_ui()
        self.update_palette(palette)
        self._start_desktop_detection_timer()

    def _setup_ui(self) -> None:
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(12)

        # Central Viewport Area (Stacked: Dashboard -> Player Container)
        self.stack = QStackedWidget()

        # Page 0: Idle Dashboard
        self.dashboard_page = self._create_dashboard_page()
        self.stack.addWidget(self.dashboard_page)

        # Page 1: Active Player Container (Viewport + Overlays)
        self.player_page = self._create_player_container_page()
        self.stack.addWidget(self.player_page)

        main_layout.addWidget(self.stack, stretch=1)

        # Side Toolbar Controls (Native Android player buttons)
        self.toolbar = self._create_side_toolbar()
        main_layout.addWidget(self.toolbar)

    # -----------------------------------------------------------------------
    # Page 0: Idle Dashboard
    # -----------------------------------------------------------------------

    def _create_dashboard_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(16)

        card = QWidget()
        card.setProperty("class", "SurfaceCard")
        card.setFixedSize(640, 480)
        c_layout = QVBoxLayout(card)
        c_layout.setContentsMargins(36, 28, 36, 28)
        c_layout.setSpacing(14)

        # Icon & Title
        title_box = QHBoxLayout()
        icon = QLabel("📱")
        icon.setFont(QFont("Segoe UI Emoji", 30))
        title = QLabel(f"Android Virtual Machine")
        title.setFont(QFont("Segoe UI", 18, QFont.Bold))
        title_box.addWidget(icon)
        title_box.addWidget(title)
        title_box.addStretch()
        c_layout.addLayout(title_box)

        desc = QLabel("Select configuration profile and start the virtual machine player session.")
        desc.setStyleSheet("color: #8B949E; font-size: 13px;")
        c_layout.addWidget(desc)

        # Active Running Detection Banner (Shows if emulator is already running outside)
        self.detected_banner = QWidget()
        self.detected_banner.setProperty("class", "ElevatedCard")
        self.detected_banner.setStyleSheet("background-color: rgba(0, 229, 255, 0.08); border: 1px solid #00E5FF; border-radius: 8px;")
        self.detected_banner.setVisible(False)
        db_layout = QHBoxLayout(self.detected_banner)
        db_layout.setContentsMargins(12, 8, 12, 8)

        self.detected_lbl = QLabel("⚡ Running Emulator window detected on desktop!")
        self.detected_lbl.setStyleSheet("color: #00E5FF; font-weight: 600; font-size: 12px;")
        self.attach_btn = QPushButton("Dock Inside App")
        self.attach_btn.setProperty("class", "PrimaryButton")
        self.attach_btn.setFixedHeight(28)
        self.attach_btn.clicked.connect(self._attach_detected_window)
        db_layout.addWidget(self.detected_lbl, stretch=1)
        db_layout.addWidget(self.attach_btn)
        c_layout.addWidget(self.detected_banner)

        c_layout.addSpacing(6)

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
        c_layout.addSpacing(12)

        # Big Launch Button
        self.launch_btn = QPushButton("▶ Launch Android Emulator")
        self.launch_btn.setProperty("class", "PrimaryButton")
        self.launch_btn.setMinimumHeight(48)
        self.launch_btn.clicked.connect(self._start_emulator)
        c_layout.addWidget(self.launch_btn)

        layout.addWidget(card)
        return page

    # -----------------------------------------------------------------------
    # Page 1: Active Player Container
    # -----------------------------------------------------------------------

    def _create_player_container_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Viewport Frame with Native Window attribute for Win32 child reparenting
        self.viewport_frame = QWidget()
        self.viewport_frame.setAttribute(Qt.WA_NativeWindow, True)
        self.viewport_frame.setProperty("class", "SurfaceCard")
        self.viewport_frame.setStyleSheet("background-color: #050505; border-radius: 10px;")

        self.viewport_layout = QVBoxLayout(self.viewport_frame)
        self.viewport_layout.setContentsMargins(0, 0, 0, 0)
        self.viewport_layout.setSpacing(0)

        # Boot / Loading Overlay inside Viewport
        self.boot_overlay = QWidget(self.viewport_frame)
        self.boot_overlay.setStyleSheet("background-color: transparent;")
        bo_layout = QVBoxLayout(self.boot_overlay)
        bo_layout.setAlignment(Qt.AlignCenter)
        bo_layout.setSpacing(12)

        spinner = QLabel("⚡")
        spinner.setFont(QFont("Segoe UI Emoji", 38))
        spinner.setAlignment(Qt.AlignCenter)

        self.boot_title_lbl = QLabel("Booting Android Emulator...")
        self.boot_title_lbl.setFont(QFont("Segoe UI", 16, QFont.Bold))
        self.boot_title_lbl.setStyleSheet("color: #FFFFFF;")
        self.boot_title_lbl.setAlignment(Qt.AlignCenter)

        self.boot_status_lbl = QLabel("Starting QEMU engine & hooking display...")
        self.boot_status_lbl.setStyleSheet("color: #00E5FF; font-weight: 600; font-size: 13px;")
        self.boot_status_lbl.setAlignment(Qt.AlignCenter)

        bo_layout.addWidget(spinner)
        bo_layout.addWidget(self.boot_title_lbl)
        bo_layout.addWidget(self.boot_status_lbl)

        self.viewport_layout.addWidget(self.boot_overlay)

        layout.addWidget(self.viewport_frame)
        return page

    # -----------------------------------------------------------------------
    # Side Toolbar
    # -----------------------------------------------------------------------

    def _create_side_toolbar(self) -> QWidget:
        toolbar = QWidget()
        toolbar.setProperty("class", "ElevatedCard")
        toolbar.setFixedWidth(54)
        t_layout = QVBoxLayout(toolbar)
        t_layout.setContentsMargins(6, 12, 6, 12)
        t_layout.setSpacing(8)

        # Hardware & utility controls
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

        # Android Navigation controls
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

    # -----------------------------------------------------------------------
    # Detection & Embedding Operations
    # -----------------------------------------------------------------------

    def _start_desktop_detection_timer(self) -> None:
        """Periodically inspects if an emulator window is already running on the desktop."""
        self._detect_timer = QTimer(self)
        self._detect_timer.setInterval(1500)
        self._detect_timer.timeout.connect(self._check_for_running_emulator)
        self._detect_timer.start()

    def _check_for_running_emulator(self) -> None:
        if self.embedded_hwnd or self.stack.currentIndex() != 0:
            return

        hwnd = find_emulator_window(self.avd_name)
        if hwnd:
            self.detected_banner.setVisible(True)
        else:
            self.detected_banner.setVisible(False)

    def _attach_detected_window(self) -> None:
        """Docks an existing running emulator window from the desktop into the app container."""
        hwnd = find_emulator_window(self.avd_name)
        if not hwnd:
            QMessageBox.warning(self, "Not Found", "Could not locate running Android Emulator window.")
            return

        self._embed_hwnd(hwnd)
        self.stack.setCurrentIndex(1)
        self.status_changed.emit("running")

    def _start_emulator(self) -> None:
        """Starts the emulator and immediately switches to the viewport container."""
        # If already running on desktop, dock it directly
        existing_hwnd = find_emulator_window(self.avd_name)
        if existing_hwnd:
            self._attach_detected_window()
            return

        # Switch immediately to viewport page with booting overlay
        self.boot_overlay.setVisible(True)
        self.boot_title_lbl.setText("Booting Android Emulator...")
        self.boot_status_lbl.setText("Initializing QEMU engine...")
        self.stack.setCurrentIndex(1)
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

        # Start fast polling timer (every 150ms) to capture the window as soon as QEMU renders it
        self._start_fast_embedding_poll()

    def _start_fast_embedding_poll(self) -> None:
        if self._embed_timer:
            self._embed_timer.stop()
        self._embed_timer = QTimer(self)
        self._embed_timer.setInterval(150)
        self._embed_timer.timeout.connect(self._try_embed_window)
        self._embed_timer.start()

    def _try_embed_window(self) -> None:
        if not user32 or self.embedded_hwnd:
            if self._embed_timer:
                self._embed_timer.stop()
            return

        target_pid = self.boot_worker.proc.pid if (self.boot_worker and self.boot_worker.proc) else None
        hwnd = find_emulator_window(self.avd_name, target_pid=target_pid)
        if hwnd:
            self._embed_hwnd(hwnd)

    def _embed_hwnd(self, hwnd: int) -> None:
        """Embeds the given HWND into the viewport frame."""
        if self.embedded_hwnd:
            return

        self.embedded_hwnd = hwnd
        if self._embed_timer:
            self._embed_timer.stop()

        container = strip_and_embed_window(hwnd, self.viewport_frame)
        if container:
            self.embedded_container = container
            self.viewport_layout.addWidget(container)
            self.boot_overlay.setVisible(False)
            self._sync_geometry()

    def _sync_geometry(self) -> None:
        """Ensures the embedded child window matches viewport bounds exactly."""
        if user32 and self.embedded_hwnd and self.viewport_frame:
            w = max(100, self.viewport_frame.width())
            h = max(100, self.viewport_frame.height())
            user32.SetWindowPos(
                self.embedded_hwnd,
                0,
                0,
                0,
                w,
                h,
                SWP_NOZORDER | SWP_FRAMECHANGED | SWP_SHOWWINDOW,
            )

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._sync_geometry()

    def _on_boot_result(self, success: bool, err_msg: str) -> None:
        if success:
            self.status_changed.emit("running")
            # If not yet embedded, perform a final sweep
            if not self.embedded_hwnd:
                self._try_embed_window()
        else:
            QMessageBox.critical(self, "Emulator Error", f"Failed to start emulator:\n{err_msg}")
            self._cleanup_embedded_session()
            self.stack.setCurrentIndex(0)
            self.status_changed.emit("offline")

    def _cleanup_embedded_session(self) -> None:
        if self._embed_timer:
            self._embed_timer.stop()
        if self.embedded_container:
            self.viewport_layout.removeWidget(self.embedded_container)
            self.embedded_container.setParent(None)
            self.embedded_container.deleteLater()
            self.embedded_container = None
        self.embedded_hwnd = None
        self.boot_overlay.setVisible(True)

    def _stop_emulator(self) -> None:
        reply = QMessageBox.question(
            self,
            "Shutdown VM",
            "Are you sure you want to shut down the Android virtual machine?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self.adb.run("emu", "kill")
            if self.boot_worker and self.boot_worker.proc:
                try:
                    self.boot_worker.proc.terminate()
                except Exception:
                    pass
            self._cleanup_embedded_session()
            self.stack.setCurrentIndex(0)
            self.status_changed.emit("offline")

    # -----------------------------------------------------------------------
    # Android Control Buttons
    # -----------------------------------------------------------------------

    def _on_power(self) -> None:
        self.adb.run("shell", "input", "keyevent", "26")

    def _on_vol_up(self) -> None:
        self.adb.run("shell", "input", "keyevent", "24")

    def _on_vol_down(self) -> None:
        self.adb.run("shell", "input", "keyevent", "25")

    def _on_rotate(self) -> None:
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
            QMessageBox.warning(
                self,
                "Installation Failed",
                f"Could not install {apk.name}:\n{res.stderr.strip() or res.stdout.strip()}",
            )

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

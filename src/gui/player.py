"""Android Emulator Player widget with pure Win32 window embedding, tablet landscape aspect ratio and polished side toolbar."""

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
from PySide6.QtGui import QColor, QDragEnterEvent, QDropEvent, QFont, QIcon, QPainter, QPixmap
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
from configurator import AvdConfigurator
from constants import AVD_ROOT, DEFAULT_AVD_NAME, REPO_ROOT, SDK_ROOT
from gui.theme import ThemePalette
from inspector import HostInspector
from launcher import EmulatorLauncher, LaunchFlags, pick_gpu_mode
from profiles import get_hardware_profile, get_spoof_profile, load_profiles


# ---------------------------------------------------------------------------
# Win32 Native Helpers for External Window Reparenting & Centering
# ---------------------------------------------------------------------------

if platform.system() == "Windows":
    user32 = ctypes.windll.user32
    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

    SetWindowLongPtr = getattr(user32, "SetWindowLongPtrW", user32.SetWindowLongW)
    SetWindowLongPtr.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
    SetWindowLongPtr.restype = ctypes.c_ssize_t

    GetWindowLongPtr = getattr(user32, "GetWindowLongPtrW", user32.GetWindowLongW)
    GetWindowLongPtr.argtypes = [wintypes.HWND, ctypes.c_int]
    GetWindowLongPtr.restype = ctypes.c_ssize_t

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
    SW_HIDE = 0
else:
    user32 = None


def find_emulator_windows(
    avd_name: str,
    target_pid: Optional[int] = None,
) -> Tuple[Optional[int], List[int]]:
    """Locates the emulator display HWND and any auxiliary floating toolbar HWNDs."""
    if not user32:
        return None, []

    my_pid = os.getpid()
    display_candidates: List[Tuple[int, str, int]] = []
    toolbars: List[int] = []

    def enum_cb(hwnd: int, lparam: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True

        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == my_pid:
            return True

        length = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value.strip()

        cls_buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cls_buf, 256)
        cls = cls_buf.value

        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        w = rect.right - rect.left
        h = rect.bottom - rect.top

        # Floating toolbars or small utility windows created by QEMU
        if ("tool" in cls.lower() or "savebits" in cls.lower() or (w < 120 and h > 50)) and (
            "emulator" in title.lower() or (target_pid and pid.value == target_pid)
        ):
            toolbars.append(hwnd)
            return True

        # Android display window
        if "android emulator" in title.lower() or (
            "qwindowicon" in cls.lower() and ("emulator" in title.lower() or avd_name.lower() in title.lower())
        ):
            if w >= 150 and h >= 150:
                priority = 90
                if target_pid and pid.value == target_pid:
                    priority = 100
                elif avd_name.lower() in title.lower():
                    priority = 95
                display_candidates.append((hwnd, title, priority))

        return True

    cb_proto = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows(cb_proto(enum_cb), 0)

    display_hwnd = None
    if display_candidates:
        display_candidates.sort(key=lambda x: x[2], reverse=True)
        display_hwnd = display_candidates[0][0]

    return display_hwnd, toolbars


def configure_docked_window(disp_hwnd: int, owner_hwnd: int = 0) -> bool:
    """Configures the external emulator window as a borderless owned window docked to the main app."""
    if not user32 or not disp_hwnd:
        return False

    try:
        # Strip popup window frames, title bar, caption, system menu, thick borders
        GWL_STYLE = -16
        WS_POPUP = 0x80000000
        WS_VISIBLE = 0x10000000
        WS_CAPTION = 0x00C00000
        WS_THICKFRAME = 0x00040000
        WS_MINIMIZEBOX = 0x00020000
        WS_MAXIMIZEBOX = 0x00010000
        WS_SYSMENU = 0x00080000

        style = GetWindowLongPtr(disp_hwnd, GWL_STYLE)
        style &= ~(WS_CAPTION | WS_THICKFRAME | WS_MINIMIZEBOX | WS_MAXIMIZEBOX | WS_SYSMENU)
        style |= (WS_POPUP | WS_VISIBLE)
        SetWindowLongPtr(disp_hwnd, GWL_STYLE, ctypes.c_ssize_t(style).value)

        # Strip taskbar icon and add toolwindow style so it behaves as an owned docked viewport
        GWL_EXSTYLE = -20
        WS_EX_APPWINDOW = 0x00040000
        WS_EX_TOOLWINDOW = 0x00000080
        ex_style = GetWindowLongPtr(disp_hwnd, GWL_EXSTYLE)
        ex_style &= ~WS_EX_APPWINDOW
        ex_style |= WS_EX_TOOLWINDOW
        SetWindowLongPtr(disp_hwnd, GWL_EXSTYLE, ctypes.c_ssize_t(ex_style).value)

        # Bind window ownership to the main application window
        if owner_hwnd:
            GWLP_HWNDPARENT = -8
            SetWindowLongPtr(disp_hwnd, GWLP_HWNDPARENT, ctypes.c_ssize_t(owner_hwnd).value)

        return True
    except Exception as exc:
        print(f"[Anvill] Error docking HWND {disp_hwnd}: {exc}")
        return False


def embed_and_reparent_display(child_hwnd: int, parent_hwnd: int) -> bool:
    """Compatibility wrapper that configures borderless owned window docking."""
    return configure_docked_window(child_hwnd, parent_hwnd)


class ViewportContainer(QWidget):
    """Container widget hosting the docked Win32 Android Emulator window with dynamic resize notification."""

    resized = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_NativeWindow, True)
        self.setObjectName("PlayerViewportFrame")
        self.setStyleSheet("background-color: #000000; border-radius: 6px;")

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.resized.emit()


# ---------------------------------------------------------------------------
# Background Boot Worker
# ---------------------------------------------------------------------------

class EmulatorBootWorker(QThread):
    """Starts the emulator process, enforces tablet resolution and awaits boot completion in background."""

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

            # Pre-apply tablet landscape settings to AVD config.ini before booting
            self.status_signal.emit("Configuring AVD tablet landscape profile...")
            configurator = AvdConfigurator(self.avd_name)
            configurator.apply(profile, gpu_mode)

            # Clear legacy phone snapshot if it exists so AVD boots cleanly in tablet mode
            snap_dir = configurator.avd_dir / "snapshots"
            if snap_dir.exists():
                import shutil
                shutil.rmtree(snap_dir, ignore_errors=True)

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

            # Enforce 16:9 Tablet Landscape resolution in Android OS
            self.status_signal.emit("Configuring Tablet Landscape Display...")
            self.adb.run("shell", "wm", "size", f"{profile.width}x{profile.height}")
            self.adb.run("shell", "wm", "density", str(profile.dpi))
            self.adb.run("shell", "settings", "put", "system", "accelerometer_rotation", "0")
            self.adb.run("shell", "settings", "put", "system", "user_rotation", "0")

            self.status_signal.emit("Injecting device spoofing & anti-detection...")
            self.adb.apply_spoof(spoof)

            self.status_signal.emit("✓ Android Tablet ready and running!")
            self.booted_signal.emit(True, "")
        except Exception as exc:
            self.booted_signal.emit(False, str(exc))


# ---------------------------------------------------------------------------
# Player View
# ---------------------------------------------------------------------------

class PlayerView(QWidget):
    """Main Android Player container with embedded emulator viewport and polished side control bar."""

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
        self._toolbars: List[int] = []
        self.is_landscape: bool = True
        self._embed_timer: Optional[QTimer] = None
        self._detect_timer: Optional[QTimer] = None
        self._watchdog_timer: Optional[QTimer] = None

        self.setAcceptDrops(True)
        self._setup_ui()
        self.update_palette(palette)
        self._start_desktop_detection_timer()

        # Watchdog alignment timer ensures docked window stays firmly positioned
        self._watchdog_timer = QTimer(self)
        self._watchdog_timer.setInterval(800)
        self._watchdog_timer.timeout.connect(self._sync_geometry)
        self._watchdog_timer.start()

    def _setup_ui(self) -> None:
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(6, 6, 6, 6)
        main_layout.setSpacing(6)

        # Central Viewport Area (Stacked: Dashboard -> Player Viewport)
        self.stack = QStackedWidget()

        # Page 0: Idle Dashboard
        self.dashboard_page = self._create_dashboard_page()
        self.stack.addWidget(self.dashboard_page)

        # Page 1: Active Player Container
        self.player_page = self._create_player_container_page()
        self.stack.addWidget(self.player_page)

        main_layout.addWidget(self.stack, stretch=1)

        # Side Toolbar Controls (Flush right dock)
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
        card.setFixedSize(580, 420)
        c_layout = QVBoxLayout(card)
        c_layout.setContentsMargins(32, 24, 32, 24)
        c_layout.setSpacing(14)

        # Header Title
        title_box = QHBoxLayout()
        icon = QLabel("📱")
        icon.setFont(QFont("Segoe UI Emoji", 26))
        title = QLabel("Android Tablet Player")
        title.setFont(QFont("Segoe UI", 16, QFont.Bold))
        title_box.addWidget(icon)
        title_box.addWidget(title)
        title_box.addStretch()
        c_layout.addLayout(title_box)

        desc = QLabel("Select hardware configuration and launch your isolated Android VM session.")
        desc.setStyleSheet("color: #8B949E; font-size: 13px;")
        c_layout.addWidget(desc)

        # Active Running Detection Banner
        self.detected_banner = QWidget()
        self.detected_banner.setProperty("class", "ElevatedCard")
        self.detected_banner.setStyleSheet("background-color: rgba(16, 185, 129, 0.1); border: 1px solid #10B981; border-radius: 6px;")
        self.detected_banner.setVisible(False)
        db_layout = QHBoxLayout(self.detected_banner)
        db_layout.setContentsMargins(12, 6, 12, 6)

        self.detected_lbl = QLabel("⚡ Running Emulator window detected on desktop!")
        self.detected_lbl.setStyleSheet("color: #10B981; font-weight: 600; font-size: 12px;")
        self.attach_btn = QPushButton("Dock Inside App")
        self.attach_btn.setProperty("class", "PrimaryButton")
        self.attach_btn.setFixedHeight(26)
        self.attach_btn.clicked.connect(self._attach_detected_window)
        db_layout.addWidget(self.detected_lbl, stretch=1)
        db_layout.addWidget(self.attach_btn)
        c_layout.addWidget(self.detected_banner)

        c_layout.addSpacing(4)

        # Options Box
        opts_box = QVBoxLayout()
        opts_box.setSpacing(8)

        row1 = QHBoxLayout()
        row1_lbl = QLabel("Hardware Profile:")
        row1_lbl.setStyleSheet("font-weight: 600;")
        self.hw_combo = QComboBox()
        self.hw_combo.addItems(["auto", "ultra", "high", "balanced", "low"])
        self.hw_combo.setCurrentText("auto")
        row1.addWidget(row1_lbl)
        row1.addWidget(self.hw_combo, stretch=1)
        opts_box.addLayout(row1)

        row2 = QHBoxLayout()
        row2_lbl = QLabel("Device Spoofing:")
        row2_lbl.setStyleSheet("font-weight: 600;")
        self.spoof_combo = QComboBox()
        self.spoof_combo.addItems(["galaxy_tab_s9", "s23_ultra", "rog_phone_7", "stock"])
        self.spoof_combo.setCurrentText("galaxy_tab_s9")
        row2.addWidget(row2_lbl)
        row2.addWidget(self.spoof_combo, stretch=1)
        opts_box.addLayout(row2)

        c_layout.addLayout(opts_box)
        c_layout.addSpacing(10)

        # Big Launch Button
        self.launch_btn = QPushButton("▶ Launch Android Tablet")
        self.launch_btn.setProperty("class", "PrimaryButton")
        self.launch_btn.setMinimumHeight(44)
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

        # Viewport Frame with native Win32 window attribute and resize notification
        self.viewport_frame = ViewportContainer()
        self.viewport_frame.resized.connect(self._sync_geometry)

        vf_layout = QVBoxLayout(self.viewport_frame)
        vf_layout.setAlignment(Qt.AlignCenter)
        vf_layout.setContentsMargins(0, 0, 0, 0)

        # Loading / Boot overlay
        self.boot_overlay = QWidget(self.viewport_frame)
        bo_layout = QVBoxLayout(self.boot_overlay)
        bo_layout.setAlignment(Qt.AlignCenter)
        bo_layout.setSpacing(10)

        spinner = QLabel("⚡")
        spinner.setFont(QFont("Segoe UI Emoji", 34))
        spinner.setAlignment(Qt.AlignCenter)

        self.boot_title_lbl = QLabel("Starting Android Tablet...")
        self.boot_title_lbl.setFont(QFont("Segoe UI", 15, QFont.Bold))
        self.boot_title_lbl.setStyleSheet("color: #FFFFFF;")
        self.boot_title_lbl.setAlignment(Qt.AlignCenter)

        self.boot_status_lbl = QLabel("Hooking display into player viewport...")
        self.boot_status_lbl.setStyleSheet("color: #00E5FF; font-weight: 600; font-size: 13px;")
        self.boot_status_lbl.setAlignment(Qt.AlignCenter)

        bo_layout.addWidget(spinner)
        bo_layout.addWidget(self.boot_title_lbl)
        bo_layout.addWidget(self.boot_status_lbl)

        vf_layout.addWidget(self.boot_overlay)
        layout.addWidget(self.viewport_frame)
        return page

    # -----------------------------------------------------------------------
    # Polished Side Toolbar
    # -----------------------------------------------------------------------

    def _create_side_toolbar(self) -> QWidget:
        toolbar = QWidget()
        toolbar.setObjectName("SideToolBarWidget")
        toolbar.setFixedWidth(46)
        toolbar.setStyleSheet(f"""
            QWidget#SideToolBarWidget {{
                background-color: {self.palette.bg_surface};
                border: 1px solid {self.palette.border_color};
                border-radius: 6px;
            }}
        """)
        t_layout = QVBoxLayout(toolbar)
        t_layout.setContentsMargins(4, 8, 4, 8)
        t_layout.setSpacing(6)

        # Quick Actions
        self.fs_btn = self._make_tool_btn("⛶", "Toggle Fullscreen", self._on_toggle_fullscreen)
        self.vol_up_btn = self._make_tool_btn("＋", "Volume Up", self._on_vol_up)
        self.vol_down_btn = self._make_tool_btn("－", "Volume Down", self._on_vol_down)
        self.rotate_btn = self._make_tool_btn("↻", "Rotate Orientation (Landscape / Portrait)", self._on_rotate)
        self.shot_btn = self._make_tool_btn("📷", "Take Screenshot", self._on_screenshot)
        self.apk_btn = self._make_tool_btn("APK", "Install APK File", self._on_install_apk)

        t_layout.addWidget(self.fs_btn)
        t_layout.addWidget(self.vol_up_btn)
        t_layout.addWidget(self.vol_down_btn)
        t_layout.addWidget(self.rotate_btn)
        t_layout.addWidget(self.shot_btn)
        t_layout.addWidget(self.apk_btn)

        # Separator line
        t_layout.addWidget(self._make_separator())
        t_layout.addStretch(1)

        # Android Navigation Keys
        self.back_btn = self._make_tool_btn("◀", "Back", self._on_back)
        self.home_btn = self._make_tool_btn("●", "Home", self._on_home)
        self.recents_btn = self._make_tool_btn("■", "Recent Apps", self._on_recents)

        t_layout.addWidget(self.back_btn)
        t_layout.addWidget(self.home_btn)
        t_layout.addWidget(self.recents_btn)

        t_layout.addStretch(1)
        t_layout.addWidget(self._make_separator())

        # Stop VM Button (Clean subtle red)
        self.stop_btn = QPushButton("⏻")
        self.stop_btn.setProperty("class", "ToolButton")
        self.stop_btn.setToolTip("Shutdown Virtual Machine")
        self.stop_btn.setStyleSheet("color: #EF4444;")
        self.stop_btn.clicked.connect(self._stop_emulator)
        t_layout.addWidget(self.stop_btn)

        return toolbar

    def _make_tool_btn(self, icon_text: str, tooltip: str, callback) -> QPushButton:
        btn = QPushButton(icon_text)
        btn.setProperty("class", "ToolButton")
        btn.setToolTip(tooltip)
        btn.clicked.connect(callback)
        return btn

    def _make_separator(self) -> QWidget:
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Plain)
        line.setStyleSheet(f"background-color: {self.palette.border_color}; max-height: 1px; border: none;")
        return line

    def update_palette(self, palette: ThemePalette) -> None:
        self.palette = palette
        if hasattr(self, "toolbar"):
            self.toolbar.setStyleSheet(f"""
                QWidget#SideToolBarWidget {{
                    background-color: {palette.bg_surface};
                    border: 1px solid {palette.border_color};
                    border-radius: 6px;
                }}
            """)

    # -----------------------------------------------------------------------
    # Detection & Embedding Operations
    # -----------------------------------------------------------------------

    def _start_desktop_detection_timer(self) -> None:
        self._detect_timer = QTimer(self)
        self._detect_timer.setInterval(1500)
        self._detect_timer.timeout.connect(self._check_for_running_emulator)
        self._detect_timer.start()

    def _check_for_running_emulator(self) -> None:
        if self.embedded_hwnd or self.stack.currentIndex() != 0:
            return

        disp_hwnd, _ = find_emulator_windows(self.avd_name)
        if disp_hwnd:
            self.detected_banner.setVisible(True)
        else:
            self.detected_banner.setVisible(False)

    def _attach_detected_window(self) -> None:
        disp_hwnd, toolbars = find_emulator_windows(self.avd_name)
        if not disp_hwnd:
            QMessageBox.warning(self, "Not Found", "Could not locate running Android Emulator window.")
            return

        self._embed_hwnd(disp_hwnd, toolbars)
        self.stack.setCurrentIndex(1)
        self.status_changed.emit("running")

    def _start_emulator(self) -> None:
        disp_hwnd, toolbars = find_emulator_windows(self.avd_name)
        if disp_hwnd:
            self._attach_detected_window()
            return

        self.boot_overlay.setVisible(True)
        self.boot_title_lbl.setText("Starting Android Tablet...")
        self.boot_status_lbl.setText("Initializing QEMU engine in 16:9 widescreen...")
        self.stack.setCurrentIndex(1)
        self.status_changed.emit("booting")

        hw = self.hw_combo.currentText()
        spoof = self.spoof_combo.currentText()

        self.boot_worker = EmulatorBootWorker(
            avd_name=self.avd_name,
            hw_profile=hw,
            spoof_profile=spoof,
            cold_boot=False,
        )
        self.boot_worker.status_signal.connect(self.boot_status_lbl.setText)
        self.boot_worker.booted_signal.connect(self._on_boot_result)
        self.boot_worker.start()

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
        disp_hwnd, toolbars = find_emulator_windows(self.avd_name, target_pid=target_pid)
        if disp_hwnd:
            self._embed_hwnd(disp_hwnd, toolbars)

    def _embed_hwnd(self, disp_hwnd: int, toolbars: Optional[List[int]] = None) -> None:
        if self.embedded_hwnd:
            return

        if self._embed_timer:
            self._embed_timer.stop()

        self._toolbars = toolbars or []
        if user32 and self._toolbars:
            for tb in self._toolbars:
                user32.ShowWindow(tb, SW_HIDE)

        top_win = self.window()
        owner_hwnd = int(top_win.winId()) if top_win else 0

        if configure_docked_window(disp_hwnd, owner_hwnd):
            self.embedded_hwnd = disp_hwnd
            self.boot_overlay.setVisible(False)
            self._sync_geometry()

            # Fast check if device is already booted
            res = self.adb.run("shell", "getprop", "sys.boot_completed", timeout=3)
            if res.stdout.strip() == "1":
                self.status_changed.emit("running")

    def _sync_geometry(self) -> None:
        """Calculates centered aspect-ratio geometry and positions the Android tablet display inside the viewport."""
        if not user32 or not self.embedded_hwnd:
            return

        top_win = self.window()
        # If top window is minimized, hidden or if Player page is not active in stack, hide emulator window
        if not top_win or top_win.isMinimized() or not self.isVisible() or self.stack.currentIndex() != 1:
            user32.ShowWindow(self.embedded_hwnd, SW_HIDE)
            return

        vp_hwnd = int(self.viewport_frame.winId()) if hasattr(self, "viewport_frame") else 0
        pt = wintypes.POINT(0, 0)
        rect = wintypes.RECT()

        # Retrieve exact physical pixels from Win32 to prevent DPI-scaling offsets (e.g. 125%/150%)
        if (
            vp_hwnd
            and user32.ClientToScreen(vp_hwnd, ctypes.byref(pt))
            and user32.GetClientRect(vp_hwnd, ctypes.byref(rect))
        ):
            vw = max(100, rect.right - rect.left)
            vh = max(100, rect.bottom - rect.top)
            start_x = pt.x
            start_y = pt.y
        else:
            vp_pt = self.viewport_frame.mapToGlobal(QPoint(0, 0))
            vw = max(100, self.viewport_frame.width())
            vh = max(100, self.viewport_frame.height())
            start_x = vp_pt.x()
            start_y = vp_pt.y()

        # Tablet 16:9 widescreen aspect ratio (landscape horizontal)
        ratio = (16.0 / 9.0) if self.is_landscape else (9.0 / 16.0)

        target_w = vw
        target_h = int(target_w / ratio)
        if target_h > vh:
            target_h = vh
            target_w = int(target_h * ratio)

        offset_x = (vw - target_w) // 2
        offset_y = (vh - target_h) // 2

        target_x = start_x + offset_x
        target_y = start_y + offset_y

        user32.SetWindowPos(
            self.embedded_hwnd,
            0,  # HWND_TOP
            target_x,
            target_y,
            target_w,
            target_h,
            0x0040 | 0x0020 | 0x0010,  # SWP_SHOWWINDOW | SWP_FRAMECHANGED | SWP_NOACTIVATE
        )

    # Public aliases for external synchronizers
    sync_geometry = _sync_geometry

    def set_emulator_visible(self, visible: bool) -> None:
        """Controls emulator display visibility when navigating away or switching tabs."""
        if not user32 or not self.embedded_hwnd:
            return
        top_win = self.window()
        if visible and self.stack.currentIndex() == 1 and top_win and not top_win.isMinimized():
            self._sync_geometry()
        else:
            user32.ShowWindow(self.embedded_hwnd, SW_HIDE)

    def moveEvent(self, event) -> None:
        super().moveEvent(event)
        self._sync_geometry()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._sync_geometry()

    def _on_boot_result(self, success: bool, err_msg: str) -> None:
        if success:
            self.status_changed.emit("running")
            if not self.embedded_hwnd:
                self._try_embed_window()
        else:
            QMessageBox.critical(self, "Emulator Error", f"Failed to start emulator:\n{err_msg}")
            self._cleanup_session()
            self.stack.setCurrentIndex(0)
            self.status_changed.emit("offline")

    def _cleanup_session(self) -> None:
        if self._embed_timer:
            self._embed_timer.stop()
        if user32 and self.embedded_hwnd:
            user32.ShowWindow(self.embedded_hwnd, SW_HIDE)
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
            self._cleanup_session()
            self.stack.setCurrentIndex(0)
            self.status_changed.emit("offline")

    # -----------------------------------------------------------------------
    # Android Key Controls
    # -----------------------------------------------------------------------

    def _on_toggle_fullscreen(self) -> None:
        win = self.window()
        if win.isFullScreen():
            win.showNormal()
        else:
            win.showFullScreen()

    def _on_power(self) -> None:
        self.adb.run("shell", "input", "keyevent", "26")

    def _on_vol_up(self) -> None:
        self.adb.run("shell", "input", "keyevent", "24")

    def _on_vol_down(self) -> None:
        self.adb.run("shell", "input", "keyevent", "25")

    def _on_rotate(self) -> None:
        self.is_landscape = not self.is_landscape
        # For tablet landscape (1920x1080), 0 is landscape horizontal and 1 is portrait vertical
        val = 0 if self.is_landscape else 1
        self.adb.run("shell", "settings", "put", "system", "accelerometer_rotation", "0")
        self.adb.run("shell", "settings", "put", "system", "user_rotation", str(val))
        self._sync_geometry()

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

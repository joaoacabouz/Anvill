"""ADB automation and device interaction."""

from __future__ import annotations

import os
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

_SRC_DIR = Path(__file__).resolve().parent
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

try:
    from constants import SDK_ROOT
except ImportError:
    from src.constants import SDK_ROOT

if TYPE_CHECKING:
    try:
        from profiles import DeviceSpoof
    except ImportError:
        from src.profiles import DeviceSpoof


def _log(msg: str) -> None:
    try:
        from ui import log
        log(msg)
    except Exception:
        print(msg)


class AdbManager:
    """Automates ADB interaction: wait-for-device, boot_completed, setprop, spoofing."""

    def __init__(
        self,
        platform_tools: Path | None = None,
        env: dict[str, str] | None = None,
        serial: str | None = None,
    ):
        self.platform_tools = platform_tools or (SDK_ROOT / "platform-tools")
        self.adb = self.platform_tools / ("adb.exe" if platform.system() == "Windows" else "adb")
        from provisioner import get_portable_env
        self.env = env if env is not None else get_portable_env(SDK_ROOT)
        self.serial = serial if serial is not None else "emulator-5554"
        self.device_ready = False

    @property
    def adb_path(self) -> Path:
        return self.adb

    def run(self, *args: str, timeout: int | None = None) -> subprocess.CompletedProcess:
        """Runs an ADB command with a safe argument list."""
        cmd = [str(self.adb)]
        if self.serial:
            if self.serial == "-e":
                cmd.append("-e")
            else:
                cmd.extend(["-s", self.serial])
        cmd.extend(args)
        extra: dict[str, int] = {}
        if platform.system() == "Windows":
            extra["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
        res = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=self.env,
            **extra,
        )
        # Self-healing fallback: if targeted serial failed with 'not found' or 'offline' and serial != "-e", retry with "-e"
        if res.returncode != 0 and self.serial and self.serial != "-e":
            err_low = (res.stderr or res.stdout).lower()
            if "device not found" in err_low or "device offline" in err_low or "not found" in err_low:
                if "device offline" in err_low:
                    subprocess.run([str(self.adb), "reconnect", "offline"], capture_output=True, env=self.env, **extra)
                fallback_cmd = [str(self.adb), "-e"] + list(args)
                fb_res = subprocess.run(
                    fallback_cmd,
                    check=False,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=timeout,
                    env=self.env,
                    **extra,
                )
                if fb_res.returncode == 0:
                    return fb_res
        return res

    def wait_for_device(
        self,
        timeout: int = 150,
        interval: float = 1.0,
        proc: subprocess.Popen | None = None,
        status_callback: Any = None,
    ) -> bool:
        """Executes ADB device detection with process liveness checking and state polling."""
        start = time.monotonic()
        end = start + timeout
        last_cb_time = 0.0
        last_reconnect_time = 0.0
        while time.monotonic() < end:
            if proc is not None and proc.poll() is not None:
                return False
            now = time.monotonic()
            elapsed = int(now - start)
            try:
                status = self.run("get-state", timeout=3).stdout.strip()
                if status == "device":
                    self.device_ready = True
                    try:
                        self.run("shell", "settings", "put", "global", "adb_enabled", "1", timeout=5)
                    except Exception:
                        pass
                    if status_callback:
                        status_callback("✓ Device online! Initializing guest...")
                    return True
                elif "offline" in status:
                    # Periodically kick offline connection to force instant handshake
                    if now - last_reconnect_time >= 5.0:
                        last_reconnect_time = now
                        self.run("reconnect", "offline", timeout=3)
                    if status_callback and (now - last_cb_time >= 3.0):
                        last_cb_time = now
                        status_callback(f"Kernel booting (ADB handshake in progress: {elapsed}s)...")
                elif status_callback and (now - last_cb_time >= 3.0):
                    last_cb_time = now
                    status_callback(f"Waiting for device connection ({elapsed}s)...")
            except Exception:
                pass
            time.sleep(interval)
        return False

    def wait_for_boot_completed(
        self,
        interval: int = 2,
        timeout: int = 300,
        proc: subprocess.Popen | None = None,
        status_callback: Any = None,
    ) -> bool:
        """Poll `adb shell getprop sys.boot_completed` until it returns '1' or proc terminates."""
        start = time.monotonic()
        end = start + timeout
        last_cb_time = 0.0
        while time.monotonic() < end:
            if proc is not None and proc.poll() is not None:
                return False
            now = time.monotonic()
            elapsed = int(now - start)
            try:
                result = self.run("shell", "getprop", "sys.boot_completed", timeout=10)
                if result.stdout.strip() == "1":
                    try:
                        self.run("shell", "settings", "put", "global", "adb_enabled", "1", timeout=5)
                    except Exception:
                        pass
                    return True
                dev_boot = self.run("shell", "getprop", "dev.bootcomplete", timeout=5)
                if dev_boot.stdout.strip() == "1":
                    return True
                if status_callback and (now - last_cb_time >= 4.0):
                    last_cb_time = now
                    status_callback(f"Loading Android UI & Play Services ({elapsed}s)...")
            except Exception:
                pass
            time.sleep(interval)
        return False

    def apply_spoof(self, spoof: DeviceSpoof, persist: bool = False) -> int:
        """Applies device spoofing properties via ADB. Returns number of applied properties."""
        if spoof.is_empty():
            return 0

        _log("[cyan]Applying device spoofing via ADB...[/cyan]")
        root_result = self.run("root", timeout=15)
        if root_result.returncode != 0:
            _log(f"[yellow]adb root response: {root_result.stdout.strip() or root_result.stderr.strip()}[/yellow]")

        # Reconnect
        time.sleep(1)
        self.wait_for_device(timeout=30)

        # Inject properties
        applied = 0
        for key, value in spoof.props.items():
            result = self.run("shell", "setprop", key, value, timeout=20)
            if result.returncode == 0:
                applied += 1
            else:
                _log(f"[yellow]setprop {key} failed: {result.stderr.strip()}[/yellow]")

        # Anti-detection: suppress QEMU indicators, hide developer options & mock locations (ensuring ADB remains active)
        self.run("shell", "resetprop --delete ro.kernel.qemu 2>/dev/null; resetprop --delete ro.boot.qemu 2>/dev/null; setprop ro.kernel.qemu 0 2>/dev/null; setprop ro.boot.qemu 0 2>/dev/null", timeout=10)
        self.run("shell", "settings put global adb_enabled 1 2>/dev/null; settings put global development_settings_enabled 0 2>/dev/null; settings put secure mock_location 0 2>/dev/null", timeout=10)
        self.run("shell", "magisk --denylist enable 2>/dev/null; magisk --denylist add com.google.android.gms com.google.android.gms.unstable 2>/dev/null; magisk --denylist add com.google.android.vending 2>/dev/null", timeout=10)

        _log(f"[green]Applied {applied}/{len(spoof.props)} spoof properties (anti-detection active)[/green]")

        if persist:
            self.persist_spoof(spoof)

        return applied

    def persist_spoof(self, spoof: DeviceSpoof) -> bool:
        """Persists props into writable system partition via remount."""
        result = self.run("remount", timeout=30)
        if result.returncode != 0:
            _log(f"[yellow]adb remount unavailable: {result.stdout.strip() or result.stderr.strip()}[/yellow]")
            return False
        for key, value in spoof.props.items():
            self.run("shell", "setprop", key, value, timeout=20)
        _log("[green]Spoof properties persisted into filesystem[/green]")
        return True


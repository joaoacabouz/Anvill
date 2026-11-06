"""ADB automation and device interaction."""

from __future__ import annotations

import os
import platform
import subprocess
import time
from pathlib import Path
from typing import TYPE_CHECKING

from anvill.constants import SDK_ROOT

if TYPE_CHECKING:
    from anvill.profiles import DeviceSpoof


def _log(msg: str) -> None:
    try:
        from anvill.ui import log
        log(msg)
    except Exception:
        print(msg)


class AdbManager:
    """Automates ADB interaction: wait-for-device, boot_completed, setprop, spoofing."""

    def __init__(
        self,
        platform_tools: Path | None = None,
        env: dict[str, str] | None = None,
        serial: str | None = "-e",
    ):
        self.platform_tools = platform_tools or (SDK_ROOT / "platform-tools")
        self.adb = self.platform_tools / ("adb.exe" if platform.system() == "Windows" else "adb")
        self.env = env or dict(os.environ)
        self.serial = serial
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
        return subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=self.env,
        )

    def wait_for_device(self, timeout: int = 120) -> bool:
        """Executes `adb wait-for-device` with fallback state polling."""
        try:
            result = self.run("wait-for-device", timeout=timeout)
            if result.returncode == 0:
                self.device_ready = True
                return True
        except subprocess.TimeoutExpired:
            pass

        end = time.monotonic() + timeout
        while time.monotonic() < end:
            try:
                status = self.run("get-state", timeout=5).stdout.strip()
                if status == "device":
                    self.device_ready = True
                    return True
            except Exception:
                pass
            time.sleep(1)
        return False

    def wait_for_boot_completed(self, interval: int = 2, timeout: int = 120) -> bool:
        """Poll `adb shell getprop sys.boot_completed` until it returns '1'."""
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            try:
                result = self.run("shell", "getprop", "sys.boot_completed", timeout=15)
                if result.stdout.strip() == "1":
                    return True
            except Exception:
                pass
            time.sleep(interval)
        return False

    def apply_spoof(self, spoof: DeviceSpoof, persist: bool = False) -> bool:
        """Applies device spoofing properties via ADB."""
        if spoof.is_empty():
            return True

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

        # Anti-detection: suppress QEMU indicators, hide developer options & mock locations
        self.run("shell", "resetprop --delete ro.kernel.qemu 2>/dev/null; resetprop --delete ro.boot.qemu 2>/dev/null; setprop ro.kernel.qemu 0 2>/dev/null; setprop ro.boot.qemu 0 2>/dev/null", timeout=10)
        self.run("shell", "settings put global adb_enabled 0 2>/dev/null; settings put global development_settings_enabled 0 2>/dev/null; settings put secure mock_location 0 2>/dev/null", timeout=10)
        self.run("shell", "magisk --denylist enable 2>/dev/null; magisk --denylist add com.google.android.gms com.google.android.gms.unstable 2>/dev/null; magisk --denylist add com.google.android.vending 2>/dev/null", timeout=10)

        _log(f"[green]Applied {applied}/{len(spoof.props)} spoof properties (anti-detection active)[/green]")

        if persist:
            self.persist_spoof(spoof)

        return True

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

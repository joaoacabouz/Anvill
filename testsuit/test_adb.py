"""Detailed unit tests for src/adb.py."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parent.parent
import sys
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from adb import AdbManager
from profiles import DeviceSpoof


class TestAdb(unittest.TestCase):
    """Granular tests for ADB manager: waiting, boot completion, and device spoofing."""

    @patch("subprocess.run")
    def test_wait_for_device_success(self, mock_run):
        """wait_for_device succeeds when get-state returns 'device'."""
        mock_run.return_value = MagicMock(returncode=0, stdout="device\n", stderr="")
        mgr = AdbManager(platform_tools=Path("C:/sdk/platform-tools"), env={})
        self.assertTrue(mgr.wait_for_device(interval=0.01, timeout=0.1))

    @patch("subprocess.run")
    def test_wait_for_device_timeout(self, mock_run):
        """wait_for_device returns False on timeout if device is offline."""
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="error: no devices/emulators found")
        mgr = AdbManager(platform_tools=Path("C:/sdk/platform-tools"), env={})
        self.assertFalse(mgr.wait_for_device(interval=0.01, timeout=0.05))

    @patch("subprocess.run")
    def test_wait_for_boot_completed_success(self, mock_run):
        """wait_for_boot_completed succeeds when sys.boot_completed returns '1'."""
        mock_run.return_value = MagicMock(returncode=0, stdout="1\n", stderr="")
        mgr = AdbManager(platform_tools=Path("C:/sdk/platform-tools"), env={})
        self.assertTrue(mgr.wait_for_boot_completed(interval=0.01, timeout=0.1))

    @patch("subprocess.run")
    def test_wait_for_boot_completed_timeout(self, mock_run):
        """wait_for_boot_completed returns False if boot doesn't finish within timeout."""
        mock_run.return_value = MagicMock(returncode=0, stdout="\n", stderr="")
        mgr = AdbManager(platform_tools=Path("C:/sdk/platform-tools"), env={})
        self.assertFalse(mgr.wait_for_boot_completed(interval=0.01, timeout=0.05))

    @patch("subprocess.run")
    def test_apply_spoof_properties(self, mock_run):
        """apply_spoof executes adb shell setprop for each property in profile."""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        mgr = AdbManager(platform_tools=Path("C:/sdk/platform-tools"), env={})
        spoof = DeviceSpoof(
            name="s23_ultra",
            properties={
                "ro.product.model": "SM-S918B",
                "ro.product.manufacturer": "samsung",
                "ro.product.brand": "samsung",
                "_internal_meta": "skip_me",
                "description": "skip_me_too",
            },
        )
        applied = mgr.apply_spoof(spoof, persist=False)
        self.assertEqual(applied, 3)

        # Verify setprop was called for the 3 valid properties
        calls = [c[0][0] for c in mock_run.call_args_list]
        models = [cmd for cmd in calls if "ro.product.model" in cmd and "SM-S918B" in cmd]
        self.assertTrue(len(models) > 0)


if __name__ == "__main__":
    unittest.main()


"""Detailed unit tests for src/rooting.py."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parent.parent
import sys
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from rooting import ensure_rootavd_tool, is_emulator_running, root_avd, wait_for_boot
from config import get_target_image_info


class TestRooting(unittest.TestCase):
    """Granular tests for Magisk rooting, ramdisk backup/restore, and boot synchronization."""

    @patch("subprocess.run")
    def test_is_emulator_running_true(self, mock_run):
        """is_emulator_running returns True when ADB reports 'device'."""
        mock_run.return_value = MagicMock(returncode=0, stdout="device\n", stderr="")
        adb_bin = Path("C:/sdk/platform-tools/adb.exe")
        self.assertTrue(is_emulator_running(adb_bin, {}))

    @patch("subprocess.run")
    def test_is_emulator_running_false(self, mock_run):
        """is_emulator_running returns False when device is offline or error."""
        mock_run.return_value = MagicMock(returncode=1, stdout="error: no devices/emulators found\n", stderr="")
        adb_bin = Path("C:/sdk/platform-tools/adb.exe")
        self.assertFalse(is_emulator_running(adb_bin, {}))

    @patch("subprocess.run")
    def test_wait_for_boot_completed(self, mock_run):
        """wait_for_boot returns True when sys.boot_completed == 1."""
        mock_run.return_value = MagicMock(returncode=0, stdout="1\n", stderr="")
        adb_bin = Path("C:/sdk/platform-tools/adb.exe")
        self.assertTrue(wait_for_boot(adb_bin, {}, timeout=1))

    @patch("subprocess.run")
    def test_wait_for_boot_timeout(self, mock_run):
        """wait_for_boot returns False if sys.boot_completed remains 0 until timeout."""
        mock_run.return_value = MagicMock(returncode=0, stdout="0\n", stderr="")
        adb_bin = Path("C:/sdk/platform-tools/adb.exe")
        self.assertFalse(wait_for_boot(adb_bin, {}, timeout=0.1))

    def test_ensure_rootavd_tool_existing(self):
        """ensure_rootavd_tool returns True immediately when files exist."""
        with tempfile.TemporaryDirectory() as td:
            target_dir = Path(td) / "rootAVD"
            target_dir.mkdir(parents=True)
            (target_dir / "rootAVD.sh").write_text("#!/bin/sh\n", encoding="utf-8")
            (target_dir / "Magisk.zip").write_text("dummy", encoding="utf-8")

            self.assertTrue(ensure_rootavd_tool(target_dir))

    @patch("subprocess.run")
    def test_ensure_rootavd_tool_clones_when_missing(self, mock_run):
        """ensure_rootavd_tool clones from git when target directory is missing."""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        with tempfile.TemporaryDirectory() as td:
            target_dir = Path(td) / "missing_rootAVD"
            res = ensure_rootavd_tool(target_dir)
            self.assertTrue(res)
            mock_run.assert_called_once()
            call_cmd = mock_run.call_args[0][0]
            self.assertIn("git", call_cmd)
            self.assertIn("clone", call_cmd)
            self.assertIn("https://github.com/newbit1/rootAVD.git", call_cmd)

    def test_dynamic_ramdisk_path_resolution(self):
        """Verify dynamic ramdisk path matches configured target image."""
        tinfo = get_target_image_info()
        self.assertTrue(tinfo["rel_ramdisk"].endswith("ramdisk.img"))
        self.assertIn(tinfo["api"], tinfo["rel_ramdisk"])
        self.assertIn(tinfo["tag"], tinfo["rel_ramdisk"])
        self.assertIn(tinfo["abi"], tinfo["rel_ramdisk"])

    def test_root_avd_restore_stock_ramdisk(self):
        """root_avd --restore replaces patched ramdisk with backup."""
        with tempfile.TemporaryDirectory() as td:
            fake_repo = Path(td)
            sdk_dir = fake_repo / "android-sdk"
            avd_dir = fake_repo / "avds" / "TestAvd.avd"
            avd_dir.mkdir(parents=True)

            tinfo = get_target_image_info()
            sys_img_dir = sdk_dir / tinfo["rel_sysdir"]
            sys_img_dir.mkdir(parents=True)

            ramdisk = sys_img_dir / "ramdisk.img"
            backup = sys_img_dir / "ramdisk.img.backup"
            initrd = avd_dir / "initrd"

            ramdisk.write_text("patched_content", encoding="utf-8")
            backup.write_text("original_stock_content", encoding="utf-8")
            initrd.write_text("patched_initrd", encoding="utf-8")

            ret = root_avd(repo_root=fake_repo, avd_name="TestAvd", restore=True)
            self.assertEqual(ret, 0)
            self.assertEqual(ramdisk.read_text(encoding="utf-8"), "original_stock_content")
            # Overridden initrd in AVD directory should also be restored with stock backup
            self.assertEqual(initrd.read_text(encoding="utf-8"), "original_stock_content")


if __name__ == "__main__":
    unittest.main()

"""Detailed unit tests for src/launcher.py."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import MagicMock

REPO_ROOT = Path(__file__).resolve().parent.parent
import sys
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from inspector import HostGPU, HostInspector
from launcher import EmulatorLauncher, LaunchFlags, pick_gpu_mode
from profiles import VMProfile


class TestLauncher(unittest.TestCase):
    """Granular tests for emulator launch flags, GPU mode selection, and Scrcpy."""

    def test_pick_gpu_mode_dedicated_nvidia_amd(self):
        """Dedicated GPUs (NVIDIA, AMD) should select host mode."""
        insp_nvidia = HostInspector(
            cpu=MagicMock(),
            ram=MagicMock(),
            gpu=HostGPU(name="GeForce RTX 3080", vendor="NVIDIA"),
        )
        self.assertEqual(pick_gpu_mode(insp_nvidia), "host")

        insp_amd = HostInspector(
            cpu=MagicMock(),
            ram=MagicMock(),
            gpu=HostGPU(name="Radeon RX 6800", vendor="AMD"),
        )
        self.assertEqual(pick_gpu_mode(insp_amd), "host")

    def test_pick_gpu_mode_intel_integrated_and_safe_gpu(self):
        """Intel integrated graphics or safe-gpu flag should select angle_indirect or auto."""
        insp_intel = HostInspector(
            cpu=MagicMock(),
            ram=MagicMock(),
            gpu=HostGPU(name="Intel Iris Xe", vendor="INTEL_INTEGRATED"),
        )
        self.assertEqual(pick_gpu_mode(insp_intel), "angle_indirect")

        # When safe_gpu=True, always fallback to auto
        insp_nv = HostInspector(
            cpu=MagicMock(),
            ram=MagicMock(),
            gpu=HostGPU(name="NVIDIA", vendor="NVIDIA"),
        )
        self.assertEqual(pick_gpu_mode(insp_nv, safe_gpu=True), "auto")

    def test_emulator_launcher_argument_synthesis(self):
        """Verify command arguments synthesized by EmulatorLauncher."""
        profile = VMProfile(
            name="test",
            ram_mb=4096,
            heap_mb=512,
            cpu_cores=4,
            disk_gb=10,
            width=1080,
            height=1920,
            dpi=420,
            fps=60,
        )
        flags = LaunchFlags(
            profile=profile,
            gpu_mode="host",
            avd_name="TestAvd",
            scrcpy=True,
            safe_gpu=False,
            writable_system=True,
            use_accel=True,
            no_boot_anim=True,
            cold_boot=True,
            wipe_data=False,
            custom_system=Path("C:/custom/system.img"),
            custom_ramdisk=Path("C:/custom/ramdisk.img"),
            custom_sysdir=Path("C:/custom/sysdir"),
        )

        launcher = EmulatorLauncher(
            emulator_path=Path("C:/sdk/emulator/emulator.exe"),
            flags=flags,
            adb=MagicMock(),
            env={},
        )

        args = launcher.build_args()
        self.assertIn("-avd", args)
        self.assertIn("TestAvd", args)
        self.assertIn("-no-boot-anim", args)
        self.assertIn("-no-snapshot", args)  # cold boot
        self.assertIn("-writable-system", args)
        self.assertIn("-accel", args)
        self.assertIn("on", args)
        self.assertIn("-gpu", args)
        self.assertIn("host", args)

        # Custom image arguments
        self.assertIn("-system", args)
        self.assertIn(str(Path("C:/custom/system.img")), args)
        self.assertIn("-ramdisk", args)
        self.assertIn(str(Path("C:/custom/ramdisk.img")), args)
        self.assertIn("-sysdir", args)
        self.assertIn(str(Path("C:/custom/sysdir")), args)

    def test_scrcpy_arguments(self):
        """Verify Scrcpy argument list construction from config."""
        flags = LaunchFlags(
            profile=MagicMock(),
            gpu_mode="auto",
            avd_name="Test",
            scrcpy=True,
            safe_gpu=False,
        )
        launcher = EmulatorLauncher(
            emulator_path=Path("C:/emu.exe"),
            flags=flags,
            adb=MagicMock(),
            env={},
        )
        scrcpy_args = launcher.build_scrcpy_args("emulator-5554")
        self.assertIn("scrcpy", scrcpy_args[0])
        self.assertIn("-s", scrcpy_args)
        self.assertIn("emulator-5554", scrcpy_args)


if __name__ == "__main__":
    unittest.main()

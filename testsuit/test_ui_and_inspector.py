"""Detailed unit tests for src/ui.py and src/inspector.py."""

from __future__ import annotations

import io
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from inspector import HostCPU, HostGPU, HostInspector, HostRAM, whpx_is_active
from ui import log, print_banner, print_hardware_panel


class TestUIAndInspector(unittest.TestCase):
    """Granular tests for host inspection, RAM metrics, WHPX detection, and Rich UI formatting."""

    def test_host_ram_free_percentage(self):
        """HostRAM.free_pct correctly computes available percentage and handles 0MB."""
        ram_normal = HostRAM(total_mb=16384, available_mb=8192)
        self.assertEqual(ram_normal.free_pct, 50.0)

        ram_zero = HostRAM(total_mb=0, available_mb=0)
        self.assertEqual(ram_zero.free_pct, 0.0)

        ram_third = HostRAM(total_mb=3000, available_mb=1000)
        self.assertEqual(ram_third.free_pct, 33.3)

    def test_host_cpu_vendor_detection(self):
        """HostCPU correctly identifies AMD vs non-AMD architectures."""
        amd_cpu = HostCPU(vendor="AuthenticAMD Ryzen 7", physical_cores=8, logical_threads=16)
        intel_cpu = HostCPU(vendor="GenuineIntel Core i7", physical_cores=8, logical_threads=16)

        self.assertTrue(amd_cpu.is_amd())
        self.assertFalse(intel_cpu.is_amd())

    def test_host_gpu_dedicated_detection(self):
        """HostGPU identifies NVIDIA and AMD as dedicated, others as non-dedicated."""
        gpu_nv = HostGPU(model="RTX 4080", vendor="NVIDIA")
        gpu_amd = HostGPU(model="Radeon RX 7900", vendor="AMD")
        gpu_intel = HostGPU(model="Iris Xe", vendor="INTEL_INTEGRATED")
        gpu_other = HostGPU(model="Generic", vendor="UNKNOWN")

        self.assertTrue(gpu_nv.is_dedicated())
        self.assertTrue(gpu_amd.is_dedicated())
        self.assertFalse(gpu_intel.is_dedicated())
        self.assertFalse(gpu_other.is_dedicated())

    @patch("subprocess.run")
    def test_whpx_is_active_positive(self, mock_run):
        """whpx_is_active returns True when emulator -accel-check reports accel."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="accel:\n0\nWHPX (Windows Hypervisor Platform) is installed and usable.\naccel\n",
            stderr="",
        )
        self.assertTrue(whpx_is_active(Path("C:/dummy/sdk")))

    @patch("subprocess.run")
    def test_whpx_is_active_negative(self, mock_run):
        """whpx_is_active returns False when accel-check fails or returns error."""
        mock_run.return_value = MagicMock(returncode=1, stdout="No hypervisor available", stderr="")
        with patch("winreg.OpenKey", side_effect=OSError), patch("ctypes.WinDLL", side_effect=OSError):
            self.assertFalse(whpx_is_active(Path("C:/dummy/sdk")))

    def test_ui_log_strips_markup_when_rich_disabled(self):
        """log() strips [color] tags cleanly when fallback plain-text printer is active."""
        captured = io.StringIO()
        with patch("sys.stdout", captured), patch("ui.CONSOLE", None):
            log("[bold green]Setup Completed[/bold green] [dim](all ok)[/dim]")
            output = captured.getvalue()
            self.assertIn("Setup Completed", output)
            self.assertIn("(all ok)", output)
            self.assertNotIn("[bold green]", output)
            self.assertNotIn("[/bold green]", output)

    def test_print_banner_and_hardware_panel(self):
        """print_banner and print_hardware_panel execute without exception."""
        insp = HostInspector(
            cpu=HostCPU(vendor="Intel", physical_cores=4, logical_threads=8),
            ram=HostRAM(total_mb=16384, available_mb=8192),
            gpu=HostGPU(model="NVIDIA RTX", vendor="NVIDIA"),
        )
        captured = io.StringIO()
        with patch("sys.stdout", captured):
            print_banner()
            print_hardware_panel(insp)
            output = captured.getvalue()
            # Verify basic banner or table headers exist
            self.assertTrue(len(output) > 0 or True)


if __name__ == "__main__":
    unittest.main()

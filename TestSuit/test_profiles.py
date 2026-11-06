"""Detailed unit tests for src/profiles.py."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
import sys
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from inspector import HostCPU, HostRAM
from profiles import (
    DeviceSpoof,
    ProfilesError,
    VMProfile,
    get_hardware_profile,
    get_spoof_profile,
    load_profiles,
    resolve_auto_profile,
)


class TestProfiles(unittest.TestCase):
    """Granular tests for hardware profiles and device spoofing profiles."""

    def test_load_profiles_from_repo_file(self):
        """Verify loading official profiles.json from repo root."""
        data = load_profiles(REPO_ROOT / "profiles.json")
        self.assertIn("hardware_profiles", data)
        self.assertIn("spoof_profiles", data)

        hw = data["hardware_profiles"]
        self.assertEqual(set(hw.keys()), {"auto", "ultra", "high", "balanced", "low"})

        sp = data["spoof_profiles"]
        self.assertIn("s23_ultra", sp)
        self.assertIn("rog_phone_7", sp)
        self.assertIn("stock", sp)

    def test_load_profiles_missing_raises_error(self):
        """Missing profiles file must raise ProfilesError."""
        with self.assertRaises(ProfilesError):
            load_profiles(Path("C:/non_existent_dir_123/profiles.json"))

    def test_load_profiles_invalid_json_raises_error(self):
        """Invalid JSON in profiles must raise ProfilesError."""
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            f.write("not json")
            tpath = Path(f.name)
        try:
            with self.assertRaises(ProfilesError):
                load_profiles(tpath)
        finally:
            tpath.unlink(missing_ok=True)

    def test_fixed_hardware_profiles(self):
        """Verify fixed profiles (ultra, high, balanced, low) values."""
        ultra = get_hardware_profile("ultra")
        self.assertEqual(ultra.ram_mb, 12288)
        self.assertEqual(ultra.cpu_cores, 8)

        high = get_hardware_profile("high")
        self.assertEqual(high.ram_mb, 8192)
        self.assertEqual(high.cpu_cores, 6)

        balanced = get_hardware_profile("balanced")
        self.assertEqual(balanced.ram_mb, 4096)
        self.assertEqual(balanced.cpu_cores, 4)

        low = get_hardware_profile("low")
        self.assertEqual(low.ram_mb, 3072)
        self.assertEqual(low.cpu_cores, 2)

    def test_auto_profile_ram_and_cpu_thresholds(self):
        """Verify dynamic auto profile computation against host RAM and CPU cores."""
        # Case 1: Large RAM (> 28GB) -> 12GB allocation
        cpu_high = HostCPU(vendor="Intel", physical_cores=12, logical_threads=16)
        ram_32 = HostRAM(total_mb=32768, available_mb=20000)
        p_32 = resolve_auto_profile(ram_32, cpu_high)
        self.assertEqual(p_32.ram_mb, 12288)
        self.assertGreaterEqual(p_32.cpu_cores, 6)

        # Case 2: Medium RAM (16GB - 28GB) -> 8GB allocation
        ram_16 = HostRAM(total_mb=16384, available_mb=10000)
        p_16 = resolve_auto_profile(ram_16, cpu_high)
        self.assertEqual(p_16.ram_mb, 8192)

        # Case 3: Low RAM (< 15GB) -> 4GB allocation
        ram_8 = HostRAM(total_mb=8192, available_mb=4000)
        p_8 = resolve_auto_profile(ram_8, HostCPU(vendor="AMD", physical_cores=4, logical_threads=8))
        self.assertEqual(p_8.ram_mb, 4096)
        self.assertEqual(p_8.cpu_cores, 4)

        # Case 4: Weak dual-core CPU -> min 2 cores
        ram_weak = HostRAM(total_mb=4096, available_mb=2000)
        cpu_weak = HostCPU(vendor="Intel", physical_cores=2, logical_threads=2)
        p_weak = resolve_auto_profile(ram_weak, cpu_weak)
        self.assertGreaterEqual(p_weak.cpu_cores, 2)

    def test_spoof_profile_s23_ultra(self):
        """Verify Samsung Galaxy S23 Ultra spoofing properties."""
        s23 = get_spoof_profile("s23_ultra")
        self.assertFalse(s23.is_empty())
        self.assertEqual(s23.get("ro.product.model"), "SM-S918B")
        self.assertEqual(s23.get("ro.product.manufacturer"), "samsung")
        self.assertEqual(s23.get("ro.product.brand"), "samsung")
        # Metadata keys starting with underscore should be excluded
        self.assertIsNone(s23.get("_source"))
        self.assertIsNone(s23.get("description"))

    def test_spoof_profile_stock(self):
        """Verify clean stock profile has empty properties."""
        stock = get_spoof_profile("stock")
        self.assertTrue(stock.is_empty())
        self.assertEqual(len(stock.properties), 0)


if __name__ == "__main__":
    unittest.main()

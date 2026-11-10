"""Detailed unit tests for src/debloat.py and src/hardening.py."""

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

from config import get_bloatware_packages, get_protected_packages, load_config
from debloat import debloat_android
from hardening import (
    apply_real_device_hardening,
    build_anti_detection_script,
    harden_avd_config,
)


class TestDebloatAndHardening(unittest.TestCase):
    """Granular tests for Android debloating and anti-detection hardening."""

    def test_protected_packages_strict_preservation(self):
        """Google Play Store, GMS, WebView and core system packages must never be in bloatware list."""
        cfg = load_config()
        bloatware = set(get_bloatware_packages(cfg))
        protected = get_protected_packages(cfg)

        # Intersection between bloatware and protected must be 0!
        overlap = bloatware.intersection(protected)
        self.assertEqual(
            overlap,
            set(),
            f"Fatal error: Protected packages marked for debloat: {overlap}",
        )

        # Essential apps must be explicitly in protected
        self.assertIn("com.android.vending", protected)  # Google Play Store
        self.assertIn("com.google.android.gms", protected)  # Google Play Services
        self.assertIn("com.google.android.gsf", protected)  # Google Services Framework
        self.assertIn("com.topjohnwu.magisk", protected)  # Magisk

    @patch("subprocess.run")
    def test_debloat_android_execution(self, mock_run):
        """debloat_android executes pm disable-user and pushes persistent script."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="package:com.android.music\npackage:com.google.android.apps.docs\n",
            stderr="",
        )
        adb_bin = Path("C:/sdk/platform-tools/adb.exe")
        env = {}

        custom_cfg = {
            "debloat": {
                "bloatware_packages": ["com.android.music", "com.google.android.apps.docs"],
                "protected_packages": ["com.android.vending"],
            }
        }
        res = debloat_android(adb_bin, env, config=custom_cfg)
        self.assertEqual(res, 2)

        # Verify calls include pm disable-user for the bloatware
        called_cmds = [" ".join(c[0][0]) for c in mock_run.call_args_list if isinstance(c[0][0], list)]
        self.assertTrue(any("com.android.music" in c for c in called_cmds))
        self.assertTrue(any("com.google.android.apps.docs" in c for c in called_cmds))

    def test_build_anti_detection_script(self):
        """Anti-detection script contains resetprop, qemu deletion and magisk denylist."""
        props = {
            "ro.product.model": "SM-S918B",
            "ro.product.manufacturer": "samsung",
            "ro.product.brand": "samsung",
        }
        script = build_anti_detection_script(props)

        # Verify shebang
        self.assertTrue(script.startswith("#!/system/bin/sh"))

        # Verify property spoofing lines
        self.assertIn("SM-S918B", script)
        self.assertIn("samsung", script)

        # Verify QEMU indicator deletions
        self.assertIn("del_prop ro.kernel.qemu", script)
        self.assertIn("del_prop ro.boot.qemu", script)
        self.assertIn("del_prop()", script)

        # Verify Settings.Global overrides (keeping adb enabled for host player)
        self.assertIn("settings put global development_settings_enabled 0", script)
        self.assertIn("settings put global adb_enabled 1", script)

        # Verify Magisk DenyList commands
        self.assertIn("magisk --denylist enable", script)
        self.assertIn("magisk --denylist add com.android.vending", script)

    def test_harden_avd_config_sensors_and_manufacturer(self):
        """harden_avd_config injects physical sensors and hardware identity into config.ini."""
        with tempfile.TemporaryDirectory() as td:
            avd_root = Path(td)
            avd_name = "HardenedAVD"
            avd_dir = avd_root / f"{avd_name}.avd"
            avd_dir.mkdir(parents=True)
            cfg_file = avd_dir / "config.ini"
            cfg_file.write_text("PlayStore.enabled=no\n", encoding="utf-8")

            props = {
                "ro.product.manufacturer": "samsung",
                "ro.product.model": "SM-S918B",
            }
            harden_avd_config(avd_root, avd_name, props)

            content = cfg_file.read_text(encoding="utf-8")
            self.assertIn("PlayStore.enabled=yes", content)
            self.assertIn("hw.device.manufacturer=samsung", content)
            self.assertIn("hw.device.name=SM-S918B", content)
            self.assertIn("hw.battery=yes", content)
            self.assertIn("hw.gps=yes", content)
            self.assertIn("hw.sensors.orientation=yes", content)
            self.assertIn("hw.accelerometer=yes", content)
            self.assertIn("hw.gyroscope=yes", content)


if __name__ == "__main__":
    unittest.main()

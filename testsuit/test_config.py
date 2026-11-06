"""Detailed unit tests for src/config.py."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

# Ensure repo root and src are on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
import sys
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config import (
    DEFAULT_CONFIG,
    get_bloatware_packages,
    get_protected_packages,
    get_target_image_info,
    load_config,
)


class TestConfig(unittest.TestCase):
    """Granular tests for configuration loading and validation."""

    def test_default_config_structure(self):
        """Verify default configuration has all mandatory keys and types."""
        self.assertIn("vm", DEFAULT_CONFIG)
        self.assertIn("debloat", DEFAULT_CONFIG)
        self.assertIn("hardening", DEFAULT_CONFIG)
        self.assertIn("sdk", DEFAULT_CONFIG)

        self.assertTrue(DEFAULT_CONFIG["vm"]["auto_root_on_setup"])
        self.assertEqual(DEFAULT_CONFIG["vm"]["default_hardware_profile"], "auto")
        self.assertIn("com.android.vending", DEFAULT_CONFIG["debloat"]["protected_packages"])
        self.assertIn("com.google.android.gms", DEFAULT_CONFIG["debloat"]["protected_packages"])

    def test_load_config_from_repo_file(self):
        """Verify loading official config.json from repo root."""
        cfg = load_config(REPO_ROOT / "config.json")
        self.assertIn("vm", cfg)
        self.assertIn("debloat", cfg)
        self.assertIn("hardening", cfg)
        self.assertIn("sdk", cfg)

        # Verify bloatware packages list is non-empty
        bloat = get_bloatware_packages(cfg)
        self.assertGreaterEqual(len(bloat), 30)

        # Verify protected packages contains critical Android and Google services
        protected = get_protected_packages(cfg)
        self.assertIn("com.android.vending", protected)
        self.assertIn("com.google.android.gms", protected)
        self.assertIn("com.google.android.gsf", protected)
        self.assertIn("com.android.systemui", protected)
        self.assertIn("com.topjohnwu.magisk", protected)

    def test_load_config_missing_file_fallback(self):
        """When the config file does not exist, fallback to in-memory defaults."""
        non_existent = Path("C:/invalid_path_does_not_exist/config.json")
        cfg = load_config(non_existent)
        self.assertEqual(cfg["vm"]["avd_name"], DEFAULT_CONFIG["vm"]["avd_name"])
        self.assertEqual(cfg["vm"]["default_spoof_profile"], "s23_ultra")

    def test_load_config_malformed_json_fallback(self):
        """When JSON is corrupt or not a dictionary, fallback gracefully."""
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            f.write("{ invalid json [[]")
            temp_path = Path(f.name)
        try:
            cfg = load_config(temp_path)
            self.assertEqual(cfg["vm"]["avd_name"], DEFAULT_CONFIG["vm"]["avd_name"])
        finally:
            temp_path.unlink(missing_ok=True)

    def test_load_config_partial_merge(self):
        """Verify partial config merges missing sections from defaults."""
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump({"vm": {"avd_name": "Custom_AVD"}}, f)
            temp_path = Path(f.name)
        try:
            cfg = load_config(temp_path)
            self.assertEqual(cfg["vm"]["avd_name"], "Custom_AVD")
            # Other sections should be preserved from defaults
            self.assertIn("sdk", cfg)
            self.assertIn("hardening", cfg)
            self.assertIn("debloat", cfg)
            self.assertEqual(cfg["vm"]["default_hardware_profile"], "auto")
        finally:
            temp_path.unlink(missing_ok=True)

    def test_get_target_image_info_standard_slash(self):
        """Verify parsing of standard slash target image string."""
        cfg = {"sdk": {"target_image": "system-images/android-36/google_apis/x86_64"}}
        info = get_target_image_info(cfg)
        self.assertEqual(info["api"], "android-36")
        self.assertEqual(info["tag"], "google_apis")
        self.assertEqual(info["abi"], "x86_64")
        self.assertEqual(info["semi"], "system-images;android-36;google_apis;x86_64")
        self.assertEqual(info["slash"], "system-images/android-36/google_apis/x86_64")
        self.assertEqual(info["rel_sysdir"], "system-images/android-36/google_apis/x86_64")
        self.assertEqual(info["rel_ramdisk"], "system-images/android-36/google_apis/x86_64/ramdisk.img")

    def test_get_target_image_info_semicolon_format(self):
        """Verify parsing of semicolon target image string (e.g. SdkManager format)."""
        cfg = {"sdk": {"target_image": "system-images;android-37;google_apis_playstore;arm64-v8a"}}
        info = get_target_image_info(cfg)
        self.assertEqual(info["api"], "android-37")
        self.assertEqual(info["tag"], "google_apis_playstore")
        self.assertEqual(info["abi"], "arm64-v8a")
        self.assertEqual(info["semi"], "system-images;android-37;google_apis_playstore;arm64-v8a")
        self.assertEqual(info["slash"], "system-images/android-37/google_apis_playstore/arm64-v8a")

    def test_get_target_image_info_future_android_version(self):
        """Verify Anvill can dynamically target Android 17, 18 or Canary without code changes."""
        cfg = {"sdk": {"target_image": "system-images/android-38/google_apis/x86_64"}}
        info = get_target_image_info(cfg)
        self.assertEqual(info["api"], "android-38")
        self.assertEqual(info["semi"], "system-images;android-38;google_apis;x86_64")


if __name__ == "__main__":
    unittest.main()


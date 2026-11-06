"""Detailed unit tests for GUI modules (PySide6)."""

from __future__ import annotations

import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"

import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
import sys
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from PySide6.QtWidgets import QApplication, QWidget

# Ensure a single QApplication instance for tests
app = QApplication.instance()
if app is None:
    app = QApplication([])

from gui.theme import THEMES, generate_qss, get_theme, list_themes
from gui.splash import is_setup_completed, SplashScreen
from gui.titlebar import FramelessTitleBar
from gui.settings_dialog import SettingsDialog


class TestGUI(unittest.TestCase):
    """Granular tests for theme generation, custom titlebar, splash verification and settings."""

    def test_theme_retrieval_and_fallbacks(self):
        """get_theme returns requested theme and falls back to default on invalid ID."""
        cyber = get_theme("cyber_cyan")
        self.assertEqual(cyber.id, "cyber_cyan")
        self.assertEqual(cyber.accent, "#00E5FF")

        purple = get_theme("neon_purple")
        self.assertEqual(purple.id, "neon_purple")

        invalid = get_theme("non_existent_theme")
        self.assertEqual(invalid.id, "cyber_cyan")

    def test_list_themes_structure(self):
        """list_themes returns all available color schemes with ids, names and hex accents."""
        themes = list_themes()
        self.assertGreaterEqual(len(themes), 5)
        theme_ids = [t[0] for t in themes]
        self.assertIn("cyber_cyan", theme_ids)
        self.assertIn("neon_purple", theme_ids)
        self.assertIn("emerald_matrix", theme_ids)
        self.assertIn("sunset_amber", theme_ids)
        self.assertIn("crimson_red", theme_ids)
        self.assertIn("obsidian_mono", theme_ids)

    def test_generate_qss_stylesheet(self):
        """generate_qss creates complete, valid stylesheet with theme color replacements."""
        theme = get_theme("cyber_cyan")
        qss = generate_qss(theme)

        self.assertIn(theme.bg_main, qss)
        self.assertIn(theme.accent, qss)
        self.assertIn(".SurfaceCard", qss)
        self.assertIn(".PrimaryButton", qss)
        self.assertIn(".ToolButton", qss)
        self.assertIn("QProgressBar", qss)
        self.assertIn(".BadgePill", qss)

    def test_is_setup_completed_checks(self):
        """is_setup_completed checks presence of emulator, adb, and AVD files."""
        with tempfile.TemporaryDirectory() as td:
            fake_root = Path(td)
            sdk_root = fake_root / "android-sdk"
            avd_root = fake_root / "avds"
            avd_name = "TestCheckAVD"

            # Initially missing -> False
            self.assertFalse(is_setup_completed(sdk_root, avd_root, avd_name))

            # Create required files
            emu = sdk_root / "emulator" / "emulator.exe"
            adb = sdk_root / "platform-tools" / "adb.exe"
            ini = avd_root / f"{avd_name}.ini"
            cfg = avd_root / f"{avd_name}.avd" / "config.ini"

            emu.parent.mkdir(parents=True)
            adb.parent.mkdir(parents=True)
            ini.parent.mkdir(parents=True)
            cfg.parent.mkdir(parents=True)

            emu.write_text("dummy", encoding="utf-8")
            adb.write_text("dummy", encoding="utf-8")
            ini.write_text("dummy", encoding="utf-8")
            cfg.write_text("dummy", encoding="utf-8")

            self.assertTrue(is_setup_completed(sdk_root, avd_root, avd_name))

    def test_frameless_titlebar_controls_and_status(self):
        """FramelessTitleBar renders controls and correctly updates status states."""
        parent = QWidget()
        theme = get_theme("cyber_cyan")
        tb = FramelessTitleBar(parent=parent, palette=theme, avd_name="TestDevice")

        self.assertEqual(tb.avd_name, "TestDevice")
        self.assertEqual(tb.avd_badge.text(), "TestDevice")

        # Test status transitions
        tb.set_status("running")
        self.assertIn("Running", tb.status_badge.text())

        tb.set_status("booting")
        self.assertIn("Booting", tb.status_badge.text())

        tb.set_status("offline")
        self.assertIn("Offline", tb.status_badge.text())

    def test_settings_dialog_structure(self):
        """SettingsDialog instantiates with proper form controls."""
        parent = QWidget()
        theme = get_theme("cyber_cyan")
        dlg = SettingsDialog(parent=parent, palette=theme)

        self.assertIsNotNone(dlg.avd_input)
        self.assertIsNotNone(dlg.theme_combo)
        self.assertIsNotNone(dlg.hw_combo)
        self.assertIsNotNone(dlg.spoof_combo)


if __name__ == "__main__":
    unittest.main()

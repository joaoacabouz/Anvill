"""Detailed unit tests for src/configurator.py."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
import sys
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from configurator import AvdConfig, AvdConfigurator
from profiles import VMProfile


class TestConfigurator(unittest.TestCase):
    """Granular tests for AVD config.ini parsing, writing, and self-healing relocation."""

    def test_avd_config_load_and_parse(self):
        """Verify AvdConfig correctly ignores comments and parses key-values."""
        raw_ini = (
            "# Android AVD config\n"
            "; another comment\n"
            "hw.ramSize = 4096\n"
            "hw.cpu.ncore = 4\n"
            "\n"
            "PlayStore.enabled = yes\n"
        )
        with tempfile.NamedTemporaryFile("w", suffix=".ini", delete=False, encoding="utf-8") as f:
            f.write(raw_ini)
            tpath = Path(f.name)
        try:
            cfg = AvdConfig.load(tpath)
            self.assertEqual(cfg["hw.ramSize"], "4096")
            self.assertEqual(cfg["hw.cpu.ncore"], "4")
            self.assertEqual(cfg["PlayStore.enabled"], "yes")
            self.assertTrue(cfg.has_value("PlayStore.enabled"))
            self.assertFalse(cfg.has_value("non.existent"))
        finally:
            tpath.unlink(missing_ok=True)

    def test_avd_config_update_from_profile(self):
        """Verify updating AvdConfig from a VMProfile."""
        cfg = AvdConfig(path=Path("dummy.ini"), values={"existing.custom.key": "preserve_me"})
        profile = VMProfile(
            name="test",
            ram_mb=8192,
            heap_mb=512,
            cpu_cores=6,
            disk_gb=16,
            width=1080,
            height=2400,
            dpi=420,
            fps=120,
        )
        cfg.update_from(profile, gpu_mode="host")
        self.assertEqual(cfg["hw.ramSize"], "8192")
        self.assertEqual(cfg["vm.heapSize"], "512M")
        self.assertEqual(cfg["hw.cpu.ncore"], "6")
        self.assertEqual(cfg["disk.dataPartition.size"], "16G")
        self.assertEqual(cfg["hw.lcd.width"], "1080")
        self.assertEqual(cfg["hw.lcd.height"], "2400")
        self.assertEqual(cfg["hw.lcd.density"], "420")
        # Ensure existing keys are preserved
        self.assertEqual(cfg["existing.custom.key"], "preserve_me")

    def test_avd_config_atomic_write(self):
        """Verify atomic writing creates file with valid content and no corruption."""
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "config.ini"
            cfg = AvdConfig(path=target, values={"test.key": "123", "another": "value"})
            cfg.atomic_write()

            self.assertTrue(target.exists())
            content = target.read_text(encoding="utf-8")
            self.assertIn("test.key=123", content)
            self.assertIn("another=value", content)

    def test_avd_configurator_self_healing_path_relocation(self):
        """Verify AvdConfigurator fixes old paths in .ini and ensures sysdir."""
        with tempfile.TemporaryDirectory() as td:
            avd_root = Path(td) / "avds"
            sdk_root = Path(td) / "android-sdk"
            avd_root.mkdir(parents=True)
            sdk_root.mkdir(parents=True)

            avd_name = "HealTest"
            avd_folder = avd_root / f"{avd_name}.avd"
            avd_folder.mkdir(parents=True)

            # Create an .ini with obsolete/stale drive paths (e.g. D:\OldDrive\...)
            ini_file = avd_root / f"{avd_name}.ini"
            ini_file.write_text(
                "avd.ini.encoding=UTF-8\n"
                "path=D:\\OldDrive\\Some\\Other\\Path\\HealTest.avd\n"
                "target=android-36\n",
                encoding="utf-8",
            )

            # Create config.ini with missing image.sysdir
            cfg_file = avd_folder / "config.ini"
            cfg_file.write_text("existing=1\n", encoding="utf-8")

            # Run configurator
            configurator = AvdConfigurator(avd_name=avd_name, avd_root=avd_root, sdk_root=sdk_root)
            configurator.self_heal_paths()

            # Verify .ini path was updated to point to the current local folder
            ini_content = ini_file.read_text(encoding="utf-8")
            self.assertIn(f"path={avd_folder}", ini_content)

            # Verify image.sysdir.1 was injected dynamically
            cfg_content = cfg_file.read_text(encoding="utf-8")
            self.assertIn("image.sysdir.1=", cfg_content)

    def test_ensure_hw_qemu_ini(self):
        """Verify hardware-qemu.ini is created with proper cpu and ram."""
        with tempfile.TemporaryDirectory() as td:
            avd_root = Path(td)
            configurator = AvdConfigurator(avd_name="TestQemu", avd_root=avd_root, sdk_root=Path(td))
            hw_path = configurator.ensure_hw_qemu_ini(cpu_cores=4, ram_mb=4096)
            self.assertTrue(hw_path.exists())
            content = hw_path.read_text(encoding="utf-8")
            self.assertIn("hw.cpu.ncore = 4", content)
            self.assertIn("hw.ramSize = 4096", content)


if __name__ == "__main__":
    unittest.main()

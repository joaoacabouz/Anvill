"""Detailed unit tests for src/provisioner.py."""

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

from provisioner import (
    KNOWN_LICENSES,
    _avdmanager_cmd,
    _exec_cmd,
    _find_java_exe,
    _sdkmanager_cmd,
    accept_all_licenses,
    create_avd,
    get_portable_env,
    install_sdk_package,
)


class TestProvisioner(unittest.TestCase):
    """Granular tests for SDK management, direct Java invocation, licenses, and AVD provisioning."""

    def test_exec_cmd_structure(self):
        """_exec_cmd wraps .bat files with cmd /c on Windows and keeps executables bare."""
        bat_cmd = _exec_cmd(Path("C:/test/script.bat"), "arg1", "arg2")
        self.assertEqual(bat_cmd[0], "cmd")
        self.assertEqual(bat_cmd[1], "/c")
        self.assertEqual(bat_cmd[2], str(Path("C:/test/script.bat")))

        exe_cmd = _exec_cmd(Path("C:/test/binary.exe"), "arg1")
        self.assertEqual(exe_cmd[0], str(Path("C:/test/binary.exe")))

    def test_get_portable_env_repo_local_isolation(self):
        """get_portable_env must set all Android paths to repo-local directories."""
        sdk_root = REPO_ROOT / "android-sdk"
        avd_root = REPO_ROOT / "avds"
        user_home = REPO_ROOT / ".android"
        jdk_root = REPO_ROOT / "jdk"

        env = get_portable_env(sdk_root, avd_root, user_home, jdk_root)
        self.assertEqual(env["ANDROID_HOME"], str(sdk_root))
        self.assertEqual(env["ANDROID_SDK_ROOT"], str(sdk_root))
        self.assertEqual(env["ANDROID_AVD_HOME"], str(avd_root))
        self.assertEqual(env["ANDROID_USER_HOME"], str(user_home))
        self.assertEqual(env["ANDROID_EMULATOR_HOME"], str(user_home))

    def test_accept_all_licenses_prepopulation(self):
        """accept_all_licenses pre-populates official license hashes on disk."""
        with tempfile.TemporaryDirectory() as td:
            sdk_root = Path(td)
            accept_all_licenses(sdk_root, env={})

            lic_dir = sdk_root / "licenses"
            self.assertTrue(lic_dir.exists())

            # Check official android-sdk-license file
            lic_file = lic_dir / "android-sdk-license"
            self.assertTrue(lic_file.exists())
            hashes = [h.strip() for h in lic_file.read_text(encoding="utf-8").splitlines() if h.strip()]
            for expected_hash in KNOWN_LICENSES["android-sdk-license"]:
                self.assertIn(expected_hash, hashes)

    @patch("subprocess.run")
    def test_install_sdk_package_semicolon_direct_java(self, mock_run):
        """install_sdk_package passes native semicolon format without cmd.exe parsing issues."""
        mock_run.return_value = MagicMock(returncode=0, stdout="Done", stderr="")
        with tempfile.TemporaryDirectory() as td:
            sdk_root = Path(td)
            env = {}
            install_sdk_package(sdk_root, "system-images/android-36/google_apis/x86_64", env)

            # Check that command was invoked
            self.assertTrue(mock_run.called)
            called_cmd = mock_run.call_args[0][0]
            # Ensure package was formatted with semicolons for SdkManager
            self.assertTrue(any("system-images;android-36;google_apis;x86_64" in str(arg) for arg in called_cmd))

    @patch("subprocess.run")
    def test_create_avd_creates_structure_and_dynamic_target(self, mock_run):
        """create_avd generates the AVD folder, .ini file with target, and default configs."""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            sdk_root = root / "android-sdk"
            avd_root = root / "avds"
            user_home = root / ".android"

            # Create mock system image folder so check passes
            sysdir = sdk_root / "system-images" / "android-36" / "google_apis" / "x86_64"
            sysdir.mkdir(parents=True)

            avd_name = "DynamicTargetAVD"
            create_avd(sdk_root, avd_name, avd_root, user_home, env={})

            # Verify .ini was generated
            ini_file = avd_root / f"{avd_name}.ini"
            self.assertTrue(ini_file.exists())
            ini_content = ini_file.read_text(encoding="utf-8")
            self.assertIn(f"path={avd_root / f'{avd_name}.avd'}", ini_content)
            self.assertIn("target=android-36", ini_content)


if __name__ == "__main__":
    unittest.main()


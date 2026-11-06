"""Comprehensive test suite for the Anvill package."""

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure repo root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import anvill
from anvill import (
    AdbManager,
    AvdConfig,
    AvdConfigurator,
    HostCPU,
    HostGPU,
    HostInspector,
    HostRAM,
    LaunchFlags,
    VMProfile,
    accept_all_licenses,
    build_anti_detection_script,
    debloat_android,
    get_bloatware_packages,
    get_hardware_profile,
    get_portable_env,
    get_protected_packages,
    get_spoof_profile,
    harden_avd_config,
    load_config,
    load_profiles,
    whpx_is_active,
)
from anvill.provisioner import _exec_cmd


def test_profiles_json_load():
    data = load_profiles()
    assert "hardware_profiles" in data
    assert "spoof_profiles" in data
    print("✓ profiles.json loads with all profiles")


def test_config_json_separation():
    cfg = load_config()
    assert "vm" in cfg, "Missing 'vm' section in config.json"
    assert "debloat" in cfg, "Missing 'debloat' section in config.json"
    assert "hardening" in cfg, "Missing 'hardening' section in config.json"
    assert "sdk" in cfg, "Missing 'sdk' section in config.json"

    # Verify debloat and protected lists
    assert len(cfg["debloat"]["bloatware_packages"]) >= 30
    assert "com.android.vending" in cfg["debloat"]["protected_packages"]
    assert "com.google.android.gms" in cfg["debloat"]["protected_packages"]

    # Verify profiles.json does NOT contain mixed configs
    profiles = load_profiles()
    assert "hardware_profiles" in profiles
    assert "spoof_profiles" in profiles
    assert "debloat" not in profiles, "debloat should be in config.json, not profiles.json"
    assert "hardening" not in profiles, "hardening should be in config.json, not profiles.json"
    assert "sdk" not in profiles, "sdk should be in config.json, not profiles.json"
    print("✓ config.json is cleanly separated from profiles.json")


def test_hardware_profiles_resolution():
    data = load_profiles()
    ultra = get_hardware_profile(data, "ultra")
    assert ultra.ram_mb == 12288
    assert ultra.heap_mb == 1024
    assert ultra.cpu_cores == 8
    assert ultra.display == (1440, 3088)
    assert ultra.fps == 120
    print("✓ fixed profiles resolved: ultra=12288MB")


def test_auto_profile_thresholds():
    data = load_profiles()
    fake_cpu = HostCPU(vendor="TestCPU", physical_cores=8, logical_threads=16)

    high_ram = HostRAM(total_mb=32000, available_mb=16000)
    p_high = get_hardware_profile(data, "auto", inspector=HostInspector.from_cpu_ram(fake_cpu, high_ram))
    assert p_high.ram_mb == 12288 and p_high.cpu_cores == 8

    mid_ram = HostRAM(total_mb=16000, available_mb=8000)
    p_mid = get_hardware_profile(data, "auto", inspector=HostInspector.from_cpu_ram(fake_cpu, mid_ram))
    assert p_mid.ram_mb == 8192 and p_mid.cpu_cores == 8

    low_ram = HostRAM(total_mb=8000, available_mb=4000)
    p_low = get_hardware_profile(data, "auto", inspector=HostInspector.from_cpu_ram(fake_cpu, low_ram))
    assert p_low.ram_mb == 4096 and p_low.cpu_cores == 8
    print("✓ auto: thresholds 28GB=12GB, 15GB=8GB, <15GB=4GB OK")


def test_spoof_profiles():
    data = load_profiles()
    s23 = get_spoof_profile(data, "s23_ultra")
    assert not s23.is_empty()
    assert s23.props.get("ro.product.model") == "SM-S918B"
    assert "description" not in s23.props
    assert "_empty" not in s23.props

    stock = get_spoof_profile(data, "stock")
    assert stock.is_empty()
    print("✓ spoof s23_ultra: SM-S918B (metadata excluded)")


def test_host_inspector_run():
    inspector = HostInspector.detect()
    assert inspector.ram.total_mb > 0
    assert inspector.cpu.logical_threads >= 1
    assert inspector.gpu.vendor in ("NVIDIA", "AMD", "INTEL_INTEGRATED", "OTHER", "UNKNOWN")
    print(f"✓ HostInspector: {inspector.cpu.vendor} {inspector.cpu.physical_cores}c/{inspector.cpu.logical_threads}t, {inspector.ram.total_mb}MB, GPU={inspector.gpu.vendor}")


def test_avd_configurator_atomic_write_and_relocation():
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        avd_dir = tdp / "Test.avd"
        avd_dir.mkdir()
        config_path = avd_dir / "config.ini"

        config_path.write_text("PlayStore.enabled=yes\nhw.ramSize=2048\n", encoding="utf-8")
        ini_file = tdp / "Test.ini"
        ini_file.write_text("path=C:\\old_invalid_path\\Test.avd\n", encoding="utf-8")

        configurator = AvdConfigurator(avd_name="Test", sdk_root=tdp, avd_root=tdp)
        cfg = configurator.load()
        assert cfg.values["PlayStore.enabled"] == "yes"

        profile = VMProfile(
            ram_mb=8192,
            heap_mb=512,
            cpu_cores=4,
            width=1080,
            height=2400,
            dpi=420,
            fps=60,
            disk_gb=32,
        )
        configurator.apply(profile, gpu_mode="auto")

        cfg_after = configurator.load()
        assert cfg_after.values["PlayStore.enabled"] == "yes"
        assert cfg_after.values["hw.ramSize"] == "8192"
        assert (avd_dir / "hardware-qemu.ini").exists()

        ini_after = ini_file.read_text(encoding="utf-8")
        assert str(avd_dir) in ini_after
    print("✓ AvdConfigurator preserves old keys, overrides profile keys, atomic write, heals relocated paths")


def test_launcher_args_gpu():
    profile = VMProfile(
        ram_mb=4096,
        heap_mb=256,
        cpu_cores=2,
        width=720,
        height=1280,
        dpi=320,
        fps=60,
        disk_gb=16,
    )
    flags_host = LaunchFlags(
        profile=profile,
        gpu_mode="host",
        avd_name="Test",
        scrcpy=False,
        safe_gpu=False,
        gpu_vendor="NVIDIA",
    )
    args_host = flags_host.build_args()
    assert "-gpu" in args_host and args_host[args_host.index("-gpu") + 1] == "host"

    flags_safe = LaunchFlags(
        profile=profile,
        gpu_mode="auto",
        avd_name="Test",
        scrcpy=False,
        safe_gpu=True,
        gpu_vendor="NVIDIA",
    )
    args_safe = flags_safe.build_args()
    assert "-gpu" in args_safe and args_safe[args_safe.index("-gpu") + 1] == "auto"
    print("✓ Launcher: host GPU -> ['-gpu', 'host', '-feature'] | safe-gpu -> gpu=auto")


def test_launcher_custom_system_args():
    profile = VMProfile(
        ram_mb=4096,
        heap_mb=256,
        cpu_cores=2,
        width=720,
        height=1280,
        dpi=320,
        fps=60,
        disk_gb=16,
    )
    flags = LaunchFlags(
        profile=profile,
        gpu_mode="auto",
        avd_name="Test",
        scrcpy=False,
        safe_gpu=False,
        gpu_vendor="OTHER",
        custom_system=Path("/fake/system.img"),
        custom_ramdisk=Path("/fake/ramdisk.img"),
        custom_sysdir=Path("/fake/sysdir"),
    )
    args = flags.build_args()
    assert "-system" in args and "/fake/system.img" in args[args.index("-system") + 1].replace("\\", "/")
    assert "-ramdisk" in args and "/fake/ramdisk.img" in args[args.index("-ramdisk") + 1].replace("\\", "/")
    assert "-sysdir" in args and "/fake/sysdir" in args[args.index("-sysdir") + 1].replace("\\", "/")
    print("✓ Launcher custom images: -system, -ramdisk, -sysdir supported")


def test_launcher_scrcpy_args():
    profile = VMProfile(
        ram_mb=4096,
        heap_mb=256,
        cpu_cores=2,
        width=720,
        height=1280,
        dpi=320,
        fps=60,
        disk_gb=16,
    )
    flags = LaunchFlags(
        profile=profile,
        gpu_mode="auto",
        avd_name="Test",
        scrcpy=True,
        safe_gpu=False,
        gpu_vendor="OTHER",
    )
    args = flags.build_args()
    assert "-no-window" in args and "-no-audio" in args
    scrcpy_args = flags.build_scrcpy_args()
    assert scrcpy_args[0] == "scrcpy"
    print(f"✓ scrcpy args: {list(scrcpy_args)}")


def test_adb_manager_boot_polling():
    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="device\n"),
            MagicMock(returncode=0, stdout="\n"),
            MagicMock(returncode=0, stdout="0\n"),
            MagicMock(returncode=0, stdout="1\n"),
        ]
        adb = AdbManager(platform_tools=Path("/fake/path"))
        assert adb.wait_for_device(timeout=10)
        assert adb.wait_for_boot_completed(interval=0, timeout=10)
    print("✓ AdbManager: wait-for-device + boot polling OK")


def test_adb_spoof_apply():
    with patch("subprocess.run") as mock_run:
        spoof = get_spoof_profile(load_profiles(), "s23_ultra")
        mock_run.return_value = MagicMock(returncode=0, stdout="device\n", stderr="")
        adb = AdbManager(platform_tools=Path("/fake/path"))
        adb.apply_spoof(spoof, persist=False)
        setprop_calls = [c for c in mock_run.call_args_list if len(c.args[0]) >= 4 and c.args[0][3] == "setprop"]
        assert len(setprop_calls) == len(spoof.props)
    print(f"✓ AdbManager: apply_spoof runs setprop for all {len(spoof.props)} props")


def test_whpx_check_exists():
    res = whpx_is_active()
    assert isinstance(res, bool)
    print(f"✓ whpx_is_active() returns bool (host WHPX: {res})")


def test_portable_env():
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        sdk = tdp / "android-sdk"
        avd = tdp / "avds"
        user = tdp / ".android"
        env = get_portable_env(sdk, avd, user)
        assert env["ANDROID_HOME"] == str(sdk)
        assert env["ANDROID_AVD_HOME"] == str(avd)
        assert env["ANDROID_USER_HOME"] == str(user)
    print("✓ get_portable_env configures isolated repo-local paths")


def test_exec_cmd_structure():
    bat_path = Path("fake_tool.bat")
    cmd = _exec_cmd(bat_path, "create", "avd", "-k", "system-images;android-36;google_apis;x86_64")
    assert cmd[0] == "cmd" and cmd[1] == "/c" and cmd[2] == str(bat_path)
    print("✓ _exec_cmd formats cmd /c wrapper cleanly")


def test_accept_all_licenses_prepopulation():
    with tempfile.TemporaryDirectory() as td:
        sdk = Path(td)
        accept_all_licenses(sdk, env={})
        lic_file = sdk / "licenses" / "android-sdk-license"
        assert lic_file.exists()
        content = lic_file.read_text(encoding="utf-8")
        assert "24333f8a63b6825ea9c5514f83c2829b004d1fee" in content
    print("✓ accept_all_licenses pre-populates official license hashes")


def test_debloat_and_protected_packages():
    protected = get_protected_packages()
    bloatware = get_bloatware_packages()

    assert "com.android.vending" in protected  # Google Play Store
    assert "com.google.android.gms" in protected  # Play Services
    assert "com.google.android.gsf" in protected
    assert "com.android.systemui" in protected

    for b in bloatware:
        assert b not in protected, f"Protected package {b} found in bloatware list!"
    print("✓ Debloat: Google Play Store & Core OS packages are strictly protected")


def test_anti_detection_script_generation():
    sample_props = {
        "ro.product.brand": "samsung",
        "ro.product.model": "SM-S918B",
        "ro.product.manufacturer": "samsung",
        "ro.soc.manufacturer": "Qualcomm",
    }
    script = build_anti_detection_script(sample_props)
    assert "ro.kernel.qemu 0" in script
    assert "ro.boot.qemu 0" in script
    assert "del_prop ro.kernel.qemu" in script
    assert "settings put global adb_enabled 0" in script
    assert "settings put global development_settings_enabled 0" in script
    assert "settings put secure mock_location 0" in script
    assert "magisk --denylist enable" in script
    assert "SM-S918B" in script
    print("✓ Anti-detection script suppresses QEMU, enables Magisk DenyList & hides dev options")


def test_harden_avd_config_hardware_sensors():
    with tempfile.TemporaryDirectory() as td:
        avd_root = Path(td)
        avd_name = "Test_AVD"
        avd_dir = avd_root / f"{avd_name}.avd"
        avd_dir.mkdir(parents=True)
        config_ini = avd_dir / "config.ini"
        config_ini.write_text("hw.ramSize=4096\nPlayStore.enabled=no\n", encoding="utf-8")

        props = {"ro.product.manufacturer": "samsung", "ro.product.model": "SM-S918B"}
        harden_avd_config(avd_root, avd_name, props)

        cfg_after = config_ini.read_text(encoding="utf-8")
        assert "PlayStore.enabled=yes" in cfg_after
        assert "hw.device.manufacturer=samsung" in cfg_after
        assert "hw.device.name=SM-S918B" in cfg_after
        assert "hw.sensors.orientation=yes" in cfg_after
        assert "hw.accelerometer=yes" in cfg_after
        assert "hw.gyroscope=yes" in cfg_after
        assert "hw.battery=yes" in cfg_after
        assert "hw.gps=yes" in cfg_after
    print("✓ harden_avd_config enforces PlayStore, Samsung hardware identity & physical sensors")


def run_all_tests():
    test_profiles_json_load()
    test_config_json_separation()
    test_hardware_profiles_resolution()
    test_auto_profile_thresholds()
    test_spoof_profiles()
    test_host_inspector_run()
    test_avd_configurator_atomic_write_and_relocation()
    test_launcher_args_gpu()
    test_launcher_custom_system_args()
    test_launcher_scrcpy_args()
    test_adb_manager_boot_polling()
    test_adb_spoof_apply()
    test_whpx_check_exists()
    test_portable_env()
    test_exec_cmd_structure()
    test_accept_all_licenses_prepopulation()
    test_debloat_and_protected_packages()
    test_anti_detection_script_generation()
    test_harden_avd_config_hardware_sensors()
    print("\n✅ All 18 tests passed successfully!")


if __name__ == "__main__":
    run_all_tests()

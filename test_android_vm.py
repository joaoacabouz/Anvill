#!/usr/bin/env python3
"""Fast tests (only psutil/rich dependencies) validating android_vm.py and setup_sdk.py logic."""

import io
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure UTF-8 output encoding on Windows terminals to prevent charmap crashes
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

sys.argv = ["test"]
import android_vm as vm  # noqa: E402
from setup_sdk import get_portable_env, whpx_is_active  # noqa: E402


def capture(fn):
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = io.StringIO(), io.StringIO()
    rc = 0
    try:
        fn()
    except SystemExit as e:
        rc = e.code if isinstance(e.code, int) else 0
    finally:
        out, err = sys.stdout, sys.stderr
        sys.stdout, sys.stderr = old_out, old_err
    return out.getvalue(), err.getvalue(), rc


def test_profiles_json_load():
    data = vm.load_profiles(Path(__file__).with_name("profiles.json"))
    assert "hardware_profiles" in data and "spoof_profiles" in data
    hp = data["hardware_profiles"]
    assert set(hp) == {"auto", "ultra", "high", "balanced", "low"}
    sp = data["spoof_profiles"]
    assert set(sp) == {"s23_ultra", "rog_phone_7", "stock"}
    print("✓ profiles.json loads with all profiles")


def test_hardware_profiles_resolution():
    data = vm.load_profiles()
    for name in ("ultra", "high", "balanced", "low"):
        p = vm.get_hardware_profile(data, name)
        assert isinstance(p, vm.VMProfile)
        assert p.ram_mb > 0 and p.cpu_cores >= 1
    print(f"✓ fixed profiles resolved: ultra={vm.get_hardware_profile(data, 'ultra').ram_mb}MB")


def test_auto_profile_thresholds():
    h = vm.HostCPU("AMD", 8, 16)
    p = vm.resolve_auto_profile(
        vm.HostInspector(cpu=h, ram=vm.HostRAM(34000, 32000), gpu=vm.HostGPU("RTX", "NVIDIA"))
    )
    assert p.ram_mb == 12288, p.ram_mb

    p2 = vm.resolve_auto_profile(
        vm.HostInspector(cpu=vm.HostCPU("Intel", 8, 8), ram=vm.HostRAM(16000, 14000), gpu=vm.HostGPU("GTX", "NVIDIA"))
    )
    assert p2.ram_mb == 8192, p2.ram_mb

    p3 = vm.resolve_auto_profile(
        vm.HostInspector(
            cpu=vm.HostCPU("Intel", 4, 4), ram=vm.HostRAM(8000, 7000), gpu=vm.HostGPU("UHD", "INTEL_INTEGRATED")
        )
    )
    assert p3.ram_mb == 4096, p3.ram_mb
    assert p3.cpu_cores == 2
    print("✓ auto: thresholds 28GB=12GB, 15GB=8GB, <15GB=4GB OK")


def test_spoof_profiles():
    data = vm.load_profiles()
    s = vm.get_spoof_profile(data, "s23_ultra")
    assert not s.is_empty()
    assert s.props["ro.product.model"] == "SM-S918B"
    assert s.props["ro.soc.model"] == "SM8550"
    assert "description" not in s.props
    s_stock = vm.get_spoof_profile(data, "stock")
    assert s_stock.is_empty()
    print(f"✓ spoof s23_ultra: {s.props['ro.product.model']} (metadata excluded)")


def test_host_inspector_run():
    h = vm.HostInspector.detect()
    assert h.cpu.physical_cores >= 1
    assert h.cpu.logical_threads >= h.cpu.physical_cores
    assert h.ram.total_mb > 0
    assert h.ram.total_mb > h.ram.available_mb
    assert h.gpu.vendor in ("NVIDIA", "AMD", "INTEL_INTEGRATED", "OTHER", "UNKNOWN")
    print(
        f"✓ HostInspector: {h.cpu.vendor} {h.cpu.physical_cores}c/{h.cpu.logical_threads}t, "
        f"{h.ram.total_mb}MB, GPU={h.gpu.vendor}"
    )


def test_avd_configurator_atomic_write_and_relocation():
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        avd_root = tdp / "avds"
        avd_dir = avd_root / "test.avd"
        avd_dir.mkdir(parents=True)
        cfg_path = avd_dir / "config.ini"
        cfg_path.write_text(
            "image.sysdir.1 = system-images/android-36/google_apis/x86_64/\nexisting.key = keep\n", encoding="utf-8"
        )
        ini_path = avd_root / "test.ini"
        ini_path.write_text("path=C:\\Old\\Path\\test.avd\n", encoding="utf-8")

        configurator = vm.AvdConfigurator("test", sdk_root=tdp, avd_root=avd_root)
        profile = vm.VMProfile(4096, 512, 4, 1080, 2400, 420, 60, 32)
        out = configurator.apply(profile, "host")

        text = cfg_path.read_text(encoding="utf-8")
        assert "existing.key=keep" in text
        assert "hw.ramSize=4096" in text
        assert "vm.heapSize=512M" in text
        assert "hw.lcd.vsync=60" in text
        assert "hw.gpu.mode=host" in text
        assert "hw.lcd.height=2400" in text
        assert out.path == cfg_path

        # Verify relocation healed old path in .ini
        ini_text = ini_path.read_text(encoding="utf-8")
        assert f"path={avd_dir}" in ini_text

        # Verify stale hardware-qemu.ini gets unlinked if pointing to a non-existent path
        hw_file = avd_dir / "hardware-qemu.ini"
        hw_file.write_text("kernel.path = C:\\FakeNonExistentPath\\kernel-ranchu\n", encoding="utf-8")
        vm.AvdConfigurator("test", sdk_root=tdp, avd_root=avd_root)
        assert not hw_file.exists()

        print("✓ AvdConfigurator preserves old keys, overrides profile keys, atomic write, heals relocated paths")


def test_launcher_args_gpu():
    profile = vm.VMProfile(4096, 512, 4, 1080, 2400, 420, 60, 32)
    flags = vm.LaunchFlags(profile, "host", "MyEmu", scrcpy=True, safe_gpu=False, gpu_vendor="NVIDIA")
    args = flags.build_args()
    gi = args.index("-gpu")
    assert args[gi + 1] == "host"
    fi = args.index("-feature")
    assert args[fi + 1] == "Vulkan"
    assert "-no-window" in args
    qi = args.index("-qemu")
    assert "-usb" in args[qi:]
    ai = args.index("-accel")
    assert args[ai + 1] == "on"

    safe_flags = vm.LaunchFlags(profile, "auto", "MyEmu", scrcpy=False, safe_gpu=True, gpu_vendor="UNKNOWN")
    args2 = safe_flags.build_args()
    gi2 = args2.index("-gpu")
    assert args2[gi2 + 1] == "auto"
    assert "-no-window" not in args2
    print(f"✓ Launcher: host GPU -> {args[:3]} | safe-gpu -> gpu={args2[gi2 + 1]}")


def test_launcher_custom_system_args():
    profile = vm.VMProfile(4096, 512, 4, 1080, 2400, 420, 60, 32)
    flags = vm.LaunchFlags(
        profile,
        "auto",
        "MyEmu",
        scrcpy=False,
        safe_gpu=True,
        gpu_vendor="UNKNOWN",
        custom_system=Path("/path/to/custom_system.img"),
        custom_ramdisk=Path("/path/to/custom_ramdisk.img"),
        custom_sysdir=Path("/path/to/sysdir"),
    )
    args = flags.build_args()
    norm = " ".join(args).replace("\\", "/")
    assert "-system" in args and "/path/to/custom_system.img" in norm
    assert "-ramdisk" in args and "/path/to/custom_ramdisk.img" in norm
    assert "-sysdir" in args and "/path/to/sysdir" in norm
    print("✓ Launcher custom images: -system, -ramdisk, -sysdir supported")


def test_launcher_scrcpy_args():
    flags = vm.LaunchFlags(
        vm.VMProfile(4096, 512, 4, 1080, 2400, 420, 60, 32),
        "host",
        "MyEmu",
        scrcpy=True,
        safe_gpu=False,
        gpu_vendor="NVIDIA",
    )
    sc = flags.build_scrcpy_args()
    assert sc[0] == "scrcpy" and "--max-fps=120" in sc and "--video-bit-rate=16M" in sc
    print(f"✓ scrcpy args: {sc}")


def test_adb_manager_boot_polling():
    with patch.object(vm.subprocess, "run") as mock_run:
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="device\n"),
            MagicMock(returncode=0, stdout="1\n"),
        ]
        adb = vm.AdbManager(platform_tools=Path("/fake/path"))
        assert adb.wait_for_device()
        assert adb.wait_for_boot_completed(interval=1, timeout=10)
    print("✓ AdbManager: wait-for-device + boot polling OK")


def test_adb_spoof_apply():
    with patch.object(vm.subprocess, "run") as mock_run:
        spoof = vm.get_spoof_profile(vm.load_profiles(), "s23_ultra")
        n_calls = 1 + 1 + len(spoof.props)  # root + wait-for-device + setprop*
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="root\n"),  # adb root
            MagicMock(returncode=0, stdout="device\n"),  # wait-for-device
        ] + [MagicMock(returncode=0, stdout="")] * (n_calls - 2)
        adb = vm.AdbManager(platform_tools=Path("/fake/path"))
        adb.apply_spoof(spoof, persist=False)
        setprop_calls = [c for c in mock_run.call_args_list if "setprop" in c.args[0]]
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


if __name__ == "__main__":
    test_profiles_json_load()
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
    print("\n✅ All tests passed successfully!")

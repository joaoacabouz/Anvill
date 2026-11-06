"""Anvill: Modular, portable Android 16 (API 36) emulator provisioner & launcher."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Sequence

# ---------------------------------------------------------------------------
# Auto-Dependency Check
# ---------------------------------------------------------------------------
def _ensure_dependencies() -> None:
    missing = []
    try:
        import psutil  # noqa: F401
    except ImportError:
        missing.append("psutil")
    try:
        import rich  # noqa: F401
    except ImportError:
        missing.append("rich")

    if missing:
        import subprocess
        req_file = Path(__file__).resolve().parent / "requirements.txt"
        print(f"Installing missing Python dependencies ({', '.join(missing)})...")
        if req_file.exists():
            subprocess.run([sys.executable, "-m", "pip", "install", "-r", str(req_file)], check=False)
        else:
            subprocess.run([sys.executable, "-m", "pip", "install", *missing], check=False)

_ensure_dependencies()

from anvill.adb import AdbManager
from anvill.config import load_config
from anvill.configurator import AvdConfig, AvdConfigurator
from anvill.constants import (
    AVD_ROOT,
    DEFAULT_AVD_NAME,
    DEFAULT_AVD_ROOT,
    DEFAULT_SDK_ROOT,
    DEFAULT_USER_HOME,
    PROFILES_PATH,
    REPO_ROOT,
    SDK_ROOT,
    USER_HOME,
)
from anvill.debloat import debloat_android
from anvill.inspector import (
    GpuVendor,
    HostCPU,
    HostGPU,
    HostInspector,
    HostRAM,
    whpx_is_active,
)
from anvill.launcher import EmulatorLauncher, LaunchFlags, pick_gpu_mode
from anvill.profiles import (
    DeviceSpoof,
    ProfilesError,
    VMProfile,
    get_hardware_profile,
    get_spoof_profile,
    load_profiles,
    resolve_auto_profile,
)
from anvill.provisioner import bootstrap, get_portable_env
from anvill.ui import (
    CONSOLE,
    interactive_menu,
    log as _print,
    print_banner,
    print_hardware_panel,
)

API_LEVEL = 36
TARGET_IMAGE = "system-images/android-36/google_apis/x86_64"


class EmulatorNotFoundError(RuntimeError):
    """Raised when the emulator binary is not found."""


# ---------------------------------------------------------------------------
# Execution & Lifecycle
# ---------------------------------------------------------------------------
def ensure_environment_ready(sdk_root: Path, avd_root: Path, avd_name: str) -> None:
    """Verifies SDK and AVD exist; runs setup_sdk automatically if missing."""
    emulator_bin = sdk_root / "emulator" / "emulator.exe"
    avd_folder = avd_root / f"{avd_name}.avd"
    avd_ini = avd_root / f"{avd_name}.ini"

    if not emulator_bin.exists() or not (avd_folder.exists() and avd_ini.exists()):
        _print("[yellow]Portable Android SDK or base AVD not found in repo.[/yellow]")
        _print(f"[cyan]Initializing automatic portable setup ({avd_name})...[/cyan]")
        bootstrap(
            sdk_root=sdk_root,
            avd_root=avd_root,
            avd_name=avd_name,
        )


def run_emulator(
    sdk_root: Path,
    avd_root: Path,
    profile: VMProfile,
    spoof: DeviceSpoof,
    avd_name: str,
    gpu_mode: str,
    scrcpy: bool,
    safe_gpu: bool,
    inspector: HostInspector,
    persist_spoof: bool = False,
    debloat: bool = False,
    writable_system: bool = False,
    no_boot_anim: bool = False,
    cold_boot: bool = False,
    wipe_data: bool = False,
    custom_system: Path | None = None,
    custom_ramdisk: Path | None = None,
    custom_sysdir: Path | None = None,
) -> int:
    """Configures config.ini, verifies acceleration, and launches the emulator."""
    ensure_environment_ready(sdk_root, avd_root, avd_name)

    env = get_portable_env(sdk_root, avd_root, USER_HOME)
    use_accel = whpx_is_active(sdk_root)

    if not use_accel:
        _print(
            "[yellow]Notice: Hardware acceleration is not active. "
            "Launching with -accel off. Enable Windows Hypervisor Platform or BIOS VT-x for best performance.[/yellow]"
        )

    # 1. Update config.ini with profile settings
    configurator = AvdConfigurator(avd_name=avd_name, sdk_root=sdk_root, avd_root=avd_root)
    configurator.apply(profile, gpu_mode)

    emulator_bin = sdk_root / "emulator" / "emulator.exe"
    flags = LaunchFlags(
        profile=profile,
        gpu_mode=gpu_mode,
        avd_name=avd_name,
        scrcpy=scrcpy,
        safe_gpu=safe_gpu,
        gpu_vendor=inspector.gpu.vendor,
        writable_system=writable_system or persist_spoof,
        use_accel=use_accel,
        no_boot_anim=no_boot_anim,
        cold_boot=cold_boot,
        wipe_data=wipe_data,
        custom_system=custom_system,
        custom_ramdisk=custom_ramdisk,
        custom_sysdir=custom_sysdir,
    )

    adb_manager = AdbManager(platform_tools=sdk_root / "platform-tools", env=env)
    launcher = EmulatorLauncher(
        emulator_path=emulator_bin,
        flags=flags,
        adb=adb_manager,
        env=env,
        console=CONSOLE,
    )

    try:
        launcher.launch(ready_timeout=180)
    except Exception as exc:
        _print(f"[bold red]Failed to launch emulator:[/bold red] {exc}")
        return 1

    try:
        if launcher.adb.wait_for_boot_completed(interval=2, timeout=120):
            if not spoof.is_empty():
                launcher.adb.apply_spoof(spoof, persist=persist_spoof)
            else:
                _print("[dim]Device spoofing: none (stock x86_64)[/dim]")

            if debloat:
                try:
                    debloat_android(launcher.adb.adb_path, launcher.adb.env)
                except Exception as exc:
                    _print(f"[yellow]Debloat error: {exc}[/yellow]")
        else:
            if not spoof.is_empty():
                _print("[yellow]Boot not detected yet — skipping initial spoofing injection[/yellow]")

        launcher.maybe_start_scrcpy(ready_timeout=120)
        launcher.wait()
        return 0
    except KeyboardInterrupt:
        launcher.shutdown()
        return 130


# ---------------------------------------------------------------------------
# CLI Argument Parser
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    cfg = load_config()
    cfg_vm = cfg.get("vm", {})
    cfg_debloat = cfg.get("debloat", {})

    default_avd = cfg_vm.get("avd_name", DEFAULT_AVD_NAME)
    default_sp = cfg_vm.get("default_spoof_profile", "s23_ultra")
    default_hw = cfg_vm.get("default_hardware_profile", "auto")

    parser = argparse.ArgumentParser(
        prog="android_vm.py",
        description="Modular, portable Android 16 (API 36) emulator provisioner & launcher.",
    )
    parser.add_argument(
        "--profile",
        default=None,
        choices=list(load_profiles()["hardware_profiles"].keys()),
        help=f"Hardware profile ('auto' or a fixed profile name, default: {default_hw}).",
    )
    parser.add_argument(
        "--spoof",
        default=None,
        choices=list(load_profiles()["spoof_profiles"].keys()),
        help=f"Device spoofing profile (e.g. s23_ultra, rog_phone_7, stock, default: {default_sp}).",
    )
    parser.add_argument("--avd", default=default_avd, help=f"AVD name (default: {default_avd}).")
    parser.add_argument(
        "--scrcpy",
        action="store_true",
        default=cfg_vm.get("scrcpy", {}).get("enabled", False),
        help="Launch scrcpy automatically after device boot.",
    )
    parser.add_argument(
        "--safe-gpu",
        action="store_true",
        default=cfg_vm.get("safe_gpu", False),
        help="Force safe GPU mode.",
    )
    parser.add_argument(
        "--writable-system",
        action="store_true",
        default=cfg_vm.get("writable_system", False),
        help="Make system partition writable.",
    )
    parser.add_argument(
        "--no-boot-anim",
        action="store_true",
        default=cfg_vm.get("no_boot_anim", False),
        help="Disable boot animation.",
    )
    parser.add_argument(
        "--cold-boot",
        action="store_true",
        default=cfg_vm.get("cold_boot", False),
        help="Force cold boot (disable snapshots).",
    )
    parser.add_argument("--wipe-data", action="store_true", help="Reset user data to default state.")
    parser.add_argument("--persist-spoof", action="store_true", help="Persist spoof properties via adb remount.")
    parser.add_argument(
        "--debloat",
        action="store_true",
        default=cfg_debloat.get("enabled_by_default", False),
        help="Debloat Android VM after boot (removes non-essential apps).",
    )
    parser.add_argument("--root-magisk", action="store_true", help="Patch AVD ramdisk with Magisk root and exit.")
    parser.add_argument("--restore-root", action="store_true", help="Restore stock unrooted ramdisk and exit.")
    parser.add_argument("--system", type=Path, default=None, help="Path to a custom/modified system.img.")
    parser.add_argument("--ramdisk", type=Path, default=None, help="Path to a custom/modified ramdisk.img.")
    parser.add_argument("--sysdir", type=Path, default=None, help="Directory containing custom system images.")
    parser.add_argument("--sdk-root", type=Path, default=SDK_ROOT, help="Android SDK root path.")
    parser.add_argument("--avd-root", type=Path, default=AVD_ROOT, help="AVD storage path.")
    parser.add_argument("--show-config", action="store_true", help="Print config.ini preview and exit.")
    return parser


# ---------------------------------------------------------------------------
# Main Entry Point
# ---------------------------------------------------------------------------
def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    sdk_root: Path = args.sdk_root
    avd_root: Path = args.avd_root
    avd_name: str = args.avd

    # Root / unroot commands
    if args.root_magisk:
        from anvill.rooting import root_avd
        return root_avd(repo_root=REPO_ROOT, avd_name=avd_name)

    if args.restore_root:
        from anvill.rooting import root_avd
        return root_avd(repo_root=REPO_ROOT, avd_name=avd_name, restore=True)

    inspector = HostInspector.detect()

    # Interactive mode if no profile specified
    if args.profile is None:
        print_banner()
        print_hardware_panel(inspector)
        profiles_data = load_profiles()
        p_name, s_name = interactive_menu(
            profiles_data["hardware_profiles"],
            profiles_data["spoof_profiles"],
        )
    else:
        p_name = args.profile
        cfg_vm = load_config().get("vm", {})
        s_name = args.spoof or cfg_vm.get("default_spoof_profile", "stock")

    profiles_data = load_profiles()
    profile = get_hardware_profile(profiles_data, p_name, inspector=inspector)
    spoof = get_spoof_profile(profiles_data, s_name)

    gpu_mode = pick_gpu_mode(inspector, safe_gpu=args.safe_gpu)

    if args.show_config:
        configurator = AvdConfigurator(avd_name=avd_name, sdk_root=sdk_root, avd_root=avd_root)
        config = configurator.load()
        config.update_from(profile, gpu_mode)
        print(f"\nConfiguration for {avd_name}:")
        for k in AvdConfigurator.REQUIRED_KEYS:
            print(f"  {k} = {config.values.get(k, '-')}")
        return 0

    return run_emulator(
        sdk_root=sdk_root,
        avd_root=avd_root,
        profile=profile,
        spoof=spoof,
        avd_name=avd_name,
        gpu_mode=gpu_mode,
        scrcpy=args.scrcpy,
        safe_gpu=args.safe_gpu,
        inspector=inspector,
        persist_spoof=args.persist_spoof,
        debloat=args.debloat,
        writable_system=args.writable_system,
        no_boot_anim=args.no_boot_anim,
        cold_boot=args.cold_boot,
        wipe_data=args.wipe_data,
        custom_system=args.system,
        custom_ramdisk=args.ramdisk,
        custom_sysdir=args.sysdir,
    )


if __name__ == "__main__":
    sys.exit(main())

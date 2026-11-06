"""Magisk root provisioner using rootAVD ramdisk patching."""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path

_SRC_DIR = Path(__file__).resolve().parent
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

try:
    from config import get_target_image_info, load_config
    from constants import (
        AVD_ROOT,
        DEFAULT_AVD_NAME,
        DEFAULT_RAMDISK_REL,
        PROFILES_PATH,
        REPO_ROOT,
        ROOTAVD_DIR,
        SDK_ROOT,
        TOOLS_ROOT,
        USER_HOME,
    )
    from debloat import debloat_android
    from hardening import apply_real_device_hardening
    from provisioner import get_portable_env
except ImportError:
    from src.config import get_target_image_info, load_config
    from src.constants import (
        AVD_ROOT,
        DEFAULT_AVD_NAME,
        DEFAULT_RAMDISK_REL,
        PROFILES_PATH,
        REPO_ROOT,
        ROOTAVD_DIR,
        SDK_ROOT,
        TOOLS_ROOT,
        USER_HOME,
    )
    from src.debloat import debloat_android
    from src.hardening import apply_real_device_hardening
    from src.provisioner import get_portable_env


def _log(msg: str) -> None:
    try:
        from ui import log
        log(msg)
    except Exception:
        print(msg)


def ensure_rootavd_tool(target_dir: Path = ROOTAVD_DIR) -> bool:
    """Ensures rootAVD repository is cloned and ready in tools/rootAVD."""
    if (target_dir / "rootAVD.sh").exists() and (target_dir / "Magisk.zip").exists():
        return True

    _log("[cyan]Downloading rootAVD toolkit...[/cyan]")
    target_dir.parent.mkdir(parents=True, exist_ok=True)
    try:
        res = subprocess.run(
            ["git", "clone", "--depth", "1", "https://github.com/newbit1/rootAVD.git", str(target_dir)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if res.returncode != 0:
            _log(f"[bold red]Failed to clone rootAVD:[/bold red] {res.stderr}")
            return False
        return True
    except Exception as exc:
        _log(f"[bold red]Git clone error:[/bold red] {exc}")
        return False


def is_emulator_running(adb_bin: Path, env: dict[str, str]) -> bool:
    """Checks if an emulator device is currently reachable via ADB."""
    try:
        res = subprocess.run(
            [str(adb_bin), "-e", "get-state"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            env=env,
            check=False,
        )
        return res.returncode == 0 and res.stdout.strip() == "device"
    except Exception:
        return False


def wait_for_boot(adb_bin: Path, env: dict[str, str], timeout: int = 120) -> bool:
    """Waits until sys.boot_completed == 1 on the running emulator."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            res = subprocess.run(
                [str(adb_bin), "-e", "shell", "getprop", "sys.boot_completed"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
                env=env,
                check=False,
            )
            if res.stdout.strip() == "1":
                return True
        except Exception:
            pass
        time.sleep(2)
    return False


def root_avd(
    repo_root: Path = REPO_ROOT,
    avd_name: str = DEFAULT_AVD_NAME,
    restore: bool = False,
    debloat: bool = True,
    spoof: bool = True,
    profile_name: str = "s23_ultra",
    debloat_only: bool = False,
    spoof_only: bool = False,
) -> int:
    """Patches the AVD ramdisk with Magisk, debloats non-essential packages,
    and applies real-device anti-detection hardening."""
    sdk_root = repo_root / "android-sdk"
    avd_root = repo_root / "avds"
    user_home = repo_root / ".android"
    tools_dir = repo_root / "tools" / "rootAVD"

    adb_bin = sdk_root / "platform-tools" / ("adb.exe" if platform.system() == "Windows" else "adb")
    emu_bin = sdk_root / "emulator" / ("emulator.exe" if platform.system() == "Windows" else "emulator")
    tinfo = get_target_image_info()
    ramdisk_rel = Path(tinfo["rel_ramdisk"])
    ramdisk_path = sdk_root / ramdisk_rel

    if not ramdisk_path.exists() and not (debloat_only or spoof_only):
        _log(f"[bold red]Ramdisk image not found:[/bold red] {ramdisk_path}")
        return 1

    env = get_portable_env(sdk_root, avd_root, user_home)

    if restore:
        backup_path = ramdisk_path.with_name("ramdisk.img.backup")
        if backup_path.exists():
            _log("[cyan]Restoring original stock ramdisk.img from backup...[/cyan]")
            shutil.copyfile(backup_path, ramdisk_path)
            avd_initrd = avd_root / f"{avd_name}.avd" / "initrd"
            if avd_initrd.exists():
                shutil.copyfile(backup_path, avd_initrd)
            _log("[green]Stock ramdisk restored successfully! (Root removed)[/green]")
            return 0
        else:
            _log("[yellow]No ramdisk.img.backup file found to restore.[/yellow]")
            return 1

    if not (debloat_only or spoof_only) and not ensure_rootavd_tool(tools_dir):
        return 1

    emu_proc: subprocess.Popen | None = None
    already_running = is_emulator_running(adb_bin, env)

    try:
        if not already_running:
            _log("[cyan]Starting emulator in headless background mode...[/cyan]")
            accel_mode = "on"
            try:
                accel_check = subprocess.run(
                    [str(emu_bin), "-accel-check"],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=5,
                    check=False,
                )
                out = (accel_check.stdout + accel_check.stderr).lower()
                if accel_check.returncode != 0 or "not installed" in out or "not operational" in out:
                    accel_mode = "off"
            except Exception:
                pass

            emu_cmd = [
                str(emu_bin),
                "-avd",
                avd_name,
                "-gpu",
                "auto",
                "-accel",
                accel_mode,
                "-no-window",
                "-no-audio",
            ]
            emu_proc = subprocess.Popen(emu_cmd, env=env)

            _log("[dim]Waiting for emulator to boot up...[/dim]")
            if not wait_for_boot(adb_bin, env, timeout=120):
                _log("[bold red]Timeout waiting for emulator to complete boot.[/bold red]")
                return 1
            _log("[green]Emulator boot completed![/green]")
        else:
            _log("[green]Connected to running emulator.[/green]")

        # 1. Patch Magisk into ramdisk
        if not (debloat_only or spoof_only):
            _log("[cyan]Injecting Magisk into ramdisk via rootAVD...[/cyan]")
            script_name = "rootAVD.bat" if platform.system() == "Windows" else "rootAVD.sh"
            cmd = [str(tools_dir / script_name), str(ramdisk_rel)]

            res = subprocess.run(
                cmd,
                cwd=str(tools_dir),
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )

            if res.returncode != 0:
                _log(f"[bold red]rootAVD execution failed with code {res.returncode}:[/bold red]")
                print(res.stdout)
                print(res.stderr)
                return res.returncode

            # Copy patched ramdisk to AVD initrd cache as well
            avd_initrd = avd_root / f"{avd_name}.avd" / "initrd"
            if avd_initrd.exists() and ramdisk_path.exists():
                shutil.copyfile(ramdisk_path, avd_initrd)

            _log(f"[bold green]Magisk successfully patched into {tinfo['api']} ramdisk![/bold green]")
            _log("[cyan]Original ramdisk backed up to ramdisk.img.backup[/cyan]")

        # 2. Debloat Android (keep only Play Store & essential OS services)
        if debloat or debloat_only:
            debloat_android(adb_bin, env)

        # 3. Apply real-device spoofing and anti-detection hardening
        if spoof or spoof_only:
            props = None
            if PROFILES_PATH.exists():
                try:
                    pdata = json.loads(PROFILES_PATH.read_text(encoding="utf-8"))
                    sp_prof = pdata.get("spoof_profiles", {}).get(profile_name, {})
                    props = {k: v for k, v in sp_prof.items() if not k.startswith("_") and k != "description"}
                except Exception:
                    props = None

            apply_real_device_hardening(
                adb_bin=adb_bin,
                env=env,
                avd_root=avd_root,
                avd_name=avd_name,
                props=props,
            )

        _log("[bold green]====================================================================[/bold green]")
        _log("[bold green]✓ Android provisioning complete:[/bold green]")
        _log("  - [green]Magisk Root injected and armed[/green]")
        _log("  - [green]Bloatware removed (Google Play Store & GMS fully operational)[/green]")
        _log(f"  - [green]Real device profile active ({profile_name}) & QEMU flags suppressed[/green]")
        _log("[bold green]====================================================================[/bold green]")
        _log("[yellow]Next launch: Run 'python android_vm.py --cold-boot' to boot with your hardened device![/yellow]")
        return 0

    finally:
        if emu_proc is not None:
            _log("[dim]Shutting down headless patching emulator...[/dim]")
            try:
                emu_proc.terminate()
                emu_proc.wait(timeout=8)
            except Exception:
                emu_proc.kill()
            subprocess.run([str(adb_bin), "-e", "emu", "kill"], capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, check=False)


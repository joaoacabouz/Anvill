#!/usr/bin/env python3
"""Portable Android Virtual Device (AVD) Magisk Rooter.

Patches the Android 16 (API 36) ramdisk image with Magisk via rootAVD,
installs Magisk.apk, and enables Superuser (su) root access for applications.

Pure Python 3.10+ orchestrator. 100% portable relative to repo root (dp0).
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Sequence

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

try:
    from rich import print as rprint
    from rich.console import Console
    from rich.panel import Panel

    CONSOLE = Console()
    _RICH = True
except ImportError:
    _RICH = False
    CONSOLE = None


def _print(msg: str) -> None:
    if _RICH:
        rprint(msg)
    else:
        import re

        clean = re.sub(r"\[/?(bold|cyan|green|yellow|red|magenta|dim)\]", "", msg)
        print(clean)


REPO_ROOT = Path(__file__).resolve().parent
SDK_ROOT = REPO_ROOT / "android-sdk"
AVD_ROOT = REPO_ROOT / "avds"
USER_HOME = REPO_ROOT / ".android"
TOOLS_ROOT = REPO_ROOT / "tools"
ROOTAVD_DIR = TOOLS_ROOT / "rootAVD"
DEFAULT_AVD_NAME = "Android16_Pro"
DEFAULT_RAMDISK_REL = Path("system-images") / "android-36" / "google_apis" / "x86_64" / "ramdisk.img"


def get_portable_env(sdk_root: Path, avd_root: Path, user_home: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["ANDROID_HOME"] = str(sdk_root)
    env["ANDROID_SDK_ROOT"] = str(sdk_root)
    env["ANDROID_AVD_HOME"] = str(avd_root)
    env["ANDROID_USER_HOME"] = str(user_home)
    platform_tools = sdk_root / "platform-tools"
    emulator_dir = sdk_root / "emulator"
    env["PATH"] = os.pathsep.join(
        [str(platform_tools), str(emulator_dir), str(ROOTAVD_DIR), env.get("PATH", "")]
    )
    return env


def ensure_rootavd_tool(target_dir: Path) -> bool:
    """Ensures rootAVD repository is cloned and ready in tools/rootAVD."""
    if (target_dir / "rootAVD.sh").exists() and (target_dir / "Magisk.zip").exists():
        return True

    _print("[cyan]Downloading rootAVD toolkit...[/cyan]")
    target_dir.parent.mkdir(parents=True, exist_ok=True)
    try:
        res = subprocess.run(
            ["git", "clone", "--depth", "1", "https://github.com/newbit1/rootAVD.git", str(target_dir)],
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode != 0:
            _print(f"[bold red]Failed to clone rootAVD:[/bold red] {res.stderr}")
            return False
        return True
    except Exception as exc:
        _print(f"[bold red]Git clone error:[/bold red] {exc}")
        return False


def is_emulator_running(adb_bin: Path, env: dict[str, str]) -> bool:
    """Checks if an emulator device is currently reachable via ADB."""
    try:
        res = subprocess.run(
            [str(adb_bin), "-e", "get-state"],
            capture_output=True,
            text=True,
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
) -> int:
    """Patches the AVD ramdisk with Magisk or restores the backup."""
    sdk_root = repo_root / "android-sdk"
    avd_root = repo_root / "avds"
    user_home = repo_root / ".android"
    tools_dir = repo_root / "tools" / "rootAVD"

    adb_bin = sdk_root / "platform-tools" / ("adb.exe" if platform.system() == "Windows" else "adb")
    emu_bin = sdk_root / "emulator" / ("emulator.exe" if platform.system() == "Windows" else "emulator")
    ramdisk_path = sdk_root / DEFAULT_RAMDISK_REL

    if not ramdisk_path.exists():
        _print(f"[bold red]Ramdisk image not found:[/bold red] {ramdisk_path}")
        return 1

    env = get_portable_env(sdk_root, avd_root, user_home)

    if restore:
        backup_path = ramdisk_path.with_name("ramdisk.img.backup")
        if backup_path.exists():
            _print("[cyan]Restoring original stock ramdisk.img from backup...[/cyan]")
            shutil.copyfile(backup_path, ramdisk_path)
            avd_initrd = avd_root / f"{avd_name}.avd" / "initrd"
            if avd_initrd.exists():
                shutil.copyfile(backup_path, avd_initrd)
            _print("[green]Stock ramdisk restored successfully! (Root removed)[/green]")
            return 0
        else:
            _print("[yellow]No ramdisk.img.backup file found to restore.[/yellow]")
            return 1

    if not ensure_rootavd_tool(tools_dir):
        return 1

    emu_proc: subprocess.Popen | None = None
    already_running = is_emulator_running(adb_bin, env)

    try:
        if not already_running:
            _print("[cyan]Starting emulator in headless background mode to apply Magisk patch...[/cyan]")
            emu_cmd = [
                str(emu_bin),
                "-avd",
                avd_name,
                "-gpu",
                "auto",
                "-accel",
                "on",
                "-no-window",
                "-no-audio",
            ]
            emu_proc = subprocess.Popen(emu_cmd, env=env)

            _print("[dim]Waiting for emulator to boot up...[/dim]")
            if not wait_for_boot(adb_bin, env, timeout=120):
                _print("[bold red]Timeout waiting for emulator to complete boot.[/bold red]")
                return 1
            _print("[green]Emulator boot completed![/green]")
        else:
            _print("[green]Connected to running emulator.[/green]")

        _print("[cyan]Injecting Magisk into ramdisk via rootAVD...[/cyan]")
        script_name = "rootAVD.bat" if platform.system() == "Windows" else "rootAVD.sh"
        cmd = [str(tools_dir / script_name), str(DEFAULT_RAMDISK_REL)]

        res = subprocess.run(
            cmd,
            cwd=str(tools_dir),
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

        if res.returncode != 0:
            _print(f"[bold red]rootAVD execution failed with code {res.returncode}:[/bold red]")
            print(res.stdout)
            print(res.stderr)
            return res.returncode

        # Copy patched ramdisk to AVD initrd cache as well
        avd_initrd = avd_root / f"{avd_name}.avd" / "initrd"
        if avd_initrd.exists() and ramdisk_path.exists():
            shutil.copyfile(ramdisk_path, avd_initrd)

        _print("[bold green]Magisk successfully patched into Android 16 ramdisk![/bold green]")
        _print("[cyan]Original ramdisk backed up to ramdisk.img.backup[/cyan]")
        _print("[yellow]Next launch: Run 'python android_vm.py --cold-boot' to boot with Magisk root active![/yellow]")
        return 0

    finally:
        if emu_proc is not None:
            _print("[dim]Shutting down headless patching emulator...[/dim]")
            try:
                emu_proc.terminate()
                emu_proc.wait(timeout=8)
            except Exception:
                emu_proc.kill()
            subprocess.run([str(adb_bin), "-e", "emu", "kill"], capture_output=True, env=env, check=False)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="root_avd.py",
        description="Magisk Root Provisioner for Android 16 (API 36) Emulator.",
    )
    parser.add_argument("--avd", default=DEFAULT_AVD_NAME, help=f"AVD name (default: {DEFAULT_AVD_NAME})")
    parser.add_argument("--restore", action="store_true", help="Restore stock unrooted ramdisk from backup.")
    args = parser.parse_args(argv)

    if _RICH and CONSOLE:
        banner = Panel(
            "[bold green]Anvill Magisk Root Provisioner[/bold green]\n"
            "[cyan]Patches Android 16 ramdisk with Magisk + installs Magisk Manager[/cyan]",
            border_style="green",
        )
        CONSOLE.print(banner)

    return root_avd(
        repo_root=REPO_ROOT,
        avd_name=args.avd,
        restore=args.restore,
    )


if __name__ == "__main__":
    sys.exit(main())


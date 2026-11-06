"""Magisk Root, Debloat & Real-Device Provisioner CLI entrypoint for Android 16."""

from __future__ import annotations

import argparse
import sys
from typing import Sequence

from anvill.config import get_bloatware_packages, get_protected_packages, load_config
from anvill.constants import DEFAULT_AVD_NAME, REPO_ROOT
from anvill.debloat import debloat_android
from anvill.hardening import (
    apply_real_device_hardening,
    build_anti_detection_script,
    harden_avd_config,
)
from anvill.rooting import (
    ensure_rootavd_tool,
    is_emulator_running,
    root_avd,
    wait_for_boot,
)
from anvill.ui import CONSOLE, log

# Backward compatibility exports
BLOATWARE_PACKAGES = get_bloatware_packages()
PROTECTED_PACKAGES = get_protected_packages()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="root_avd.py",
        description="Magisk Root, Debloat & Real-Device Provisioner for Android 16 (API 36).",
    )
    parser.add_argument("--avd", default=DEFAULT_AVD_NAME, help=f"AVD name (default: {DEFAULT_AVD_NAME})")
    parser.add_argument("--restore", action="store_true", help="Restore stock unrooted ramdisk from backup.")
    parser.add_argument("--profile", default="s23_ultra", help="Spoofing profile to apply (default: s23_ultra)")
    parser.add_argument("--no-debloat", action="store_true", help="Skip debloating non-essential packages.")
    parser.add_argument("--no-spoof", action="store_true", help="Skip real-device spoofing and anti-detection.")
    parser.add_argument("--debloat-only", action="store_true", help="Only run debloat against a running or headless AVD.")
    parser.add_argument("--spoof-only", action="store_true", help="Only run real-device spoofing against a running or headless AVD.")
    args = parser.parse_args(argv)

    if CONSOLE:
        try:
            from rich.panel import Panel
            banner = Panel(
                "[bold green]Anvill Magisk Root & Anti-Detection Provisioner[/bold green]\n"
                "[cyan]Patches Magisk Root + Debloats Non-Essentials (Play Store preserved) + Hardens Real-Device Identity[/cyan]",
                border_style="green",
            )
            CONSOLE.print(banner)
        except Exception:
            pass

    return root_avd(
        repo_root=REPO_ROOT,
        avd_name=args.avd,
        restore=args.restore,
        debloat=not args.no_debloat,
        spoof=not args.no_spoof,
        profile_name=args.profile,
        debloat_only=args.debloat_only,
        spoof_only=args.spoof_only,
    )


if __name__ == "__main__":
    sys.exit(main())

"""Portable Android SDK, AVD & Automated Provisioning Bootstrap CLI."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

_SRC_DIR = Path(__file__).resolve().parent
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

try:
    from config import load_config
    from constants import (
        AVD_ROOT,
        DEFAULT_AVD_NAME,
        JDK_ROOT,
        REPO_ROOT,
        SDK_ROOT,
        USER_HOME,
    )
    from inspector import whpx_is_active
    from provisioner import (
        KNOWN_LICENSES,
        SetupResult,
        _avdmanager_cmd,
        _exec_cmd,
        _sdkmanager_cmd,
        accept_all_licenses,
        bootstrap,
        create_avd,
        download_zip,
        ensure_java,
        extract_zip,
        get_portable_env,
        has_command_line_tools,
        import_existing_assets,
        install_command_line_tools,
        install_packages,
        install_sdk_package,
        link_tree,
        run,
    )
    from ui import CONSOLE, log
except ImportError:
    from src.config import load_config
    from src.constants import (
        AVD_ROOT,
        DEFAULT_AVD_NAME,
        JDK_ROOT,
        REPO_ROOT,
        SDK_ROOT,
        USER_HOME,
    )
    from src.inspector import whpx_is_active
    from src.provisioner import (
        KNOWN_LICENSES,
        SetupResult,
        _avdmanager_cmd,
        _exec_cmd,
        _sdkmanager_cmd,
        accept_all_licenses,
        bootstrap,
        create_avd,
        download_zip,
        ensure_java,
        extract_zip,
        get_portable_env,
        has_command_line_tools,
        import_existing_assets,
        install_command_line_tools,
        install_packages,
        install_sdk_package,
        link_tree,
        run,
    )
    from src.ui import CONSOLE, log

# Backward compatibility aliases
DEFAULT_SDK_ROOT = SDK_ROOT
DEFAULT_AVD_ROOT = AVD_ROOT
DEFAULT_USER_HOME = USER_HOME
DEFAULT_JDK_ROOT = JDK_ROOT

_CFG = load_config()
COMMAND_LINE_TOOLS_URL = _CFG.get("sdk", {}).get(
    "command_line_tools_url",
    "https://dl.google.com/android/repository/commandlinetools-win-11076708_latest.zip",
)
ADOPTIUM_JDK_17_URL = _CFG.get(
    "openjdk_17_url",
    "https://api.adoptium.net/v3/binary/latest/17/ga/windows/x64/jdk/hotspot/normal/eclipse",
)
REQUIRED_PACKAGES = tuple(
    _CFG.get(
        "required_packages",
        (
            "emulator",
            "platform-tools",
            "system-images/android-34/google_apis_playstore/x86_64",
            "extras/google/usb_driver",
            "extras/google/Android_Emulator_Hypervisor_Driver",
        ),
    )
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="setup_sdk.py",
        description="Portable Android SDK & AVD bootstrap, root and hardening provisioner",
    )
    parser.add_argument("--sdk-root", type=Path, default=SDK_ROOT, help="SDK root to use/install (default: <repo>/android-sdk)")
    parser.add_argument("--avd-root", type=Path, default=AVD_ROOT, help="AVD directory (default: <repo>/avds)")
    parser.add_argument("--avd-name", default=DEFAULT_AVD_NAME, help=f"Base AVD name (default: {DEFAULT_AVD_NAME})")
    parser.add_argument("--skip-install", action="store_true", help="Only check WHPX and print paths; do not install.")
    parser.add_argument("--skip-root", action="store_true", help="Skip automated first-boot Magisk root, debloat and hardening.")
    parser.add_argument("--yes", "-y", action="store_true", help="Non-interactive; auto-confirm.")
    args = parser.parse_args(argv)

    if args.skip_install:
        whpx = whpx_is_active(args.sdk_root)
        print(f"SDK Root: {args.sdk_root}")
        print(f"AVD Root: {args.avd_root}")
        print(f"AVD Name: {args.avd_name}")
        print(f"WHPX/Hypervisor active: {whpx}")
        return 0

    try:
        res = bootstrap(
            sdk_root=args.sdk_root,
            avd_root=args.avd_root,
            avd_name=args.avd_name,
            auto_root=not args.skip_root,
        )
        if CONSOLE:
            try:
                from rich.panel import Panel
                CONSOLE.print(Panel(f"Bootstrap complete!\nAVD: {res.avd_name}\nEmulator: {res.emulator}", title="Success", border_style="green"))
            except Exception:
                pass
        return 0
    except Exception as exc:
        log(f"[bold red]Error during setup:[/bold red] {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())

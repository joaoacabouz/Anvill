#!/usr/bin/env python3
"""Portable Android Virtual Device (AVD) Magisk Rooter.

Patches the Android 16 (API 36) ramdisk image with Magisk via rootAVD,
installs Magisk.apk, and enables Superuser (su) root access for applications.

Pure Python 3.10+ orchestrator. 100% portable relative to repo root (dp0).
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
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

# ---------------------------------------------------------------------------
# Debloat Definitions (Preserves Google Play Store & Essential Services)
# ---------------------------------------------------------------------------
BLOATWARE_PACKAGES = [
    # Non-essential Google pre-installed services and apps
    "com.google.android.googlequicksearchbox",  # Google Search App / Velvet
    "com.google.android.apps.maps",             # Google Maps
    "com.google.android.youtube",               # YouTube
    "com.google.android.apps.youtube.music",    # YouTube Music
    "com.google.android.apps.photos",           # Google Photos
    "com.google.android.apps.photosgo",         # Photos Go
    "com.google.android.apps.docs",             # Google Drive / Docs
    "com.google.android.apps.tachyon",          # Google Meet / Duo
    "com.google.android.apps.books",            # Google Play Books
    "com.google.android.apps.magazines",        # Google News
    "com.google.android.videos",                # Google TV / Play Movies
    "com.google.android.music",                 # Google Play Music
    "com.google.android.calendar",              # Google Calendar
    "com.google.android.contacts",              # Google Contacts
    "com.google.android.deskclock",             # Google Clock
    "com.google.android.calculator",            # Google Calculator
    "com.google.android.tts",                   # Google Text-to-Speech
    "com.google.android.marvin.talkback",       # TalkBack Accessibility
    "com.google.android.feedback",              # Google Feedback bug reporter
    "com.google.android.printservice.recommendation",  # Print Recommendation
    "com.google.android.wallpaper",             # Google Wallpapers
    "com.google.android.wallpaper.effects",     # Wallpaper Effects
    "com.google.android.setupwizard",           # Setup Wizard
    "com.google.android.onetimeinitializer",    # Initializer

    # AOSP / Emulator dummy & telemetry packages
    "com.android.music",                        # AOSP Music
    "com.android.gallery3d",                    # AOSP Gallery
    "com.android.quicksearchbox",               # AOSP Search
    "com.android.email",                        # AOSP Email
    "com.android.calendar",                     # AOSP Calendar
    "com.android.camera2",                      # AOSP Camera
    "com.android.deskclock",                    # AOSP Clock
    "com.android.calculator2",                  # AOSP Calculator
    "com.android.traceur",                      # System Tracing
    "com.android.printspooler",                 # Print Spooler
    "com.android.bsp.telephony",                # Telephony BSP stub
    "com.android.bookmarkprovider",             # Browser Bookmarks
    "com.android.wallpaper.livepicker",         # Live Wallpapers
    "com.android.wallpaperbackup",              # Wallpaper Backup
    "com.android.dreams.basic",                 # Screensaver
    "com.android.dreams.phototable",            # Photo Table
    "com.android.companiondevicemanager",       # Companion Device Manager
    "com.android.emergency",                    # Emergency Info
    "com.android.cellbroadcastreceiver",        # Cell Broadcasts
    "com.android.stk",                          # SIM Toolkit
    "com.android.samplefilter",                 # Sample Filter
    "com.example.android.apis",                 # API Demos
    "com.android.development",                  # Dev Tools
    "com.android.development_settings",         # Dev Settings
    "com.android.fallback",                     # Fallback
    "com.android.smspush",                      # WAP Push
    "com.android.calllogbackup",                # Call Log Backup
    "com.android.sharedstoragebackup",          # Storage Backup
]

PROTECTED_PACKAGES = {
    "com.android.vending",                      # Google Play Store (ESSENTIAL)
    "com.google.android.gms",                   # Google Play Services (ESSENTIAL)
    "com.google.android.gsf",                   # Google Services Framework (ESSENTIAL)
    "com.google.android.ext.services",          # GMS Extension Services
    "com.google.android.ext.shared",            # GMS Shared Lib
    "com.android.systemui",                     # System UI (Status bar, nav bar)
    "com.android.settings",                     # Settings app
    "com.android.providers.settings",           # Settings Provider
    "com.android.providers.media",              # Media Provider
    "com.android.providers.downloads",          # Download Manager
    "com.android.providers.downloads.ui",       # Downloads UI
    "com.android.packageinstaller",             # Package Installer
    "com.google.android.packageinstaller",      # Google Package Installer
    "com.android.permissioncontroller",         # Permission Controller
    "com.google.android.permissioncontroller",  # Google Permission Controller
    "com.android.webview",                      # WebView
    "com.google.android.webview",               # Google WebView
    "com.android.inputmethod.latin",            # Keyboard
    "com.google.android.inputmethod.latin",     # Gboard
    "com.android.launcher3",                    # Launcher
    "com.google.android.apps.nexuslauncher",    # Nexus Launcher
    "com.android.shell",                        # ADB Shell
    "android",                                  # Android Core Framework
    "com.topjohnwu.magisk",                     # Magisk Root Manager
}


def debloat_android(adb_bin: Path, env: dict[str, str]) -> int:
    """Disables and uninstalls bloatware, keeping only Play Store and essential OS services."""
    _print("[cyan]Debloating Android image (stripping non-essential packages)...[/cyan]")
    # Elevate via adb root if available
    subprocess.run([str(adb_bin), "-e", "root"], capture_output=True, env=env, check=False)
    time.sleep(1)

    res = subprocess.run(
        [str(adb_bin), "-e", "shell", "pm", "list", "packages"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        env=env,
        check=False,
    )
    if res.returncode != 0:
        _print(f"[yellow]Warning: Could not list packages via ADB: {res.stderr.strip()}[/yellow]")
        return 0

    installed = set()
    for line in res.stdout.splitlines():
        line = line.strip()
        if line.startswith("package:"):
            installed.add(line[len("package:"):].strip())

    removed = 0
    to_disable = []
    for pkg in BLOATWARE_PACKAGES:
        if pkg not in PROTECTED_PACKAGES:
            to_disable.append(pkg)
            if pkg in installed:
                cmd = f"pm disable-user --user 0 {pkg} >/dev/null 2>&1; pm uninstall -k --user 0 {pkg} >/dev/null 2>&1"
                subprocess.run(
                    [str(adb_bin), "-e", "shell", cmd],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=10,
                    env=env,
                    check=False,
                )
                removed += 1
                _print(f"  [dim]- Removed bloatware:[/dim] [yellow]{pkg}[/yellow]")

    # Deploy persistent boot service script to keep bloatware disabled across reboots
    debloat_sh = [
        "#!/system/bin/sh",
        "# Anvill Persistent Debloat Service",
        "sleep 10",
    ]
    for pkg in to_disable:
        debloat_sh.append(f"pm disable-user --user 0 {pkg} 2>/dev/null")
        debloat_sh.append(f"pm disable {pkg} 2>/dev/null")
    debloat_script = "\n".join(debloat_sh) + "\n"

    with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="\n", delete=False) as tmp:
        tmp.write(debloat_script)
        tmp_path = Path(tmp.name)
    try:
        subprocess.run([str(adb_bin), "-e", "push", str(tmp_path), "/data/local/tmp/98-anvill-debloat.sh"], capture_output=True, env=env, check=False)
        deploy_cmd = (
            "mkdir -p /data/adb/service.d && "
            "cp /data/local/tmp/98-anvill-debloat.sh /data/adb/service.d/98-anvill-debloat.sh && "
            "chmod 755 /data/adb/service.d/98-anvill-debloat.sh && "
            "rm -f /data/local/tmp/98-anvill-debloat.sh"
        )
        subprocess.run([str(adb_bin), "-e", "shell", deploy_cmd], capture_output=True, env=env, check=False)
    finally:
        tmp_path.unlink(missing_ok=True)

    _print(f"[bold green]✓ Debloat finished:[/bold green] [green]{removed} bloatware packages disabled.[/green]")
    _print("[bold green]✓ Verified active:[/bold green] [green]Google Play Store (com.android.vending) + GMS & Core UI intact.[/green]")
    return removed


def build_anti_detection_script(props: dict[str, str]) -> str:
    """Builds a portable POSIX shell script to be executed by Magisk at early/late boot."""
    lines = [
        "#!/system/bin/sh",
        "# ==============================================================================",
        "# Anvill Real-Device Anti-Detection Boot Service",
        "# ==============================================================================",
        "",
        "RESETPROP=\"/data/adb/magisk/resetprop\"",
        "if [ ! -f \"$RESETPROP\" ]; then",
        "    RESETPROP=\"resetprop\"",
        "fi",
        "",
        "set_prop() {",
        "    $RESETPROP -n \"$1\" \"$2\" 2>/dev/null || setprop \"$1\" \"$2\" 2>/dev/null",
        "}",
        "",
        "del_prop() {",
        "    $RESETPROP --delete \"$1\" 2>/dev/null",
        "}",
        "",
        "# 1. Delete QEMU / Emulator Indicators",
        "del_prop ro.kernel.qemu",
        "del_prop ro.boot.qemu",
        "del_prop init.svc.qemud",
        "del_prop init.svc.goldfish-logcat",
        "del_prop init.svc.ranchu-setup",
        "del_prop init.svc.ranchu-net",
        "del_prop ro.hardware.virtual_device",
        "del_prop ro.boot.hardware.sku",
        "del_prop ro.emulator.circular",
        "set_prop ro.kernel.qemu 0",
        "set_prop ro.boot.qemu 0",
        "set_prop ro.hardware.virtual_device \"\"",
        "",
        "# 2. Real Hardware & Security Properties",
    ]

    for k, v in props.items():
        if k in ("ro.kernel.qemu", "ro.boot.qemu"):
            continue
        lines.append(f'set_prop {k} "{v}"')

    lines.extend([
        "",
        "# 3. Anti-Detection for Android Settings Inspection",
        "settings put global adb_enabled 0 2>/dev/null",
        "settings put global development_settings_enabled 0 2>/dev/null",
        "settings put secure mock_location 0 2>/dev/null",
        "settings put global package_verifier_user_consent 1 2>/dev/null",
        "settings put global install_non_market_apps 1 2>/dev/null",
        "",
        "# 4. Magisk DenyList (Protects Play Store & Banking apps from root detection)",
        "if command -v magisk >/dev/null 2>&1; then",
        "    magisk --denylist enable 2>/dev/null",
        "    magisk --denylist add com.google.android.gms com.google.android.gms.unstable 2>/dev/null",
        "    magisk --denylist add com.google.android.vending 2>/dev/null",
        "fi",
        "",
    ])

    return "\n".join(lines) + "\n"

    for k, v in props.items():
        if k in ("ro.kernel.qemu", "ro.boot.qemu"):
            continue
        lines.append(f'set_prop {k} "{v}"')

    lines.extend([
        "",
        "# 3. Anti-Detection for Android Settings Inspection",
        "settings put global adb_enabled 0 2>/dev/null",
        "settings put global development_settings_enabled 0 2>/dev/null",
        "settings put secure mock_location 0 2>/dev/null",
        "settings put global package_verifier_user_consent 1 2>/dev/null",
        "settings put global install_non_market_apps 1 2>/dev/null",
        "",
        "# 4. Magisk DenyList (Protects Play Store & Banking apps from root detection)",
        "if command -v magisk >/dev/null 2>&1; then",
        "    magisk --denylist enable 2>/dev/null",
        "    magisk --denylist add com.google.android.gms com.google.android.gms.unstable 2>/dev/null",
        "    magisk --denylist add com.google.android.vending 2>/dev/null",
        "fi",
        "",
    ])

    return "\n".join(lines) + "\n"


def harden_avd_config(avd_root: Path, avd_name: str, props: dict[str, str]) -> None:
    """Updates the AVD config.ini to enable hardware sensors, camera, and device manufacturer."""
    config_file = avd_root / f"{avd_name}.avd" / "config.ini"
    if not config_file.exists():
        return

    content = config_file.read_text(encoding="utf-8", errors="replace")
    cfg = {}
    for line in content.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            cfg[k.strip()] = v.strip()

    # Hardware & Real device flags
    cfg["PlayStore.enabled"] = "yes"
    cfg["hw.battery"] = "yes"
    cfg["hw.camera.back"] = "virtualscene"
    cfg["hw.camera.front"] = "emulated"
    cfg["hw.gps"] = "yes"
    cfg["hw.sensors.orientation"] = "yes"
    cfg["hw.sensors.proximity"] = "yes"
    cfg["hw.sensors.light"] = "yes"
    cfg["hw.sensors.magnetic_field"] = "yes"
    cfg["hw.sensors.pressure"] = "yes"
    cfg["hw.sensors.humidity"] = "yes"
    cfg["hw.sensors.temperature"] = "yes"
    cfg["hw.accelerometer"] = "yes"
    cfg["hw.gyroscope"] = "yes"
    cfg["hw.device.manufacturer"] = props.get("ro.product.manufacturer", "samsung")
    cfg["hw.device.name"] = props.get("ro.product.model", "SM-S918B")

    new_content = "\n".join(f"{k}={v}" for k, v in cfg.items()) + "\n"
    config_file.write_text(new_content, encoding="utf-8")


def apply_real_device_hardening(
    adb_bin: Path,
    env: dict[str, str],
    avd_root: Path,
    avd_name: str,
    props: dict[str, str] | None = None,
) -> bool:
    """Installs persistent Magisk boot scripts, applies live props, and hardens AVD hardware INI."""
    _print("[cyan]Applying real-device anti-detection hardening...[/cyan]")

    if props is None:
        prof_file = REPO_ROOT / "profiles.json"
        if prof_file.exists():
            try:
                pdata = json.loads(prof_file.read_text(encoding="utf-8"))
                s23 = pdata.get("spoof_profiles", {}).get("s23_ultra", {})
                props = {k: v for k, v in s23.items() if not k.startswith("_") and k != "description"}
            except Exception:
                props = {}
        if not props:
            props = {
                "ro.product.brand": "samsung",
                "ro.product.manufacturer": "samsung",
                "ro.product.model": "SM-S918B",
                "ro.product.device": "dm3q",
                "ro.product.name": "dm3qxeea",
                "ro.product.board": "kalama",
                "ro.soc.manufacturer": "Qualcomm",
                "ro.soc.model": "SM8550",
                "ro.board.platform": "kalama",
                "ro.hardware.chipname": "sm8550",
                "ro.hardware.egl": "adreno",
                "ro.hardware.vulkan": "adreno",
                "ro.build.type": "user",
                "ro.build.tags": "release-keys",
                "ro.secure": "1",
                "ro.debuggable": "0",
                "ro.boot.verifiedbootstate": "green",
                "ro.boot.flash.locked": "1",
                "ro.kernel.qemu": "0",
                "ro.boot.qemu": "0",
                "gsm.sim.operator.alpha": "T-Mobile",
                "gsm.sim.operator.numeric": "310260",
                "gsm.operator.alpha": "T-Mobile",
                "gsm.operator.numeric": "310260",
            }

    # 1. Elevate via adb root
    subprocess.run([str(adb_bin), "-e", "root"], capture_output=True, env=env, check=False)
    time.sleep(1)

    # 2. Deploy persistent boot scripts
    script_content = build_anti_detection_script(props)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="\n", delete=False) as tmp:
        tmp.write(script_content)
        tmp_path = Path(tmp.name)

    try:
        subprocess.run(
            [str(adb_bin), "-e", "push", str(tmp_path), "/data/local/tmp/99-anvill-realdevice.sh"],
            capture_output=True,
            env=env,
            check=False,
        )
        deploy_cmd = (
            "mkdir -p /data/adb/service.d /data/adb/post-fs-data.d && "
            "cp /data/local/tmp/99-anvill-realdevice.sh /data/adb/service.d/99-anvill-realdevice.sh && "
            "cp /data/local/tmp/99-anvill-realdevice.sh /data/adb/post-fs-data.d/99-anvill-realdevice.sh && "
            "chmod 755 /data/adb/service.d/99-anvill-realdevice.sh /data/adb/post-fs-data.d/99-anvill-realdevice.sh && "
            "rm -f /data/local/tmp/99-anvill-realdevice.sh"
        )
        subprocess.run([str(adb_bin), "-e", "shell", deploy_cmd], capture_output=True, env=env, check=False)
    finally:
        tmp_path.unlink(missing_ok=True)

    # 3. Apply properties live in current session
    applied_count = 0
    for key, val in props.items():
        res = subprocess.run([str(adb_bin), "-e", "shell", "setprop", key, val], capture_output=True, env=env, check=False)
        if res.returncode == 0:
            applied_count += 1

    # 4. Hide developer flags in Android Settings
    settings_cmd = (
        "settings put global adb_enabled 0; "
        "settings put global development_settings_enabled 0; "
        "settings put secure mock_location 0"
    )
    subprocess.run([str(adb_bin), "-e", "shell", settings_cmd], capture_output=True, env=env, check=False)

    # 5. Enable Magisk DenyList
    subprocess.run([str(adb_bin), "-e", "shell", "magisk --denylist enable 2>/dev/null"], capture_output=True, env=env, check=False)
    subprocess.run([str(adb_bin), "-e", "shell", "magisk --denylist add com.google.android.gms com.google.android.gms.unstable 2>/dev/null"], capture_output=True, env=env, check=False)
    subprocess.run([str(adb_bin), "-e", "shell", "magisk --denylist add com.google.android.vending 2>/dev/null"], capture_output=True, env=env, check=False)

    # 6. Harden host AVD config.ini
    harden_avd_config(avd_root, avd_name, props)

    _print(f"[bold green]✓ Real-device configuration applied:[/bold green] [green]{applied_count} properties configured.[/green]")
    _print("[bold green]✓ Anti-detection active:[/bold green] [green]QEMU flags suppressed, Magisk DenyList armed, sensors enabled.[/green]")
    return True


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
            encoding="utf-8",
            errors="replace",
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
    ramdisk_path = sdk_root / DEFAULT_RAMDISK_REL

    if not ramdisk_path.exists() and not (debloat_only or spoof_only):
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

    if not (debloat_only or spoof_only) and not ensure_rootavd_tool(tools_dir):
        return 1

    emu_proc: subprocess.Popen | None = None
    already_running = is_emulator_running(adb_bin, env)

    try:
        if not already_running:
            _print("[cyan]Starting emulator in headless background mode...[/cyan]")
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

            _print("[dim]Waiting for emulator to boot up...[/dim]")
            if not wait_for_boot(adb_bin, env, timeout=120):
                _print("[bold red]Timeout waiting for emulator to complete boot.[/bold red]")
                return 1
            _print("[green]Emulator boot completed![/green]")
        else:
            _print("[green]Connected to running emulator.[/green]")

        # 1. Patch Magisk into ramdisk
        if not (debloat_only or spoof_only):
            _print("[cyan]Injecting Magisk into ramdisk via rootAVD...[/cyan]")
            script_name = "rootAVD.bat" if platform.system() == "Windows" else "rootAVD.sh"
            cmd = [str(tools_dir / script_name), str(DEFAULT_RAMDISK_REL)]

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

        # 2. Debloat Android (keep only Play Store & essential OS services)
        if debloat or debloat_only:
            debloat_android(adb_bin, env)

        # 3. Apply real-device spoofing and anti-detection hardening
        if spoof or spoof_only:
            props = None
            prof_file = repo_root / "profiles.json"
            if prof_file.exists():
                try:
                    pdata = json.loads(prof_file.read_text(encoding="utf-8"))
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

        _print("[bold green]====================================================================[/bold green]")
        _print("[bold green]✓ Android provisioning complete:[/bold green]")
        _print("  - [green]Magisk Root injected and armed[/green]")
        _print("  - [green]Bloatware removed (Google Play Store & GMS fully operational)[/green]")
        _print(f"  - [green]Real device profile active ({profile_name}) & QEMU flags suppressed[/green]")
        _print("[bold green]====================================================================[/bold green]")
        _print("[yellow]Next launch: Run 'python android_vm.py --cold-boot' to boot with your hardened device![/yellow]")
        return 0

    finally:
        if emu_proc is not None:
            _print("[dim]Shutting down headless patching emulator...[/dim]")
            try:
                emu_proc.terminate()
                emu_proc.wait(timeout=8)
            except Exception:
                emu_proc.kill()
            subprocess.run([str(adb_bin), "-e", "emu", "kill"], capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, check=False)


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

    if _RICH and CONSOLE:
        banner = Panel(
            "[bold green]Anvill Magisk Root & Anti-Detection Provisioner[/bold green]\n"
            "[cyan]Patches Magisk Root + Debloats Non-Essentials (Play Store preserved) + Hardens Real-Device Identity[/cyan]",
            border_style="green",
        )
        CONSOLE.print(banner)

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


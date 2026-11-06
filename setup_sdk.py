#!/usr/bin/env python3
"""Android SDK bootstrap: checks WHPX, downloads Command-line Tools,
accepts licenses, installs emulator + platform-tools + Android 16 system image + Google drivers,
and creates the base AVD in a portable repo-local directory.

Manual usage:
    python setup_sdk.py                       # Installs locally inside repo (./android-sdk, ./avds)
    python setup_sdk.py --sdk-root C:\\Custom  # Installs to custom path
    python setup_sdk.py -y                    # Non-interactive mode (yes to all)

Pure Python 3.10+ (no PowerShell or Batch used for logic).
"""

from __future__ import annotations

import argparse
import ctypes
import os
import platform
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from dataclasses import dataclass
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

# ---------------------------------------------------------------------------
# Auto-ensure dependencies (psutil, rich)
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
        req_file = Path(__file__).resolve().parent / "requirements.txt"
        print(f"Installing missing Python dependencies ({', '.join(missing)})...")
        if req_file.exists():
            subprocess.run([sys.executable, "-m", "pip", "install", "-r", str(req_file)], check=False)
        else:
            subprocess.run([sys.executable, "-m", "pip", "install", *missing], check=False)

_ensure_dependencies()

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.progress import Progress, SpinnerColumn, TextColumn
    from rich.table import Table
    _HAS_RICH = True
except ImportError:
    _HAS_RICH = False

CONSOLE: Console | None = Console() if _HAS_RICH else None

from config import load_config

# ---------------------------------------------------------------------------
# Portable Directory Paths (dp0 - Repo-Local) & Configurations
# ---------------------------------------------------------------------------
REPO_ROOT: Path = Path(__file__).resolve().parent
DEFAULT_SDK_ROOT: Path = REPO_ROOT / "android-sdk"
DEFAULT_AVD_ROOT: Path = REPO_ROOT / "avds"
DEFAULT_USER_HOME: Path = REPO_ROOT / ".android"
DEFAULT_JDK_ROOT: Path = REPO_ROOT / "jdk"

_CONFIG = load_config()
_VM_CFG = _CONFIG.get("vm", {})
_SDK_CFG = _CONFIG.get("sdk", {})

DEFAULT_AVD_NAME: str = _VM_CFG.get("avd_name", "Android16_Pro")

# Official download URLs from config.json
COMMAND_LINE_TOOLS_URL: str = _SDK_CFG.get(
    "command_line_tools_url",
    "https://dl.google.com/android/repository/commandlinetools-win-11076708_latest.zip",
)
ADOPTIUM_JDK_17_URL: str = _SDK_CFG.get(
    "openjdk_17_url",
    "https://api.adoptium.net/v3/binary/latest/17/ga/windows/x64/jdk/hotspot/normal/eclipse",
)

# Required SDK packages from config.json
REQUIRED_PACKAGES: tuple[str, ...] = tuple(
    _SDK_CFG.get(
        "required_packages",
        (
            "emulator",
            "platform-tools",
            "system-images/android-36/google_apis/x86_64",
            "extras/google/usb_driver",
            "extras/google/Android_Emulator_Hypervisor_Driver",
        ),
    )
)


@dataclass
class SetupResult:
    """Setup result."""
    sdk_root: Path
    avd_root: Path
    avd_name: str
    emulator: Path | None
    platform_tools: Path | None
    avd_created: bool
    whpx_active: bool


# ---------------------------------------------------------------------------
# Portable Environment Builder
# ---------------------------------------------------------------------------
def get_portable_env(
    sdk_root: Path,
    avd_root: Path | None = None,
    user_home: Path | None = None,
    jdk_root: Path | None = None,
) -> dict[str, str]:
    """Generates an environment dict that isolates Android SDK and AVD to repo-local paths."""
    env = dict(os.environ)
    if avd_root is None:
        avd_root = sdk_root.parent / "avds"
    if user_home is None:
        user_home = sdk_root.parent / ".android"
    if jdk_root is None:
        jdk_root = sdk_root.parent / "jdk"

    env["ANDROID_HOME"] = str(sdk_root)
    env["ANDROID_SDK_ROOT"] = str(sdk_root)
    env["ANDROID_USER_HOME"] = str(user_home)
    env["ANDROID_AVD_HOME"] = str(avd_root)
    env["ANDROID_EMULATOR_HOME"] = str(user_home)

    paths_to_add: list[str] = []
    if (jdk_root / "bin").exists():
        env["JAVA_HOME"] = str(jdk_root)
        paths_to_add.append(str(jdk_root / "bin"))

    cmdline_bin = sdk_root / "cmdline-tools" / "latest" / "bin"
    if cmdline_bin.exists():
        paths_to_add.append(str(cmdline_bin))

    platform_tools = sdk_root / "platform-tools"
    if platform_tools.exists():
        paths_to_add.append(str(platform_tools))

    emulator_dir = sdk_root / "emulator"
    if emulator_dir.exists():
        paths_to_add.append(str(emulator_dir))

    if paths_to_add:
        env["PATH"] = os.pathsep.join(paths_to_add) + os.pathsep + env.get("PATH", "")

    return env


# ---------------------------------------------------------------------------
# Java / JDK Management (Portable OpenJDK)
# ---------------------------------------------------------------------------
def ensure_java(jdk_root: Path = DEFAULT_JDK_ROOT) -> Path | None:
    """Ensures a working Java Runtime is available for sdkmanager/avdmanager.

    1. Checks if local portable JDK exists at jdk_root.
    2. Checks if host system has a functional java binary.
    3. If none found, automatically downloads portable OpenJDK 17 (Temurin).
    """
    java_exe = jdk_root / "bin" / ("java.exe" if platform.system() == "Windows" else "java")
    if java_exe.exists():
        return jdk_root

    # Check if host java works
    host_java = shutil.which("java")
    if host_java:
        try:
            res = subprocess.run([host_java, "-version"], capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
            if res.returncode == 0:
                return None  # Host Java is operational
        except Exception:
            pass

    # No functional Java found: download portable OpenJDK 17
    print(f"No Java detected. Downloading portable OpenJDK 17 to {jdk_root}...")
    jdk_root.mkdir(parents=True, exist_ok=True)
    zip_path = jdk_root / "openjdk17.zip"
    try:
        req = urllib.request.Request(ADOPTIUM_JDK_17_URL, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req) as resp, open(zip_path, "wb") as out_file:
            shutil.copyfileobj(resp, out_file)

        # Extract and unpack the nested folder
        temp_extract = jdk_root / "_temp_extract"
        temp_extract.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path, "r") as z:
            z.extractall(temp_extract)

        # Temurin zip root is usually jdk-17.0.x+y
        subdirs = [d for d in temp_extract.iterdir() if d.is_dir()]
        extracted_root = subdirs[0] if subdirs else temp_extract

        for item in extracted_root.iterdir():
            target = jdk_root / item.name
            if target.exists():
                if target.is_dir():
                    shutil.rmtree(target)
                else:
                    target.unlink()
            shutil.move(str(item), str(target))

        shutil.rmtree(temp_extract, ignore_errors=True)
        zip_path.unlink(missing_ok=True)
        print(f"Portable OpenJDK 17 installed at {jdk_root}")
        return jdk_root
    except Exception as exc:
        print(f"Warning: Failed to auto-download OpenJDK: {exc}")
        return None


# ---------------------------------------------------------------------------
# WHPX & Acceleration Detection
# ---------------------------------------------------------------------------
def whpx_is_active(sdk_root: Path | None = None) -> bool:
    """Checks whether WHPX (Windows Hypervisor Platform) or hardware acceleration
    is operational on Windows.

    Uses emulator -accel-check if emulator binary is installed, and falls back
    to Windows Hypervisor registry & WinHvPlatform.dll checks.
    """
    if platform.system() != "Windows":
        return True

    # 1. Authoritative check via emulator binary if available
    cand_emulators = []
    if sdk_root is not None:
        cand_emulators.append(sdk_root / "emulator" / "emulator.exe")
    cand_emulators.append(DEFAULT_SDK_ROOT / "emulator" / "emulator.exe")
    if "LOCALAPPDATA" in os.environ:
        cand_emulators.append(Path(os.environ["LOCALAPPDATA"]) / "Android" / "Sdk" / "emulator" / "emulator.exe")

    for emu in cand_emulators:
        if emu.exists():
            try:
                res = subprocess.run([str(emu), "-accel-check"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=5)
                out = (res.stdout + res.stderr).lower()
                if res.returncode == 0 and ("usable" in out or "operational" in out or "installed" in out):
                    return True
            except Exception:
                pass

    # 2. Check Windows Hypervisor Launch Type in registry
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Control\Hypervisor",
            0,
            winreg.KEY_READ | winreg.KEY_WOW64_32KEY,
        )
        launch_type, _ = winreg.QueryValueEx(key, "HypervisorLaunchType")
        winreg.CloseKey(key)
        # 1 = Auto / Enabled
        if launch_type in (1, 2):
            dll = Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32" / "WinHvPlatform.dll"
            if dll.exists():
                return True
    except OSError:
        pass

    # 3. Check AEHD (Android Emulator Hypervisor Driver) service
    try:
        import winreg
        for svc in ("gvm", "aehd", "HAX"):
            try:
                k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, rf"SYSTEM\CurrentControlSet\Services\{svc}", 0, winreg.KEY_READ)
                winreg.CloseKey(k)
                return True
            except OSError:
                continue
    except Exception:
        pass

    return False


# ---------------------------------------------------------------------------
# Safe subprocess runner (no shell=True)
# ---------------------------------------------------------------------------
def run(
    cmd: Sequence[str],
    cwd: Path | None = None,
    check: bool = False,
    env: dict[str, str] | None = None,
    input_text: str | None = None,
) -> subprocess.CompletedProcess:
    """Executes a command safely with list arguments (shell=False)."""
    cwd_str = str(cwd) if cwd is not None else None
    if env is None:
        env = dict(os.environ)
    try:
        result = subprocess.run(
            cmd,
            check=check,
            cwd=cwd_str,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=0,
            input=input_text,
        )
        if result.stdout:
            for line in result.stdout.splitlines():
                print(line)
        return result
    except subprocess.CalledProcessError as exc:
        if exc.stdout:
            for line in exc.stdout.splitlines():
                print(line)
        raise


def _exec_cmd(path: Path, *args: str) -> list[str]:
    """Build a subprocess arg list for a binary or batch wrapper on Windows."""
    if platform.system() == "Windows" and path.suffix.lower() == ".bat":
        return ["cmd", "/c", str(path), *args]
    return [str(path), *args]


def _sdkmanager_cmd(sdk_root: Path, *args: str) -> list[str]:
    """Build a subprocess arg list for sdkmanager."""
    sdkmanager = sdk_root / "cmdline-tools" / "latest" / "bin" / "sdkmanager"
    if platform.system() == "Windows":
        sdkmanager = sdkmanager.with_suffix(".bat")
    return _exec_cmd(sdkmanager, *args)


# ---------------------------------------------------------------------------
# Local Asset Reuse / Fast Import
# ---------------------------------------------------------------------------
def link_tree(src: Path, dst: Path) -> None:
    """Creates a local hardlink tree of files (instant on same NTFS volume, fallback to copy)."""
    for root, dirs, files in os.walk(src):
        rel = Path(root).relative_to(src)
        target_dir = dst / rel
        target_dir.mkdir(parents=True, exist_ok=True)
        for f in files:
            s_file = Path(root) / f
            d_file = target_dir / f
            if not d_file.exists():
                try:
                    os.link(s_file, d_file)
                except Exception:
                    shutil.copy2(s_file, d_file)


def import_existing_assets(target_sdk: Path) -> bool:
    """Checks for existing SDK packages in %LOCALAPPDATA%\\Android\\Sdk and imports them locally."""
    candidates = []
    if "LOCALAPPDATA" in os.environ:
        candidates.append(Path(os.environ["LOCALAPPDATA"]) / "Android" / "Sdk")
    env_home = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT")
    if env_home:
        candidates.append(Path(env_home))

    for cand in candidates:
        if cand.exists() and cand != target_sdk:
            print(f"Found existing Android SDK at {cand}. Linking packages locally for fast portable setup...")
            for sub in ("licenses", "cmdline-tools", "emulator", "platform-tools", "system-images", "extras"):
                src_sub = cand / sub
                dst_sub = target_sdk / sub
                if src_sub.exists() and not dst_sub.exists():
                    print(f"  Importing {sub} -> {dst_sub}...")
                    link_tree(src_sub, dst_sub)
            return True
    return False


# ---------------------------------------------------------------------------
# Download & Extraction
# ---------------------------------------------------------------------------
def download_zip(url: str, dest: Path) -> None:
    """Downloads a ZIP file to destination."""
    print(f"Downloading {url} -> {dest}...")
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req) as resp, open(dest, "wb") as out_file:
        shutil.copyfileobj(resp, out_file)
    if not dest.exists():
        raise RuntimeError(f"Failed to download {url}")


def extract_zip(src: Path, dest: Path) -> Path:
    """Extracts a ZIP preserving directory structure."""
    with zipfile.ZipFile(src, "r") as z:
        z.extractall(dest)
    return dest


def has_command_line_tools(sdk_root: Path) -> bool:
    sdkmanager = sdk_root / "cmdline-tools" / "latest" / "bin" / "sdkmanager"
    if platform.system() == "Windows":
        sdkmanager = sdkmanager.with_suffix(".bat")
    return sdkmanager.exists()


def install_command_line_tools(sdk_root: Path) -> None:
    """Downloads and places Command-line Tools into <sdk_root>/cmdline-tools/latest."""
    zip_path = sdk_root / "cmdlinetools.zip"
    download_zip(COMMAND_LINE_TOOLS_URL, zip_path)

    temp_extract = sdk_root / "_cmdline_temp"
    temp_extract.mkdir(parents=True, exist_ok=True)
    extract_zip(zip_path, temp_extract)

    latest_dir = sdk_root / "cmdline-tools" / "latest"
    latest_dir.parent.mkdir(parents=True, exist_ok=True)
    if latest_dir.exists():
        shutil.rmtree(latest_dir)

    # The zip contains a root folder 'cmdline-tools'
    src_folder = temp_extract / "cmdline-tools"
    if src_folder.exists():
        shutil.move(str(src_folder), str(latest_dir))
    else:
        shutil.move(str(temp_extract), str(latest_dir))

    shutil.rmtree(temp_extract, ignore_errors=True)
    zip_path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Licenses & Packages
# ---------------------------------------------------------------------------
KNOWN_LICENSES: dict[str, list[str]] = {
    "android-sdk-license": [
        "24333f8a63b6825ea9c5514f83c2829b004d1fee",
        "d56f5187479451eabf01fb78af6dfcb131a6481e",
        "8933bad161af4178b1185d1a37fbf41ea5269c55",
        "84831b9409646a918e30573bab4c9c91346d8abd",
    ],
    "android-sdk-preview-license": [
        "84831b9409646a918e30573bab4c9c91346d8abd",
    ],
    "android-googletv-license": [
        "601085b94cd77f0b54ff86406957099150008536",
    ],
    "android-sdk-arm-dbt-license": [
        "859f317696e35e261e4799ebd1670e1694f41904",
    ],
    "google-gdk-license": [
        "33b6a2b64920402e966c42954d26ff787e492d47",
    ],
    "mips-android-sysimage-license": [
        "e9acab5b5fbb560a72c114f70c73c41649980c73",
    ],
}


def accept_all_licenses(sdk_root: Path, env: dict[str, str]) -> None:
    """Accepts all Android SDK licenses non-interactively.

    1. Pre-populates known license hashes directly into <sdk_root>/licenses/
       to ensure package downloads are never blocked by unaccepted licenses.
    2. Runs sdkmanager --licenses with non-interactive 'y' pipe and safe UTF-8 decoding
       as an authoritative confirmation.
    """
    print("Accepting SDK licenses...")
    lic_dir = sdk_root / "licenses"
    lic_dir.mkdir(parents=True, exist_ok=True)
    for lic_name, hashes in KNOWN_LICENSES.items():
        lic_file = lic_dir / lic_name
        existing = []
        if lic_file.exists():
            try:
                existing = [line.strip() for line in lic_file.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip()]
            except Exception:
                existing = []
        combined = list(dict.fromkeys(existing + hashes))
        lic_file.write_text("\n".join(combined) + "\n", encoding="utf-8")

    # Authoritative sdkmanager license acceptance
    sdkmanager_bin = sdk_root / "cmdline-tools" / "latest" / "bin" / ("sdkmanager.bat" if platform.system() == "Windows" else "sdkmanager")
    if sdkmanager_bin.exists():
        try:
            run(_exec_cmd(sdkmanager_bin, f"--sdk_root={sdk_root}", "--licenses"), cwd=sdk_root, env=env, input_text="y\n" * 100)
        except Exception as exc:
            print(f"Note: sdkmanager --licenses check completed ({exc})")


def install_sdk_package(sdk_root: Path, package: str, env: dict[str, str]) -> None:
    """Installs an SDK package using native android CLI when available, or classic sdkmanager."""
    android_bin = sdk_root / "cmdline-tools" / "latest" / "bin" / ("android.exe" if platform.system() == "Windows" else "android")
    pkg_slash = package.replace(";", "/")

    if android_bin.exists():
        cmd = [str(android_bin), f"--sdk={sdk_root}", "sdk", "install", pkg_slash]
        run(cmd, cwd=sdk_root, check=True, env=env, input_text="y\n" * 10)
        return

    # Classic sdkmanager: pass slash notation first (prevents cmd.exe semicolon splitting)
    sdkmanager = sdk_root / "cmdline-tools" / "latest" / "bin" / "sdkmanager"
    if platform.system() == "Windows":
        sdkmanager = sdkmanager.with_suffix(".bat")
    try:
        cmd = _exec_cmd(sdkmanager, f"--sdk_root={sdk_root}", pkg_slash)
        run(cmd, cwd=sdk_root, check=True, env=env, input_text="y\n" * 10)
    except Exception:
        # Fallback with semicolon notation if legacy sdkmanager specifically requires it
        pkg_semi = package.replace("/", ";")
        cmd = _exec_cmd(sdkmanager, f"--sdk_root={sdk_root}", pkg_semi)
        run(cmd, cwd=sdk_root, check=True, env=env, input_text="y\n" * 10)


def install_packages(sdk_root: Path, packages: Sequence[str], env: dict[str, str]) -> None:
    """Installs requested packages via android CLI or sdkmanager."""
    for package in packages:
        pkg_norm = package.replace(";", "/")
        # Check if already installed
        if pkg_norm.startswith("system-images/"):
            parts = pkg_norm.split("/")
            if len(parts) >= 4 and (sdk_root / "system-images" / parts[1] / parts[2] / parts[3]).exists():
                print(f"Package {package} is already installed.")
                continue
        elif pkg_norm == "emulator" and (sdk_root / "emulator" / "emulator.exe").exists():
            print("Package emulator is already installed.")
            continue
        elif pkg_norm == "platform-tools" and (sdk_root / "platform-tools" / "adb.exe").exists():
            print("Package platform-tools is already installed.")
            continue
        elif pkg_norm == "extras/google/usb_driver" and (sdk_root / "extras" / "google" / "usb_driver").exists():
            print("Package usb_driver is already installed.")
            continue
        elif pkg_norm == "extras/google/Android_Emulator_Hypervisor_Driver" and (
            sdk_root / "extras" / "google" / "Android_Emulator_Hypervisor_Driver"
        ).exists():
            print("Package Android_Emulator_Hypervisor_Driver is already installed.")
            continue

        print(f"Installing {package}...")
        try:
            install_sdk_package(sdk_root, package, env)
        except Exception as exc:
            # If optional driver fails, warn but continue
            if "extras" in package:
                print(f"Notice: Optional driver {package} skipped or not required ({exc})")
            else:
                print(f"Warning: Failed to install package {package}: {exc}")


# ---------------------------------------------------------------------------
# Base AVD Creation
# ---------------------------------------------------------------------------
def create_avd(
    sdk_root: Path,
    avd_name: str,
    avd_root: Path,
    user_home: Path,
    env: dict[str, str],
) -> None:
    """Creates base Android 16 AVD in the repo-local AVD directory."""
    avdmanager = sdk_root / "cmdline-tools" / "latest" / "bin" / "avdmanager"
    if platform.system() == "Windows":
        avdmanager = avdmanager.with_suffix(".bat")

    sys_img_dir = sdk_root / "system-images" / "android-36" / "google_apis" / "x86_64"
    if not sys_img_dir.exists():
        print(f"System image not found at {sys_img_dir}. Attempting direct package installation...")
        try:
            install_sdk_package(sdk_root, "system-images/android-36/google_apis/x86_64", env)
        except Exception as exc:
            print(f"Direct install failed: {exc}")

    if not sys_img_dir.exists():
        raise RuntimeError(
            f"System image not found at {sys_img_dir}. "
            "The system-images package failed to download or install. "
            "Please ensure network access and rerun setup."
        )

    avd_root.mkdir(parents=True, exist_ok=True)
    user_home.mkdir(parents=True, exist_ok=True)
    avd_folder = avd_root / f"{avd_name}.avd"
    avd_folder.mkdir(parents=True, exist_ok=True)

    print(f"Creating portable AVD '{avd_name}' in {avd_folder}...")
    run(
        _exec_cmd(
            avdmanager,
            "create", "avd",
            "-n", avd_name,
            "-k", "system-images;android-36;google_apis;x86_64",
            "-g", "google_apis",
            "-b", "x86_64",
            "--device", "pixel_7",
            "-c", "512M",
            "-p", str(avd_folder),
            "--force",
        ),
        check=True,
        cwd=sdk_root,
        env=env,
        input_text="y\n" * 10,
    )

    # Ensure .ini points to the local .avd directory
    ini_file = avd_root / f"{avd_name}.ini"
    ini_content = (
        f"avd.ini.encoding=UTF-8\n"
        f"path={avd_folder}\n"
        f"path.rel=avds/{avd_name}.avd\n"
        f"target=android-36\n"
    )
    ini_file.write_text(ini_content, encoding="utf-8")

    # Ensure hardware-qemu.ini exists
    hw_config = avd_folder / "hardware-qemu.ini"
    if not hw_config.exists():
        hw_config.write_text(
            "hw.cpu.ncore = 4\n"
            "hw.ramSize = 4096\n"
            "hw.screensTouch = yes\n"
            "hw.keyboard = yes\n"
            "hw.trackMouse = yes\n",
            encoding="utf-8",
        )

    # Ensure config.ini has Google Play Store enabled and sensors configured from config.json
    cfg_file = avd_folder / "config.ini"
    if cfg_file.exists():
        cfg_lines = cfg_file.read_text(encoding="utf-8", errors="replace").splitlines()
        cfg_dict = {}
        for line in cfg_lines:
            if "=" in line:
                k, v = line.split("=", 1)
                cfg_dict[k.strip()] = v.strip()
        sensor_defaults = _CONFIG.get("hardening", {}).get("hardware_sensors", {})
        for sk, sv in sensor_defaults.items():
            cfg_dict[sk] = sv
        cfg_file.write_text("\n".join(f"{k}={v}" for k, v in cfg_dict.items()) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def bootstrap(
    sdk_root: Path = DEFAULT_SDK_ROOT,
    avd_root: Path = DEFAULT_AVD_ROOT,
    user_home: Path = DEFAULT_USER_HOME,
    avd_name: str = DEFAULT_AVD_NAME,
    jdk_root: Path = DEFAULT_JDK_ROOT,
) -> SetupResult:
    """Executes full automated bootstrap and returns SetupResult."""
    if CONSOLE is not None:
        CONSOLE.print("[bold green]Starting Portable Android SDK bootstrap[/bold green]")
        CONSOLE.print(f"[dim]Repo Root: {REPO_ROOT}[/dim]")
        CONSOLE.print(f"[dim]SDK Root:  {sdk_root}[/dim]")
        CONSOLE.print(f"[dim]AVD Root:  {avd_root}[/dim]")

    sdk_root.mkdir(parents=True, exist_ok=True)
    avd_root.mkdir(parents=True, exist_ok=True)
    user_home.mkdir(parents=True, exist_ok=True)

    # 1. Ensure Java / OpenJDK
    detected_jdk = ensure_java(jdk_root)
    env = get_portable_env(sdk_root, avd_root, user_home, detected_jdk or jdk_root)

    # 2. Check & announce WHPX acceleration
    whpx_ok = whpx_is_active(sdk_root)
    if not whpx_ok:
        msg = (
            "Notice: WHPX / Hypervisor Platform is not active. "
            "Emulator will run with -accel off. "
            "For full performance, enable Windows Hypervisor Platform or VT-x in BIOS."
        )
        if CONSOLE is not None:
            CONSOLE.print(f"[bold yellow]{msg}[/bold yellow]")
        else:
            print(msg)
    else:
        if CONSOLE is not None:
            CONSOLE.print("[bold green]✓ Hardware acceleration (WHPX/Hypervisor) is active![/bold green]")

    # 3. Check for existing system SDK to link fast
    if not has_command_line_tools(sdk_root):
        import_existing_assets(sdk_root)

    # 4. Command-line tools
    if not has_command_line_tools(sdk_root):
        print("Command-line Tools not found. Downloading...")
        install_command_line_tools(sdk_root)

    # 5. Licenses & Packages
    accept_all_licenses(sdk_root, env)
    install_packages(sdk_root, REQUIRED_PACKAGES, env)

    emulator_bin = sdk_root / "emulator" / "emulator.exe"
    adb_bin = sdk_root / "platform-tools" / "adb.exe"

    if not emulator_bin.exists():
        raise RuntimeError(f"emulator.exe not found at {emulator_bin}")
    if not adb_bin.exists():
        raise RuntimeError(f"adb.exe not found at {adb_bin}")

    # 6. Create base AVD
    avd_ini = avd_root / f"{avd_name}.ini"
    avd_folder = avd_root / f"{avd_name}.avd"
    avd_created = False
    if not (avd_ini.exists() and avd_folder.exists() and (avd_folder / "config.ini").exists()):
        create_avd(sdk_root, avd_name, avd_root, user_home, env)
        avd_created = True
    else:
        print(f"Base AVD '{avd_name}' already exists at {avd_folder}.")

    if CONSOLE is not None:
        CONSOLE.print("[bold green]Portable setup complete![/bold green]")
        CONSOLE.print(f"SDK:      {sdk_root}")
        CONSOLE.print(f"AVD:      {avd_name} ({avd_root})")
        CONSOLE.print(f"WHPX:     {'active' if whpx_is_active(sdk_root) else 'inactive'}")

    return SetupResult(
        sdk_root=sdk_root,
        avd_root=avd_root,
        avd_name=avd_name,
        emulator=emulator_bin,
        platform_tools=sdk_root / "platform-tools",
        avd_created=avd_created,
        whpx_active=whpx_is_active(sdk_root),
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Portable Android SDK & AVD bootstrap (API 36)")
    parser.add_argument(
        "--sdk-root",
        type=Path,
        default=DEFAULT_SDK_ROOT,
        help="SDK root to use/install (default: <repo>/android-sdk)",
    )
    parser.add_argument(
        "--avd-root",
        type=Path,
        default=DEFAULT_AVD_ROOT,
        help="AVD directory (default: <repo>/avds)",
    )
    parser.add_argument(
        "--avd-name",
        type=str,
        default=DEFAULT_AVD_NAME,
        help="Base AVD name (default: Android16_Pro)",
    )
    parser.add_argument(
        "--skip-install",
        action="store_true",
        help="Only check WHPX and print paths; do not install.",
    )
    parser.add_argument("--yes", "-y", action="store_true", help="Non-interactive; auto-confirm.")
    args = parser.parse_args(argv)

    if args.skip_install:
        print(f"WHPX active: {whpx_is_active(args.sdk_root)}")
        print(f"SDK:         {args.sdk_root}")
        print(f"AVD root:    {args.avd_root}")
        print(f"Emulator:    {(args.sdk_root / 'emulator' / 'emulator.exe').exists()}")
        return 0

    try:
        bootstrap(
            sdk_root=args.sdk_root,
            avd_root=args.avd_root,
            avd_name=args.avd_name,
        )
        return 0
    except KeyboardInterrupt:
        print("\nOperation cancelled by user.")
        return 130
    except Exception as exc:
        if CONSOLE is not None:
            CONSOLE.print(f"[bold red]Error:[/bold red] {exc}")
        else:
            print(f"Error: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())

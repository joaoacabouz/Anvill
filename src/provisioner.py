"""Automated Android SDK, OpenJDK, licenses, packages and AVD provisioner."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import sys

_SRC_DIR = Path(__file__).resolve().parent
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

try:
    from config import get_target_image_info, load_config
    from constants import (
        AVD_ROOT,
        DEFAULT_AVD_NAME,
        JDK_ROOT,
        SDK_ROOT,
        USER_HOME,
    )
    from inspector import whpx_is_active
except ImportError:
    from src.config import get_target_image_info, load_config
    from src.constants import (
        AVD_ROOT,
        DEFAULT_AVD_NAME,
        JDK_ROOT,
        SDK_ROOT,
        USER_HOME,
    )
    from src.inspector import whpx_is_active


def _log(msg: str) -> None:
    try:
        from ui import log
        log(msg)
    except Exception:
        print(msg)


# Official known SDK license hashes
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


def ensure_java(jdk_root: Path = JDK_ROOT) -> Path | None:
    """Ensures a working Java Runtime is available for sdkmanager/avdmanager."""
    java_exe = jdk_root / "bin" / ("java.exe" if platform.system() == "Windows" else "java")
    if java_exe.exists():
        return jdk_root

    host_java = shutil.which("java")
    if host_java:
        try:
            res = subprocess.run([host_java, "-version"], capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
            if res.returncode == 0:
                return None
        except Exception:
            pass

    cfg = load_config()
    jdk_url = cfg.get("sdk", {}).get(
        "openjdk_17_url",
        "https://api.adoptium.net/v3/binary/latest/17/ga/windows/x64/jdk/hotspot/normal/eclipse",
    )
    _log(f"No Java detected. Downloading portable OpenJDK 17 to {jdk_root}...")
    jdk_root.mkdir(parents=True, exist_ok=True)
    zip_path = jdk_root / "openjdk17.zip"
    try:
        req = urllib.request.Request(jdk_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req) as resp, open(zip_path, "wb") as out_file:
            shutil.copyfileobj(resp, out_file)

        temp_extract = jdk_root / "_temp_extract"
        temp_extract.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path, "r") as z:
            z.extractall(temp_extract)

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
        _log(f"Portable OpenJDK 17 installed at {jdk_root}")
        return jdk_root
    except Exception as exc:
        _log(f"Warning: Failed to auto-download OpenJDK: {exc}")
        return None


def run(
    cmd: list[str],
    cwd: Path | None = None,
    check: bool = True,
    env: dict[str, str] | None = None,
    input_text: str | None = None,
) -> subprocess.CompletedProcess:
    """Executes a command safely with list arguments (shell=False)."""
    cwd_str = str(cwd) if cwd is not None else None
    if env is None:
        env = dict(os.environ)
    extra: dict[str, int] = {}
    if platform.system() == "Windows":
        extra["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
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
            input=input_text,
            **extra,
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


def _find_java_exe(sdk_root: Path | None = None, env: dict[str, str] | None = None) -> Path | None:
    """Locates java.exe from portable JDK, env, or system PATH."""
    java_name = "java.exe" if platform.system() == "Windows" else "java"
    # 1. Repo portable JDK
    local_java = JDK_ROOT / "bin" / java_name
    if local_java.exists():
        return local_java
    # 2. Check repo parent if sdk_root provided
    if sdk_root is not None:
        sibling_java = sdk_root.parent / "jdk" / "bin" / java_name
        if sibling_java.exists():
            return sibling_java
    # 3. Environment JAVA_HOME
    if env and "JAVA_HOME" in env:
        ej = Path(env["JAVA_HOME"]) / "bin" / java_name
        if ej.exists():
            return ej
    if "JAVA_HOME" in os.environ:
        ej = Path(os.environ["JAVA_HOME"]) / "bin" / java_name
        if ej.exists():
            return ej
    # 4. System PATH
    which_java = shutil.which(java_name)
    if which_java:
        return Path(which_java)
    return None


def _exec_cmd(path: Path, *args: str) -> list[str]:
    """Build a subprocess arg list for a binary or batch wrapper on Windows."""
    if platform.system() == "Windows" and path.suffix.lower() == ".bat":
        safe_args = [f'"{a}"' if (";" in a and not (a.startswith('"') and a.endswith('"'))) else a for a in args]
        return ["cmd", "/c", str(path), *safe_args]
    return [str(path), *args]


def _sdkmanager_cmd(sdk_root: Path, *args: str, env: dict[str, str] | None = None) -> list[str]:
    """Build a subprocess arg list for sdkmanager (direct Java preferred, avoids cmd.exe semicolon bugs)."""
    java_exe = _find_java_exe(sdk_root, env)
    for sub in ("latest", "cmdline-tools"):
        cp = sdk_root / "cmdline-tools" / sub / "lib" / "sdkmanager-classpath.jar"
        if cp.exists() and java_exe and java_exe.exists():
            tools_dir = cp.parent.parent
            return [
                str(java_exe),
                f"-Dcom.android.sdklib.toolsdir={tools_dir}",
                "-classpath",
                str(cp),
                "com.android.sdklib.tool.sdkmanager.SdkManagerCli",
                f"--sdk_root={sdk_root}",
                *args,
            ]

    # Native android binary fallback if present
    android_bin = sdk_root / "cmdline-tools" / "latest" / "bin" / ("android.exe" if platform.system() == "Windows" else "android")
    if android_bin.exists():
        slash_args = [a.replace(";", "/") for a in args]
        return [str(android_bin), f"--sdk={sdk_root}", "sdk", *slash_args]

    # Batch script fallback
    for sub in ("latest", "cmdline-tools"):
        sdkmanager_bat = sdk_root / "cmdline-tools" / sub / "bin" / ("sdkmanager.bat" if platform.system() == "Windows" else "sdkmanager")
        if sdkmanager_bat.exists():
            return _exec_cmd(sdkmanager_bat, f"--sdk_root={sdk_root}", *args)

    sdkmanager_def = sdk_root / "cmdline-tools" / "latest" / "bin" / ("sdkmanager.bat" if platform.system() == "Windows" else "sdkmanager")
    return _exec_cmd(sdkmanager_def, f"--sdk_root={sdk_root}", *args)


def _avdmanager_cmd(sdk_root: Path, *args: str, env: dict[str, str] | None = None) -> list[str]:
    """Build a subprocess arg list for avdmanager (direct Java preferred, avoids cmd.exe semicolon bugs)."""
    java_exe = _find_java_exe(sdk_root, env)
    for sub in ("latest", "cmdline-tools"):
        cp = sdk_root / "cmdline-tools" / sub / "lib" / "avdmanager-classpath.jar"
        if cp.exists() and java_exe and java_exe.exists():
            tools_dir = cp.parent.parent
            return [
                str(java_exe),
                f"-Dcom.android.sdkmanager.toolsdir={tools_dir}",
                "-classpath",
                str(cp),
                "com.android.sdklib.tool.AvdManagerCli",
                *args,
            ]

    for sub in ("latest", "cmdline-tools"):
        avdmanager_bat = sdk_root / "cmdline-tools" / sub / "bin" / ("avdmanager.bat" if platform.system() == "Windows" else "avdmanager")
        if avdmanager_bat.exists():
            return _exec_cmd(avdmanager_bat, *args)

    avdmanager_def = sdk_root / "cmdline-tools" / "latest" / "bin" / ("avdmanager.bat" if platform.system() == "Windows" else "avdmanager")
    return _exec_cmd(avdmanager_def, *args)


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
            _log(f"Found existing Android SDK at {cand}. Linking packages locally for fast portable setup...")
            for sub in ("licenses", "cmdline-tools", "emulator", "platform-tools", "system-images", "extras"):
                src_sub = cand / sub
                dst_sub = target_sdk / sub
                if src_sub.exists() and not dst_sub.exists():
                    _log(f"  Importing {sub} -> {dst_sub}...")
                    link_tree(src_sub, dst_sub)
            return True
    return False


def download_zip(url: str, dest: Path) -> None:
    """Downloads a ZIP file to destination."""
    _log(f"Downloading {url} -> {dest}...")
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
    cfg = load_config()
    url = cfg.get("sdk", {}).get(
        "command_line_tools_url",
        "https://dl.google.com/android/repository/commandlinetools-win-11076708_latest.zip",
    )
    zip_path = sdk_root / "cmdlinetools.zip"
    download_zip(url, zip_path)

    temp_extract = sdk_root / "_cmdline_temp"
    temp_extract.mkdir(parents=True, exist_ok=True)
    extract_zip(zip_path, temp_extract)

    latest_dir = sdk_root / "cmdline-tools" / "latest"
    latest_dir.parent.mkdir(parents=True, exist_ok=True)
    if latest_dir.exists():
        shutil.rmtree(latest_dir)

    src_folder = temp_extract / "cmdline-tools"
    if src_folder.exists():
        shutil.move(str(src_folder), str(latest_dir))
    else:
        shutil.move(str(temp_extract), str(latest_dir))

    shutil.rmtree(temp_extract, ignore_errors=True)
    zip_path.unlink(missing_ok=True)


def accept_all_licenses(sdk_root: Path, env: dict[str, str]) -> None:
    """Accepts all Android SDK licenses non-interactively."""
    _log("Accepting SDK licenses...")
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

    try:
        cmd = _sdkmanager_cmd(sdk_root, "--licenses", env=env)
        run(cmd, cwd=sdk_root, env=env, input_text="y\n" * 100)
    except Exception as exc:
        _log(f"Note: sdkmanager --licenses check completed ({exc})")


def install_sdk_package(sdk_root: Path, package: str, env: dict[str, str]) -> None:
    """Installs an SDK package using direct Java execution, native android CLI, or sdkmanager."""
    pkg_semi = package.replace("/", ";")
    pkg_slash = package.replace(";", "/")

    # Native android binary if available in future cmdline-tools releases
    android_bin = sdk_root / "cmdline-tools" / "latest" / "bin" / ("android.exe" if platform.system() == "Windows" else "android")
    if android_bin.exists():
        cmd = [str(android_bin), f"--sdk={sdk_root}", "sdk", "install", pkg_slash]
        run(cmd, cwd=sdk_root, check=True, env=env, input_text="y\n" * 10)
        return

    # Direct Java SdkManagerCli or classic sdkmanager with native semicolon format
    cmd = _sdkmanager_cmd(sdk_root, pkg_semi, env=env)
    try:
        run(cmd, cwd=sdk_root, check=True, env=env, input_text="y\n" * 10)
    except Exception:
        # Fallback to slash notation if specific platform tool requires it
        cmd_slash = _sdkmanager_cmd(sdk_root, pkg_slash, env=env)
        run(cmd_slash, cwd=sdk_root, check=True, env=env, input_text="y\n" * 10)


def install_packages(sdk_root: Path, packages: Sequence[str], env: dict[str, str]) -> None:
    """Installs requested packages via android CLI or sdkmanager."""
    for package in packages:
        pkg_norm = package.replace(";", "/")
        if pkg_norm.startswith("system-images/"):
            parts = pkg_norm.split("/")
            if len(parts) >= 4 and (sdk_root / "system-images" / parts[1] / parts[2] / parts[3]).exists():
                _log(f"Package {package} is already installed.")
                continue
        elif pkg_norm == "emulator" and (sdk_root / "emulator" / "emulator.exe").exists():
            _log("Package emulator is already installed.")
            continue
        elif pkg_norm == "platform-tools" and (sdk_root / "platform-tools" / "adb.exe").exists():
            _log("Package platform-tools is already installed.")
            continue
        elif pkg_norm == "extras/google/usb_driver" and (sdk_root / "extras" / "google" / "usb_driver").exists():
            _log("Package usb_driver is already installed.")
            continue
        elif pkg_norm == "extras/google/Android_Emulator_Hypervisor_Driver" and (
            sdk_root / "extras" / "google" / "Android_Emulator_Hypervisor_Driver"
        ).exists():
            _log("Package Android_Emulator_Hypervisor_Driver is already installed.")
            continue

        _log(f"Installing {package}...")
        try:
            install_sdk_package(sdk_root, package, env)
        except Exception as exc:
            if "extras" in package:
                _log(f"Notice: Optional driver {package} skipped or not required ({exc})")
            else:
                _log(f"Warning: Failed to install package {package}: {exc}")


def create_avd(
    sdk_root: Path,
    avd_name: str,
    avd_root: Path,
    user_home: Path,
    env: dict[str, str],
) -> None:
    """Creates base AVD dynamically using the target image configured in config.json."""
    cfg = load_config()
    tinfo = get_target_image_info(cfg)
    sys_img_dir = sdk_root / "system-images" / tinfo["api"] / tinfo["tag"] / tinfo["abi"]
    if not sys_img_dir.exists():
        _log(f"System image not found at {sys_img_dir}. Attempting direct package installation...")
        try:
            install_sdk_package(sdk_root, tinfo["semi"], env)
        except Exception as exc:
            _log(f"Direct install failed: {exc}")

    if not sys_img_dir.exists():
        raise RuntimeError(
            f"System image not found at {sys_img_dir}. "
            f"The system-images package '{tinfo['semi']}' failed to download or install. "
            "Please ensure network access and rerun setup."
        )

    avd_root.mkdir(parents=True, exist_ok=True)
    user_home.mkdir(parents=True, exist_ok=True)
    avd_folder = avd_root / f"{avd_name}.avd"
    avd_folder.mkdir(parents=True, exist_ok=True)

    _log(f"Creating portable AVD '{avd_name}' in {avd_folder} (target: {tinfo['api']})...")
    avd_cmd = _avdmanager_cmd(
        sdk_root,
        "create", "avd",
        "-n", avd_name,
        "-k", tinfo["semi"],
        "-g", tinfo["tag"],
        "-b", tinfo["abi"],
        "--device", "pixel_tablet",
        "-c", "512M",
        "-p", str(avd_folder),
        "--force",
        env=env,
    )
    run(
        avd_cmd,
        check=True,
        cwd=sdk_root,
        env=env,
        input_text="y\n" * 10,
    )

    ini_file = avd_root / f"{avd_name}.ini"
    ini_content = (
        f"avd.ini.encoding=UTF-8\n"
        f"path={avd_folder}\n"
        f"path.rel=avds/{avd_name}.avd\n"
        f"target={tinfo['api']}\n"
    )
    ini_file.write_text(ini_content, encoding="utf-8")

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

    # Configure hardware sensors and PlayStore from config.json
    cfg = load_config()
    cfg_file = avd_folder / "config.ini"
    if cfg_file.exists():
        cfg_lines = cfg_file.read_text(encoding="utf-8", errors="replace").splitlines()
        cfg_dict = {}
        for line in cfg_lines:
            if "=" in line:
                k, v = line.split("=", 1)
                cfg_dict[k.strip()] = v.strip()
        sensor_defaults = cfg.get("hardening", {}).get("hardware_sensors", {})
        for sk, sv in sensor_defaults.items():
            cfg_dict[sk] = sv
        cfg_file.write_text("\n".join(f"{k}={v}" for k, v in cfg_dict.items()) + "\n", encoding="utf-8")


def bootstrap(
    sdk_root: Path = SDK_ROOT,
    avd_root: Path = AVD_ROOT,
    user_home: Path = USER_HOME,
    avd_name: str = DEFAULT_AVD_NAME,
    jdk_root: Path = JDK_ROOT,
    auto_root: bool = True,
) -> SetupResult:
    """Executes full automated bootstrap, creates AVD, and performs initial root/hardening."""
    _log("[bold green]Starting Portable Android SDK bootstrap[/bold green]")
    _log(f"[dim]SDK Root:  {sdk_root}[/dim]")
    _log(f"[dim]AVD Root:  {avd_root}[/dim]")

    sdk_root.mkdir(parents=True, exist_ok=True)
    avd_root.mkdir(parents=True, exist_ok=True)
    user_home.mkdir(parents=True, exist_ok=True)

    detected_jdk = ensure_java(jdk_root)
    env = get_portable_env(sdk_root, avd_root, user_home, detected_jdk or jdk_root)

    whpx_ok = whpx_is_active(sdk_root)
    if not whpx_ok:
        _log(
            "Notice: WHPX / Hypervisor Platform is not active. "
            "Emulator will run with -accel off. "
            "For full performance, enable Windows Hypervisor Platform or VT-x in BIOS."
        )
    else:
        _log("[bold green]✓ Hardware acceleration (WHPX/Hypervisor) is active![/bold green]")

    if not has_command_line_tools(sdk_root):
        import_existing_assets(sdk_root)

    if not has_command_line_tools(sdk_root):
        _log("Command-line Tools not found. Downloading...")
        install_command_line_tools(sdk_root)

    accept_all_licenses(sdk_root, env)

    cfg = load_config()
    required_pkgs = cfg.get("sdk", {}).get("required_packages", [
        "emulator",
        "platform-tools",
        "system-images/android-36/google_apis/x86_64",
        "extras/google/usb_driver",
        "extras/google/Android_Emulator_Hypervisor_Driver",
    ])
    install_packages(sdk_root, required_pkgs, env)

    emulator_bin = sdk_root / "emulator" / "emulator.exe"
    adb_bin = sdk_root / "platform-tools" / "adb.exe"

    if not emulator_bin.exists():
        raise RuntimeError(f"emulator.exe not found at {emulator_bin}")
    if not adb_bin.exists():
        raise RuntimeError(f"adb.exe not found at {adb_bin}")

    avd_ini = avd_root / f"{avd_name}.ini"
    avd_folder = avd_root / f"{avd_name}.avd"
    avd_created = False
    if not (avd_ini.exists() and avd_folder.exists() and (avd_folder / "config.ini").exists()):
        create_avd(sdk_root, avd_name, avd_root, user_home, env)
        avd_created = True
    else:
        _log(f"AVD '{avd_name}' is already created in {avd_folder}.")

    # 7. Automated First-Boot Root & Real-Device Provisioning
    should_auto_root = auto_root and cfg.get("vm", {}).get("auto_root_on_setup", True)
    if should_auto_root:
        _log("\n[bold green]Executing First-Boot Automated Root & Real-Device Provisioning...[/bold green]")
        _log("Booting emulator headlessly, injecting Magisk, debloating non-essentials & hardening device...")
        try:
            from rooting import root_avd
            ret = root_avd(
                repo_root=sdk_root.parent,
                avd_name=avd_name,
                restore=False,
                debloat=True,
                spoof=True,
            )
            if ret == 0:
                _log("[bold green]✓ Initial setup with Magisk root, debloat & real-device hardening complete![/bold green]")
            else:
                _log(f"Notice: Root provisioning finished with exit code {ret}.")
        except Exception as exc:
            _log(f"Notice during first-boot root: {exc}. You can run root.bat manually at any time.")

    return SetupResult(
        sdk_root=sdk_root,
        avd_root=avd_root,
        avd_name=avd_name,
        emulator=emulator_bin,
        platform_tools=adb_bin,
        avd_created=avd_created,
        whpx_active=whpx_ok,
    )

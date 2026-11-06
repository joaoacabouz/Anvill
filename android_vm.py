#!/usr/bin/env python3
"""CLI orchestrator + interactive menu to provision, configure and launch an
Android 16 (API 36) emulator on Windows, based on the Android SDK QEMU engine.

Auto-adapts to host hardware (CPU/RAM/GPU), uses JSON profiles and supports
device spoofing via ADB. No .ps1/.bat scripts are used for logic.

Examples:
    python android_vm.py                                        # interactive menu
    python android_vm.py --profile ultra --spoof s23_ultra
    python android_vm.py --profile auto --avd Android16_Pro --scrcpy
    python android_vm.py --profile balanced --safe-gpu

Portable & standalone: all SDK, AVD, and emulator files are self-contained
within this repository directory.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Literal, Sequence, Tuple

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

from setup_sdk import (  # noqa: E402
    DEFAULT_AVD_NAME,
    DEFAULT_AVD_ROOT,
    DEFAULT_SDK_ROOT,
    DEFAULT_USER_HOME,
    bootstrap,
    get_portable_env,
    whpx_is_active,
)

# ---------------------------------------------------------------------------
# Rich TUI / Console Setup
# ---------------------------------------------------------------------------
try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.progress import Progress
    import rich.prompt as rich_prompt
    from rich.table import Table
    from rich.text import Text

    _RICH = True
except ImportError:
    _RICH = False

CONSOLE: Console | None = Console() if _RICH else None


# ---------------------------------------------------------------------------
# Path Constants (pathlib everywhere, no hardcoded path strings)
# ---------------------------------------------------------------------------
REPO_ROOT: Path = Path(__file__).resolve().parent
PROFILES_PATH: Path = REPO_ROOT / "profiles.json"
SDK_ROOT: Path = DEFAULT_SDK_ROOT
AVD_ROOT: Path = DEFAULT_AVD_ROOT
USER_HOME: Path = DEFAULT_USER_HOME

API_LEVEL = 36
TARGET_IMAGE = "system-images/android-36/google_apis/x86_64"
GPU_REG_KEY = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"


def _print(msg: str) -> None:
    """Safe log print: uses rich console if available, otherwise plain print."""
    if CONSOLE is not None:
        CONSOLE.print(msg)
    else:
        clean = re.sub(r"\[/?\w+(?:=[^\]]*)?\]", "", msg)
        print(clean)


class EmulatorNotFoundError(RuntimeError):
    """Raised when the emulator binary is not found."""


class ProfilesError(RuntimeError):
    """Raised when the profiles JSON is invalid."""


# ---------------------------------------------------------------------------
# Data Models (dataclasses with type hints)
# ---------------------------------------------------------------------------
@dataclass
class HostCPU:
    """Host CPU description."""

    vendor: str
    physical_cores: int
    logical_threads: int

    def is_amd(self) -> bool:
        return "AMD" in self.vendor

    def is_intel(self) -> bool:
        return "Intel" in self.vendor


@dataclass
class HostRAM:
    """Host RAM description (in MB)."""

    total_mb: int
    available_mb: int

    @property
    def free_pct(self) -> float:
        if self.total_mb == 0:
            return 0.0
        return round(100.0 * self.available_mb / self.total_mb, 1)


@dataclass
class HostGPU:
    """Host primary GPU description."""

    model: str
    vendor: Literal["NVIDIA", "AMD", "INTEL_INTEGRATED", "OTHER", "UNKNOWN"]

    def is_dedicated(self) -> bool:
        return self.vendor in ("NVIDIA", "AMD")


@dataclass
class HostInspector:
    """Detects CPU, RAM and GPU of the computer in real time."""

    cpu: HostCPU
    ram: HostRAM
    gpu: HostGPU

    @classmethod
    def detect(cls) -> "HostInspector":
        return cls(
            cpu=cls._detect_cpu(),
            ram=cls._detect_ram(),
            gpu=cls._detect_gpu(),
        )

    @classmethod
    def from_cpu_ram(cls, cpu: HostCPU, ram: HostRAM) -> "HostInspector":
        return cls(cpu=cpu, ram=ram, gpu=cls._detect_gpu())

    @staticmethod
    def _detect_cpu() -> HostCPU:
        try:
            import psutil
        except ImportError:
            import psutil  # type: ignore[no-redef]  # noqa: F811

        vendor = ""
        logical = psutil.cpu_count(logical=True) or 1
        physical = psutil.cpu_count(logical=False) or logical

        if platform.system() == "Windows":
            try:
                import winreg
                key = winreg.OpenKey(
                    winreg.HKEY_LOCAL_MACHINE,
                    r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
                    0,
                    winreg.KEY_READ | winreg.KEY_WOW64_32KEY,
                )
                try:
                    vendor = winreg.QueryValueEx(key, "ProcessorNameString")[0]
                finally:
                    winreg.CloseKey(key)
            except OSError:
                pass

        if vendor is None or not vendor.strip():
            vendor = platform.processor() or "Unknown"

        if "AMD" in vendor or vendor.startswith("AuthenticAMD"):
            vendor_clean = f"AMD ({vendor.strip()})"
        elif "Intel" in vendor or vendor.startswith("GenuineIntel"):
            vendor_clean = f"Intel ({vendor.strip()})"
        else:
            vendor_clean = vendor.strip()

        return HostCPU(
            vendor=vendor_clean,
            physical_cores=physical,
            logical_threads=logical,
        )

    @staticmethod
    def _detect_ram() -> HostRAM:
        try:
            import psutil
        except ImportError:
            import psutil  # type: ignore[no-redef]  # noqa: F811

        mem = psutil.virtual_memory()  # type: ignore[no-any-return]
        total_mb = round(mem.total / (1024 * 1024))
        available_mb = round(mem.available / (1024 * 1024))
        return HostRAM(total_mb=total_mb, available_mb=available_mb)

    @staticmethod
    def _detect_gpu() -> HostGPU:
        if platform.system() == "Windows":
            try:
                import winreg

                key = winreg.OpenKey(
                    winreg.HKEY_LOCAL_MACHINE,
                    GPU_REG_KEY,
                    0,
                    winreg.KEY_READ | winreg.KEY_WOW64_32KEY,
                )
                try:
                    subkey_count, _, _ = winreg.QueryInfoKey(key)
                    for i in range(subkey_count):
                        try:
                            subkey_name = winreg.EnumKey(key, i)
                            subkey = winreg.OpenKey(
                                key, subkey_name, 0, winreg.KEY_READ | winreg.KEY_WOW64_32KEY
                            )
                            try:
                                desc, _ = winreg.QueryValueEx(subkey, "DriverDesc")
                                if desc:
                                    desc_str = str(desc).strip()
                                    if "NVIDIA" in desc_str.upper():
                                        return HostGPU(model=desc_str, vendor="NVIDIA")
                                    if "AMD" in desc_str.upper() or "RADEON" in desc_str.upper():
                                        return HostGPU(model=desc_str, vendor="AMD")
                                    if "INTEL" in desc_str.upper():
                                        return HostGPU(model=desc_str, vendor="INTEL_INTEGRATED")
                            finally:
                                winreg.CloseKey(subkey)
                        except OSError:
                            continue
                finally:
                    winreg.CloseKey(key)
            except OSError:
                pass

        if HostInspector._probe_nvidia_smi():
            return HostGPU(model="NVIDIA GPU (detected via nvidia-smi)", vendor="NVIDIA")
        if HostInspector._probe_amd():
            return HostGPU(model="AMD GPU (detected)", vendor="AMD")

        return HostGPU(
            model="Integrated/Generic GPU (fallback: angle_indirect)",
            vendor="INTEL_INTEGRATED",
        )

    @staticmethod
    def _probe_nvidia_smi() -> bool:
        return shutil.which("nvidia-smi") is not None

    @staticmethod
    def _probe_amd() -> bool:
        return shutil.which("radeon-profile") is not None or shutil.which("radeontop") is not None


@dataclass
class VMProfile:
    """VM configuration after profile resolution."""

    ram_mb: int
    heap_mb: int
    cpu_cores: int
    width: int
    height: int
    dpi: int
    fps: int
    disk_gb: int

    @property
    def display(self) -> Tuple[int, int]:
        return self.width, self.height

    def screen_density(self) -> int:
        return self.dpi


@dataclass
class DeviceSpoof:
    """Device properties to inject via ADB (setprop)."""

    props: Dict[str, str]

    def is_empty(self) -> bool:
        return not self.props


# ---------------------------------------------------------------------------
# 'auto' Profile Resolution
# ---------------------------------------------------------------------------
def resolve_auto_profile(inspector: HostInspector) -> VMProfile:
    """Calculates the 'auto' profile dynamically from host hardware."""
    ram_total_gb = inspector.ram.total_mb / 1024.0

    if ram_total_gb >= 28:
        ram_mb, heap_mb = 12288, 1024
    elif ram_total_gb >= 15:
        ram_mb, heap_mb = 8192, 768
    else:
        ram_mb, heap_mb = 4096, 512

    logical = inspector.cpu.logical_threads
    cpu_cores = max(2, min(8, round(logical * 0.5)))

    return VMProfile(
        ram_mb=ram_mb,
        heap_mb=heap_mb,
        cpu_cores=cpu_cores,
        width=1080,
        height=2400,
        dpi=420,
        fps=60,
        disk_gb=32,
    )


# ---------------------------------------------------------------------------
# Loading and Resolving Profiles (profiles.json)
# ---------------------------------------------------------------------------
def load_profiles(path: Path | None = None) -> Dict[str, Any]:
    """Loads profiles.json."""
    if path is None:
        path = PROFILES_PATH
    if not path.exists():
        raise ProfilesError(f"Profiles not found at {path}")

    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)

    missing = [k for k in ("hardware_profiles", "spoof_profiles") if k not in data]
    if missing:
        raise ProfilesError(f"profiles.json invalid: missing {missing}")

    return data  # type: ignore[return-value]


def get_hardware_profile(data: Dict[str, Any], name: str, inspector: HostInspector | None = None) -> VMProfile:
    """Resolves a hardware profile by name ('auto' or a fixed profile)."""
    profiles = data["hardware_profiles"]
    if name not in profiles:
        names = ", ".join(profiles)
        raise ProfilesError(f"Profile '{name}' does not exist. Options: {names}")

    spec = profiles[name]
    if name == "auto":
        insp = inspector or HostInspector.detect()
        return resolve_auto_profile(inspector=insp)

    required = ("ram_mb", "heap_mb", "cpu_cores", "width", "height", "dpi", "fps", "disk_gb")
    for key in required:
        if key not in spec:
            raise ProfilesError(f"Profile '{name}' is missing '{key}' in hardware_profiles")

    return VMProfile(
        ram_mb=spec["ram_mb"],
        heap_mb=spec["heap_mb"],
        cpu_cores=spec["cpu_cores"],
        width=spec["width"],
        height=spec["height"],
        dpi=spec["dpi"],
        fps=spec["fps"],
        disk_gb=spec["disk_gb"],
    )


def get_spoof_profile(data: Dict[str, Any], name: str) -> DeviceSpoof:
    """Resolves a spoofing profile by name.

    Filters out metadata like 'description' and '_empty' to only keep valid Android properties.
    """
    profiles = data["spoof_profiles"]
    if name not in profiles:
        names = ", ".join(profiles)
        raise ProfilesError(f"Spoof '{name}' does not exist. Options: {names}")

    spec = profiles[name]
    if not isinstance(spec, dict) or "_empty" in spec:
        return DeviceSpoof(props={})

    # Only include keys that look like valid Android property keys (e.g. ro.*, sys.*, persist.*, etc.)
    props = {
        k: str(v)
        for k, v in spec.items()
        if isinstance(k, str) and not k.startswith("_") and k != "description"
    }
    return DeviceSpoof(props=props)


# ---------------------------------------------------------------------------
# config.ini Handler (key-value without sections, atomic UTF-8 without BOM)
# ---------------------------------------------------------------------------
@dataclass
class AvdConfig:
    """AVD config.ini: key-value parser/writer without section headers."""

    path: Path
    values: Dict[str, str] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> "AvdConfig":
        config = cls(path=path, values={})
        if not path.exists():
            return config
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or line.startswith(";"):
                continue
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            config.values[key.strip()] = value.strip()
        return config

    def has_value(self, key: str) -> bool:
        return key in self.values

    def __setitem__(self, key: str, value: str) -> None:
        self.values[key] = value

    def update_from(self, profile: VMProfile, gpu_mode: str) -> None:
        """Applies VM profile keys into the config."""
        self["hw.ramSize"] = str(profile.ram_mb)
        self["vm.heapSize"] = f"{profile.heap_mb}M"
        self["hw.cpu.ncore"] = str(profile.cpu_cores)
        if "disk.dataPartition.size" not in self.values:
            self["disk.dataPartition.size"] = f"{profile.disk_gb}G"
        self["hw.lcd.width"] = str(profile.width)
        self["hw.lcd.height"] = str(profile.height)
        self["hw.lcd.density"] = str(profile.dpi)
        self["hw.lcd.vsync"] = str(profile.fps)
        self["hw.gpu.enabled"] = "yes"
        self["hw.gpu.mode"] = gpu_mode
        self["hw.keyboard"] = "yes"
        self["fastboot.forceColdBoot"] = "no"

    def atomic_write(self) -> None:
        """Writes the file atomically (UTF-8, no BOM)."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        try:
            with tmp.open("w", encoding="utf-8", newline="\n") as fh:
                for key, value in self.values.items():
                    fh.write(f"{key}={value}\n")
            tmp.replace(self.path)
        except BaseException:
            if tmp.exists():
                tmp.unlink(missing_ok=True)
            raise


class AvdConfigurator:
    """Builds, applies and relocates AVD config.ini and .ini files."""

    REQUIRED_KEYS = (
        "hw.ramSize",
        "vm.heapSize",
        "hw.cpu.ncore",
        "disk.dataPartition.size",
        "hw.lcd.width",
        "hw.lcd.height",
        "hw.lcd.density",
        "hw.lcd.vsync",
        "hw.gpu.enabled",
        "hw.gpu.mode",
        "hw.keyboard",
        "fastboot.forceColdBoot",
    )

    def __init__(
        self,
        avd_name: str,
        sdk_root: Path | None = None,
        avd_root: Path | None = None,
    ):
        self.avd_name = avd_name
        self.sdk_root = sdk_root or SDK_ROOT
        self.avd_root = avd_root or AVD_ROOT
        self.avd_dir = self.avd_root / f"{self.avd_name}.avd"
        self.config_path = self.avd_dir / "config.ini"
        self.relocate_paths()

    def relocate_paths(self) -> None:
        """Self-healing portability: updates .ini and config.ini paths if the repo moved."""
        # 1. Update <avd_name>.ini path
        ini_file = self.avd_root / f"{self.avd_name}.ini"
        if ini_file.exists():
            lines = ini_file.read_text(encoding="utf-8").splitlines()
            expected_path = str(self.avd_dir)
            updated_lines = []
            needs_update = False
            for line in lines:
                if line.startswith("path="):
                    curr_path = line.split("=", 1)[1].strip()
                    if curr_path != expected_path:
                        updated_lines.append(f"path={expected_path}")
                        needs_update = True
                    else:
                        updated_lines.append(line)
                else:
                    updated_lines.append(line)
            if needs_update:
                ini_file.write_text("\n".join(updated_lines) + "\n", encoding="utf-8")

        # 2. Update image.sysdir.1 if needed
        if self.config_path.exists():
            cfg = self.load()
            sysdir = cfg.values.get("image.sysdir.1", "")
            # Ensure sysdir is valid relative or points inside current SDK
            if not sysdir or (not (self.sdk_root / sysdir).exists() and not Path(sysdir).exists()):
                cfg["image.sysdir.1"] = r"system-images\android-36\google_apis\x86_64\\"
                cfg.atomic_write()

        # 3. Heal hardware-qemu.ini if paths point to a previous host location
        hw_file = self.avd_dir / "hardware-qemu.ini"
        if hw_file.exists():
            try:
                content = hw_file.read_text(encoding="utf-8", errors="ignore")
                needs_regen = False
                for line in content.splitlines():
                    if "=" in line:
                        k, v = [x.strip() for x in line.split("=", 1)]
                        if k in ("kernel.path", "disk.systemPartition.initPath", "android.sdk.root"):
                            if not Path(v).exists():
                                needs_regen = True
                                break
                if needs_regen:
                    hw_file.unlink(missing_ok=True)
            except Exception:
                pass

    def load(self) -> AvdConfig:
        """Loads current config.ini (preserving existing/critical keys)."""
        return AvdConfig.load(self.config_path)

    def apply(self, profile: VMProfile, gpu_mode: str) -> AvdConfig:
        """Applies VM profile and writes config.ini."""
        config = self.load()
        config.update_from(profile, gpu_mode)
        config.atomic_write()
        self.ensure_hw_qemu_ini(profile.cpu_cores, profile.ram_mb)
        return config

    def ensure_hw_qemu_ini(self, cpu_cores: int, ram_mb: int) -> Path:
        """Ensures a hardware-qemu.ini exists for the emulator."""
        hw_path = self.avd_dir / "hardware-qemu.ini"
        if not hw_path.exists():
            hw_path.parent.mkdir(parents=True, exist_ok=True)
            hw_path.write_text(
                f"hw.cpu.ncore = {cpu_cores}\n"
                f"hw.ramSize = {ram_mb}\n"
                "hw.screensTouch = yes\n"
                "hw.keyboard = yes\n"
                "hw.trackMouse = yes\n",
                encoding="utf-8",
            )
        return hw_path


# ---------------------------------------------------------------------------
# Emulator Argument Builder
# ---------------------------------------------------------------------------
@dataclass
class LaunchFlags:
    """Emulator launch flags builder."""

    profile: VMProfile
    gpu_mode: str
    avd_name: str
    scrcpy: bool
    safe_gpu: bool
    gpu_vendor: str
    writable_system: bool = False
    use_accel: bool = True
    no_boot_anim: bool = False
    cold_boot: bool = False
    wipe_data: bool = False
    custom_system: Path | None = None
    custom_ramdisk: Path | None = None
    custom_sysdir: Path | None = None

    @property
    def is_safe_gpu(self) -> bool:
        return self.safe_gpu or self.gpu_vendor == "INTEL_INTEGRATED"

    def build_args(self) -> Sequence[str]:
        """Builds the full argument list for emulator.exe."""
        args: list[str] = []

        # GPU
        if self.is_safe_gpu:
            args += ["-gpu", "auto"]
        else:
            args += ["-gpu", "host", "-feature", "Vulkan", "-feature", "GLDirectMem"]

        # Base flags
        args += ["-avd", self.avd_name]
        args += ["-accel", "on" if self.use_accel else "off"]
        if self.writable_system:
            args.append("-writable-system")
        if self.no_boot_anim:
            args.append("-no-boot-anim")
        if self.cold_boot:
            args.append("-no-snapshot")
        if self.wipe_data:
            args.append("-wipe-data")

        # Custom system / ramdisk / sysdir images
        if self.custom_system:
            args.extend(["-system", str(self.custom_system)])
        if self.custom_ramdisk:
            args.extend(["-ramdisk", str(self.custom_ramdisk)])
        if self.custom_sysdir:
            args.extend(["-sysdir", str(self.custom_sysdir)])

        # Window / framebuffer (scrcpy runs headless)
        if self.scrcpy:
            args.extend(["-no-window", "-no-audio"])

        # Raw QEMU flags
        # NOTE: On Windows with WHPX, '-cpu max' causes an unrecoverable exception
        # ('WHPX: Unexpected VP exit code 4') because Hyper-V rejects unsupported MSRs.
        # Android Emulator automatically selects the optimal virtual CPU for WHPX.
        qemu_args = ["-qemu", "-usb", "-device", "usb-kbd", "-device", "usb-mouse"]
        if platform.system() != "Windows":
            qemu_args.extend(["-cpu", "max"])
        args += qemu_args
        return args

    def build_scrcpy_args(self) -> Sequence[str]:
        """Builds scrcpy arguments after boot."""
        return ["scrcpy", "--max-fps=120", "--video-bit-rate=16M"]


def pick_gpu_mode(host: HostInspector, safe_gpu: bool) -> str:
    """Chooses GPU mode based on vendor and --safe-gpu flag."""
    if safe_gpu or host.gpu.vendor == "INTEL_INTEGRATED":
        return "auto"
    return "host"


# ---------------------------------------------------------------------------
# ADB Automation & Device Spoofing
# ---------------------------------------------------------------------------
class AdbManager:
    """Automates ADB interaction: wait-for-device, boot_completed, setprop."""

    def __init__(
        self,
        platform_tools: Path | None = None,
        env: dict[str, str] | None = None,
        serial: str | None = "-e",
    ):
        self.platform_tools = platform_tools or (SDK_ROOT / "platform-tools")
        self.adb = self.platform_tools / ("adb.exe" if platform.system() == "Windows" else "adb")
        self.env = env or dict(os.environ)
        self.serial = serial
        self.device_ready = False

    def run(self, *args: str, timeout: int | None = None) -> subprocess.CompletedProcess:
        """Runs an ADB command with a safe argument list."""
        cmd = [str(self.adb)]
        if self.serial:
            if self.serial == "-e":
                cmd.append("-e")
            else:
                cmd.extend(["-s", self.serial])
        cmd.extend(args)
        return subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=self.env,
        )

    def wait_for_device(self, timeout: int = 120) -> bool:
        """Executes `adb wait-for-device` with fallback state polling."""
        try:
            result = self.run("wait-for-device", timeout=timeout)
            if result.returncode == 0:
                self.device_ready = True
                return True
        except subprocess.TimeoutExpired:
            pass

        end = time.monotonic() + timeout
        while time.monotonic() < end:
            try:
                status = self.run("get-state", timeout=5).stdout.strip()
                if status == "device":
                    self.device_ready = True
                    return True
            except Exception:
                pass
            time.sleep(1)
        return False

    def wait_for_boot_completed(self, interval: int = 2, timeout: int = 120) -> bool:
        """Poll `adb shell getprop sys.boot_completed` until it returns '1'."""
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            try:
                result = self.run("shell", "getprop", "sys.boot_completed", timeout=15)
                if result.stdout.strip() == "1":
                    return True
            except Exception:
                pass
            time.sleep(interval)
        return False

    def apply_spoof(self, spoof: DeviceSpoof, persist: bool = False) -> bool:
        """Applies device spoofing properties via ADB."""
        if spoof.is_empty():
            return True

        _print("[cyan]Applying device spoofing via ADB...[/cyan]")
        root_result = self.run("root", timeout=15)
        if root_result.returncode != 0:
            _print(f"[yellow]adb root response: {root_result.stdout.strip() or root_result.stderr.strip()}[/yellow]")

        # Reconnect
        time.sleep(1)
        self.wait_for_device(timeout=30)

        # Inject properties
        applied = 0
        for key, value in spoof.props.items():
            result = self.run("shell", "setprop", key, value, timeout=20)
            if result.returncode == 0:
                applied += 1
            else:
                _print(f"[yellow]setprop {key} failed: {result.stderr.strip()}[/yellow]")

        _print(f"[green]Applied {applied}/{len(spoof.props)} spoof properties[/green]")

        if persist:
            self.persist_spoof(spoof)

        return True

    def persist_spoof(self, spoof: DeviceSpoof) -> bool:
        """Persists props into writable system partition via remount."""
        result = self.run("remount", timeout=30)
        if result.returncode != 0:
            _print(f"[yellow]adb remount unavailable: {result.stdout.strip() or result.stderr.strip()}[/yellow]")
            return False
        for key, value in spoof.props.items():
            self.run("shell", "setprop", key, value, timeout=20)
        _print("[green]Spoof properties persisted into filesystem[/green]")
        return True


# ---------------------------------------------------------------------------
# Emulator Launcher & Process Management
# ---------------------------------------------------------------------------
class EmulatorLauncher:
    """Launches emulator as a subprocess and manages scrcpy & shutdown."""

    def __init__(
        self,
        emulator_path: Path,
        flags: LaunchFlags,
        adb: AdbManager,
        env: dict[str, str],
        console: Console | None = None,
    ):
        self.emulator_path = emulator_path
        self.flags = flags
        self.adb = adb
        self.env = env
        self.console = console or CONSOLE
        self.process: subprocess.Popen[bytes] | None = None
        self.scrcpy_process: subprocess.Popen[bytes] | None = None
        self.scrcpy_started = False
        self._output_thread: threading.Thread | None = None

    def launch(self, ready_timeout: int = 180) -> subprocess.Popen[bytes]:
        """Launches the emulator and awaits device readiness."""
        args = [str(self.emulator_path)] + list(self.flags.build_args())

        if CONSOLE is not None:
            CONSOLE.print(Panel(f"Emulator: {self.emulator_path}\nAVD: {self.flags.avd_name}", title="Launch", border_style="cyan"))
        _print("Command: " + " ".join(args))
        _print(f"[dim]GPU: {self.flags.gpu_mode} | Acceleration: {'on' if self.flags.use_accel else 'off'}[/dim]")

        self.process = subprocess.Popen(
            args,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=0,
            env=self.env,
        )
        self._output_thread = threading.Thread(target=self._stream_output, daemon=True)
        self._output_thread.start()

        _print("[cyan]Waiting for Android device to connect...[/cyan]")
        self.adb.wait_for_device(timeout=ready_timeout)

        if self.adb.device_ready:
            _print("[green]Device connected. Waiting for boot completion...[/green]")
        else:
            _print("[yellow]Device not detected yet — emulator is booting...[/yellow]")

        if self.adb.wait_for_boot_completed(interval=2, timeout=120):
            _print("[bold green]Android 16 Boot complete![/bold green]")
        else:
            _print("[yellow]Boot polling timed out — emulator may still be initializing...[/yellow]")

        return self.process

    def _stream_output(self) -> None:
        """Streams emulator stdout/stderr to the console."""
        assert self.process is not None
        assert self.process.stdout is not None
        for line in iter(self.process.stdout.readline, b""):
            try:
                text = line.decode("utf-8", errors="replace").rstrip()
            except Exception:
                text = str(line)
            if text:
                _print(f"[dim][emulator] {text}[/dim]")

    def maybe_start_scrcpy(self, ready_timeout: int = 120) -> None:
        """Starts scrcpy after boot if requested."""
        if not self.flags.scrcpy or self.scrcpy_started:
            return

        scrcpy_bin = shutil.which("scrcpy")
        if not scrcpy_bin:
            _print("[yellow]scrcpy not found in PATH. Install scrcpy to use --scrcpy.[/yellow]")
            return

        if not self.adb.wait_for_device(timeout=ready_timeout):
            _print("[yellow]scrcpy: device not ready[/yellow]")
            return

        args = list(self.flags.build_scrcpy_args())
        _print(f"[cyan]Starting scrcpy: {' '.join(args)}[/cyan]")
        self.scrcpy_process = subprocess.Popen(
            [scrcpy_bin] + args[1:],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=0,
            env=self.env,
        )
        self.scrcpy_started = True

    def wait(self) -> None:
        """Waits for emulator process or keyboard interrupt."""
        try:
            assert self.process is not None
            rc = self.process.wait()
            if rc != 0:
                _print(f"[yellow]Emulator exited with code {rc}[/yellow]")
        except KeyboardInterrupt:
            _print("[dim]Received Ctrl+C — shutting down emulator...[/dim]")
            self.shutdown()

    def shutdown(self) -> None:
        """Gracefully shuts down scrcpy and emulator processes."""
        if self.scrcpy_process is not None and self.scrcpy_process.poll() is None:
            try:
                self.scrcpy_process.terminate()
                self.scrcpy_process.wait(timeout=5)
            except Exception:
                self.scrcpy_process.kill()
            _print("[dim]scrcpy terminated[/dim]")
        if self.process is not None and self.process.poll() is None:
            try:
                self.process.terminate()
                self.process.wait(timeout=10)
            except Exception:
                self.process.kill()
            _print("[dim]emulator terminated[/dim]")


# ---------------------------------------------------------------------------
# Interactive Menu (Rich TUI or Stdlib Fallback)
# ---------------------------------------------------------------------------
def print_banner() -> None:
    if _RICH and CONSOLE is not None:
        banner = Text()
        banner.append("Android 16 Portable Emulator Launcher\n", style="bold green")
        banner.append("Modular, Portable (dp0), Multi-Hardware — Python 3.10+\n", style="bold cyan")
        banner.append(f"Workspace: {REPO_ROOT}", style="dim")
        CONSOLE.print(Panel(banner, title="Anvill Android VM", border_style="cyan"))
    else:
        print("=" * 60)
        print("Android 16 Portable Emulator Launcher")
        print(f"Workspace: {REPO_ROOT}")
        print("=" * 60)


def print_hardware_panel(inspector: HostInspector) -> None:
    if _RICH and CONSOLE is not None:
        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("Component", style="cyan")
        table.add_column("Details", style="white")

        table.add_row(
            "CPU",
            f"{inspector.cpu.vendor} ({inspector.cpu.physical_cores} cores / {inspector.cpu.logical_threads} threads)",
        )
        table.add_row(
            "RAM",
            f"{inspector.ram.total_mb} MB total | {inspector.ram.available_mb} MB available ({inspector.ram.free_pct}%)",
        )
        table.add_row("GPU", f"{inspector.gpu.vendor} — {inspector.gpu.model}")

        CONSOLE.print(Panel(table, title="Detected Host Hardware", border_style="green"))
    else:
        print(f"CPU : {inspector.cpu.vendor} | {inspector.cpu.physical_cores} cores / {inspector.cpu.logical_threads} threads")
        print(f"RAM : {inspector.ram.total_mb} MB total | {inspector.ram.available_mb} MB available ({inspector.ram.free_pct}%)")
        print(f"GPU : {inspector.gpu.vendor} — {inspector.gpu.model}")


def interactive_menu(hardware: Dict[str, Any], spoof: Dict[str, Any]) -> Tuple[str, str]:
    """Interactive number-based selection menu."""
    hw_keys = list(hardware.keys())
    sp_keys = list(spoof.keys())

    if _RICH and CONSOLE is not None:
        hw_table = Table(title="Hardware Profiles", show_header=True, header_style="bold cyan")
        hw_table.add_column("#", style="bold yellow", width=4)
        hw_table.add_column("Profile", style="bold white", width=12)
        hw_table.add_column("Description", style="dim")

        for idx, k in enumerate(hw_keys, start=1):
            hw_table.add_row(str(idx), k, hardware[k].get("description", ""))
        CONSOLE.print(hw_table)

        sp_table = Table(title="Device Spoofing Profiles", show_header=True, header_style="bold cyan")
        sp_table.add_column("#", style="bold yellow", width=4)
        sp_table.add_column("Profile", style="bold white", width=14)
        sp_table.add_column("Description", style="dim")

        for idx, k in enumerate(sp_keys, start=1):
            sp_table.add_row(str(idx), k, spoof[k].get("description", ""))
        CONSOLE.print(sp_table)

        p_choice = rich_prompt.Prompt.ask("[bold blue]Select hardware profile[/bold blue] (number)", default="1")
        s_choice = rich_prompt.Prompt.ask("[bold blue]Select spoof profile[/bold blue] (number)", default="1")

        try:
            p_idx = int(p_choice) - 1
            s_idx = int(s_choice) - 1
        except ValueError:
            p_idx, s_idx = 0, len(sp_keys) - 1
    else:
        print("\nHardware Profiles:")
        for idx, k in enumerate(hw_keys, start=1):
            print(f"  {idx}. {k} — {hardware[k].get('description', '')}")
        print("\nDevice Spoofing Profiles:")
        for idx, k in enumerate(sp_keys, start=1):
            print(f"  {idx}. {k} — {spoof[k].get('description', '')}")

        try:
            p_idx = int(input("\nSelect hardware profile (number) [1]: ") or "1") - 1
            s_idx = int(input("Select spoof profile (number) [1]: ") or "1") - 1
        except Exception:
            p_idx, s_idx = 0, 0

    p_name = hw_keys[p_idx] if 0 <= p_idx < len(hw_keys) else "auto"
    s_name = sp_keys[s_idx] if 0 <= s_idx < len(sp_keys) else "stock"
    return p_name, s_name


# ---------------------------------------------------------------------------
# CLI Argument Parser
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="android_vm.py",
        description="Modular, portable Android 16 (API 36) emulator provisioner & launcher.",
    )
    parser.add_argument(
        "--profile",
        default=None,
        choices=list(load_profiles()["hardware_profiles"].keys()),
        help="Hardware profile ('auto' or a fixed profile name).",
    )
    parser.add_argument(
        "--spoof",
        default=None,
        choices=list(load_profiles()["spoof_profiles"].keys()),
        help="Device spoofing profile (e.g. s23_ultra, rog_phone_7, stock).",
    )
    parser.add_argument("--avd", default=DEFAULT_AVD_NAME, help=f"AVD name (default: {DEFAULT_AVD_NAME}).")
    parser.add_argument("--scrcpy", action="store_true", help="Launch scrcpy automatically after device boot.")
    parser.add_argument("--safe-gpu", action="store_true", help="Force safe GPU mode.")
    parser.add_argument("--writable-system", action="store_true", help="Make system partition writable.")
    parser.add_argument("--no-boot-anim", action="store_true", help="Disable boot animation.")
    parser.add_argument("--cold-boot", action="store_true", help="Force cold boot (disable snapshots).")
    parser.add_argument("--wipe-data", action="store_true", help="Reset user data to default state.")
    parser.add_argument("--persist-spoof", action="store_true", help="Persist spoof properties via adb remount.")
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
        if not spoof.is_empty():
            if launcher.adb.wait_for_boot_completed(interval=2, timeout=120):
                launcher.adb.apply_spoof(spoof, persist=persist_spoof)
            else:
                _print("[yellow]Boot not detected yet — skipping initial spoofing injection[/yellow]")
        else:
            _print("[dim]Device spoofing: none (stock x86_64)[/dim]")

        launcher.maybe_start_scrcpy(ready_timeout=120)
        launcher.wait()
        return 0
    except KeyboardInterrupt:
        launcher.shutdown()
        return 130


# ---------------------------------------------------------------------------
# Main Entry Point
# ---------------------------------------------------------------------------
def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    sdk_root = args.sdk_root
    avd_root = args.avd_root
    avd_name = args.avd or DEFAULT_AVD_NAME

    if args.root_magisk:
        from root_avd import root_avd
        return root_avd(repo_root=REPO_ROOT, avd_name=avd_name, restore=False)

    if args.restore_root:
        from root_avd import root_avd
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
        s_name = args.spoof or "stock"

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

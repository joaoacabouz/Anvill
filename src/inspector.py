"""Host hardware detection and virtualization inspection."""

from __future__ import annotations

import os
import platform
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

GpuVendor = Literal["NVIDIA", "AMD", "INTEL_INTEGRATED", "OTHER", "UNKNOWN"]
GPU_REG_KEY = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"


@dataclass
class HostCPU:
    """Host CPU description."""

    vendor: str
    physical_cores: int
    logical_threads: int

    def is_amd(self) -> bool:
        return "amd" in self.vendor.lower()


@dataclass
class HostRAM:
    """System RAM in megabytes."""

    total_mb: int
    available_mb: int

    @property
    def free_pct(self) -> float:
        if self.total_mb == 0:
            return 0.0
        return round(100.0 * self.available_mb / self.total_mb, 1)


@dataclass
class HostGPU:
    """Detected graphics adapter."""

    model: str
    vendor: GpuVendor
    name: str = ""

    def __init__(self, model: str = "", vendor: GpuVendor = "UNKNOWN", name: str = ""):
        self.model = model or name
        self.vendor = vendor
        self.name = self.model

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
            except Exception:
                vendor = platform.processor() or "Unknown CPU"
        else:
            vendor = platform.processor() or "Unknown CPU"

        return HostCPU(vendor=vendor, physical_cores=physical, logical_threads=logical)

    @staticmethod
    def _detect_ram() -> HostRAM:
        try:
            import psutil
            mem = psutil.virtual_memory()
            return HostRAM(
                total_mb=int(mem.total // (1024 * 1024)),
                available_mb=int(mem.available // (1024 * 1024)),
            )
        except Exception:
            return HostRAM(total_mb=8192, available_mb=4096)

    @classmethod
    def _detect_gpu(cls) -> HostGPU:
        if platform.system() == "Windows":
            return cls._detect_gpu_windows()
        return HostGPU(model="Generic GPU", vendor="UNKNOWN")

    @classmethod
    def _detect_gpu_windows(cls) -> HostGPU:
        best_vendor: GpuVendor = "UNKNOWN"
        best_model = "Generic GPU"

        try:
            import winreg
            base_key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, GPU_REG_KEY, 0, winreg.KEY_READ)
            try:
                subkeys_count = winreg.QueryInfoKey(base_key)[0]
                for idx in range(subkeys_count):
                    try:
                        subkey_name = winreg.EnumKey(base_key, idx)
                        subkey = winreg.OpenKey(base_key, subkey_name, 0, winreg.KEY_READ)
                        try:
                            desc, _ = winreg.QueryValueEx(subkey, "DriverDesc")
                            vendor = cls._vendor_from_description(desc)
                            if vendor == "NVIDIA" or (vendor == "AMD" and best_vendor != "NVIDIA"):
                                best_vendor = vendor
                                best_model = desc
                            elif vendor == "INTEL_INTEGRATED" and best_vendor == "UNKNOWN":
                                best_vendor = vendor
                                best_model = desc
                            elif best_vendor == "UNKNOWN" and desc:
                                best_model = desc
                        except OSError:
                            pass
                        finally:
                            winreg.CloseKey(subkey)
                    except OSError:
                        pass
            finally:
                winreg.CloseKey(base_key)
        except Exception:
            pass

        return HostGPU(model=best_model, vendor=best_vendor)

    @staticmethod
    def _vendor_from_description(desc: str) -> GpuVendor:
        lower = desc.lower()
        if "nvidia" in lower or "geforce" in lower or "quadro" in lower or "rtx" in lower or "gtx" in lower:
            return "NVIDIA"
        if "amd" in lower or "radeon" in lower:
            return "AMD"
        if "intel" in lower or "uhd" in lower or "iris" in lower or "hd graphics" in lower:
            return "INTEL_INTEGRATED"
        return "OTHER"


def whpx_is_active(sdk_root: Path | None = None) -> bool:
    """Checks whether WHPX (Windows Hypervisor Platform) or hardware acceleration is operational."""
    if platform.system() != "Windows":
        return True

    try:
        from constants import DEFAULT_SDK_ROOT
    except ImportError:
        from src.constants import DEFAULT_SDK_ROOT

    cand_emulators = []
    if sdk_root is not None:
        cand_emulators.append(sdk_root / "emulator" / "emulator.exe")
    cand_emulators.append(DEFAULT_SDK_ROOT / "emulator" / "emulator.exe")
    if "LOCALAPPDATA" in os.environ:
        cand_emulators.append(Path(os.environ["LOCALAPPDATA"]) / "Android" / "Sdk" / "emulator" / "emulator.exe")

    for emu in cand_emulators:
        if emu.exists():
            try:
                res = subprocess.run(
                    [str(emu), "-accel-check"],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=5,
                )
                out = (res.stdout + res.stderr).lower()
                if res.returncode == 0 and ("usable" in out or "operational" in out or "installed" in out):
                    return True
            except Exception:
                pass

    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Virtualization",
            0,
            winreg.KEY_READ | winreg.KEY_WOW64_64KEY,
        )
        try:
            val, _ = winreg.QueryValueEx(key, "HypervisorPresent")
            if val == 1:
                return True
        finally:
            winreg.CloseKey(key)
    except Exception:
        pass

    try:
        import ctypes
        whv = ctypes.WinDLL("WinHvPlatform.dll")
        if whv:
            return True
    except Exception:
        pass

    return False

"""Anvill - Modular, Portable Android 16 (API 36) Emulator Provisioner & Orchestrator."""

from __future__ import annotations

__version__ = "1.0.0"

from anvill.adb import AdbManager
from anvill.config import get_bloatware_packages, get_protected_packages, load_config
from anvill.configurator import AvdConfig, AvdConfigurator
from anvill.constants import (
    AVD_ROOT,
    CONFIG_PATH,
    DEFAULT_AVD_NAME,
    JDK_ROOT,
    PROFILES_PATH,
    REPO_ROOT,
    ROOTAVD_DIR,
    SDK_ROOT,
    TOOLS_ROOT,
    USER_HOME,
)
from anvill.debloat import debloat_android
from anvill.hardening import (
    apply_real_device_hardening,
    build_anti_detection_script,
    harden_avd_config,
)
from anvill.inspector import HostCPU, HostGPU, HostInspector, HostRAM, whpx_is_active
from anvill.launcher import EmulatorLauncher, LaunchFlags, pick_gpu_mode
from anvill.profiles import (
    DeviceSpoof,
    ProfilesError,
    VMProfile,
    get_hardware_profile,
    get_spoof_profile,
    load_profiles,
)
from anvill.provisioner import (
    accept_all_licenses,
    bootstrap,
    create_avd,
    get_portable_env,
    install_packages,
    install_sdk_package,
)
from anvill.rooting import root_avd

__all__ = [
    "AdbManager",
    "AvdConfig",
    "AvdConfigurator",
    "AVD_ROOT",
    "CONFIG_PATH",
    "DEFAULT_AVD_NAME",
    "DeviceSpoof",
    "EmulatorLauncher",
    "HostCPU",
    "HostGPU",
    "HostInspector",
    "HostRAM",
    "JDK_ROOT",
    "LaunchFlags",
    "PROFILES_PATH",
    "ProfilesError",
    "REPO_ROOT",
    "ROOTAVD_DIR",
    "SDK_ROOT",
    "TOOLS_ROOT",
    "USER_HOME",
    "VMProfile",
    "accept_all_licenses",
    "apply_real_device_hardening",
    "bootstrap",
    "build_anti_detection_script",
    "create_avd",
    "debloat_android",
    "get_bloatware_packages",
    "get_hardware_profile",
    "get_portable_env",
    "get_protected_packages",
    "get_spoof_profile",
    "harden_avd_config",
    "install_packages",
    "install_sdk_package",
    "load_config",
    "load_profiles",
    "pick_gpu_mode",
    "root_avd",
    "whpx_is_active",
]

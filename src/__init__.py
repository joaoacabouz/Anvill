"""Anvill - Modular, Portable Android Emulator Provisioner & Orchestrator."""

from __future__ import annotations

import sys
from pathlib import Path

_SRC_DIR = Path(__file__).resolve().parent
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

__version__ = "1.0.0"

try:
    from .adb import AdbManager
    from .config import (
        get_bloatware_packages,
        get_protected_packages,
        get_target_image_info,
        load_config,
    )
    from .configurator import AvdConfig, AvdConfigurator
    from .constants import (
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
    from .debloat import debloat_android
    from .hardening import (
        apply_real_device_hardening,
        build_anti_detection_script,
        harden_avd_config,
    )
    from .inspector import HostCPU, HostGPU, HostInspector, HostRAM, whpx_is_active
    from .launcher import EmulatorLauncher, LaunchFlags, pick_gpu_mode
    from .profiles import (
        DeviceSpoof,
        ProfilesError,
        VMProfile,
        get_hardware_profile,
        get_spoof_profile,
        load_profiles,
    )
    from .provisioner import (
        accept_all_licenses,
        bootstrap,
        create_avd,
        get_portable_env,
        install_packages,
        install_sdk_package,
    )
    from .rooting import root_avd
except ImportError:
    from adb import AdbManager
    from config import (
        get_bloatware_packages,
        get_protected_packages,
        get_target_image_info,
        load_config,
    )
    from configurator import AvdConfig, AvdConfigurator
    from constants import (
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
    from debloat import debloat_android
    from hardening import (
        apply_real_device_hardening,
        build_anti_detection_script,
        harden_avd_config,
    )
    from inspector import HostCPU, HostGPU, HostInspector, HostRAM, whpx_is_active
    from launcher import EmulatorLauncher, LaunchFlags, pick_gpu_mode
    from profiles import (
        DeviceSpoof,
        ProfilesError,
        VMProfile,
        get_hardware_profile,
        get_spoof_profile,
        load_profiles,
    )
    from provisioner import (
        accept_all_licenses,
        bootstrap,
        create_avd,
        get_portable_env,
        install_packages,
        install_sdk_package,
    )
    from rooting import root_avd

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
    "get_target_image_info",
    "harden_avd_config",
    "install_packages",
    "install_sdk_package",
    "load_config",
    "load_profiles",
    "pick_gpu_mode",
    "root_avd",
    "whpx_is_active",
]

"""Configuration Manager for Anvill.

Loads and validates system-wide configurations from config.json, keeping
runtime settings, debloat rules, anti-detection policies, and SDK definitions
completely separated from hardware/device profiles in profiles.json.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Set

_SRC_DIR = Path(__file__).resolve().parent
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

try:
    from constants import CONFIG_PATH
except ImportError:
    from src.constants import CONFIG_PATH

# In-memory default configuration fallback
DEFAULT_CONFIG: Dict[str, Any] = {
    "vm": {
        "avd_name": "Android14_PlayStore",
        "auto_root_on_setup": True,
        "default_hardware_profile": "auto",
        "default_spoof_profile": "s23_ultra",
        "default_gpu_mode": "auto",
        "cold_boot": False,
        "safe_gpu": False,
        "no_boot_anim": False,
        "writable_system": False,
        "scrcpy": {
            "enabled": False,
            "max_fps": 120,
            "video_bit_rate": "16M",
        },
    },
    "debloat": {
        "enabled_by_default": True,
        "bloatware_packages": [],
        "protected_packages": [
            "com.android.vending",
            "com.google.android.gms",
            "com.google.android.gsf",
            "com.android.systemui",
            "com.android.settings",
            "com.android.webview",
            "com.topjohnwu.magisk",
        ],
    },
    "hardening": {
        "enabled_by_default": True,
        "qemu_props_to_delete": [
            "ro.kernel.qemu",
            "ro.boot.qemu",
            "init.svc.qemud",
            "init.svc.goldfish-logcat",
            "init.svc.ranchu-setup",
            "init.svc.ranchu-net",
            "ro.hardware.virtual_device",
            "ro.boot.hardware.sku",
            "ro.emulator.circular",
        ],
        "settings_overrides": {
            "global": {
                "adb_enabled": "0",
                "development_settings_enabled": "0",
                "package_verifier_user_consent": "1",
                "install_non_market_apps": "1",
            },
            "secure": {
                "mock_location": "0",
            },
        },
        "magisk_denylist_packages": [
            "com.google.android.gms",
            "com.google.android.gms.unstable",
            "com.android.vending",
        ],
        "hardware_sensors": {
            "PlayStore.enabled": "yes",
            "hw.battery": "yes",
            "hw.camera.back": "virtualscene",
            "hw.camera.front": "emulated",
            "hw.gps": "yes",
            "hw.sensors.orientation": "yes",
            "hw.sensors.proximity": "yes",
            "hw.sensors.light": "yes",
            "hw.sensors.magnetic_field": "yes",
            "hw.sensors.pressure": "yes",
            "hw.sensors.humidity": "yes",
            "hw.sensors.temperature": "yes",
            "hw.accelerometer": "yes",
            "hw.gyroscope": "yes",
        },
    },
    "sdk": {
        "target_image": "system-images/android-34/google_apis_playstore/x86_64",
        "command_line_tools_url": "https://dl.google.com/android/repository/commandlinetools-win-11076708_latest.zip",
        "openjdk_17_url": "https://api.adoptium.net/v3/binary/latest/17/ga/windows/x64/jdk/hotspot/normal/eclipse",
        "required_packages": [
            "emulator",
            "platform-tools",
            "system-images/android-34/google_apis_playstore/x86_64",
            "extras/google/usb_driver",
            "extras/google/Android_Emulator_Hypervisor_Driver",
        ],
    },
}


def load_config(config_path: Path | None = None) -> Dict[str, Any]:
    """Loads configuration dictionary from config.json with fallback to defaults."""
    path = config_path or CONFIG_PATH
    if not path.exists():
        return dict(DEFAULT_CONFIG)

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return dict(DEFAULT_CONFIG)

        # Merge with defaults to ensure all required sub-dictionaries exist
        merged = dict(DEFAULT_CONFIG)
        for section in ("vm", "debloat", "hardening", "sdk"):
            if section in data and isinstance(data[section], dict):
                merged[section] = {**DEFAULT_CONFIG.get(section, {}), **data[section]}
        return merged
    except Exception:
        return dict(DEFAULT_CONFIG)


def get_bloatware_packages(config: Dict[str, Any] | None = None) -> List[str]:
    """Returns the list of bloatware packages configured for debloating."""
    cfg = config or load_config()
    return list(cfg.get("debloat", {}).get("bloatware_packages", []))


def get_protected_packages(config: Dict[str, Any] | None = None) -> Set[str]:
    """Returns the set of protected packages that must NEVER be removed or disabled."""
    cfg = config or load_config()
    return set(cfg.get("debloat", {}).get("protected_packages", []))


def get_target_image_info(config: Dict[str, Any] | None = None) -> Dict[str, str]:
    """Dynamically parses target image configuration (not limited to any single Android version).
    
    Returns breakdown with api level, tag, abi, relative sysdir and ramdisk paths.
    """
    cfg = config or load_config()
    target = cfg.get("sdk", {}).get("target_image", "system-images/android-34/google_apis_playstore/x86_64")
    norm = target.replace(";", "/").strip("/")
    parts = [p for p in norm.split("/") if p]
    if len(parts) >= 4 and parts[0] == "system-images":
        api, tag, abi = parts[1], parts[2], parts[3]
    elif len(parts) >= 3:
        api, tag, abi = parts[0], parts[1], parts[2]
    else:
        api, tag, abi = "android-34", "google_apis_playstore", "x86_64"

    return {
        "raw": target,
        "slash": f"system-images/{api}/{tag}/{abi}",
        "semi": f"system-images;{api};{tag};{abi}",
        "api": api,                                        # e.g. "android-34"
        "tag": tag,                                        # e.g. "google_apis_playstore"
        "abi": abi,                                        # e.g. "x86_64"
        "rel_sysdir": f"system-images/{api}/{tag}/{abi}",
        "rel_ramdisk": f"system-images/{api}/{tag}/{abi}/ramdisk.img",
    }


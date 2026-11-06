"""Profiles Manager for Anvill.

Loads and resolves hardware execution profiles and device spoofing profiles
from profiles.json.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Tuple

import sys

_SRC_DIR = Path(__file__).resolve().parent
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

try:
    from constants import PROFILES_PATH
    from inspector import HostInspector
except ImportError:
    from src.constants import PROFILES_PATH
    from src.inspector import HostInspector


class ProfilesError(RuntimeError):
    """Raised when the profiles JSON is invalid or missing."""


@dataclass
class VMProfile:
    """VM hardware configuration after profile resolution."""

    ram_mb: int
    heap_mb: int
    cpu_cores: int
    width: int
    height: int
    dpi: int
    fps: int
    disk_gb: int
    name: str = ""

    @property
    def display(self) -> Tuple[int, int]:
        return self.width, self.height

    def screen_density(self) -> int:
        return self.dpi


@dataclass
class DeviceSpoof:
    """Device properties to inject via ADB (setprop)."""

    props: Dict[str, str] = field(default_factory=dict)
    name: str = ""

    def __init__(
        self,
        props: Dict[str, str] | None = None,
        name: str = "",
        properties: Dict[str, str] | None = None,
    ):
        raw = props if props is not None else (properties or {})
        self.props = {
            k: str(v)
            for k, v in raw.items()
            if isinstance(k, str) and not k.startswith("_") and k != "description"
        }
        self.name = name

    def is_empty(self) -> bool:
        return not self.props

    def get(self, key: str, default: str | None = None) -> str | None:
        return self.props.get(key, default)

    @property
    def properties(self) -> Dict[str, str]:
        return self.props


def resolve_auto_profile(
    inspector_or_ram: Any = None,
    cpu: Any | None = None,
    inspector: Any | None = None,
) -> VMProfile:
    """Calculates the 'auto' profile dynamically from host hardware."""
    target_inspector = inspector if inspector is not None else inspector_or_ram
    if cpu is not None:
        ram = target_inspector
        ram_total_gb = ram.total_mb / 1024.0
        logical = cpu.logical_threads
    else:
        ram_total_gb = target_inspector.ram.total_mb / 1024.0
        logical = target_inspector.cpu.logical_threads

    if ram_total_gb >= 28:
        ram_mb, heap_mb = 12288, 1024
    elif ram_total_gb >= 15:
        ram_mb, heap_mb = 8192, 768
    else:
        ram_mb, heap_mb = 4096, 512

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


def load_profiles(path: Path | None = None) -> Dict[str, Any]:
    """Loads profiles.json."""
    prof_path = path or PROFILES_PATH
    if not prof_path.exists():
        raise ProfilesError(f"Profiles not found at {prof_path}")

    try:
        with prof_path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception as exc:
        raise ProfilesError(f"Failed to parse profiles at {prof_path}: {exc}") from exc

    missing = [k for k in ("hardware_profiles", "spoof_profiles") if k not in data]
    if missing:
        raise ProfilesError(f"profiles.json invalid: missing {missing}")

    return data


def get_hardware_profile(
    data_or_name: Dict[str, Any] | str,
    name_or_data: str | Dict[str, Any] | None = None,
    inspector: HostInspector | None = None,
) -> VMProfile:
    """Resolves a hardware profile by name ('auto' or a fixed profile)."""
    if isinstance(data_or_name, str):
        name = data_or_name
        data = name_or_data if isinstance(name_or_data, dict) else load_profiles()
    else:
        data = data_or_name
        name = str(name_or_data) if name_or_data is not None else "auto"

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
        name=name,
        ram_mb=spec["ram_mb"],
        heap_mb=spec["heap_mb"],
        cpu_cores=spec["cpu_cores"],
        width=spec["width"],
        height=spec["height"],
        dpi=spec["dpi"],
        fps=spec["fps"],
        disk_gb=spec["disk_gb"],
    )


def get_spoof_profile(
    data_or_name: Dict[str, Any] | str,
    name_or_data: str | Dict[str, Any] | None = None,
) -> DeviceSpoof:
    """Resolves a spoofing profile by name.

    Filters out metadata like 'description' and '_empty' to only keep valid Android properties.
    """
    if isinstance(data_or_name, str):
        name = data_or_name
        data = name_or_data if isinstance(name_or_data, dict) else load_profiles()
    else:
        data = data_or_name
        name = str(name_or_data) if name_or_data is not None else "stock"

    profiles = data["spoof_profiles"]
    if name not in profiles:
        names = ", ".join(profiles)
        raise ProfilesError(f"Spoof '{name}' does not exist. Options: {names}")

    spec = profiles[name]
    if not isinstance(spec, dict) or "_empty" in spec:
        return DeviceSpoof(name=name, props={})

    props = {
        k: str(v)
        for k, v in spec.items()
        if isinstance(k, str) and not k.startswith("_") and k != "description"
    }
    return DeviceSpoof(name=name, props=props)


"""AVD configuration reader, writer and self-healing path relocator."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict

_SRC_DIR = Path(__file__).resolve().parent
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

try:
    from constants import AVD_ROOT, SDK_ROOT
    from profiles import VMProfile
    from config import get_target_image_info
except ImportError:
    from src.constants import AVD_ROOT, SDK_ROOT
    from src.profiles import VMProfile
    from src.config import get_target_image_info


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
                tinfo = get_target_image_info()
                cfg["image.sysdir.1"] = tinfo["rel_sysdir"].replace("/", "\\") + "\\"
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


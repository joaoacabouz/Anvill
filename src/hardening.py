"""Real-device anti-detection hardening, property spoofing and sensor injection."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict

_SRC_DIR = Path(__file__).resolve().parent
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

try:
    from config import load_config
    from constants import PROFILES_PATH
except ImportError:
    from src.config import load_config
    from src.constants import PROFILES_PATH


def _log(msg: str) -> None:
    try:
        from ui import log
        log(msg)
    except Exception:
        print(msg)


def build_anti_detection_script(props: dict[str, str], config: dict[str, Any] | None = None) -> str:
    """Builds a portable POSIX shell script to be executed by Magisk at early/late boot."""
    cfg = config or load_config()
    hardening = cfg.get("hardening", {})

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
    ]

    for qprop in hardening.get("qemu_props_to_delete", []):
        lines.append(f"del_prop {qprop}")

    lines.extend([
        "set_prop ro.kernel.qemu 0",
        "set_prop ro.boot.qemu 0",
        "set_prop ro.hardware.virtual_device \"\"",
        "",
        "# 2. Real Hardware & Security Properties",
    ])

    for k, v in props.items():
        if k in ("ro.kernel.qemu", "ro.boot.qemu"):
            continue
        lines.append(f'set_prop {k} "{v}"')

    lines.extend([
        "",
        "# 3. Anti-Detection for Android Settings Inspection",
    ])
    settings_overrides = hardening.get("settings_overrides", {})
    for namespace, kv in settings_overrides.items():
        for skey, sval in kv.items():
            lines.append(f"settings put {namespace} {skey} {sval} 2>/dev/null")

    lines.extend([
        "",
        "# 4. Magisk DenyList (Protects Play Store & Banking apps from root detection)",
        "if command -v magisk >/dev/null 2>&1; then",
        "    magisk --denylist enable 2>/dev/null",
    ])
    for denylist_pkg in hardening.get("magisk_denylist_packages", []):
        lines.append(f"    magisk --denylist add {denylist_pkg} 2>/dev/null")
    lines.extend([
        "fi",
        "",
    ])

    return "\n".join(lines) + "\n"


def harden_avd_config(
    avd_root: Path,
    avd_name: str,
    props: dict[str, str],
    config: dict[str, Any] | None = None,
) -> None:
    """Updates the AVD config.ini to enable hardware sensors, camera, and device manufacturer."""
    config_file = avd_root / f"{avd_name}.avd" / "config.ini"
    if not config_file.exists():
        return

    cfg_dict = config or load_config()
    sensor_defaults = cfg_dict.get("hardening", {}).get("hardware_sensors", {})

    content = config_file.read_text(encoding="utf-8", errors="replace")
    cfg = {}
    for line in content.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            cfg[k.strip()] = v.strip()

    # Apply all sensor & hardware defaults from config.json
    for k, v in sensor_defaults.items():
        cfg[k] = v

    # Device brand & model from spoofing profile
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
    config: dict[str, Any] | None = None,
) -> bool:
    """Installs persistent Magisk boot scripts, applies live props, and hardens AVD hardware INI."""
    _log("[cyan]Applying real-device anti-detection hardening...[/cyan]")

    if props is None:
        if PROFILES_PATH.exists():
            try:
                pdata = json.loads(PROFILES_PATH.read_text(encoding="utf-8"))
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
    script_content = build_anti_detection_script(props, config=config)
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
    harden_avd_config(avd_root, avd_name, props, config=config)

    _log(f"[bold green]✓ Real-device configuration applied:[/bold green] [green]{applied_count} properties configured.[/green]")
    _log("[bold green]✓ Anti-detection active:[/bold green] [green]QEMU flags suppressed, Magisk DenyList armed, sensors enabled.[/green]")
    return True


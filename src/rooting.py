"""Magisk root provisioner using rootAVD ramdisk patching."""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path

_SRC_DIR = Path(__file__).resolve().parent
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

CREATE_NO_WINDOW = 0x08000000 if platform.system() == "Windows" else 0

try:
    from config import get_target_image_info, load_config
    from constants import (
        AVD_ROOT,
        DEFAULT_AVD_NAME,
        DEFAULT_RAMDISK_REL,
        PROFILES_PATH,
        REPO_ROOT,
        ROOTAVD_DIR,
        SDK_ROOT,
        TOOLS_ROOT,
        USER_HOME,
    )
    from debloat import debloat_android
    from hardening import apply_real_device_hardening
    from provisioner import get_portable_env
except ImportError:
    from src.config import get_target_image_info, load_config
    from src.constants import (
        AVD_ROOT,
        DEFAULT_AVD_NAME,
        DEFAULT_RAMDISK_REL,
        PROFILES_PATH,
        REPO_ROOT,
        ROOTAVD_DIR,
        SDK_ROOT,
        TOOLS_ROOT,
        USER_HOME,
    )
    from src.debloat import debloat_android
    from src.hardening import apply_real_device_hardening
    from src.provisioner import get_portable_env


def _log(msg: str) -> None:
    try:
        from ui import log
        log(msg)
    except Exception:
        print(msg)


def patch_ramdisk_with_magisk_offline(
    ramdisk_path: Path,
    tools_dir: Path = TOOLS_ROOT,
    avd_root: Path = AVD_ROOT,
    avd_name: str = DEFAULT_AVD_NAME,
) -> bool:
    """Offline patches the Android ramdisk with Magisk 31.1 binaries without requiring a running VM."""
    import zipfile

    mb = tools_dir / "magiskboot" / "magiskboot.exe"
    magisk_zip = tools_dir / "rootAVD" / "Magisk.zip"

    if not mb.exists() or not magisk_zip.exists():
        _log(f"[bold red]Magisk tools missing:[/bold red] {mb} or {magisk_zip}")
        return False

    backup_path = ramdisk_path.with_name("ramdisk.img.backup")
    if not backup_path.exists():
        _log("[cyan]Creating original ramdisk backup (ramdisk.img.backup)...[/cyan]")
        shutil.copyfile(ramdisk_path, backup_path)

    work_dir = tools_dir / "magiskboot" / "_patch_work"
    if work_dir.exists():
        shutil.rmtree(work_dir, ignore_errors=True)
    work_dir.mkdir(parents=True, exist_ok=True)

    try:
        # 1. Extract Magisk x86_64 binaries & assets
        with zipfile.ZipFile(magisk_zip) as z:
            (work_dir / "magiskinit").write_bytes(z.read("lib/x86_64/libmagiskinit.so"))
            (work_dir / "magisk").write_bytes(z.read("lib/x86_64/libmagisk.so"))
            (work_dir / "init-ld").write_bytes(z.read("lib/x86_64/libinit-ld.so"))
            (work_dir / "magiskboot").write_bytes(z.read("lib/x86_64/libmagiskboot.so"))
            (work_dir / "magiskpolicy").write_bytes(z.read("lib/x86_64/libmagiskpolicy.so"))
            (work_dir / "busybox").write_bytes(z.read("lib/x86_64/libbusybox.so"))
            (work_dir / "util_functions.sh").write_bytes(z.read("assets/util_functions.sh"))
            (work_dir / "boot_patch.sh").write_bytes(z.read("assets/boot_patch.sh"))

        # 2. Compress binaries to .xz
        for b in ["magisk", "init-ld", "magiskboot", "magiskpolicy", "busybox", "magiskinit"]:
            subprocess.run([str(mb), "compress=xz", b, f"{b}.xz"], cwd=str(work_dir), check=True, creationflags=CREATE_NO_WINDOW)

        # 3. Build preconfigured magisk.db (granting root to Apps and ADB shell UID 2000)
        import sqlite3
        db_path = work_dir / "magisk.db"
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        c.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value INT)")
        c.execute("CREATE TABLE strings (key TEXT PRIMARY KEY, value TEXT)")
        c.execute("CREATE TABLE policies (uid INT PRIMARY KEY, policy INT, until INT, logging INT, notification INT)")
        c.execute("CREATE TABLE denylist (package_name TEXT, process TEXT, PRIMARY KEY(package_name, process))")
        c.execute("INSERT INTO settings (key, value) VALUES ('root_access', 3)")
        c.execute("INSERT INTO settings (key, value) VALUES ('su_request_timeout', 15)")
        c.execute("INSERT INTO settings (key, value) VALUES ('su_auto_response', 1)")
        c.execute("INSERT INTO policies (uid, policy, until, logging, notification) VALUES (2000, 2, 0, 1, 0)")
        c.execute("INSERT INTO policies (uid, policy, until, logging, notification) VALUES (0, 2, 0, 1, 0)")
        conn.commit()
        conn.close()

        # 4. Create anvill_init.sh to populate /data/adb/magisk environment on boot
        init_sh = (
            "#!/system/bin/sh\n"
            "mkdir -p /data/adb/magisk\n"
            "chmod 755 /data/adb\n"
            "chmod 755 /data/adb/magisk\n"
            "for b in magisk magiskinit magiskboot magiskpolicy busybox util_functions.sh boot_patch.sh; do\n"
            "    if [ -f /debug_ramdisk/$b ]; then\n"
            "        cp -af /debug_ramdisk/$b /data/adb/magisk/$b\n"
            "    fi\n"
            "done\n"
            "chmod -R 755 /data/adb/magisk\n"
            "chown -R 0:0 /data/adb/magisk\n"
            "if [ ! -f /data/adb/magisk.db ] && [ -f /debug_ramdisk/magisk.db ]; then\n"
            "    cp -af /debug_ramdisk/magisk.db /data/adb/magisk.db\n"
            "fi\n"
            "chmod 600 /data/adb/magisk.db\n"
            "chown 0:0 /data/adb/magisk.db\n"
            "/debug_ramdisk/magisk --sqlite \"INSERT OR REPLACE INTO settings (key, value) VALUES ('root_access', 3); INSERT OR REPLACE INTO policies (uid, policy, until, logging, notification) VALUES (2000, 2, 0, 1, 0);\"\n"
        )
        (work_dir / "anvill_init.sh").write_text(init_sh, newline="\n")

        # 5. Write config and anvill.rc
        config_content = "KEEPVERITY=true\nKEEPFORCEENCRYPT=true\nRECOVERYMODE=false\nVENDORBOOT=false\nPREINITDEVICE=metadata\n"
        (work_dir / "config").write_text(config_content)

        rc_content = (
            "# Anvill Root & PATH Injection\n"
            "on init\n"
            "    export PATH /debug_ramdisk:/product/bin:/apex/com.android.runtime/bin:/apex/com.android.art/bin:/system/bin:/system/xbin:/odm/bin:/vendor/bin:/vendor/xbin\n"
            "\n"
            "on post-fs-data\n"
            "    start anvill_init\n"
            "\n"
            "on property:sys.boot_completed=1\n"
            "    start anvill_init\n"
            "\n"
            "service anvill_init /system/bin/sh /debug_ramdisk/anvill_init.sh\n"
            "    user root\n"
            "    group root\n"
            "    seclabel u:r:magisk:s0\n"
            "    oneshot\n"
        )
        (work_dir / "anvill.rc").write_text(rc_content, newline="\n")

        # 6. Decompress stock ramdisk
        shutil.copyfile(backup_path, work_dir / "ramdisk.img")
        subprocess.run([str(mb), "decompress", "ramdisk.img", "ramdisk.cpio"], cwd=str(work_dir), check=True, creationflags=CREATE_NO_WINDOW)
        shutil.copyfile(work_dir / "ramdisk.cpio", work_dir / "ramdisk.cpio.orig")

        # 7. CPIO patch
        env_patch = dict(os.environ)
        env_patch["KEEPVERITY"] = "true"
        env_patch["KEEPFORCEENCRYPT"] = "true"

        cpio_cmds = [
            str(mb), "cpio", "ramdisk.cpio",
            "add 0750 init magiskinit",
            "mkdir 0750 overlay.d",
            "mkdir 0750 overlay.d/sbin",
            "add 0644 overlay.d/sbin/magisk.xz magisk.xz",
            "add 0644 overlay.d/sbin/init-ld.xz init-ld.xz",
            "add 0644 overlay.d/sbin/magiskboot.xz magiskboot.xz",
            "add 0644 overlay.d/sbin/magiskpolicy.xz magiskpolicy.xz",
            "add 0644 overlay.d/sbin/busybox.xz busybox.xz",
            "add 0644 overlay.d/sbin/magiskinit.xz magiskinit.xz",
            "add 0750 overlay.d/sbin/anvill_init.sh anvill_init.sh",
            "add 0644 overlay.d/sbin/magisk.db magisk.db",
            "add 0644 overlay.d/sbin/util_functions.sh util_functions.sh",
            "add 0644 overlay.d/sbin/boot_patch.sh boot_patch.sh",
            "add 0750 overlay.d/anvill.rc anvill.rc",
            "patch",
            "backup ramdisk.cpio.orig",
            "mkdir 000 .backup",
            "add 000 .backup/.magisk config",
        ]
        res_patch = subprocess.run(cpio_cmds, cwd=str(work_dir), env=env_patch, capture_output=True, text=True, creationflags=CREATE_NO_WINDOW)
        if res_patch.returncode != 0:
            _log(f"[bold red]CPIO patching failed:[/bold red] {res_patch.stderr}")
            return False

        # 6. Compress to final ramdisk.img
        patched_out = work_dir / "ramdisk_patched.img"
        subprocess.run([str(mb), "compress=lz4_legacy", "ramdisk.cpio", str(patched_out.name)], cwd=str(work_dir), check=True, creationflags=CREATE_NO_WINDOW)

        # 7. Deploy to system image & AVD initrd
        shutil.copyfile(patched_out, ramdisk_path)
        avd_initrd = avd_root / f"{avd_name}.avd" / "initrd"
        if avd_initrd.parent.exists():
            shutil.copyfile(patched_out, avd_initrd)

        _log("[bold green]Magisk 31.1 successfully patched into ramdisk![/bold green]")
        return True
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def ensure_rootavd_tool(target_dir: Path = ROOTAVD_DIR) -> bool:
    """Ensures rootAVD repository is cloned and ready in tools/rootAVD."""
    if (target_dir / "rootAVD.sh").exists() and (target_dir / "Magisk.zip").exists():
        return True

    _log("[cyan]Downloading rootAVD toolkit...[/cyan]")
    target_dir.parent.mkdir(parents=True, exist_ok=True)
    try:
        res = subprocess.run(
            ["git", "clone", "--depth", "1", "https://github.com/newbit1/rootAVD.git", str(target_dir)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            creationflags=CREATE_NO_WINDOW,
        )
        if res.returncode != 0:
            _log(f"[bold red]Failed to clone rootAVD:[/bold red] {res.stderr}")
            return False
        return True
    except Exception as exc:
        _log(f"[bold red]Git clone error:[/bold red] {exc}")
        return False


def is_emulator_running(adb_bin: Path, env: dict[str, str]) -> bool:
    """Checks if an emulator device is currently reachable via ADB."""
    try:
        res = subprocess.run(
            [str(adb_bin), "-e", "get-state"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            env=env,
            check=False,
            creationflags=CREATE_NO_WINDOW,
        )
        return res.returncode == 0 and res.stdout.strip() == "device"
    except Exception:
        return False


def wait_for_boot(adb_bin: Path, env: dict[str, str], timeout: int = 120) -> bool:
    """Waits until sys.boot_completed == 1 on the running emulator."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            res = subprocess.run(
                [str(adb_bin), "-e", "shell", "getprop", "sys.boot_completed"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
                env=env,
                check=False,
                creationflags=CREATE_NO_WINDOW,
            )
            if res.stdout.strip() == "1":
                return True
        except Exception:
            pass
        time.sleep(2)
    return False


def root_avd(
    repo_root: Path = REPO_ROOT,
    avd_name: str = DEFAULT_AVD_NAME,
    restore: bool = False,
    debloat: bool = True,
    spoof: bool = True,
    profile_name: str = "s23_ultra",
    debloat_only: bool = False,
    spoof_only: bool = False,
) -> int:
    """Patches the AVD ramdisk with Magisk, debloats non-essential packages,
    and applies real-device anti-detection hardening."""
    sdk_root = repo_root / "android-sdk"
    avd_root = repo_root / "avds"
    user_home = repo_root / ".android"
    tools_dir = repo_root / "tools" / "rootAVD"

    adb_bin = sdk_root / "platform-tools" / ("adb.exe" if platform.system() == "Windows" else "adb")
    emu_bin = sdk_root / "emulator" / ("emulator.exe" if platform.system() == "Windows" else "emulator")
    tinfo = get_target_image_info()
    ramdisk_rel = Path(tinfo["rel_ramdisk"])
    ramdisk_path = sdk_root / ramdisk_rel

    if not ramdisk_path.exists() and not (debloat_only or spoof_only):
        _log(f"[bold red]Ramdisk image not found:[/bold red] {ramdisk_path}")
        return 1

    env = get_portable_env(sdk_root, avd_root, user_home)

    if restore:
        backup_path = ramdisk_path.with_name("ramdisk.img.backup")
        if backup_path.exists():
            _log("[cyan]Restoring original stock ramdisk.img from backup...[/cyan]")
            shutil.copyfile(backup_path, ramdisk_path)
            avd_initrd = avd_root / f"{avd_name}.avd" / "initrd"
            if avd_initrd.exists():
                shutil.copyfile(backup_path, avd_initrd)
            _log("[green]Stock ramdisk restored successfully! (Root removed)[/green]")
            return 0
        else:
            _log("[yellow]No ramdisk.img.backup file found to restore.[/yellow]")
            return 1

    if not (debloat_only or spoof_only) and not ensure_rootavd_tool(tools_dir):
        return 1

    emu_proc: subprocess.Popen | None = None
    already_running = is_emulator_running(adb_bin, env)

    try:
        if not already_running:
            _log("[cyan]Starting emulator in headless background mode...[/cyan]")
            accel_mode = "on"
            try:
                accel_check = subprocess.run(
                    [str(emu_bin), "-accel-check"],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=5,
                    check=False,
                    creationflags=CREATE_NO_WINDOW,
                )
                out = (accel_check.stdout + accel_check.stderr).lower()
                if accel_check.returncode != 0 or "not installed" in out or "not operational" in out:
                    accel_mode = "off"
            except Exception:
                pass

            emu_cmd = [
                str(emu_bin),
                "-port",
                "5554",
                "-avd",
                avd_name,
                "-gpu",
                "auto",
                "-accel",
                accel_mode,
                "-no-window",
                "-no-audio",
            ]
            emu_proc = subprocess.Popen(emu_cmd, env=env, creationflags=CREATE_NO_WINDOW)

            _log("[dim]Waiting for emulator to boot up...[/dim]")
            if not wait_for_boot(adb_bin, env, timeout=120):
                _log("[bold red]Timeout waiting for emulator to complete boot.[/bold red]")
                return 1
            _log("[green]Emulator boot completed![/green]")
        else:
            _log("[green]Connected to running emulator.[/green]")

        # 1. Patch Magisk into ramdisk
        if not (debloat_only or spoof_only):
            _log("[cyan]Patching ramdisk with Magisk 31.1...[/cyan]")
            ok = patch_ramdisk_with_magisk_offline(ramdisk_path, tools_dir=tools_dir.parent, avd_root=avd_root, avd_name=avd_name)
            if not ok:
                _log("[bold red]Failed to patch ramdisk with Magisk.[/bold red]")
                return 1

        # 1.5. Ensure Magisk Manager APK is installed
        magisk_apk = tools_dir / "Apps" / "Magisk.apk"
        if magisk_apk.exists():
            _log("[cyan]Installing Magisk Manager APK...[/cyan]")
            subprocess.run(
                [str(adb_bin), "-e", "install", "-r", "-d", str(magisk_apk)],
                capture_output=True,
                env=env,
                check=False,
                creationflags=CREATE_NO_WINDOW,
            )

        # 2. Debloat Android (keep only Play Store & essential OS services)
        if debloat or debloat_only:
            debloat_android(adb_bin, env)

        # 3. Apply real-device spoofing and anti-detection hardening
        if spoof or spoof_only:
            props = None
            if PROFILES_PATH.exists():
                try:
                    pdata = json.loads(PROFILES_PATH.read_text(encoding="utf-8"))
                    sp_prof = pdata.get("spoof_profiles", {}).get(profile_name, {})
                    props = {k: v for k, v in sp_prof.items() if not k.startswith("_") and k != "description"}
                except Exception:
                    props = None

            apply_real_device_hardening(
                adb_bin=adb_bin,
                env=env,
                avd_root=avd_root,
                avd_name=avd_name,
                props=props,
            )

        _log("[bold green]====================================================================[/bold green]")
        _log("[bold green]✓ Android provisioning complete:[/bold green]")
        _log("  - [green]Magisk Root injected and armed[/green]")
        _log("  - [green]Bloatware removed (Google Play Store & GMS fully operational)[/green]")
        _log(f"  - [green]Real device profile active ({profile_name}) & QEMU flags suppressed[/green]")
        _log("[bold green]====================================================================[/bold green]")
        _log("[yellow]Next launch: Run 'python android_vm.py --cold-boot' to boot with your hardened device![/yellow]")
        return 0

    finally:
        if emu_proc is not None:
            _log("[dim]Shutting down headless patching emulator...[/dim]")
            try:
                emu_proc.terminate()
                emu_proc.wait(timeout=8)
            except Exception:
                emu_proc.kill()
            subprocess.run(
                [str(adb_bin), "-e", "emu", "kill"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                check=False,
                creationflags=CREATE_NO_WINDOW,
            )


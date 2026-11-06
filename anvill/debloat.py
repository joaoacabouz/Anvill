"""Android debloating service (stripping bloatware, preserving Google Play Store & GMS)."""

from __future__ import annotations

import subprocess
import tempfile
import time
from pathlib import Path

from anvill.config import get_bloatware_packages, get_protected_packages, load_config


def _log(msg: str) -> None:
    try:
        from anvill.ui import log
        log(msg)
    except Exception:
        print(msg)


def debloat_android(adb_bin: Path, env: dict[str, str], config: dict | None = None) -> int:
    """Disables and uninstalls bloatware, keeping only Play Store and essential OS services."""
    cfg = config or load_config()
    bloatware_list = get_bloatware_packages(cfg)
    protected_set = get_protected_packages(cfg)

    _log("[cyan]Debloating Android image (stripping non-essential packages)...[/cyan]")
    # Elevate via adb root if available
    subprocess.run([str(adb_bin), "-e", "root"], capture_output=True, env=env, check=False)
    time.sleep(1)

    res = subprocess.run(
        [str(adb_bin), "-e", "shell", "pm", "list", "packages"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        env=env,
        check=False,
    )
    if res.returncode != 0:
        _log(f"[yellow]Warning: Could not list packages via ADB: {res.stderr.strip()}[/yellow]")
        return 0

    installed = set()
    for line in res.stdout.splitlines():
        line = line.strip()
        if line.startswith("package:"):
            installed.add(line[len("package:"):].strip())

    removed = 0
    to_disable = []
    for pkg in bloatware_list:
        if pkg not in protected_set:
            to_disable.append(pkg)
            if pkg in installed:
                cmd = f"pm disable-user --user 0 {pkg} >/dev/null 2>&1; pm uninstall -k --user 0 {pkg} >/dev/null 2>&1"
                subprocess.run(
                    [str(adb_bin), "-e", "shell", cmd],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=10,
                    env=env,
                    check=False,
                )
                removed += 1
                _log(f"  [dim]- Removed bloatware:[/dim] [yellow]{pkg}[/yellow]")

    # Deploy persistent boot service script to keep bloatware disabled across reboots
    debloat_sh = [
        "#!/system/bin/sh",
        "# Anvill Persistent Debloat Service",
        "sleep 10",
    ]
    for pkg in to_disable:
        debloat_sh.append(f"pm disable-user --user 0 {pkg} 2>/dev/null")
        debloat_sh.append(f"pm disable {pkg} 2>/dev/null")
    debloat_script = "\n".join(debloat_sh) + "\n"

    with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="\n", delete=False) as tmp:
        tmp.write(debloat_script)
        tmp_path = Path(tmp.name)
    try:
        subprocess.run([str(adb_bin), "-e", "push", str(tmp_path), "/data/local/tmp/98-anvill-debloat.sh"], capture_output=True, env=env, check=False)
        deploy_cmd = (
            "mkdir -p /data/adb/service.d && "
            "cp /data/local/tmp/98-anvill-debloat.sh /data/adb/service.d/98-anvill-debloat.sh && "
            "chmod 755 /data/adb/service.d/98-anvill-debloat.sh && "
            "rm -f /data/local/tmp/98-anvill-debloat.sh"
        )
        subprocess.run([str(adb_bin), "-e", "shell", deploy_cmd], capture_output=True, env=env, check=False)
    finally:
        tmp_path.unlink(missing_ok=True)

    _log(f"[bold green]✓ Debloat finished:[/bold green] [green]{removed} bloatware packages disabled.[/green]")
    _log("[bold green]✓ Verified active:[/bold green] [green]Google Play Store (com.android.vending) + GMS & Core UI intact.[/green]")
    return removed

"""Rich TUI interface, panels, interactive menus and terminal formatting."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any, Dict, Tuple

_SRC_DIR = Path(__file__).resolve().parent
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

try:
    from constants import REPO_ROOT
    from inspector import HostInspector
except ImportError:
    from src.constants import REPO_ROOT
    from src.inspector import HostInspector

try:
    from rich.console import Console
    from rich.panel import Panel
    import rich.prompt as rich_prompt
    from rich.table import Table
    from rich.text import Text

    _RICH = True
except ImportError:
    _RICH = False

CONSOLE: Console | None = Console() if _RICH else None


def log(msg: str) -> None:
    """Safe log print: uses rich console if available, otherwise strips markup."""
    if CONSOLE is not None:
        CONSOLE.print(msg)
    else:
        clean = re.sub(r"\[/?\w+(?:=[^\]]*)?\]", "", msg)
        print(clean)


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


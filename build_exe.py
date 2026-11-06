"""Nuitka + Clang build orchestrator for Anvill standalone binary distribution."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
ENTRY_POINT = REPO_ROOT / "src" / "app_gui.py"
OUTPUT_DIR = REPO_ROOT / "dist"


def build() -> int:
    print("=" * 70)
    print("  ANVILL NUITKA + CLANG STANDALONE COMPILER")
    print("=" * 70)
    print(f"Target Entry Point: {ENTRY_POINT}")
    print(f"Output Directory:   {OUTPUT_DIR}")

    # Check Nuitka availability
    nuitka_bin = shutil.which("nuitka")
    python_bin = sys.executable

    cmd = [
        python_bin,
        "-m", "nuitka",
        "--standalone",
        "--clang",
        "--enable-plugin=pyside6",
        "--windows-disable-console",
        f"--output-dir={OUTPUT_DIR}",
        f"--include-data-file={REPO_ROOT / 'config.json'}=config.json",
        f"--include-data-file={REPO_ROOT / 'profiles.json'}=profiles.json",
        "--assume-yes-for-downloads",
        str(ENTRY_POINT),
    ]

    print("\nExecuting Nuitka build command:")
    print(" ".join(cmd))
    print("\nCompiling... (this may take a few minutes)\n")

    try:
        res = subprocess.run(cmd, cwd=REPO_ROOT, check=False)
        if res.returncode == 0:
            print("\n" + "=" * 70)
            print("✓ BUILD SUCCESSFUL!")
            print(f"Standalone executable located in: {OUTPUT_DIR / 'app_gui.dist'}")
            print("=" * 70)
            return 0
        else:
            print(f"\n[ERROR] Nuitka compilation failed with exit code {res.returncode}")
            return res.returncode
    except FileNotFoundError:
        print("\n[ERROR] Nuitka not found. Please install Nuitka in your environment:")
        print("    pip install nuitka zstandard")
        return 1


if __name__ == "__main__":
    sys.exit(build())

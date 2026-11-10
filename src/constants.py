"""Global constants and repo-local paths for Anvill."""

from __future__ import annotations

import os
from pathlib import Path

# Repo Root (dp0 - 100% portable)
REPO_ROOT: Path = Path(__file__).resolve().parent.parent

# Isolated local directories
SDK_ROOT: Path = REPO_ROOT / "android-sdk"
AVD_ROOT: Path = REPO_ROOT / "avds"
USER_HOME: Path = REPO_ROOT / ".android"
JDK_ROOT: Path = REPO_ROOT / "jdk"
TOOLS_ROOT: Path = REPO_ROOT / "tools"
ROOTAVD_DIR: Path = TOOLS_ROOT / "rootAVD"

# Config and Profiles files
CONFIG_PATH: Path = REPO_ROOT / "config.json"
PROFILES_PATH: Path = REPO_ROOT / "profiles.json"

DEFAULT_AVD_NAME: str = "Android14_PlayStore"
DEFAULT_RAMDISK_REL: Path = Path("system-images") / "android-34" / "google_apis_playstore" / "x86_64" / "ramdisk.img"

# Backward compatibility aliases
DEFAULT_SDK_ROOT: Path = SDK_ROOT
DEFAULT_AVD_ROOT: Path = AVD_ROOT
DEFAULT_USER_HOME: Path = USER_HOME
DEFAULT_JDK_ROOT: Path = JDK_ROOT

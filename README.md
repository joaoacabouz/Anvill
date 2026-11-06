# Anvill - Portable Android 16 (API 36) Emulator Provisioner

[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![Platform Windows](https://img.shields.io/badge/Platform-Windows%2010%20%2F%2011-0078D6.svg)](https://microsoft.com/windows)
[![WHPX Acceleration](https://img.shields.io/badge/Acceleration-WHPX%20%2F%20QEMU-green.svg)](https://docs.microsoft.com/virtualization/hyper-v-on-windows/)
[![Android 16](https://img.shields.io/badge/Android-16%20(API%2036)-brightgreen.svg)](https://developer.android.com/)
[![License MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A modular, 100% portable, hardware-adaptive **Python 3.10+** command-line tool to provision, dynamically configure, root with **Magisk**, and run an **Android 16 (API 36)** emulator based on the official Google Android SDK QEMU engine.

---

## ✨ Key Features

- **100% Portable (`%~dp0` / Repo-Local)**:
  - All Android SDK components (`android-sdk/`), Virtual Devices (`avds/`), user keys, and caches (`.android/`) reside strictly inside the repository root.
  - Zero pollution of `%USERPROFILE%\.android` or system directories.
  - **Self-Healing Path Relocation**: Moving the repository to another drive letter or directory automatically updates and heals internal paths in `<avd>.ini` and `hardware-qemu.ini` on startup.

- **Zero Android Studio Dependency**:
  - No need to install, configure, or run the bulky Android Studio IDE.
  - Automates downloading official Google Command-line Tools (`cmdline-tools`), `emulator.exe`, and `adb.exe`.
  - **Embedded / Portable Java**: If the host machine lacks a Java runtime, the bootstrapper automatically downloads and configures a portable OpenJDK 17 (Adoptium Temurin) inside `jdk/`.
  - Automatically accepts Google SDK license agreements programmatically.

- **Hardware Acceleration & GPU Adaptation**:
  - Detects **Windows Hypervisor Platform (WHPX)** / Hyper-V acceleration automatically.
  - **Host Hardware Inspector**: Inspects CPU (physical cores, logical threads), RAM, and primary GPU (NVIDIA, AMD, or Intel Integrated Graphics) via native Windows Registry and `psutil`.
  - Adapts GPU rendering automatically (`auto`, `host` with Vulkan & GLDirectMem for dedicated GPUs, or `angle_indirect` / SwiftShader for integrated graphics).

- **Root Access with Magisk**:
  - Includes a dedicated Python root manager (`root_avd.py`) and Windows dispatcher (`root.bat`).
  - Automatically patches the Android 16 `ramdisk.img` with Magisk Init and installs the Magisk Manager app.
  - Grants full Superuser (`su`) privileges to Android applications.
  - One-click restore back to clean stock unrooted ramdisk (`--restore`).

- **Hardware & Device Spoofing Profiles (`profiles.json`)**:
  - **Hardware Profiles**: `auto` (dynamically computed from host RAM/CPU), `ultra` (12GB RAM / 120 FPS), `high` (8GB RAM / 120 FPS), `balanced` (4GB RAM / 60 FPS), and `low` (3GB RAM / 60 FPS).
  - **Device Spoofing**: Samsung Galaxy S23 Ultra (`s23_ultra`), ASUS ROG Phone 7 (`rog_phone_7`), or clean stock (`stock`) applied automatically via ADB.

- **Scrcpy & Headless Mode**:
  - Run the emulator headlessly (`-no-window`) and mirror with ultra-low latency via `scrcpy` (`--scrcpy`).

- **Custom Image Loading**:
  - Direct support for loading custom or modified system images via `--system`, `--ramdisk`, and `--sysdir`.

---

## 📁 Repository Structure

```text
Anvill/
├── android-sdk/                  # Portable Android SDK (downloaded automatically)
│   ├── cmdline-tools/latest/     # sdkmanager, avdmanager
│   ├── emulator/                 # Google QEMU emulator engine (emulator.exe)
│   ├── platform-tools/           # ADB tools (adb.exe)
│   └── system-images/android-36/ # Android 16 Google APIs x86_64 system image
├── avds/                         # Virtual Devices storage (Android16_Pro)
│   ├── Android16_Pro.ini
│   └── Android16_Pro.avd/
├── .android/                     # Isolated Android user configuration & ADB keys
├── jdk/                          # (Optional) Portable OpenJDK 17 if host lacks Java
├── tools/                        # Helper utilities (rootAVD for Magisk patching)
├── android_vm.py                 # Main CLI orchestrator & Interactive TUI
├── setup_sdk.py                  # Standalone portable SDK & AVD bootstrap
├── root_avd.py                   # Automated Magisk root, debloat & hardening provisioner
├── config.py                     # Central configuration loader
├── config.json                   # General runtime, debloat, hardening & SDK settings
├── profiles.json                 # Hardware and Device Spoofing profiles (device specs)
├── requirements.txt              # Minimal Python dependencies (psutil, rich)
├── test_android_vm.py            # Comprehensive test suite (100% passing)
├── run.bat                       # Quick launcher (calls python android_vm.py)
├── setup.bat                     # Quick installer (calls python setup_sdk.py -y)
├── root.bat                      # Quick root patcher (calls python root_avd.py)
├── LICENSE                       # MIT License
└── README.md                     # Documentation
```

---

## 🚀 Quick Start

### Prerequisites
- **Operating System**: Windows 10 (Build 1809+) or Windows 11 (64-bit).
- **Python**: Python 3.10 or newer (tested up to Python 3.13).
- **Virtualization**: Enable **Windows Hypervisor Platform** (WHPX) or Hyper-V in Windows Features (or AMD-V / Intel VT-x in BIOS).

### 1. Installation & Provisioning

Simply run the setup dispatcher:
```cmd
setup.bat
```
*(Or run via command line: `python setup_sdk.py -y`)*

This automated step:
1. Verifies hardware virtualization / WHPX.
2. Checks for Java (auto-downloads portable OpenJDK 17 if not present).
3. Downloads Google's official commandline-tools.
4. Accepts SDK licenses and installs `emulator`, `platform-tools`, and `system-images;android-36;google_apis;x86_64`.
5. Generates the base virtual device `Android16_Pro`.

### 2. Launching the Emulator

Double-click **`run.bat`** or launch directly from terminal:

```bash
# Launch interactive Rich TUI menu
python android_vm.py
```

The interactive menu displays detected CPU, RAM, and GPU specs, and allows you to pick a performance profile and spoofing profile with numeric inputs.

---

## 💻 Command-Line Usage

You can bypass the interactive menu by specifying CLI arguments directly:

```bash
# Launch with Balanced hardware profile and Galaxy S23 Ultra spoofing
python android_vm.py --profile balanced --spoof s23_ultra

# Launch with Auto profile and safe GPU settings (ideal for Intel Integrated Graphics)
python android_vm.py --profile auto --safe-gpu

# Force a clean cold boot (skips quickboot snapshots)
python android_vm.py --cold-boot

# Wipe user data partition (factory reset)
python android_vm.py --wipe-data

# Headless launch with automatic Scrcpy screen mirroring
python android_vm.py --profile high --scrcpy

# Preview config.ini parameters without starting the emulator
python android_vm.py --profile ultra --show-config

# Run with a custom system.img or ramdisk.img
python android_vm.py --system "C:\path\to\custom_system.img"
python android_vm.py --ramdisk "C:\path\to\custom_ramdisk.img"
```

---

## ⚡ Rooting with Magisk

To enable Superuser root access for Android applications using Magisk:

1. Make sure your emulator is set up (run `setup.bat` once).
2. Execute the root patcher:
   ```cmd
   root.bat
   ```
   *(Or via terminal: `python root_avd.py` or `python android_vm.py --root-magisk`)*
3. The tool boots the VM in the background, patches `ramdisk.img` with Magisk Init, pulls the patched image, and installs `Magisk.apk`.
4. Start the emulator with cold boot:
   ```bash
   python android_vm.py --cold-boot
   ```
5. Open the app drawer to find the **Magisk** app installed. Superuser access (`su`) is active.

### Restoring Stock Unrooted Image
To remove Magisk and restore the factory unrooted image:
```bash
python root_avd.py --restore
```
*(Or: `python android_vm.py --restore-root`)*

---

## ⚙️ CLI Reference Table

| Argument | Type | Description |
| :--- | :--- | :--- |
| `--profile` | `string` | Hardware profile: `auto`, `ultra`, `high`, `balanced`, `low`. |
| `--spoof` | `string` | Device spoof profile: `s23_ultra`, `rog_phone_7`, `stock`. |
| `--avd` | `string` | AVD name to launch (default: `Android16_Pro`). |
| `--scrcpy` | `flag` | Start emulator headlessly (`-no-window`) and stream via `scrcpy`. |
| `--safe-gpu` | `flag` | Force safe GPU mode (recommended for Intel HD/UHD/Iris). |
| `--cold-boot` | `flag` | Disable quickboot snapshots and force cold startup. |
| `--wipe-data` | `flag` | Reset user data partition to default state. |
| `--writable-system` | `flag` | Make `/system` partition writable after `adb remount`. |
| `--persist-spoof` | `flag` | Persist spoof properties across boots via `adb remount`. |
| `--system` | `path` | Path to a custom or modified `system.img`. |
| `--ramdisk` | `path` | Path to a custom or modified `ramdisk.img`. |
| `--sysdir` | `path` | Directory containing custom system images. |
| `--root-magisk` | `flag` | Patch AVD ramdisk with Magisk root and exit. |
| `--restore-root` | `flag` | Restore factory unrooted stock ramdisk and exit. |
| `--show-config` | `flag` | Print parsed `config.ini` parameters and exit. |

---

## 🧪 Testing

A comprehensive automated test suite is included to validate profile resolution, host inspection, atomic config writing, path relocation, argument generation, ADB polling, and environment isolation:

```bash
python test_android_vm.py
```

Expected output:
```text
✓ profiles.json loads with all profiles
✓ fixed profiles resolved: ultra=12288MB
✓ auto: thresholds 28GB=12GB, 15GB=8GB, <15GB=4GB OK
✓ spoof s23_ultra: SM-S918B (metadata excluded)
✓ HostInspector: Intel / AMD physical cores & threads detected
✓ AvdConfigurator preserves old keys, overrides profile keys, atomic write, heals relocated paths
✓ Launcher: host GPU -> ['-gpu', 'host', '-feature'] | safe-gpu -> gpu=auto
✓ Launcher custom images: -system, -ramdisk, -sysdir supported
✓ scrcpy args: ['scrcpy', '--max-fps=120', '--video-bit-rate=16M']
✓ AdbManager: wait-for-device + boot polling OK
✓ AdbManager: apply_spoof runs setprop for all props
✓ whpx_is_active() returns bool
✓ get_portable_env configures isolated repo-local paths

✅ All tests passed successfully!
```

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
Official Android SDK binaries, system images, and tools are subject to the [Google Android SDK Terms and Conditions](https://developer.android.com/studio/terms).
Magisk is created by [topjohnwu](https://github.com/topjohnwu/Magisk) under the GNU GPL v3 license.
RootAVD toolkit is developed by [newbit1](https://github.com/newbit1/rootAVD) under the GNU GPL v3 license.

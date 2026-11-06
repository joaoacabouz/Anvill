# Anvill - Portable, Hardware-Adaptive Android Emulator & Provisioner

[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![Platform Windows](https://img.shields.io/badge/Platform-Windows%2010%20%2F%2011-0078D6.svg)](https://microsoft.com/windows)
[![WHPX Acceleration](https://img.shields.io/badge/Acceleration-WHPX%20%2F%20QEMU-green.svg)](https://docs.microsoft.com/virtualization/hyper-v-on-windows/)
[![Android Version](https://img.shields.io/badge/Android-Version%20Configurable-brightgreen.svg)](config.json)
[![License MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A modular, 100% portable, hardware-adaptive **Python 3.10+** command-line framework to provision, dynamically configure, root with **Magisk**, debloat, and run Android Virtual Devices based on the official Google Android SDK QEMU engine.

> [!NOTE]
> **Android Version Agnostic**: Anvill is currently pre-configured for **Android 16 (API 36)**, but is completely version-agnostic. All target image settings, API levels, and system image paths are dynamically controlled via [`config.json`](config.json). You can target Android 15, 16, 17, or future Canary releases simply by updating the configuration.

---

## Key Features

- **100% Portable (`%~dp0` / Repo-Local)**:
  - All Android SDK binaries (`android-sdk/`), Virtual Devices (`avds/`), user keys, and caches (`.android/`) reside strictly inside the repository directory.
  - Zero pollution of `%USERPROFILE%\.android` or system directories.
  - **Self-Healing Path Relocation**: Moving the repository to another folder or drive letter automatically updates and heals internal paths in `<avd>.ini` and `hardware-qemu.ini` on startup.

- **Zero Android Studio Dependency**:
  - No need to install or run the heavy Android Studio IDE.
  - Automates downloading official Google Command-line Tools (`cmdline-tools`), `emulator.exe`, and `adb.exe`.
  - **Direct Java SDK Management**: Executes Google's SDK tools directly via the Java runtime (`java.exe`), completely bypassing Windows `cmd.exe` batch parsing bugs and delimiter errors.
  - **Embedded / Portable Java**: If the host machine lacks Java, Anvill automatically downloads and configures a portable OpenJDK 17 (Adoptium Temurin) inside `jdk/`.
  - Programmatically accepts all Google SDK license agreements.

- **All-in-One Automated Setup (`setup.bat`)**:
  - Automatically downloads SDK tools and the configured target Android system image.
  - Generates the base virtual device.
  - **Automated First-Boot Provisioning**: Boots the emulator headlessly, waits for Android to complete boot, injects **Magisk Root**, debloats non-essential apps (strictly preserving Google Play Store & GMS), applies real-device anti-detection hardening, and shuts down cleanly.

- **Automated Debloating & Anti-Detection Hardening**:
  - **Debloat**: Strips non-essential preinstalled packages, freeing RAM and CPU while strictly preserving the **Google Play Store**, Google Play Services (GMS), WebView, keyboard, and core system UI.
  - **Real-Device Identity**: Spoofs device fingerprint, model, and manufacturer (e.g. Samsung Galaxy S23 Ultra `SM-S918B`), injects physical sensor parameters into `config.ini`, hides developer options, suppresses QEMU indicators, and configures the Magisk DenyList.

- **Hardware Acceleration & Adaptive GPU**:
  - Detects **Windows Hypervisor Platform (WHPX)** / Hyper-V acceleration automatically.
  - **Host Hardware Inspector**: Inspects host CPU (physical cores, logical threads), RAM, and primary GPU (NVIDIA, AMD, or Intel Integrated Graphics) via native Windows APIs.
  - Adapts GPU rendering automatically (`auto`, `host` with Vulkan & GLDirectMem for dedicated GPUs, or `angle_indirect` / SwiftShader for integrated graphics).

- **Hardware & Device Spoofing Profiles (`profiles.json`)**:
  - **Hardware Profiles**: `auto` (dynamically allocated based on host RAM/CPU), `ultra` (12GB RAM / 120 FPS), `high` (8GB RAM / 120 FPS), `balanced` (4GB RAM / 60 FPS), and `low` (3GB RAM / 60 FPS).
  - **Device Profiles**: Samsung Galaxy S23 Ultra (`s23_ultra`), ASUS ROG Phone 7 (`rog_phone_7`), or clean stock (`stock`).

- **Scrcpy & Headless Mode**:
  - Run the emulator headlessly (`-no-window`) and mirror with ultra-low latency via `scrcpy` (`--scrcpy`).

---

## Repository Structure

All Python source code is cleanly isolated inside `src/`. Only convenient Windows dispatchers (`.bat`) and configuration files reside at the root:

```text
Anvill/
├── src/                          # All core Python source code
│   ├── gui/                      # PySide6 Modern Dark Mode GUI & Emulator Player
│   │   ├── app.py                # Main Frameless window & view orchestrator
│   │   ├── player.py             # Emulator player container & Win32 embedding
│   │   ├── settings_dialog.py    # Preferences modal (themes, hardware & spoofing)
│   │   ├── setup_wizard.py       # First-time visual setup experience (QThread)
│   │   ├── splash.py             # Loading / verification screen
│   │   ├── theme.py              # 6 Dark mode color themes & QSS generator
│   │   ├── titlebar.py           # Custom draggable frameless titlebar
│   │   └── __init__.py
│   ├── adb.py                    # ADB automation, boot polling & property injection
│   ├── android_vm.py             # Main CLI launcher & Interactive TUI
│   ├── app_gui.py                # GUI Application entry point
│   ├── config.py                 # Configuration loader & dynamic target image parser
│   ├── configurator.py           # AVD config.ini parser, atomic writer & path healer
│   ├── constants.py              # Repository paths, directory defaults & constants
│   ├── debloat.py                # Android system image debloater (Play Store preserved)
│   ├── hardening.py              # Anti-detection scripts, QEMU suppression & sensor injection
│   ├── inspector.py              # Host hardware inspector (CPU, RAM, GPU, WHPX)
│   ├── launcher.py               # Emulator process manager, GPU args & Scrcpy launcher
│   ├── profiles.py               # Hardware & device profile manager (profiles.json)
│   ├── provisioner.py            # SDK bootstrap, direct Java SdkManager & AVD creation
│   ├── root_avd.py               # Standalone Magisk root, debloat & hardening provisioner
│   ├── rooting.py                # Magisk ramdisk patching via rootAVD toolkit
│   ├── setup_sdk.py              # Standalone portable SDK & AVD bootstrap CLI
│   ├── ui.py                     # Rich console banners, hardware tables & menus
│   └── __init__.py               # Clean package exports
├── android-sdk/                  # Portable Android SDK (downloaded automatically)
│   ├── cmdline-tools/latest/     # Google SdkManager & AvdManager tools
│   ├── emulator/                 # Google QEMU emulator engine (emulator.exe)
│   ├── platform-tools/           # ADB tools (adb.exe)
│   └── system-images/            # Downloaded Android system images
├── avds/                         # Virtual Devices storage (e.g. Android16_Pro.avd/)
├── .android/                     # Isolated Android user configuration & ADB keys
├── jdk/                          # Portable OpenJDK 17 (auto-downloaded if host lacks Java)
├── tools/                        # Helper utilities (rootAVD for Magisk patching)
├── testsuit/                     # Granular, comprehensive test suite (59 unit tests)
│   ├── run_tests.py              # Suite test runner with rich execution reporting
│   ├── test_adb.py               # ADB synchronization, wait-for-device & spoof injection
│   ├── test_config.py            # config.json validation & version-agnostic image parsing
│   ├── test_configurator.py      # config.ini parsing, hardware updates & self-healing paths
│   ├── test_debloat_and_hardening.py # Debloat package isolation & anti-detection verification
│   ├── test_gui.py               # PySide6 themes, titlebar, splash & settings tests
│   ├── test_launcher.py          # Emulator args synthesis, GPU mode selection & Scrcpy
│   ├── test_profiles.py          # profiles.json hardware profiles & device spoofing
│   ├── test_provisioner.py       # SDK package installation, direct Java & target AVD creation
│   ├── test_rooting.py           # Magisk rootAVD patching, ramdisk backup & restore
│   ├── test_ui_and_inspector.py  # Host hardware inspection, RAM metrics & Rich UI
│   ├── test_anvill.py            # Modular unit tests
│   └── test_android_vm.py        # Integration & backward compatibility tests
├── app.bat                       # Launch Modern GUI Player (python src\app_gui.py)
├── run.bat                       # CLI interactive launcher (python src\android_vm.py)
├── setup.bat                     # Quick installer (python src\setup_sdk.py -y)
├── root.bat                      # Standalone root patcher (python src\root_avd.py)
├── build.bat                     # Nuitka + Clang standalone build dispatcher
├── build_exe.py                  # Standalone compilation orchestrator
├── config.json                   # General runtime, debloat, hardening & SDK settings
├── profiles.json                 # Hardware and Device Spoofing profiles (device specs)
├── requirements.txt              # Python dependencies (psutil, rich, pyside6)
├── LICENSE                       # MIT License
└── README.md                     # Documentation
```

---

## Quick Start

### Prerequisites
- **Operating System**: Windows 10 (Build 1809+) or Windows 11 (64-bit).
- **Python**: Python 3.10 or newer (tested up to Python 3.13).
- **Virtualization**: Enable **Windows Hypervisor Platform** (WHPX) or Hyper-V in Windows Features (or AMD-V / Intel VT-x in BIOS).

### 1. Installation & Initial Provisioning

Simply double-click **`setup.bat`** (or run from terminal):
```cmd
setup.bat
```
*(Or via Python: `python src/setup_sdk.py -y`)*

This automated step:
1. Verifies hardware virtualization / WHPX.
2. Checks for Java (auto-downloads portable OpenJDK 17 if not present).
3. Downloads Google's official commandline-tools.
4. Accepts SDK licenses and installs `emulator`, `platform-tools`, and the target system image.
5. Generates the base virtual device.
6. **Automatically boots the VM headlessly**, waits for boot, patches **Magisk Root**, debloats non-essentials, hardens real-device identity, and closes the VM.

### 2. Launching the Emulator (CLI / TUI)

Double-click **`run.bat`** (or run from terminal):
```cmd
run.bat
```
*(Or via Python: `python src/android_vm.py`)*

The interactive menu displays detected CPU, RAM, and GPU specs, and allows you to select your performance and device spoofing profiles with numeric inputs.

### 3. Launching the Modern GUI Player (PySide6)

Double-click **`app.bat`** (or run from terminal):
```cmd
app.bat
```
*(Or via Python: `python src/app_gui.py`)*

#### GUI Highlights:
- **Custom Frameless Window**: Clean, modern dark window with custom draggable title bar, status badge and window controls.
- **Multiple Color Themes**: Real-time theme switcher with 6 palettes:
  - **Cyber Cyan** (Default high-tech neon)
  - **Neon Purple** (Synthwave / Deep violet)
  - **Emerald Matrix** (Terminal emerald)
  - **Sunset Amber** (Warm amber / Cyberpunk)
  - **Crimson Red** (Aggressive gaming red)
  - **Obsidian Mono** (Clean monochrome luxury)
- **Automated First-Run Setup**: On first launch, automatically detects unconfigured environments, runs the complete 6-stage setup pipeline on a background `QThread`, displays live progress, and streams real-time logs.
- **Android Emulator Player**: Hooks and embeds the Google emulator window directly inside the PySide6 viewport.
- **Full Player Controls**: Side toolbar providing quick access to:
  - **Volume Up / Down** (`adb input keyevent 24/25`)
  - **Rotate Screen** (Portrait / Landscape toggle)
  - **Screenshot** (Captures screen via ADB into `./screenshots/`)
  - **Power Button** (Screen lock / wake up)
  - **Home Button** (`adb input keyevent 3`)
  - **Back Button** (`adb input keyevent 4`)
  - **Recents / Overview** (`adb input keyevent 187`)
  - **Install APK** (File picker or Drag & Drop `.apk` directly onto the window)
  - **Settings Modal** (Instant hardware, spoofing and theme configuration)
  - **Shutdown Emulator** (Clean graceful shutdown)

---

## Standalone Compilation (Nuitka + Clang)

Anvill is engineered to compile directly into a high-performance standalone Windows binary using Nuitka and Clang:

```cmd
build.bat
```
*(Or via Python: `python build_exe.py`)*

This runs:
```bash
nuitka --standalone --clang --enable-plugin=pyside6 --windows-disable-console --output-dir=dist src/app_gui.py
```
The output directory `dist/app_gui.dist/` contains the fully portable executable with all PySide6 plugins and data files bundled.

---

## Configuration System

Anvill strictly separates runtime configuration from hardware profiles:

### 1. `config.json` (General Settings, Debloat & Hardening)
Contains all system-level settings:
- **`vm`**: Default AVD name, default profiles, GPU mode, cold boot flag, `auto_root_on_setup: true`, and Scrcpy settings.
- **`sdk`**: Target image definition (`system-images/android-36/google_apis/x86_64`), download URLs, and required packages.
- **`debloat`**: List of non-essential packages to remove and list of protected packages (Google Play Store, GMS, WebView, system UI).
- **`hardening`**: QEMU properties to suppress, Settings overrides (hide developer options, mock location), Magisk DenyList packages, and hardware sensor emulation (`config.ini`).

### 2. `profiles.json` (Hardware & Device Specifications)
Contains hardware resource allocations and device spoofing definitions:
- **`hardware_profiles`**: `auto`, `ultra` (12GB RAM), `high` (8GB RAM), `balanced` (4GB RAM), `low` (3GB RAM).
- **`spoof_profiles`**: Real-device fingerprints (Samsung Galaxy S23 Ultra, ASUS ROG Phone 7, Stock).

---

## How to Change or Upgrade the Android Version

To target a different Android version (for example, Android 17 / API 37, or an ARM64 image), simply update [`config.json`](config.json):

```json
  "sdk": {
    "target_image": "system-images/android-37/google_apis/x86_64",
    "required_packages": [
      "emulator",
      "platform-tools",
      "system-images/android-37/google_apis/x86_64",
      "extras/google/usb_driver"
    ]
  }
```

Anvill will dynamically:
1. Download and install the new system image package via SdkManager.
2. Build the AVD pointing to the new API target.
3. Locate and patch the new target version's `ramdisk.img` with Magisk.

---

## Command-Line Usage

### Running the Emulator (`src/android_vm.py`)

```bash
# Launch with Balanced hardware profile and Galaxy S23 Ultra spoofing
python src/android_vm.py --profile balanced --spoof s23_ultra

# Launch with Auto profile and safe GPU settings (ideal for Intel Integrated Graphics)
python src/android_vm.py --profile auto --safe-gpu

# Force a clean cold boot (skips quickboot snapshots)
python src/android_vm.py --cold-boot

# Wipe user data partition (factory reset)
python src/android_vm.py --wipe-data

# Headless launch with automatic Scrcpy screen mirroring
python src/android_vm.py --profile high --scrcpy

# Run with custom system or ramdisk images
python src/android_vm.py --system "C:\path\to\custom_system.img"
python src/android_vm.py --ramdisk "C:\path\to\custom_ramdisk.img"
```

### Setup & Provisioning (`src/setup_sdk.py`)

```bash
# Standard automated setup (installs SDK, creates AVD, auto-roots & hardens)
python src/setup_sdk.py -y

# Setup without initial auto-rooting
python src/setup_sdk.py -y --skip-root

# Check hardware acceleration and paths only
python src/setup_sdk.py --skip-install
```

### Standalone Rooting & Debloating (`src/root_avd.py`)

```bash
# Re-apply Magisk root, debloating and real-device hardening
python src/root_avd.py

# Restore clean, unrooted stock ramdisk image from backup
python src/root_avd.py --restore

# Run debloat only on a currently running emulator
python src/root_avd.py --debloat-only

# Run device spoofing and anti-detection only
python src/root_avd.py --spoof-only
```

---

## Testing

Anvill includes a comprehensive test suite in `testsuit/` covering 100% of the architecture:

```bash
# Run the complete test suite runner with detailed summary
python testsuit/run_tests.py

# Or discover tests automatically via Python's unittest module
python -m unittest discover -s testsuit
```

---

## License

This project is licensed under the [MIT License](LICENSE).
Anvill is an independent open-source tool and is not affiliated with Google or Samsung.

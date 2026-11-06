"""Emulator process launching, runtime argument synthesis, and scrcpy management."""

from __future__ import annotations

import platform
import shutil
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from anvill.adb import AdbManager
from anvill.config import load_config
from anvill.inspector import HostInspector
from anvill.profiles import VMProfile


def _log(msg: str) -> None:
    try:
        from anvill.ui import log
        log(msg)
    except Exception:
        print(msg)


@dataclass
class LaunchFlags:
    """Emulator launch flags builder."""

    profile: VMProfile
    gpu_mode: str
    avd_name: str
    scrcpy: bool
    safe_gpu: bool
    gpu_vendor: str
    writable_system: bool = False
    use_accel: bool = True
    no_boot_anim: bool = False
    cold_boot: bool = False
    wipe_data: bool = False
    custom_system: Path | None = None
    custom_ramdisk: Path | None = None
    custom_sysdir: Path | None = None

    @property
    def is_safe_gpu(self) -> bool:
        return self.safe_gpu or self.gpu_vendor == "INTEL_INTEGRATED"

    def build_args(self) -> Sequence[str]:
        """Builds the full argument list for emulator.exe."""
        args: list[str] = []

        # GPU
        if self.is_safe_gpu:
            args += ["-gpu", "auto"]
        else:
            args += ["-gpu", "host", "-feature", "Vulkan", "-feature", "GLDirectMem"]

        # Base flags
        args += ["-avd", self.avd_name]
        args += ["-accel", "on" if self.use_accel else "off"]
        if self.writable_system:
            args.append("-writable-system")
        if self.no_boot_anim:
            args.append("-no-boot-anim")
        if self.cold_boot:
            args.append("-no-snapshot")
        if self.wipe_data:
            args.append("-wipe-data")

        # Custom system / ramdisk / sysdir images
        if self.custom_system:
            args.extend(["-system", str(self.custom_system)])
        if self.custom_ramdisk:
            args.extend(["-ramdisk", str(self.custom_ramdisk)])
        if self.custom_sysdir:
            args.extend(["-sysdir", str(self.custom_sysdir)])

        # Window / framebuffer (scrcpy runs headless)
        if self.scrcpy:
            args.extend(["-no-window", "-no-audio"])

        # Raw QEMU flags (WHPX safety on Windows)
        qemu_args = ["-qemu", "-usb", "-device", "usb-kbd", "-device", "usb-mouse"]
        if platform.system() != "Windows":
            qemu_args.extend(["-cpu", "max"])
        args += qemu_args
        return args

    def build_scrcpy_args(self) -> Sequence[str]:
        """Builds scrcpy arguments after boot."""
        cfg = load_config()
        scrcpy_cfg = cfg.get("vm", {}).get("scrcpy", {})
        fps = scrcpy_cfg.get("max_fps", 120)
        bitrate = scrcpy_cfg.get("video_bit_rate", "16M")
        return ["scrcpy", f"--max-fps={fps}", f"--video-bit-rate={bitrate}"]


def pick_gpu_mode(host: HostInspector, safe_gpu: bool) -> str:
    """Chooses GPU mode based on vendor and --safe-gpu flag."""
    if safe_gpu or host.gpu.vendor == "INTEL_INTEGRATED":
        return "auto"
    return "host"


class EmulatorLauncher:
    """Launches emulator as a subprocess and manages scrcpy & shutdown."""

    def __init__(
        self,
        emulator_path: Path,
        flags: LaunchFlags,
        adb: AdbManager,
        env: dict[str, str],
        console: object | None = None,
    ):
        self.emulator_path = emulator_path
        self.flags = flags
        self.adb = adb
        self.env = env
        self.console = console
        self.process: subprocess.Popen[bytes] | None = None
        self.scrcpy_process: subprocess.Popen[bytes] | None = None
        self.scrcpy_started = False
        self._output_thread: threading.Thread | None = None

    def launch(self, ready_timeout: int = 180) -> subprocess.Popen[bytes]:
        """Launches the emulator and awaits device readiness."""
        args = [str(self.emulator_path)] + list(self.flags.build_args())

        _log(f"[bold cyan]Launching emulator:[/bold cyan] {self.emulator_path} (AVD: {self.flags.avd_name})")
        _log(f"[dim]Command: {' '.join(args)}[/dim]")
        _log(f"[dim]GPU: {self.flags.gpu_mode} | Acceleration: {'on' if self.flags.use_accel else 'off'}[/dim]")

        self.process = subprocess.Popen(
            args,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=0,
            env=self.env,
        )
        self._output_thread = threading.Thread(target=self._stream_output, daemon=True)
        self._output_thread.start()

        _log("[cyan]Waiting for Android device to connect...[/cyan]")
        self.adb.wait_for_device(timeout=ready_timeout)

        if self.adb.device_ready:
            _log("[green]Device connected. Waiting for boot completion...[/green]")
        else:
            _log("[yellow]Device not detected yet — emulator is booting...[/yellow]")

        if self.adb.wait_for_boot_completed(interval=2, timeout=120):
            _log("[bold green]Android 16 Boot complete![/bold green]")
        else:
            _log("[yellow]Boot polling timed out — emulator may still be initializing...[/yellow]")

        return self.process

    def _stream_output(self) -> None:
        """Streams emulator stdout/stderr to the console."""
        assert self.process is not None
        assert self.process.stdout is not None
        for line in iter(self.process.stdout.readline, b""):
            try:
                text = line.decode("utf-8", errors="replace").rstrip()
            except Exception:
                text = str(line)
            if text:
                _log(f"[dim][emulator] {text}[/dim]")

    def maybe_start_scrcpy(self, ready_timeout: int = 120) -> None:
        """Starts scrcpy after boot if requested."""
        if not self.flags.scrcpy or self.scrcpy_started:
            return

        scrcpy_bin = shutil.which("scrcpy")
        if not scrcpy_bin:
            _log("[yellow]scrcpy not found in PATH. Install scrcpy to use --scrcpy.[/yellow]")
            return

        if not self.adb.wait_for_device(timeout=ready_timeout):
            _log("[yellow]scrcpy: device not ready[/yellow]")
            return

        args = list(self.flags.build_scrcpy_args())
        _log(f"[cyan]Starting scrcpy: {' '.join(args)}[/cyan]")
        self.scrcpy_process = subprocess.Popen(
            [scrcpy_bin] + args[1:],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=0,
            env=self.env,
        )
        self.scrcpy_started = True

    def wait(self) -> None:
        """Waits for emulator process or keyboard interrupt."""
        try:
            assert self.process is not None
            rc = self.process.wait()
            if rc != 0:
                _log(f"[yellow]Emulator exited with code {rc}[/yellow]")
        except KeyboardInterrupt:
            _log("[dim]Received Ctrl+C — shutting down emulator...[/dim]")
            self.shutdown()

    def shutdown(self) -> None:
        """Gracefully shuts down scrcpy and emulator processes."""
        if self.scrcpy_process is not None and self.scrcpy_process.poll() is None:
            try:
                self.scrcpy_process.terminate()
                self.scrcpy_process.wait(timeout=5)
            except Exception:
                self.scrcpy_process.kill()
            _log("[dim]scrcpy terminated[/dim]")
        if self.process is not None and self.process.poll() is None:
            try:
                self.process.terminate()
                self.process.wait(timeout=10)
            except Exception:
                self.process.kill()
            _log("[dim]emulator terminated[/dim]")

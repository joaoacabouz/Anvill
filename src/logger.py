"""Central logging infrastructure for Anvill with rotating file logs and stream redirection."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
import os
import platform
import sys
from pathlib import Path

# Repo Root
REPO_ROOT: Path = Path(__file__).resolve().parent.parent
LOGS_DIR: Path = REPO_ROOT / "logs"
LOG_FILE: Path = LOGS_DIR / "anvill.log"

# Win32 flag to prevent spawning console windows for subprocesses
CREATE_NO_WINDOW: int = 0x08000000 if platform.system() == "Windows" else 0


class StreamToLogger:
    """Redirects stdout and stderr stream writes into Python logger while preserving original streams."""

    def __init__(self, logger: logging.Logger, log_level: int, original_stream=None):
        self.logger = logger
        self.log_level = log_level
        self.original_stream = original_stream

    def write(self, buf: str) -> None:
        for line in buf.rstrip().splitlines():
            line_str = line.strip()
            if line_str:
                self.logger.log(self.log_level, line_str)
        if self.original_stream and hasattr(self.original_stream, "write"):
            try:
                self.original_stream.write(buf)
                self.original_stream.flush()
            except Exception:
                pass

    def flush(self) -> None:
        if self.original_stream and hasattr(self.original_stream, "flush"):
            try:
                self.original_stream.flush()
            except Exception:
                pass


def setup_logging() -> Path:
    """Initializes rotating file handler and captures stdout/stderr into logs/anvill.log."""
    try:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # Avoid duplicate file handlers if invoked multiple times
    if not any(isinstance(h, RotatingFileHandler) for h in root_logger.handlers):
        try:
            file_handler = RotatingFileHandler(
                LOG_FILE,
                maxBytes=10 * 1024 * 1024,  # 10 MB per log file
                backupCount=5,
                encoding="utf-8",
            )
            formatter = logging.Formatter(
                "[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
            file_handler.setFormatter(formatter)
            root_logger.addHandler(file_handler)
        except Exception:
            pass

    # Redirect sys.stdout and sys.stderr to log file so pythonw.exe never crashes on prints
    sys.stdout = StreamToLogger(logging.getLogger("STDOUT"), logging.INFO, sys.stdout)
    sys.stderr = StreamToLogger(logging.getLogger("STDERR"), logging.ERROR, sys.stderr)

    logging.info("Anvill logging initialized. Log file: %s", LOG_FILE)
    return LOG_FILE


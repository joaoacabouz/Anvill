"""Backward-compatibility bridge for config.py."""

from anvill.config import (
    DEFAULT_CONFIG,
    get_bloatware_packages,
    get_protected_packages,
    load_config,
)

__all__ = [
    "DEFAULT_CONFIG",
    "get_bloatware_packages",
    "get_protected_packages",
    "load_config",
]

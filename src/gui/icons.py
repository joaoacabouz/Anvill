"""High-fidelity vector icon and SVG asset management for Anvill GUI."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, Optional

from PySide6.QtCore import QByteArray, QSize
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

ASSETS_DIR: Path = Path(__file__).resolve().parent.parent / "Assets"

# In-memory text cache to prevent repetitive disk I/O
_SVG_CACHE: Dict[str, str] = {}


def load_raw_svg(filename: str) -> str:
    """Loads raw SVG XML string from the Assets directory with caching."""
    if filename not in _SVG_CACHE:
        path = ASSETS_DIR / filename
        if path.is_file():
            _SVG_CACHE[filename] = path.read_text(encoding="utf-8")
        else:
            _SVG_CACHE[filename] = ""
    return _SVG_CACHE[filename]


def tint_svg(svg_xml: str, color: str) -> str:
    """Tints SVG colors while strictly preserving 'none' values for fills/strokes."""
    if not svg_xml:
        return ""
    # Tint non-none fills
    res = re.sub(r'fill="(?!(?:none))[^"]*"', f'fill="{color}"', svg_xml, flags=re.IGNORECASE)
    # Tint non-none strokes
    res = re.sub(r'stroke="(?!(?:none))[^"]*"', f'stroke="{color}"', res, flags=re.IGNORECASE)
    return res


def get_svg_pixmap(filename: str, color: str = "#FFFFFF", size: int = 24) -> QPixmap:
    """Renders a tinted SVG into a crisp transparent QPixmap of the specified dimensions."""
    raw = load_raw_svg(filename)
    if not raw:
        return QPixmap(size, size)

    tinted = tint_svg(raw, color)
    renderer = QSvgRenderer(QByteArray(tinted.encode("utf-8")))
    if not renderer.isValid():
        return QPixmap(size, size)

    pix = QPixmap(size, size)
    pix.fill(QColor(0, 0, 0, 0))

    painter = QPainter(pix)
    renderer.render(painter)
    painter.end()
    return pix


def get_svg_icon(
    filename: str,
    color_normal: str = "#94A3B8",
    color_active: Optional[str] = None,
    size: int = 24,
) -> QIcon:
    """Creates a multi-state QIcon for push buttons (normal and hovered/active states)."""
    icon = QIcon()
    pix_normal = get_svg_pixmap(filename, color_normal, size=size)
    icon.addPixmap(pix_normal, QIcon.Normal)

    active_color = color_active or "#FFFFFF"
    pix_active = get_svg_pixmap(filename, active_color, size=size)
    icon.addPixmap(pix_active, QIcon.Active)
    icon.addPixmap(pix_active, QIcon.Selected)

    return icon


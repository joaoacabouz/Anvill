"""Theme manager and modern dark mode styling for Anvill GUI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple


@dataclass(frozen=True)
class ThemePalette:
    """Color palette definition for Anvill dark mode themes."""

    id: str
    name: str
    accent: str           # Primary glow & active state (e.g. #00E5FF)
    accent_hover: str     # Lighter or slightly different for hover
    accent_dim: str       # Low-opacity / dim accent
    bg_main: str          # Main window background
    bg_surface: str       # Card & widget surface background
    bg_elevated: str      # Inputs, toolbars, elevated elements
    border_color: str     # Subtle element borders
    border_focus: str     # Border color when focused
    text_primary: str     # High-contrast text
    text_secondary: str   # Muted / dim text
    text_accent: str      # Text using accent color
    danger: str           # Destructive actions (e.g. #EF4444)
    success: str          # Positive status (e.g. #10B981)
    warning: str          # Warnings / booting (e.g. #F59E0B)


THEMES: Dict[str, ThemePalette] = {
    "cyber_cyan": ThemePalette(
        id="cyber_cyan",
        name="Cyber Cyan",
        accent="#00E5FF",
        accent_hover="#38EFFF",
        accent_dim="rgba(0, 229, 255, 0.15)",
        bg_main="#0B0F17",
        bg_surface="#111823",
        bg_elevated="#17212F",
        border_color="#1E2B3D",
        border_focus="#00E5FF",
        text_primary="#F0F6FC",
        text_secondary="#8B949E",
        text_accent="#00E5FF",
        danger="#FF4D4D",
        success="#00E676",
        warning="#FFD600",
    ),
    "neon_purple": ThemePalette(
        id="neon_purple",
        name="Neon Purple",
        accent="#A855F7",
        accent_hover="#C084FC",
        accent_dim="rgba(168, 85, 247, 0.18)",
        bg_main="#0F0E17",
        bg_surface="#161524",
        bg_elevated="#201E34",
        border_color="#2D2A47",
        border_focus="#A855F7",
        text_primary="#F8FAFC",
        text_secondary="#94A3B8",
        text_accent="#C084FC",
        danger="#F43F5E",
        success="#10B981",
        warning="#F59E0B",
    ),
    "emerald_matrix": ThemePalette(
        id="emerald_matrix",
        name="Emerald Matrix",
        accent="#10B981",
        accent_hover="#34D399",
        accent_dim="rgba(16, 185, 129, 0.18)",
        bg_main="#061A14",
        bg_surface="#0B261E",
        bg_elevated="#11362B",
        border_color="#1C4B3C",
        border_focus="#10B981",
        text_primary="#ECFDF5",
        text_secondary="#6EE7B7",
        text_accent="#34D399",
        danger="#EF4444",
        success="#10B981",
        warning="#F59E0B",
    ),
    "sunset_amber": ThemePalette(
        id="sunset_amber",
        name="Sunset Amber",
        accent="#F59E0B",
        accent_hover="#FBBF24",
        accent_dim="rgba(245, 158, 11, 0.18)",
        bg_main="#140E0A",
        bg_surface="#1F1710",
        bg_elevated="#2C2016",
        border_color="#3D2D1F",
        border_focus="#F59E0B",
        text_primary="#FFFBEB",
        text_secondary="#D97706",
        text_accent="#FBBF24",
        danger="#EF4444",
        success="#10B981",
        warning="#F59E0B",
    ),
    "crimson_red": ThemePalette(
        id="crimson_red",
        name="Crimson Red",
        accent="#EF4444",
        accent_hover="#F87171",
        accent_dim="rgba(239, 68, 68, 0.18)",
        bg_main="#120A0B",
        bg_surface="#1C1012",
        bg_elevated="#2A181B",
        border_color="#422026",
        border_focus="#EF4444",
        text_primary="#FEF2F2",
        text_secondary="#B91C1C",
        text_accent="#F87171",
        danger="#EF4444",
        success="#10B981",
        warning="#F59E0B",
    ),
    "obsidian_mono": ThemePalette(
        id="obsidian_mono",
        name="Obsidian Mono",
        accent="#E2E8F0",
        accent_hover="#FFFFFF",
        accent_dim="rgba(226, 232, 240, 0.12)",
        bg_main="#09090B",
        bg_surface="#121215",
        bg_elevated="#1C1C21",
        border_color="#2E2E38",
        border_focus="#E2E8F0",
        text_primary="#F8FAFC",
        text_secondary="#71717A",
        text_accent="#E2E8F0",
        danger="#F87171",
        success="#34D399",
        warning="#FBBF24",
    ),
}

DEFAULT_THEME_ID = "cyber_cyan"


def get_theme(theme_id: str | None = None) -> ThemePalette:
    """Retrieves palette by theme ID, falling back to default."""
    if not theme_id or theme_id not in THEMES:
        return THEMES[DEFAULT_THEME_ID]
    return THEMES[theme_id]


def list_themes() -> List[Tuple[str, str, str]]:
    """Returns list of (id, display_name, accent_hex)."""
    return [(p.id, p.name, p.accent) for p in THEMES.values()]


def generate_qss(palette: ThemePalette) -> str:
    """Generates the full modern Qt stylesheet for the application."""
    return f"""
    /* Global Application Styles */
    QWidget {{
        background-color: {palette.bg_main};
        color: {palette.text_primary};
        font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, Roboto, sans-serif;
        font-size: 13px;
        outline: none;
    }}

    /* Card Panels & Surfaces */
    .SurfaceCard {{
        background-color: {palette.bg_surface};
        border: 1px solid {palette.border_color};
        border-radius: 12px;
    }}

    .ElevatedCard {{
        background-color: {palette.bg_elevated};
        border: 1px solid {palette.border_color};
        border-radius: 10px;
    }}

    /* Buttons */
    QPushButton {{
        background-color: {palette.bg_elevated};
        color: {palette.text_primary};
        border: 1px solid {palette.border_color};
        border-radius: 8px;
        padding: 8px 16px;
        font-weight: 600;
        min-height: 20px;
    }}

    QPushButton:hover {{
        background-color: {palette.accent_dim};
        border-color: {palette.accent};
        color: {palette.accent};
    }}

    QPushButton:pressed {{
        background-color: {palette.accent};
        color: #000000;
    }}

    QPushButton:disabled {{
        background-color: {palette.bg_surface};
        color: {palette.text_secondary};
        border-color: {palette.border_color};
    }}

    /* Primary Accent Button */
    QPushButton.PrimaryButton {{
        background-color: {palette.accent};
        color: #000000;
        border: none;
        border-radius: 8px;
        padding: 10px 20px;
        font-size: 14px;
        font-weight: 700;
    }}

    QPushButton.PrimaryButton:hover {{
        background-color: {palette.accent_hover};
    }}

    QPushButton.PrimaryButton:pressed {{
        background-color: {palette.accent};
        opacity: 0.9;
    }}

    /* Danger Button */
    QPushButton.DangerButton {{
        background-color: rgba(239, 68, 68, 0.15);
        color: {palette.danger};
        border: 1px solid {palette.danger};
        border-radius: 8px;
        padding: 8px 16px;
        font-weight: 600;
    }}

    QPushButton.DangerButton:hover {{
        background-color: {palette.danger};
        color: #FFFFFF;
    }}

    /* Toolbar Action Buttons (Player Bar) */
    QPushButton.ToolButton {{
        background-color: {palette.bg_surface};
        color: {palette.text_primary};
        border: 1px solid {palette.border_color};
        border-radius: 8px;
        padding: 8px;
        min-width: 36px;
        max-width: 36px;
        min-height: 36px;
        max-height: 36px;
        font-size: 16px;
    }}

    QPushButton.ToolButton:hover {{
        background-color: {palette.accent_dim};
        border-color: {palette.accent};
        color: {palette.accent};
    }}

    QPushButton.ToolButton:pressed {{
        background-color: {palette.accent};
        color: #000000;
    }}

    /* Inputs & LineEdits */
    QLineEdit, QTextEdit, QPlainTextEdit {{
        background-color: {palette.bg_elevated};
        color: {palette.text_primary};
        border: 1px solid {palette.border_color};
        border-radius: 8px;
        padding: 8px 12px;
        selection-background-color: {palette.accent};
        selection-color: #000000;
    }}

    QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {{
        border: 1px solid {palette.border_focus};
    }}

    /* ComboBox */
    QComboBox {{
        background-color: {palette.bg_elevated};
        color: {palette.text_primary};
        border: 1px solid {palette.border_color};
        border-radius: 8px;
        padding: 8px 12px;
        min-height: 20px;
    }}

    QComboBox:hover {{
        border-color: {palette.accent};
    }}

    QComboBox::drop-down {{
        subcontrol-origin: padding;
        subcontrol-position: top right;
        width: 25px;
        border-left: none;
    }}

    QComboBox QAbstractItemView {{
        background-color: {palette.bg_surface};
        color: {palette.text_primary};
        border: 1px solid {palette.border_color};
        border-radius: 8px;
        selection-background-color: {palette.accent_dim};
        selection-color: {palette.accent};
        outline: none;
        padding: 4px;
    }}

    /* CheckBoxes */
    QCheckBox {{
        spacing: 8px;
        color: {palette.text_primary};
        font-weight: 500;
    }}

    QCheckBox::indicator {{
        width: 18px;
        height: 18px;
        border-radius: 4px;
        border: 1px solid {palette.border_color};
        background-color: {palette.bg_elevated};
    }}

    QCheckBox::indicator:hover {{
        border-color: {palette.accent};
    }}

    QCheckBox::indicator:checked {{
        background-color: {palette.accent};
        border-color: {palette.accent};
    }}

    /* Progress Bar */
    QProgressBar {{
        background-color: {palette.bg_elevated};
        border: 1px solid {palette.border_color};
        border-radius: 6px;
        text-align: center;
        color: {palette.text_primary};
        font-size: 11px;
        font-weight: 700;
        height: 16px;
    }}

    QProgressBar::chunk {{
        background: qlineargradient(
            x1: 0, y1: 0, x2: 1, y2: 0,
            stop: 0 {palette.accent},
            stop: 1 {palette.accent_hover}
        );
        border-radius: 5px;
    }}

    /* Scrollbars */
    QScrollBar:vertical {{
        background: {palette.bg_main};
        width: 8px;
        margin: 0;
        border-radius: 4px;
    }}

    QScrollBar::handle:vertical {{
        background: {palette.border_color};
        min-height: 25px;
        border-radius: 4px;
    }}

    QScrollBar::handle:vertical:hover {{
        background: {palette.accent};
    }}

    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0px;
    }}

    QScrollBar:horizontal {{
        background: {palette.bg_main};
        height: 8px;
        margin: 0;
        border-radius: 4px;
    }}

    QScrollBar::handle:horizontal {{
        background: {palette.border_color};
        min-width: 25px;
        border-radius: 4px;
    }}

    QScrollBar::handle:horizontal:hover {{
        background: {palette.accent};
    }}

    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
        width: 0px;
    }}

    /* Labels & Badges */
    QLabel {{
        background: transparent;
    }}

    .BadgePill {{
        background-color: {palette.accent_dim};
        color: {palette.accent};
        border: 1px solid {palette.accent};
        border-radius: 12px;
        padding: 4px 10px;
        font-size: 11px;
        font-weight: 700;
    }}

    .StatusRunning {{
        background-color: rgba(16, 185, 129, 0.15);
        color: {palette.success};
        border: 1px solid {palette.success};
        border-radius: 10px;
        padding: 3px 8px;
        font-size: 11px;
        font-weight: 600;
    }}

    .StatusBooting {{
        background-color: rgba(245, 158, 11, 0.15);
        color: {palette.warning};
        border: 1px solid {palette.warning};
        border-radius: 10px;
        padding: 3px 8px;
        font-size: 11px;
        font-weight: 600;
    }}

    .StatusOffline {{
        background-color: rgba(148, 163, 184, 0.12);
        color: {palette.text_secondary};
        border: 1px solid {palette.border_color};
        border-radius: 10px;
        padding: 3px 8px;
        font-size: 11px;
        font-weight: 600;
    }}

    /* Tooltips */
    QToolTip {{
        background-color: {palette.bg_surface};
        color: {palette.text_primary};
        border: 1px solid {palette.border_color};
        border-radius: 6px;
        padding: 6px 10px;
        font-size: 12px;
    }}
    """

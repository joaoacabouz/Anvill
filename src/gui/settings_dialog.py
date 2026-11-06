"""Settings and VM configuration modal dialog."""

from __future__ import annotations

import json
from pathlib import Path
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from config import load_config
from constants import CONFIG_PATH
from gui.theme import ThemePalette, list_themes


class SettingsDialog(QDialog):
    """Configuration modal for Anvill VM, profiles and themes."""

    theme_selected = Signal(str)

    def __init__(self, parent: QWidget, palette: ThemePalette):
        super().__init__(parent)
        self.palette = palette
        self.setWindowTitle("Anvill Settings")
        self.setFixedSize(480, 520)
        self.setModal(True)

        self.cfg = load_config()
        self._setup_ui()
        self.update_palette(palette)

    def _setup_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(28, 24, 28, 24)
        main_layout.setSpacing(16)

        title = QLabel("Settings & Emulation Preferences")
        title.setFont(QFont("Segoe UI", 16, QFont.Bold))
        main_layout.addWidget(title)

        # Form Card
        card = QWidget()
        card.setProperty("class", "SurfaceCard")
        form_layout = QVBoxLayout(card)
        form_layout.setContentsMargins(20, 18, 20, 18)
        form_layout.setSpacing(12)

        # AVD Name
        l1 = QLabel("AVD Name:")
        l1.setStyleSheet("font-weight: 600;")
        self.avd_input = QLineEdit(self.cfg.get("vm", {}).get("avd_name", "Android16_Pro"))
        form_layout.addWidget(l1)
        form_layout.addWidget(self.avd_input)

        # Theme
        l2 = QLabel("Interface Theme:")
        l2.setStyleSheet("font-weight: 600;")
        self.theme_combo = QComboBox()
        current_theme = self.cfg.get("vm", {}).get("theme", self.palette.id)
        for tid, tname, accent in list_themes():
            self.theme_combo.addItem(f"🎨 {tname}", tid)
        idx = self.theme_combo.findData(current_theme)
        if idx >= 0:
            self.theme_combo.setCurrentIndex(idx)
        form_layout.addWidget(l2)
        form_layout.addWidget(self.theme_combo)

        # Default Hardware Profile
        l3 = QLabel("Default Hardware Profile:")
        l3.setStyleSheet("font-weight: 600;")
        self.hw_combo = QComboBox()
        self.hw_combo.addItems(["auto", "ultra", "high", "balanced", "low"])
        self.hw_combo.setCurrentText(self.cfg.get("vm", {}).get("default_hardware_profile", "auto"))
        form_layout.addWidget(l3)
        form_layout.addWidget(self.hw_combo)

        # Default Spoofing Profile
        l4 = QLabel("Default Device Spoof:")
        l4.setStyleSheet("font-weight: 600;")
        self.spoof_combo = QComboBox()
        self.spoof_combo.addItems(["s23_ultra", "rog_phone_7", "stock"])
        self.spoof_combo.setCurrentText(self.cfg.get("vm", {}).get("default_spoof_profile", "s23_ultra"))
        form_layout.addWidget(l4)
        form_layout.addWidget(self.spoof_combo)

        # Checkboxes
        self.cold_boot_chk = QCheckBox("Force Cold Boot (Disable Snapshots)")
        self.cold_boot_chk.setChecked(self.cfg.get("vm", {}).get("cold_boot", False))
        form_layout.addWidget(self.cold_boot_chk)

        self.safe_gpu_chk = QCheckBox("Safe GPU Mode (Software / Angle Indirect)")
        self.safe_gpu_chk.setChecked(self.cfg.get("vm", {}).get("safe_gpu", False))
        form_layout.addWidget(self.safe_gpu_chk)

        main_layout.addWidget(card)

        # Buttons
        btn_box = QHBoxLayout()
        btn_box.setSpacing(10)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)

        save_btn = QPushButton("Save Settings")
        save_btn.setProperty("class", "PrimaryButton")
        save_btn.clicked.connect(self._save_settings)

        btn_box.addStretch()
        btn_box.addWidget(cancel_btn)
        btn_box.addWidget(save_btn)
        main_layout.addLayout(btn_box)

    def update_palette(self, palette: ThemePalette) -> None:
        self.palette = palette
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {palette.bg_main};
                color: {palette.text_primary};
            }}
        """)

    def _save_settings(self) -> None:
        try:
            cfg = load_config()
            vm_cfg = cfg.setdefault("vm", {})
            vm_cfg["avd_name"] = self.avd_input.text().strip()
            selected_theme = self.theme_combo.currentData()
            vm_cfg["theme"] = selected_theme
            vm_cfg["default_hardware_profile"] = self.hw_combo.currentText()
            vm_cfg["default_spoof_profile"] = self.spoof_combo.currentText()
            vm_cfg["cold_boot"] = self.cold_boot_chk.isChecked()
            vm_cfg["safe_gpu"] = self.safe_gpu_chk.isChecked()

            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2)

            self.theme_selected.emit(selected_theme)
            self.accept()
        except Exception as exc:
            QMessageBox.critical(self, "Save Error", f"Failed to save settings:\n{exc}")


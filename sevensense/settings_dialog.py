"""Settings dialog — accessible from the tray icon right-click menu."""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGroupBox,
    QCheckBox, QSpinBox, QLabel, QDialogButtonBox,
)
from PyQt6.QtGui import QIcon

from .appicon import app_icon
from .welcome import _install_autostart, remove_autostart


class SettingsDialog(QDialog):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("7Sense Settings")
        self.setWindowIcon(app_icon())
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(16, 16, 16, 16)

        # --- Startup & tray ---
        startup_group = QGroupBox("Startup & tray")
        startup_layout = QVBoxLayout()
        startup_layout.setSpacing(8)

        self.cb_autostart = QCheckBox("Start 7Sense automatically at login")
        self.cb_autostart.setChecked(config.get("autostart", True))

        self.cb_tray_always = QCheckBox("Keep tray icon visible when nothing is extracting")
        self.cb_tray_always.setChecked(config.get("tray_always_visible", True))

        startup_layout.addWidget(self.cb_autostart)
        startup_layout.addWidget(self.cb_tray_always)
        startup_group.setLayout(startup_layout)

        # --- Archive types ---
        watch_group = QGroupBox("Watch these archive types")
        watch_layout = QVBoxLayout()
        watch_layout.setSpacing(8)

        self.cb_7z = QCheckBox("7-Zip  (.7z, .7z.001, …)")
        self.cb_7z.setChecked(config.get("watch_7z", True))

        self.cb_tar = QCheckBox("Tarballs  (.tar.gz, .tar.xz, .tar.bz2, …)")
        self.cb_tar.setChecked(config.get("watch_tar", True))

        self.cb_zip = QCheckBox("ZIP  (.zip)")
        self.cb_zip.setChecked(config.get("watch_unzip", True))

        self.cb_rar = QCheckBox("RAR  (.rar)  — via unar or unrar")
        self.cb_rar.setChecked(config.get("watch_unrar", True))

        watch_layout.addWidget(self.cb_7z)
        watch_layout.addWidget(self.cb_tar)
        watch_layout.addWidget(self.cb_zip)
        watch_layout.addWidget(self.cb_rar)
        watch_group.setLayout(watch_layout)

        # --- Behavior ---
        behavior_group = QGroupBox("Behavior")
        behavior_layout = QVBoxLayout()
        behavior_layout.setSpacing(8)

        delay_row = QHBoxLayout()
        delay_row.addWidget(QLabel("Ignore extractions finishing in under"))
        self.spin_delay = QSpinBox()
        self.spin_delay.setRange(1, 30)
        self.spin_delay.setValue(config.get("min_notify_seconds", 3))
        self.spin_delay.setSuffix(" s")
        self.spin_delay.setFixedWidth(72)
        delay_row.addWidget(self.spin_delay)
        delay_row.addStretch()

        behavior_layout.addLayout(delay_row)
        behavior_group.setLayout(behavior_layout)

        # --- Buttons ---
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)

        layout.addWidget(startup_group)
        layout.addWidget(watch_group)
        layout.addWidget(behavior_group)
        layout.addWidget(buttons)

    def _save(self):
        self.config.set("watch_7z", self.cb_7z.isChecked())
        self.config.set("watch_tar", self.cb_tar.isChecked())
        self.config.set("watch_unzip", self.cb_zip.isChecked())
        self.config.set("watch_unrar", self.cb_rar.isChecked())
        self.config.set("min_notify_seconds", self.spin_delay.value())
        self.config.set("tray_always_visible", self.cb_tray_always.isChecked())

        autostart_was = self.config.get("autostart", True)
        autostart_now = self.cb_autostart.isChecked()
        self.config.set("autostart", autostart_now)

        if autostart_now and not autostart_was:
            _install_autostart()
        elif not autostart_now and autostart_was:
            remove_autostart()

        self.config.save()
        self.accept()

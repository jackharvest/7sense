"""
7Sense entry point.

Three modes, selected by command-line flag:
  (no flag)      First run → show wizard. Already set up → launch daemon and exit.
  --settings     Open the settings dialog, then exit.
  --about        Show the About box, then exit.

The Rust daemon (7sense-daemon/target/release/7sense-daemon) does the actual
monitoring. This Python side only runs once per login to show the wizard or
briefly to open a dialog window.
"""

import sys
from pathlib import Path

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt

from .appicon import app_icon
from .config import Config

APP_VERSION = "1.0.0"


def _show_about():
    """Standalone About box — does not need a TrayApp or any other context."""
    from PyQt6.QtWidgets import QMessageBox
    from .appicon import app_icon as _icon
    box = QMessageBox()
    box.setWindowTitle("About 7Sense")
    box.setWindowIcon(_icon())
    box.setIconPixmap(_icon().pixmap(48, 48))
    box.setText(
        f"<b>7Sense</b> v{APP_VERSION}<br><br>"
        "Real extraction progress for Linux archive tools.<br><br>"
        "Open source · <a href='https://github.com/jackharvest/7sense'>github.com/jackharvest/7sense</a><br><br>"
        "If it's been useful — <a href='https://www.paypal.me/mongolianmiller'>buy us a coffee ☕</a>"
    )
    box.exec()


def main():
    args = sys.argv[1:]

    # --settings and --about are invoked by the Rust daemon's tray menu.
    # We spin up a minimal QApplication, show the window, and exit cleanly.
    if "--settings" in args or "--about" in args:
        app = QApplication(sys.argv)
        app.setQuitOnLastWindowClosed(True)
        app.setWindowIcon(app_icon())
        config = Config()
        if "--settings" in args:
            from .settings_dialog import SettingsDialog
            SettingsDialog(config).exec()
        else:
            _show_about()
        sys.exit(0)

    config = Config()

    if not config.get("setup_complete", False):
        # First run: show the setup wizard. The wizard launches the daemon on finish.
        app = QApplication(sys.argv)
        app.setQuitOnLastWindowClosed(True)
        app.setWindowIcon(app_icon())
        app.setApplicationName("7Sense")
        app.setApplicationVersion(APP_VERSION)
        app.setDesktopFileName("7sense")
        from .welcome import WelcomeWizard
        wizard = WelcomeWizard(config)
        wizard.show()
        sys.exit(app.exec())
    else:
        # Already configured: start the daemon and exit.
        # The daemon runs as a separate process and takes over from here.
        from .welcome import _launch_daemon
        _launch_daemon()
        sys.exit(0)

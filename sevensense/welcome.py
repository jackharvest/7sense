"""First-run welcome wizard."""

import os
import shutil
import subprocess

from PyQt6.QtWidgets import (
    QWizard, QWizardPage, QVBoxLayout, QHBoxLayout,
    QLabel, QCheckBox, QSpinBox, QApplication, QProgressBar, QFrame,
    QPushButton,
)
from PyQt6.QtGui import QIcon, QFont, QPixmap, QImage, QDesktopServices
from PyQt6.QtCore import Qt, QTimer, QProcess, QUrl

from .appicon import app_icon


class _StyledBar(QProgressBar):
    """Rounded progress bar used in both comparison panels.

    Pass value=None for the looping indeterminate (bouncing) animation,
    or an int 0-100 for a static filled bar.
    Both modes share the same paintEvent so they look identical."""

    _CHUNK_RATIO = 0.55   # the bouncing chunk is 55% of the bar's total width
    _SPEED       = 1.8    # pixels to advance per 16ms frame (~60 fps)

    def __init__(self, value=None, greyscale=False):
        super().__init__()
        self.setTextVisible(False)
        self._static_value = value
        self._greyscale = greyscale
        self._offset = 0.0
        if value is None:
            self._timer = QTimer(self)
            self._timer.timeout.connect(self._tick)
            self._timer.start(16)

    def _tick(self):
        self._offset += self._SPEED
        chunk_w = self.width() * self._CHUNK_RATIO
        if self._offset > self.width() + chunk_w:
            self._offset = -chunk_w
        self.update()

    def paintEvent(self, _event):
        from PyQt6.QtGui import QPainter, QPalette
        from PyQt6.QtCore import QRectF

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()
        r = h / 2.0
        pal = self.palette()

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(pal.color(QPalette.ColorRole.Mid))
        p.drawRoundedRect(QRectF(0, 0, w, h), r, r)

        p.setClipRect(0, 0, w, h)
        chunk_color = pal.color(QPalette.ColorRole.Mid).lighter(140) if self._greyscale \
            else pal.color(QPalette.ColorRole.Highlight)
        p.setBrush(chunk_color)

        if self._static_value is None:
            chunk_w = self.width() * self._CHUNK_RATIO
            p.drawRoundedRect(QRectF(self._offset, 0, chunk_w, h), r, r)
        else:
            p.drawRoundedRect(QRectF(0, 0, w * self._static_value / 100.0, h), r, r)

        p.end()


class WelcomePage(QWizardPage):
    def __init__(self):
        super().__init__()
        self.setTitle("Finally.")

        layout = QVBoxLayout()
        layout.setSpacing(16)
        layout.setContentsMargins(24, 20, 24, 16)

        # Before / After panels
        panels = QHBoxLayout()
        panels.setSpacing(20)
        panels.addWidget(_ComparisonPanel(
            icon="dialog-question",
            bar_value=None,
            caption="your archive tool",
            greyscale=True,
        ))
        arrow = QLabel("→")
        arrow_font = QFont()
        arrow_font.setPointSize(20)
        arrow.setFont(arrow_font)
        arrow.setAlignment(Qt.AlignmentFlag.AlignCenter)
        panels.addWidget(arrow)
        panels.addWidget(_ComparisonPanel(
            icon=None,
            bar_value=47,
            caption="with 7Sense",
            animated=True,
        ))

        kicker = QLabel("It's been right there in the file the whole time.")
        kicker.setAlignment(Qt.AlignmentFlag.AlignCenter)
        kicker_font = QFont()
        kicker_font.setItalic(True)
        kicker.setFont(kicker_font)

        layout.addStretch(1)
        layout.addLayout(panels)
        layout.addSpacing(8)
        layout.addWidget(kicker)
        layout.addStretch(2)
        self.setLayout(layout)


class _ComparisonPanel(QFrame):
    """One side of the before/after comparison on the welcome page.

    The left panel (greyscale=True) shows a bouncing bar with no info.
    The right panel (animated=True) slowly ticks from START to END percent
    so the user can watch a real number climb while the wizard is open."""

    _START_PCT = 23    # animated panel starts here (percent)
    _END_PCT   = 88    # and loops back to START when it reaches here
    _TOTAL_S   = 330   # fake "time remaining" shown when at _START_PCT (seconds)

    def __init__(self, icon, bar_value, caption, greyscale=False, animated=False):
        super().__init__()
        self.setFrameShape(QFrame.Shape.StyledPanel)

        layout = QVBoxLayout(self)
        layout.setSpacing(6)
        layout.setContentsMargins(16, 16, 16, 12)

        qicon = app_icon() if icon is None else QIcon.fromTheme(icon)
        pix = qicon.pixmap(80, 80)
        if greyscale:
            pix = QPixmap.fromImage(
                pix.toImage().convertToFormat(QImage.Format.Format_Grayscale8)
            )
        icon_label = QLabel()
        icon_label.setPixmap(pix)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._pct = float(self._START_PCT if animated else (bar_value or 0))
        # animated panel: always drive a static bar manually via _tick
        # non-animated: None bar_value = bouncing, int = filled
        self._bar = _StyledBar(
            value=None if (bar_value is None and not animated) else self._pct,
            greyscale=greyscale,
        )
        self._bar.setFixedHeight(14)

        small_font = QFont()
        small_font.setPointSize(8)

        self._stats_label = QLabel("" if not animated else self._format_stats())
        self._stats_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._stats_label.setFont(small_font)

        caption_label = QLabel(caption)
        caption_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        caption_label.setFont(small_font)

        layout.addWidget(icon_label)
        layout.addWidget(self._bar)
        layout.addWidget(self._stats_label)
        layout.addWidget(caption_label)

        if animated:
            self._anim = QTimer(self)
            self._anim.timeout.connect(self._tick)
            self._anim.start(120)

    def _format_stats(self):
        span = self._END_PCT - self._START_PCT
        remaining_s = self._TOTAL_S * (1.0 - (self._pct - self._START_PCT) / span)
        if remaining_s >= 60:
            m, s = divmod(int(remaining_s), 60)
            time_str = f"{m}m {s:02d}s left"
        else:
            time_str = f"{int(remaining_s)}s left"
        return f"{int(self._pct)}%  ·  {time_str}"

    def _tick(self):
        self._pct += 0.4
        if self._pct >= self._END_PCT:
            self._pct = float(self._START_PCT)
        self._bar._static_value = self._pct
        self._bar.update()
        self._stats_label.setText(self._format_stats())


class PrereqPage(QWizardPage):
    """Checks system dependencies and offers to install anything missing."""

    # (label, internal_key, is_critical)
    # key "rar" accepts unar or unrar; key "7z" accepts 7z or 7zz
    _CHECKS = [
        ("Desktop notifications", "notify-send", True),
        ("RAR support",           "rar",         False),
        ("7-Zip support",         "7z",          False),
    ]

    # key → {package_manager: "package name(s)" or None = not in official repos}
    _PKG = {
        "notify-send": {
            "apt":    "libnotify-bin",
            "pacman": "libnotify",
            "dnf":    "libnotify",
            "zypper": "libnotify-tools",
        },
        "rar": {
            "apt":    "unar",
            "pacman": "unrar",   # unrar is in official Arch repos; unar is AUR-only
            "dnf":    "unar",
            "zypper": "unar",
        },
        "7z": {
            "apt":    "p7zip-full",
            "pacman": "p7zip",
            "dnf":    "p7zip p7zip-plugins",
            "zypper": "p7zip-full",
        },
        "gnome-appindicator": {
            "apt":    "gnome-shell-extension-appindicator",
            "pacman": None,   # AUR: gnome-shell-extension-appindicator
            "dnf":    None,   # extensions.gnome.org
            "zypper": None,
        },
    }

    _INSTALL_CMD = {
        "apt":    ["apt",    "install", "-y"],
        "pacman": ["pacman", "-S", "--noconfirm"],
        "dnf":    ["dnf",    "install", "-y"],
        "zypper": ["zypper", "--non-interactive", "install"],
    }

    @staticmethod
    def _detect_manager():
        for m in ("apt", "pacman", "dnf", "zypper"):
            if shutil.which(m):
                return m
        return None

    @staticmethod
    def _check_present(key):
        if key == "rar":
            return shutil.which("unar") or shutil.which("unrar")
        if key == "7z":
            return shutil.which("7z") or shutil.which("7zz")
        return shutil.which(key)

    def __init__(self):
        super().__init__()
        self.setTitle("One quick check.")
        self.setSubTitle("Making sure your system has what 7Sense needs.")
        self._complete = False
        self._install_proc = None
        self._installable_pkgs = []

        layout = QVBoxLayout()
        layout.setSpacing(10)
        layout.setContentsMargins(24, 16, 24, 16)

        small = QFont()
        small.setPointSize(9)

        self._rows = {}
        for label, key, _critical in self._CHECKS:
            row = QHBoxLayout()
            row.setSpacing(10)
            icon = QLabel("…")
            icon.setFixedWidth(18)
            icon.setFont(small)
            name = QLabel(label)
            name.setFont(small)
            status = QLabel("")
            status.setFont(small)
            status.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            row.addWidget(icon)
            row.addWidget(name, 1)
            row.addWidget(status)
            layout.addLayout(row)
            self._rows[key] = (icon, status)

        # GNOME AppIndicator row
        gnome_row = QHBoxLayout()
        gnome_row.setSpacing(10)
        self._gnome_icon = QLabel("…")
        self._gnome_icon.setFixedWidth(18)
        self._gnome_icon.setFont(small)
        gnome_name = QLabel("Tray icon (GNOME AppIndicator)")
        gnome_name.setFont(small)
        self._gnome_status = QLabel("")
        self._gnome_status.setFont(small)
        self._gnome_status.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        gnome_row.addWidget(self._gnome_icon)
        gnome_row.addWidget(gnome_name, 1)
        gnome_row.addWidget(self._gnome_status)
        layout.addLayout(gnome_row)

        layout.addSpacing(8)

        self._install_btn = QPushButton("Install missing packages")
        self._install_btn.setVisible(False)
        self._install_btn.clicked.connect(self._install)
        layout.addWidget(self._install_btn)

        self._note = QLabel("")
        self._note.setFont(small)
        self._note.setVisible(False)
        self._note.setWordWrap(True)
        layout.addWidget(self._note)

        layout.addStretch()
        self.setLayout(layout)

    def initializePage(self):
        QTimer.singleShot(50, self._run_checks)

    def _run_checks(self):
        self._installable_pkgs = []
        notes = []
        has_critical_fail = False
        mgr = self._detect_manager()
        is_gnome = "gnome" in os.environ.get("XDG_CURRENT_DESKTOP", "").lower()

        for _label, key, critical in self._CHECKS:
            icon_lbl, status_lbl = self._rows[key]
            if self._check_present(key):
                icon_lbl.setText("✓")
                icon_lbl.setStyleSheet("color: #4caf50; font-weight: bold;")
                status_lbl.setText("ready")
            else:
                icon_lbl.setText("✗" if critical else "⚠")
                icon_lbl.setStyleSheet(
                    "color: #f44336; font-weight: bold;" if critical
                    else "color: #ff9800; font-weight: bold;"
                )
                pkg = self._PKG.get(key, {}).get(mgr) if mgr else None
                if pkg:
                    self._installable_pkgs.extend(pkg.split())
                    status_lbl.setText(f"not found — {pkg}")
                else:
                    status_lbl.setText("not found — install manually")
                    notes.append(self._manual_note(key, mgr))
                if critical:
                    has_critical_fail = True

        # GNOME AppIndicator (KDE/others handle tray natively — skip)
        if is_gnome:
            ext_state = self._gnome_ext_state()
            if ext_state == "active":
                self._gnome_icon.setText("✓")
                self._gnome_icon.setStyleSheet("color: #4caf50; font-weight: bold;")
                self._gnome_status.setText("ready")
            elif ext_state == "installed":
                self._gnome_icon.setText("⚠")
                self._gnome_icon.setStyleSheet("color: #ff9800; font-weight: bold;")
                self._gnome_status.setText("installed — needs logout")
                notes.append("Log out and back in, then enable AppIndicator in GNOME Extensions.")
            else:
                self._gnome_icon.setText("⚠")
                self._gnome_icon.setStyleSheet("color: #ff9800; font-weight: bold;")
                self._gnome_status.setText("extension needed")
                gnome_pkg = self._PKG["gnome-appindicator"].get(mgr) if mgr else None
                if gnome_pkg:
                    self._installable_pkgs.extend(gnome_pkg.split())
                    notes.append("After install, log out and back in, then enable AppIndicator in GNOME Extensions.")
                else:
                    notes.append(self._manual_note("gnome-appindicator", mgr))
        else:
            self._gnome_icon.setText("✓")
            self._gnome_icon.setStyleSheet("color: #4caf50; font-weight: bold;")
            self._gnome_status.setText("not needed")

        self._install_btn.setVisible(False)
        self._note.setVisible(False)

        if self._installable_pkgs:
            mgr_label = mgr or "your package manager"
            self._install_btn.setText(
                f"Install {len(self._installable_pkgs)} missing package(s)  via {mgr_label}"
            )
            self._install_btn.setEnabled(True)
            self._install_btn.setVisible(True)

        if notes:
            self._note.setText("\n\n".join(notes))
            self._note.setVisible(True)

        self._complete = not has_critical_fail
        self.completeChanged.emit()

    @staticmethod
    def _manual_note(key, mgr):
        if key == "rar":
            return "RAR support: install unar or unrar with your package manager."
        if key == "gnome-appindicator":
            if mgr == "pacman":
                return (
                    "Tray icon: install via AUR —\n"
                    "  yay -S gnome-shell-extension-appindicator\n"
                    "or visit extensions.gnome.org and search 'AppIndicator'."
                )
            return (
                "Tray icon: visit extensions.gnome.org and install\n"
                "'AppIndicator and KStatusNotifierItem Support'."
            )
        return f"Install '{key}' with your package manager."

    def _gnome_ext_state(self):
        """Returns 'active', 'installed' (present but not yet enabled), or 'absent'."""
        try:
            r = subprocess.run(["gnome-extensions", "list", "--active"],
                               capture_output=True, text=True, timeout=3)
            if "appindicator" in r.stdout.lower():
                return "active"
        except Exception:
            pass
        # Installed but not active yet (needs logout + enable)
        try:
            r = subprocess.run(["dpkg", "-l", "gnome-shell-extension-appindicator"],
                               capture_output=True, text=True, timeout=3)
            if any(line.startswith("ii") for line in r.stdout.splitlines()):
                return "installed"
        except Exception:
            pass
        try:
            r = subprocess.run(["pacman", "-Qs", "appindicator"],
                               capture_output=True, text=True, timeout=3)
            if "appindicator" in r.stdout.lower():
                return "installed"
        except Exception:
            pass
        return "absent"

    def _install(self):
        self._install_btn.setEnabled(False)
        self._install_btn.setText("Installing…")
        cmd = self._INSTALL_CMD.get(self._detect_manager() or "apt")
        self._install_proc = QProcess(self)
        self._install_proc.finished.connect(self._on_install_done)
        self._install_proc.start("pkexec", cmd + self._installable_pkgs)

    def _on_install_done(self, _exit_code, _status):
        self._install_btn.setVisible(False)
        self._run_checks()

    def isComplete(self):
        return self._complete


class WatchPage(QWizardPage):
    def __init__(self, config):
        super().__init__()
        self.config = config
        self.setTitle("What do you work with?")
        self.setSubTitle(
            "Pick the archive types you'd like to have opinions about."
        )

        layout = QVBoxLayout()
        layout.setSpacing(10)
        layout.setContentsMargins(24, 16, 24, 16)

        self.cb_7z = QCheckBox("7-Zip archives  (.7z, .7z.001, …)")
        self.cb_7z.setChecked(config.get("watch_7z", True))

        self.cb_tar = QCheckBox("Compressed tarballs  (.tar.gz, .tar.xz, .tar.bz2, …)")
        self.cb_tar.setChecked(config.get("watch_tar", True))

        self.cb_zip = QCheckBox("ZIP archives  (.zip)")
        self.cb_zip.setChecked(config.get("watch_unzip", True))

        self.cb_rar = QCheckBox("RAR archives  (.rar)  — via unar or unrar")
        self.cb_rar.setChecked(config.get("watch_unrar", True))

        layout.addSpacing(4)
        layout.addWidget(self.cb_7z)
        layout.addWidget(self.cb_tar)
        layout.addWidget(self.cb_zip)
        layout.addWidget(self.cb_rar)
        layout.addStretch()
        self.setLayout(layout)

    def validatePage(self):
        self.config.set("watch_7z", self.cb_7z.isChecked())
        self.config.set("watch_tar", self.cb_tar.isChecked())
        self.config.set("watch_unzip", self.cb_zip.isChecked())
        self.config.set("watch_unrar", self.cb_rar.isChecked())
        return True


class BehaviorPage(QWizardPage):
    def __init__(self, config):
        super().__init__()
        self.config = config
        self.setTitle("Stay out of the way.")
        self.setSubTitle(
            "7Sense shouldn't bother you when it has nothing useful to say."
        )

        layout = QVBoxLayout()
        layout.setSpacing(14)
        layout.setContentsMargins(24, 16, 24, 16)

        self.cb_autostart = QCheckBox("Start 7Sense automatically when I log in")
        self.cb_autostart.setChecked(config.get("autostart", True))

        self.cb_tray_always = QCheckBox("Keep the tray icon visible even when nothing is extracting")
        self.cb_tray_always.setChecked(config.get("tray_always_visible", True))

        delay_row = QHBoxLayout()
        delay_row.addWidget(QLabel("Ignore extractions that finish in under"))
        self.spin_delay = QSpinBox()
        self.spin_delay.setRange(1, 30)
        self.spin_delay.setValue(config.get("min_notify_seconds", 3))
        self.spin_delay.setSuffix(" seconds")
        delay_row.addWidget(self.spin_delay)
        delay_row.addStretch()

        layout.addWidget(self.cb_autostart)
        layout.addWidget(self.cb_tray_always)
        layout.addSpacing(4)
        layout.addLayout(delay_row)
        layout.addStretch()
        self.setLayout(layout)

    def validatePage(self):
        self.config.set("autostart", self.cb_autostart.isChecked())
        self.config.set("tray_always_visible", self.cb_tray_always.isChecked())
        self.config.set("min_notify_seconds", self.spin_delay.value())
        return True


class DonePage(QWizardPage):
    def __init__(self):
        super().__init__()
        self.setTitle("Done.")

        layout = QVBoxLayout()
        layout.setSpacing(12)
        layout.setContentsMargins(24, 16, 24, 16)

        icon_label = QLabel()
        icon_label.setPixmap(app_icon().pixmap(56, 56))
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        msg = QLabel(
            "7Sense is quietly in your system tray, out of the way until you need it.\n\n"
            "Go extract something. You'll finally be informed on extraction progress."
        )
        msg.setWordWrap(True)
        msg.setAlignment(Qt.AlignmentFlag.AlignCenter)

        footprint = QLabel("~4 MB RAM  ·  3 threads  ·  Rust-powered")
        footprint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        footprint_font = QFont()
        footprint_font.setPointSize(8)
        footprint.setFont(footprint_font)

        hint = QLabel("Right-click the tray icon anytime to adjust or quit.")
        hint.setWordWrap(True)
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint_font = QFont()
        hint_font.setItalic(True)
        hint.setFont(hint_font)

        donate_btn = QPushButton("☕  Buy us a coffee")
        donate_btn.setFlat(True)
        donate_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        donate_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl("https://www.paypal.me/mongolianmiller"))
        )
        donate_font = QFont()
        donate_font.setPointSize(8)
        donate_btn.setFont(donate_font)

        layout.addStretch(1)
        layout.addWidget(icon_label)
        layout.addSpacing(8)
        layout.addWidget(msg)
        layout.addSpacing(6)
        layout.addWidget(footprint)
        layout.addSpacing(4)
        layout.addWidget(hint)
        layout.addSpacing(12)
        layout.addWidget(donate_btn, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addStretch(2)
        self.setLayout(layout)


class WelcomeWizard(QWizard):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config

        self.setWindowTitle("7Sense Setup")
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.setMinimumSize(560, 400)
        self.setWindowIcon(app_icon())

        self.addPage(WelcomePage())
        self.addPage(PrereqPage())
        self.addPage(WatchPage(config))
        self.addPage(BehaviorPage(config))
        self.addPage(DonePage())

        self.button(QWizard.WizardButton.FinishButton).setText("Let's go")

        self.finished.connect(self._on_finish)

    def _on_finish(self, result):
        if result != QWizard.DialogCode.Accepted:
            QApplication.quit()
            return

        self.config.set("setup_complete", True)
        self.config.save()

        if self.config.get("autostart", True):
            _install_autostart()

        _launch_daemon()
        QApplication.quit()


def _launch_daemon():
    import subprocess
    from pathlib import Path
    daemon = Path(__file__).parent.parent / "7sense-daemon" / "target" / "release" / "7sense-daemon"
    if daemon.exists():
        subprocess.Popen([str(daemon)], start_new_session=True)


def _install_autostart():
    import sys
    from pathlib import Path

    autostart_dir = Path.home() / ".config" / "autostart"
    autostart_dir.mkdir(parents=True, exist_ok=True)

    daemon = Path(__file__).parent.parent / "7sense-daemon" / "target" / "release" / "7sense-daemon"
    exe = str(daemon) if daemon.exists() else sys.argv[0]
    icon = Path(__file__).parent / "icon.png"
    entry = autostart_dir / "7sense.desktop"
    entry.write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=7Sense\n"
        "Comment=Archive extraction progress notifications\n"
        f"Exec={exe}\n"
        f"Icon={icon}\n"
        "X-GNOME-Autostart-enabled=true\n"
    )


def remove_autostart():
    from pathlib import Path
    entry = Path.home() / ".config" / "autostart" / "7sense.desktop"
    entry.unlink(missing_ok=True)

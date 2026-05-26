"""
User configuration — stored as JSON at ~/.config/7sense/config.json.

The Rust daemon reads this same file on every poll cycle, so any changes
made here take effect on the next tick without a restart.
"""

import json
from pathlib import Path

CONFIG_DIR  = Path.home() / ".config" / "7sense"
CONFIG_FILE = CONFIG_DIR / "config.json"

# These values are used when a key is missing from the config file —
# e.g. on first run, or when new settings are added in a later version.
DEFAULTS = {
    "setup_complete":     False,
    "watch_7z":           True,
    "watch_tar":          True,
    "watch_unzip":        True,
    "watch_unrar":        True,
    "tray_always_visible": True,
    "min_notify_seconds": 3,     # ignore extractions that finish faster than this
    "poll_interval":      1.5,   # seconds between /proc scans
    "autostart":          True,
}


class Config:
    def __init__(self):
        self._data = {**DEFAULTS}
        self._load()

    def _load(self):
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE) as f:
                    self._data.update(json.load(f))
            except (json.JSONDecodeError, IOError):
                pass  # corrupted config — fall back to defaults silently

    def save(self):
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_FILE, "w") as f:
            json.dump(self._data, f, indent=2)

    def get(self, key, default=None):
        return self._data.get(key, default)

    def set(self, key, value):
        self._data[key] = value

    # Dict-style access so callers can do config["key"] if they prefer
    def __getitem__(self, key):
        return self._data[key]

    def __setitem__(self, key, value):
        self._data[key] = value

"""
App icon helper.

Loads the bundled icon.png from the package directory.
Falls back to the system theme if the file is somehow missing
(shouldn't happen in a normal install, but better than a crash).
"""

from pathlib import Path
from PyQt6.QtGui import QIcon

_ICON_PATH = Path(__file__).parent / "icon.png"


def app_icon() -> QIcon:
    if _ICON_PATH.exists():
        return QIcon(str(_ICON_PATH))
    return QIcon.fromTheme("utilities-file-archiver")

"""Where things live. Imports nothing heavy: `localdub/__init__.py` uses it at import time."""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
# Written by the installer (Windows: next to the program in Program Files; macOS: inside the .app
# bundle), places a normal user cannot or should not write to: user data then lives in the user's
# own folder instead of next to the program.
INSTALLED_MARKER = REPO_ROOT / ".installed"
APP_FOLDER = "LocalDub Studio"


def user_root() -> Path:
    """The per-user folder of an installed program (Windows: %LOCALAPPDATA%, macOS: Library)."""
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_FOLDER
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    return base / APP_FOLDER


def user_dir(name: str) -> Path:
    """Where projects (`data`), downloaded models (`models`) and optional packages (`extras`) go."""
    if INSTALLED_MARKER.is_file():
        return user_root() / name
    return REPO_ROOT / name

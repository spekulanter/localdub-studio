"""Where things live. Imports nothing heavy: `localdub/__init__.py` uses it at import time."""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
# Written by the Windows installer next to the program (usually in Program Files, which a normal
# user cannot write to): user data then lives in %LOCALAPPDATA% instead of the install folder.
INSTALLED_MARKER = REPO_ROOT / ".installed"


def user_dir(name: str) -> Path:
    """Where projects (`data`), downloaded models (`models`) and optional packages (`extras`) go."""
    if INSTALLED_MARKER.is_file():
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        return base / "LocalDub Studio" / name
    return REPO_ROOT / name

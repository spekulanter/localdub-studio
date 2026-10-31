"""Settings the user changes in the app (kept in the data folder, so they survive updates)."""

from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)

MIN_UPLOAD_MB = 100
MAX_UPLOAD_MB = 1_000_000  # about 1 TB


def valid_upload_mb(value: object) -> bool:
    if not isinstance(value, int) or isinstance(value, bool):
        return False
    return MIN_UPLOAD_MB <= value <= MAX_UPLOAD_MB


def load(path: Path) -> dict[str, int]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        log.warning("Ignoring unreadable %s", path)
        return {}
    if isinstance(raw, dict) and valid_upload_mb(raw.get("max_upload_mb")):
        return {"max_upload_mb": raw["max_upload_mb"]}
    return {}


def save(path: Path, values: dict[str, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(values, indent=2), encoding="utf-8")
    tmp.replace(path)

"""What the user chose and what the program learned: stored in `models-state.json` (data folder).

Deleting this file loses nothing important: selections fall back to the defaults, custom Ollama
models can be added again and update checks can be repeated.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

from localdub.core.jobs.checkpoints import atomic_write_json

VERSION = 1


class ModelState:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.RLock()
        self._data = self._load()

    def _load(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return {
                    "version": VERSION,
                    "selected": dict(data.get("selected") or {}),
                    "custom_ollama": list(data.get("custom_ollama") or []),
                    "records": dict(data.get("records") or {}),
                }
        except (OSError, ValueError):
            pass
        return {"version": VERSION, "selected": {}, "custom_ollama": [], "records": {}}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(self.path, self._data)

    # ----- selection ---------------------------------------------------------------------
    def selected(self, role: str) -> str | None:
        with self._lock:
            value = self._data["selected"].get(role)
            return str(value) if value else None

    def set_selected(self, role: str, entry_id: str) -> None:
        with self._lock:
            self._data["selected"][role] = entry_id
            self._save()

    # ----- custom Ollama models ------------------------------------------------------------
    def custom_ollama(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(x) for x in self._data["custom_ollama"]]

    def add_custom(self, tag: str, size_bytes: int) -> None:
        with self._lock:
            items = [x for x in self._data["custom_ollama"] if x.get("tag") != tag]
            items.append({"tag": tag, "size_bytes": int(size_bytes), "added": time.time()})
            self._data["custom_ollama"] = items
            self._save()

    def remove_custom(self, tag: str) -> None:
        with self._lock:
            self._data["custom_ollama"] = [
                x for x in self._data["custom_ollama"] if x.get("tag") != tag
            ]
            self._save()

    # ----- per-entry records (revision seen at install, update checks) ----------------------
    def record(self, entry_id: str) -> dict[str, Any]:
        with self._lock:
            return dict(self._data["records"].get(entry_id, {}))

    def update_record(self, entry_id: str, **fields: Any) -> None:
        with self._lock:
            rec = self._data["records"].setdefault(entry_id, {})
            rec.update(fields)
            self._save()

    def drop_record(self, entry_id: str) -> None:
        with self._lock:
            if self._data["records"].pop(entry_id, None) is not None:
                self._save()

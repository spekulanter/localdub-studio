"""Per-stage checkpoints so a failed or interrupted run resumes from the first incomplete stage.

A stage is complete when its record exists, its fingerprint (parameters + input file digests)
is unchanged and all of its outputs still exist. Writes are atomic (temp file + os.replace).
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel

_SMALL_FILE = 64 * 1024 * 1024


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def atomic_write_json(path: Path, data: Any) -> None:
    atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2))


def file_digest(path: Path) -> str:
    """Content hash for small files; size + mtime for large media (fast, good enough)."""
    st = path.stat()
    if st.st_size > _SMALL_FILE:
        return f"stat:{st.st_size}:{st.st_mtime_ns}"
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def fingerprint(params: dict[str, Any], inputs: list[Path]) -> str:
    h = hashlib.sha256(json.dumps(params, sort_keys=True, default=str).encode())
    for p in inputs:
        h.update(str(p.name).encode())
        h.update(file_digest(p).encode())
    return h.hexdigest()


class StageRecord(BaseModel):
    fingerprint: str
    outputs: list[str]
    completed_at: float
    elapsed_s: float


class CheckpointStore:
    def __init__(self, workdir: Path) -> None:
        self.workdir = workdir
        self.path = workdir / "state.json"

    def _load(self) -> dict[str, StageRecord]:
        if not self.path.is_file():
            return {}
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        return {k: StageRecord.model_validate(v) for k, v in raw.get("stages", {}).items()}

    def _save(self, records: dict[str, StageRecord]) -> None:
        atomic_write_json(self.path, {"stages": {k: v.model_dump() for k, v in records.items()}})

    def is_complete(self, stage: str, fp: str) -> bool:
        rec = self._load().get(stage)
        if rec is None or rec.fingerprint != fp:
            return False
        return all((self.workdir / o).exists() for o in rec.outputs)

    def mark_complete(self, stage: str, fp: str, outputs: list[Path], elapsed_s: float) -> None:
        records = self._load()
        records[stage] = StageRecord(
            fingerprint=fp,
            outputs=[str(o.relative_to(self.workdir)) for o in outputs],
            completed_at=time.time(),
            elapsed_s=round(elapsed_s, 3),
        )
        self._save(records)

    def invalidate(self, stages: list[str]) -> None:
        records = self._load()
        for s in stages:
            records.pop(s, None)
        self._save(records)

    def records(self) -> dict[str, StageRecord]:
        return self._load()

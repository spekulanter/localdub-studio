"""SQLite store for projects and jobs. Segments stay in the per-project work directory."""

from __future__ import annotations

import sqlite3
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    original_name TEXT NOT NULL,
    input_rel TEXT NOT NULL,
    duration REAL NOT NULL,
    source_lang TEXT NOT NULL,
    voice TEXT NOT NULL,
    llm_model TEXT NOT NULL,
    original_audio TEXT NOT NULL DEFAULT 'duck',
    keep_original_track INTEGER NOT NULL DEFAULT 1,
    diarize INTEGER NOT NULL DEFAULT 0,
    clone_voice INTEGER NOT NULL DEFAULT 0,
    num_speakers INTEGER,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    status TEXT NOT NULL,
    stage TEXT NOT NULL DEFAULT '',
    message TEXT NOT NULL DEFAULT '',
    progress REAL NOT NULL DEFAULT 0,
    error TEXT,
    from_stage TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    pid INTEGER,
    heartbeat REAL,
    created_at REAL NOT NULL,
    started_at REAL,
    finished_at REAL
);
CREATE INDEX IF NOT EXISTS jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS jobs_project ON jobs(project_id);
"""

MIGRATIONS = {
    "diarize": "INTEGER NOT NULL DEFAULT 0",
    "num_speakers": "INTEGER",
    "clone_voice": "INTEGER NOT NULL DEFAULT 0",
}
ACTIVE = ("queued", "running")
TERMINAL = ("done", "failed", "cancelled")
Row = dict[str, Any]


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        with self.tx() as c:
            c.executescript(SCHEMA)
            # Databases created by an earlier version lack the newer columns.
            have = {r["name"] for r in c.execute("PRAGMA table_info(projects)")}
            for col, ddl in MIGRATIONS.items():
                if col not in have:
                    c.execute(f"ALTER TABLE projects ADD COLUMN {col} {ddl}")

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        """One short-lived connection per transaction: safe across threads and processes."""
        with self._lock:
            conn = sqlite3.connect(self.path, timeout=30)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            try:
                yield conn
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
            finally:
                conn.close()

    # ----- projects ----------------------------------------------------------------------
    def create_project(self, **f: Any) -> int:
        f.setdefault("created_at", time.time())
        cols = ", ".join(f)
        marks = ", ".join(f":{k}" for k in f)
        with self.tx() as c:
            cur = c.execute(f"INSERT INTO projects ({cols}) VALUES ({marks})", f)
            assert cur.lastrowid is not None
            return cur.lastrowid

    def get_project(self, project_id: int) -> Row | None:
        with self.tx() as c:
            row = c.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        return dict(row) if row else None

    def list_projects(self) -> list[Row]:
        with self.tx() as c:
            rows = c.execute("SELECT * FROM projects ORDER BY id DESC").fetchall()
        return [dict(r) for r in rows]

    def update_project(self, project_id: int, **f: Any) -> None:
        sets = ", ".join(f"{k}=:{k}" for k in f)
        with self.tx() as c:
            c.execute(f"UPDATE projects SET {sets} WHERE id=:_id", {**f, "_id": project_id})

    def delete_project(self, project_id: int) -> None:
        with self.tx() as c:
            c.execute("DELETE FROM projects WHERE id=?", (project_id,))

    # ----- jobs --------------------------------------------------------------------------
    def create_job(self, project_id: int, from_stage: str | None = None) -> int:
        with self.tx() as c:
            cur = c.execute(
                "INSERT INTO jobs (project_id, status, from_stage, created_at) "
                "VALUES (?, 'queued', ?, ?)",
                (project_id, from_stage, time.time()),
            )
            assert cur.lastrowid is not None
            return cur.lastrowid

    def get_job(self, job_id: int) -> Row | None:
        with self.tx() as c:
            row = c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return dict(row) if row else None

    def list_jobs(self, project_id: int) -> list[Row]:
        with self.tx() as c:
            rows = c.execute(
                "SELECT * FROM jobs WHERE project_id=? ORDER BY id DESC", (project_id,)
            ).fetchall()
        return [dict(r) for r in rows]

    def active_job(self, project_id: int) -> Row | None:
        with self.tx() as c:
            row = c.execute(
                "SELECT * FROM jobs WHERE project_id=? AND status IN ('queued','running') "
                "ORDER BY id LIMIT 1",
                (project_id,),
            ).fetchone()
        return dict(row) if row else None

    def next_queued(self) -> Row | None:
        with self.tx() as c:
            row = c.execute(
                "SELECT * FROM jobs WHERE status='queued' ORDER BY id LIMIT 1"
            ).fetchone()
        return dict(row) if row else None

    def running_jobs(self) -> list[Row]:
        with self.tx() as c:
            rows = c.execute("SELECT * FROM jobs WHERE status='running'").fetchall()
        return [dict(r) for r in rows]

    def update_job(self, job_id: int, **f: Any) -> None:
        sets = ", ".join(f"{k}=:{k}" for k in f)
        with self.tx() as c:
            c.execute(f"UPDATE jobs SET {sets} WHERE id=:_id", {**f, "_id": job_id})

    def finish_job(self, job_id: int, status: str, error: str | None = None) -> bool:
        """Set a terminal status unless the job already has one (cancel wins over a late exit)."""
        with self.tx() as c:
            cur = c.execute(
                "UPDATE jobs SET status=?, error=?, finished_at=?, pid=NULL "
                "WHERE id=? AND status IN ('queued','running')",
                (status, error, time.time(), job_id),
            )
            return cur.rowcount > 0

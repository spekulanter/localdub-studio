"""An update must never lose or break the projects of the installed version.

OLD_SCHEMA is the database schema of the released versions 0.1.0-0.1.3, copied verbatim from the
git tag v0.1.2 (`git show v0.1.2:localdub/api/db.py`).
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from localdub.api.app import create_app
from localdub.api.db import Database
from localdub.config import Settings

OLD_SCHEMA = """
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


@pytest.fixture
def old_install(tmp_path: Path) -> Settings:
    """A data folder as version 0.1.x left it: one finished dub and one that was voice-cloned."""
    data = tmp_path / "data"
    data.mkdir()
    conn = sqlite3.connect(data / "localdub.sqlite")
    conn.executescript(OLD_SCHEMA)
    now = time.time()
    conn.execute(
        "INSERT INTO projects (name, original_name, input_rel, duration, source_lang, voice, llm_model,"
        " original_audio, created_at) VALUES ('Clip ľščťžýáíé', 'Clip.mp4', 'input/Clip.mp4', 50.0,"
        " 'en', 'M2', 'translategemma:4b', 'mute', ?)",
        (now,),
    )
    conn.execute(
        "INSERT INTO projects (name, original_name, input_rel, duration, source_lang, voice, llm_model,"
        " clone_voice, diarize, num_speakers, created_at) VALUES ('Second', 's.mp4', 'input/s.mp4', 9.5,"
        " 'en', 'F1', 'translategemma:4b', 1, 1, 3, ?)",
        (now,),
    )
    conn.execute(
        "INSERT INTO jobs (project_id, status, stage, progress, attempts, created_at, finished_at)"
        " VALUES (1, 'done', 'export', 1.0, 1, ?, ?)",
        (now, now),
    )
    conn.commit()
    conn.close()
    pdir = data / "projects" / "1"
    (pdir / "input").mkdir(parents=True)
    (pdir / "input" / "Clip.mp4").write_bytes(b"x")
    return Settings(data_dir=data, models_dir=tmp_path / "models", require_models_before_jobs=False)


def test_opening_an_old_database_adds_the_new_columns_and_keeps_every_value(old_install: Settings):
    db = Database(old_install.data_dir / "localdub.sqlite")
    first, second = db.get_project(1), db.get_project(2)
    assert first is not None and second is not None
    assert (first["name"], first["voice"], first["original_audio"], first["duration"]) == (
        "Clip ľščťžýáíé", "M2", "mute", 50.0,
    )  # fmt: skip
    assert (second["clone_voice"], second["diarize"], second["num_speakers"]) == (1, 1, 3)
    for row in (first, second):  # the YouTube columns arrived with safe defaults
        assert row["source_url"] is None
        assert row["download_quality"] == "auto"
        assert row["cookies_browser"] == "none"
    job = db.get_job(1)
    assert job is not None and job["status"] == "done" and job["progress"] == 1.0


def test_opening_it_twice_is_harmless(old_install: Settings):
    for _ in range(3):
        Database(old_install.data_dir / "localdub.sqlite")
    assert len(Database(old_install.data_dir / "localdub.sqlite").list_projects()) == 2


def test_the_api_serves_old_projects_and_can_work_on_them(old_install: Settings):
    with TestClient(create_app(old_install, start_queue=False)) as client:
        rows = {p["id"]: p for p in client.get("/api/projects").json()}
        assert set(rows) == {1, 2}
        assert rows[1]["source_url"] is None and rows[1]["download_quality"] == "auto"
        assert rows[1]["has_input"] is True and rows[2]["has_input"] is False
        assert rows[1]["latest_job"]["status"] == "done"
        assert rows[2]["clone_voice"] is True and rows[2]["num_speakers"] == 3
        # settings can be changed and a new job queued, exactly as before the update
        assert client.patch("/api/projects/1", json={"voice": "F3"}).json()["voice"] == "F3"
        assert client.post("/api/projects/1/jobs", json={"from_stage": "tts"}).status_code == 201
        # and a brand-new YouTube project can sit next to the old ones
        assert client.get("/api/projects/2").json()["name"] == "Second"

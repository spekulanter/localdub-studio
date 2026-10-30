from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

from localdub import worker
from localdub.api.db import Database
from localdub.config import Settings


class FakePipeline:
    """Reports what a link-based job reports, including text-only statuses."""

    seen_remote = None

    def __init__(self, input_path, workdir, settings, **kw):
        self.on_progress = kw["on_progress"]
        FakePipeline.seen_remote = kw.get("remote")

    def run(self, from_stage=None):
        report = self.on_progress
        for stage, state in [
            ("download", "running"), ("download", "Starting yt-dlp..."), ("download", "45.0% - 3MiB/s"),
            ("download", "90.0% - 3MiB/s"), ("download", "[Merger] Merging formats into x.mp4"),
            ("download", "[VideoRemuxer] Not remuxing"), ("download", "done"),
            ("probe", "running"), ("probe", "done"), ("tts", "3/10"), ("tts", "done"),
        ]:  # fmt: skip
            report(stage, state)
        return {}

    def info(self):
        return SimpleNamespace(duration=52.25)


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(worker, "Pipeline", FakePipeline)
    monkeypatch.setattr(worker, "_watch", lambda *a: None)  # it would end the test process
    monkeypatch.setattr(worker, "make_remote", lambda project, base: "remote-object")
    data = tmp_path / "data"
    db = Database(data / "localdub.sqlite")
    pid = db.create_project(
        name="t", original_name="t", input_rel="input/source.mp4", duration=0.0,
        source_lang="en", voice="F1", llm_model="m", source_url="https://youtu.be/abc",
    )  # fmt: skip
    return data, db, pid


def test_a_text_status_never_pulls_the_progress_bar_back(setup, monkeypatch):
    data, db, pid = setup
    job_id = db.create_job(pid)
    history: list[float] = []
    original = Database.update_job

    def spy(self, job, **fields):
        if "progress" in fields:
            history.append(fields["progress"])
        original(self, job, **fields)

    monkeypatch.setattr(Database, "update_job", spy)
    assert worker.run_job(data, job_id, os.getpid(), Settings(data_dir=data)) == 0
    assert history == sorted(history), history
    assert history[0] == 0.0 and 0.05 < history[5] < 0.12  # during/after the download
    job = db.get_job(job_id)
    assert job["status"] == "done" and job["progress"] == 1.0


def test_the_real_duration_replaces_the_one_from_the_link(setup):
    data, db, pid = setup
    job_id = db.create_job(pid)
    worker.run_job(data, job_id, os.getpid(), Settings(data_dir=data))
    assert db.get_project(pid)["duration"] == 52.25
    assert FakePipeline.seen_remote == "remote-object"  # a project with a link gets the downloader

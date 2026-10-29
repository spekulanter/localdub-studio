from __future__ import annotations

import os
import subprocess
import sys
import time

import pytest

from localdub.api.db import Database
from localdub.api.jobs import JobManager
from localdub.config import Settings
from localdub.core.platform import pid_alive
from localdub.worker import progress_fraction


@pytest.fixture
def db(settings: Settings) -> Database:
    return Database(settings.data_dir / "localdub.sqlite")


@pytest.fixture
def project_id(db: Database) -> int:
    return db.create_project(
        name="p", original_name="p.mp4", input_rel="input/p.mp4", duration=2.0,
        source_lang="en", voice="F1", llm_model="m",
    )  # fmt: skip


def wait_for(db: Database, job_id: int, statuses: tuple[str, ...], timeout: float = 20.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = db.get_job(job_id)
        assert job is not None
        if job["status"] in statuses:
            return job
        time.sleep(0.1)
    raise AssertionError(f"job {job_id} stuck in {db.get_job(job_id)}")


def make_manager(db: Database, settings: Settings, fake_worker, mode: str) -> JobManager:
    return JobManager(db, settings, poll_s=0.05, worker_command=fake_worker(settings, mode))


@pytest.mark.parametrize(
    ("mode", "status", "error"),
    [
        ("ok", "done", None),
        ("fail", "failed", "boom"),
        ("crash", "failed", "unexpectedly (code 7)"),
    ],
)
def test_worker_outcomes(db, settings, project_id, fake_worker, mode, status, error):
    mgr = make_manager(db, settings, fake_worker, mode)
    mgr.start()
    try:
        job = wait_for(db, mgr.submit(project_id), ("done", "failed"))
    finally:
        mgr.stop()
    assert job["status"] == status
    assert error is None or error in job["error"]
    assert job["attempts"] == 1 and job["finished_at"] is not None


def test_jobs_run_one_at_a_time_in_order(db, settings, project_id, fake_worker):
    mgr = make_manager(db, settings, fake_worker, "ok")
    mgr.start()
    try:
        ids = [mgr.submit(project_id) for _ in range(3)]
        jobs = [wait_for(db, i, ("done",)) for i in ids]
    finally:
        mgr.stop()
    starts = [j["started_at"] for j in jobs]
    assert starts == sorted(starts)
    assert all(
        a["finished_at"] <= b["started_at"] + 0.5 for a, b in zip(jobs, jobs[1:], strict=False)
    )


def test_cancel_running_job_kills_worker(db, settings, project_id, fake_worker):
    mgr = make_manager(db, settings, fake_worker, "hang")
    mgr.start()
    try:
        job_id = mgr.submit(project_id)
        job = wait_for(db, job_id, ("running",))
        deadline = time.time() + 10
        while not (db.get_job(job_id) or {}).get("pid") and time.time() < deadline:
            time.sleep(0.1)
        pid = db.get_job(job_id)["pid"]
        assert pid and pid_alive(pid)
        assert mgr.cancel(job_id) is True
        assert db.get_job(job_id)["status"] == "cancelled"
        deadline = time.time() + 10
        while pid_alive(pid) and time.time() < deadline:
            time.sleep(0.1)
        assert not pid_alive(pid)
        assert mgr.cancel(job_id) is False
    finally:
        mgr.stop()
    assert db.get_job(job_id)["status"] == "cancelled"
    assert job["started_at"] is not None


def test_cancel_queued_job(db, project_id, settings, fake_worker):
    mgr = make_manager(db, settings, fake_worker, "ok")  # queue not started
    job_id = mgr.submit(project_id)
    assert mgr.cancel(job_id) is True
    assert db.get_job(job_id)["status"] == "cancelled"


def test_recover_requeues_interrupted_job_and_resumes(db, settings, project_id, fake_worker):
    job_id = db.create_job(project_id)
    db.update_job(job_id, status="running", attempts=1, pid=999999, heartbeat=time.time() - 3600)
    mgr = make_manager(db, settings, fake_worker, "ok")
    mgr.start()
    try:
        job = wait_for(db, job_id, ("done",))
    finally:
        mgr.stop()
    assert job["attempts"] == 2


def test_recover_gives_up_after_max_attempts(db, settings, project_id, fake_worker):
    job_id = db.create_job(project_id)
    db.update_job(job_id, status="running", attempts=settings.max_job_attempts, pid=999999)
    make_manager(db, settings, fake_worker, "ok").recover()
    job = db.get_job(job_id)
    assert job["status"] == "failed" and "giving up" in job["error"]


def test_stop_requeues_running_job(db, settings, project_id, fake_worker):
    mgr = make_manager(db, settings, fake_worker, "hang")
    mgr.start()
    job_id = mgr.submit(project_id)
    wait_for(db, job_id, ("running",))
    time.sleep(0.5)
    mgr.stop()
    assert db.get_job(job_id)["status"] == "queued"


def test_finish_job_cannot_override_cancel(db, project_id):
    job_id = db.create_job(project_id)
    assert db.finish_job(job_id, "cancelled") is True
    assert db.finish_job(job_id, "done") is False
    assert db.get_job(job_id)["status"] == "cancelled"


def test_progress_fraction_is_monotonic_and_bounded():
    from localdub.pipeline import STAGES

    values = []
    for stage in STAGES:
        values += [progress_fraction(stage, "running"), progress_fraction(stage, "done")]
    assert values == sorted(values) and values[0] == 0 and values[-1] == pytest.approx(1.0)
    assert progress_fraction("tts", "3/10") > progress_fraction("tts", "1/10")
    assert progress_fraction("tts", "garbage") == progress_fraction("tts", "running")


def test_pid_alive_for_self_and_dead_process():
    assert pid_alive(os.getpid())
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    assert not pid_alive(proc.pid)
    assert not pid_alive(0)

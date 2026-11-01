"""Restart-safe, single-slot job queue. One worker process at a time keeps the GPU to one model."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
import time
from collections.abc import Callable

from localdub.api.db import Database
from localdub.config import Settings
from localdub.core.platform import kill_tree, pid_alive

log = logging.getLogger(__name__)

HEARTBEAT_STALE_S = 15.0
CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


class JobManager:
    def __init__(
        self,
        db: Database,
        settings: Settings,
        poll_s: float = 0.5,
        worker_command: Callable[[int], list[str]] | None = None,
    ) -> None:
        self.db = db
        self.worker_command = worker_command or self._default_command
        self.settings = settings
        self.poll_s = poll_s
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self._proc: subprocess.Popen[bytes] | None = None
        self._current: int | None = None
        self._lock = threading.Lock()

    # ----- lifecycle ---------------------------------------------------------------------
    def start(self) -> None:
        self.recover()
        self._thread = threading.Thread(target=self._loop, name="job-manager", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop the queue; a running job is stopped and re-queued so it resumes next start."""
        self._stop.set()
        self._wake.set()
        with self._lock:
            proc, job_id = self._proc, self._current
        if proc is not None and job_id is not None:
            kill_tree(proc.pid)
            self.db.update_job(job_id, status="queued", pid=None, message="interrupted")
        if self._thread:
            self._thread.join(timeout=10)

    def recover(self) -> None:
        """After a server crash/restart: running jobs go back to the queue (or fail after N)."""
        for job in self.db.running_jobs():
            pid = job["pid"]
            if pid and pid_alive(pid) and time.time() - (job["heartbeat"] or 0) < HEARTBEAT_STALE_S:
                # An orphaned worker notices the missing server within seconds and exits.
                deadline = time.time() + HEARTBEAT_STALE_S
                while pid_alive(pid) and time.time() < deadline:
                    time.sleep(0.5)
                if pid_alive(pid):
                    kill_tree(pid)
            if job["attempts"] >= self.settings.max_job_attempts:
                self.db.finish_job(
                    job["id"], "failed", f"Interrupted {job['attempts']} times; giving up"
                )
            else:
                log.warning("Re-queueing interrupted job %s", job["id"])
                self.db.update_job(
                    job["id"], status="queued", pid=None, message="resuming after restart"
                )

    # ----- API used by routes ------------------------------------------------------------
    def submit(self, project_id: int, from_stage: str | None = None) -> int:
        job_id = self.db.create_job(project_id, from_stage)
        self._wake.set()
        return job_id

    def cancel(self, job_id: int) -> bool:
        job = self.db.get_job(job_id)
        if job is None or job["status"] not in ("queued", "running"):
            return False
        if not self.db.finish_job(job_id, "cancelled"):
            return False
        with self._lock:
            proc = self._proc if self._current == job_id else None
        if proc is not None:
            kill_tree(proc.pid)
            self._unload_ollama(job["project_id"])
        return True

    def _default_command(self, job_id: int) -> list[str]:
        return [
            sys.executable, "-m", "localdub.worker",
            "--data-dir", str(self.settings.data_dir),
            "--job", str(job_id),
            "--parent-pid", str(os.getpid()),
        ]  # fmt: skip

    # ----- internals ---------------------------------------------------------------------
    def _unload_ollama(self, project_id: int) -> None:
        project = self.db.get_project(project_id)
        if project is None:
            return
        from localdub.core.translation.ollama_provider import OllamaClient

        try:
            client = OllamaClient(self.settings.ollama_url)
            try:
                client.unload(project["llm_model"])
            finally:
                client.close()
        except Exception:  # noqa: BLE001 - best effort
            log.debug("Could not unload Ollama model", exc_info=True)

    def _loop(self) -> None:
        while not self._stop.is_set():
            job = self.db.next_queued()
            if job is None:
                self._wake.wait(self.poll_s)
                self._wake.clear()
                continue
            try:
                self._run(job)
            except Exception:  # noqa: BLE001 - the queue must survive any single job
                log.exception("Job %s crashed the manager", job["id"])
                self.db.finish_job(job["id"], "failed", "Internal error; see server log")

    def _run(self, job: dict[str, object]) -> None:
        job_id = int(job["id"])  # type: ignore[call-overload]
        attempts = int(job["attempts"]) + 1  # type: ignore[call-overload]
        self.db.update_job(
            job_id,
            status="running",
            attempts=attempts,
            started_at=time.time(),
            heartbeat=time.time(),
        )
        proc = subprocess.Popen(  # noqa: S603
            self.worker_command(job_id),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=CREATE_NO_WINDOW,
            start_new_session=sys.platform != "win32",  # its own process group on macOS
        )
        with self._lock:
            self._proc, self._current = proc, job_id
        try:
            code = proc.wait()
        finally:
            with self._lock:
                self._proc, self._current = None, None
        row = self.db.get_job(job_id)
        if row and row["status"] == "running" and not self._stop.is_set():
            # Exited without reporting a result: crashed or was killed from outside.
            self.db.finish_job(job_id, "failed", f"Worker exited unexpectedly (code {code})")

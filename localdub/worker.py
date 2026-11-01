"""Job worker process: runs one pipeline job and reports progress through SQLite.

Started by the API's JobManager as `python -m localdub.worker --data-dir D --job N`. It exits by
itself if the server disappears, so a crashed server never leaves a GPU-holding orphan behind.
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import sys
import threading
import time
import traceback
from pathlib import Path

from localdub.api.db import Database
from localdub.config import Settings
from localdub.core.gpu import register_cuda_dlls
from localdub.core.platform import disable_power_throttling, keep_awake, pid_alive
from localdub.core.youtube import ytdlp
from localdub.core.youtube.remote import make_remote
from localdub.pipeline import STAGES, Pipeline, PipelineError

log = logging.getLogger("localdub.worker")

# Rough share of total wall time per stage, used only for the progress bar.
STAGE_WEIGHTS = {
    "download": 0.12,  # only counted for projects that came from a link
    "probe": 0.01,
    "extract": 0.02,
    "asr": 0.18,
    "diarize": 0.04,
    "translate": 0.14,
    "tts": 0.37,
    "separate": 0.08,
    "convert": 0.04,
    "assemble": 0.04,
    "export": 0.08,
}


def progress_fraction(stage: str, state: str, *, has_download: bool = False) -> float:
    """Progress at the moment `stage` reports `state` ('running', 'done', 'n/m' or '37.5% ...')."""
    weights = {k: v for k, v in STAGE_WEIGHTS.items() if has_download or k != "download"}
    total = sum(weights.values()) or 1.0
    before = 0.0
    for s in STAGES:
        if s == stage:
            break
        before += weights.get(s, 0.0)
    weight = weights.get(stage, 0.0)
    fraction = 0.0
    if state == "done":
        fraction = 1.0
    elif m := re.match(r"\s*(\d+(?:\.\d+)?)%", state):  # "37.5% - 2MiB/s" (a download)
        fraction = float(m.group(1)) / 100.0
    elif m := re.fullmatch(r"(\d+)/(\d+)", state):  # "3/10" (item n of m)
        fraction = (int(m.group(1)) - 1) / max(int(m.group(2)), 1)
    return min((before + weight * min(max(fraction, 0.0), 1.0)) / total, 1.0)


def project_settings(base: Settings, project: dict[str, object]) -> Settings:
    s = base.model_copy()
    s.translation_model = str(project["llm_model"])
    s.asr_id = str(project.get("asr_id") or s.asr_id)
    mode = project["original_audio"]
    s.original_audio = mode if mode in ("mute", "background") else "duck"
    s.keep_original_track = bool(project["keep_original_track"])
    s.voice_cloning_enabled = bool(project["clone_voice"])
    s.diarization_enabled = bool(project["diarize"])
    num = project["num_speakers"]
    s.diarization_num_speakers = int(num) if isinstance(num, int) and num > 0 else None
    return s


def _watch(db: Database, job_id: int, parent_pid: int) -> None:
    """Heartbeat, and exit if the server process is gone or the job was cancelled."""
    while True:
        time.sleep(2)
        job = db.get_job(job_id)
        if job is None or job["status"] != "running" or not pid_alive(parent_pid):
            log.warning("Server gone or job no longer running; exiting")
            ytdlp.terminate_active()  # os._exit would leave a running download behind
            os._exit(3)
        db.update_job(job_id, heartbeat=time.time())


def run_job(data_dir: Path, job_id: int, parent_pid: int, base: Settings | None = None) -> int:
    base = base or Settings()
    db = Database(data_dir / "localdub.sqlite")
    job = db.get_job(job_id)
    if job is None:
        return 2
    project = db.get_project(job["project_id"])
    if project is None:
        db.finish_job(job_id, "failed", "Project no longer exists")
        return 2

    db.update_job(job_id, pid=os.getpid(), heartbeat=time.time())
    threading.Thread(target=_watch, args=(db, job_id, parent_pid), daemon=True).start()

    has_download = bool(project["source_url"])
    best = [0.0]  # progress never goes back: a text status ("Merging...") carries no number

    def best_progress(stage: str, state: str) -> float:
        best[0] = max(best[0], progress_fraction(stage, state, has_download=has_download))
        return best[0]

    def on_progress(stage: str, state: str) -> None:
        db.update_job(
            job_id,
            stage=stage,
            message=state if state != "running" else "",
            progress=round(best_progress(stage, state), 4),
            heartbeat=time.time(),
        )

    disable_power_throttling()
    keep_awake()
    register_cuda_dlls()
    project_dir = data_dir / "projects" / str(project["id"])
    pipe = Pipeline(
        project_dir / project["input_rel"],
        project_dir / "work",
        project_settings(base, project),
        source_lang=None if project["source_lang"] == "auto" else str(project["source_lang"]),
        voice=str(project["voice"]),
        on_progress=on_progress,
        remote=make_remote(project, base) if has_download else None,
    )
    try:
        pipe.run(from_stage=job["from_stage"])
    except PipelineError as exc:
        db.finish_job(job_id, "failed", str(exc))
        return 1
    except Exception as exc:  # noqa: BLE001 - report anything to the user instead of dying silently
        log.error("Unexpected failure:\n%s", traceback.format_exc())
        db.finish_job(job_id, "failed", f"{type(exc).__name__}: {exc}")
        return 1
    try:  # the length of a downloaded video is only known exactly now
        db.update_project(project["id"], duration=pipe.info().duration)
    except Exception:  # noqa: BLE001 - cosmetic; the job itself succeeded
        log.debug("Could not update the project duration", exc_info=True)
    db.update_job(job_id, stage="export", progress=1.0, message="")
    db.finish_job(job_id, "done")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--job", type=int, required=True)
    parser.add_argument("--parent-pid", type=int, required=True)
    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    log_path = args.data_dir / "logs" / f"job-{args.job}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        handlers=[logging.FileHandler(log_path, encoding="utf-8"), logging.StreamHandler()],
    )
    return run_job(args.data_dir, args.job, args.parent_pid)


if __name__ == "__main__":
    raise SystemExit(main())

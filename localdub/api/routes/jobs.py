"""Jobs: start, list, cancel, follow progress and read the log."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response, StreamingResponse

from localdub.api.common import AppContext, JobRequest


def build(ctx: AppContext) -> APIRouter:
    router = APIRouter()
    db, jobs, settings = ctx.db, ctx.jobs, ctx.settings
    job_out = ctx.job_out

    def log_path(job_id: int) -> Any:
        return settings.data_dir / "logs" / f"job-{job_id}.log"

    @router.post("/api/projects/{pid}/jobs", status_code=201)
    def start_job(pid: int, req: JobRequest | None = None) -> dict[str, Any]:
        row = ctx.require_project(pid)
        if db.active_job(pid):
            raise HTTPException(409, "A job is already queued or running for this project")
        ctx.require_models(str(row["asr_id"]), str(row["llm_model"]))
        job_id = jobs.submit(pid, req.from_stage if req else None)
        return job_out(db.get_job(job_id)) or {}

    @router.get("/api/projects/{pid}/jobs")
    def project_jobs(pid: int) -> list[dict[str, Any]]:
        ctx.require_project(pid)
        return [j for j in (job_out(x) for x in db.list_jobs(pid)) if j]

    @router.get("/api/jobs/{job_id}")
    def get_job(job_id: int) -> dict[str, Any]:
        job = db.get_job(job_id)
        if job is None:
            raise HTTPException(404, "Job not found")
        return job_out(job) or {}

    @router.post("/api/jobs/{job_id}/cancel")
    def cancel_job(job_id: int) -> dict[str, Any]:
        if db.get_job(job_id) is None:
            raise HTTPException(404, "Job not found")
        if not jobs.cancel(job_id):
            raise HTTPException(409, "Job is not queued or running")
        return job_out(db.get_job(job_id)) or {}

    @router.get("/api/jobs/{job_id}/events")
    async def job_events(job_id: int) -> StreamingResponse:
        if db.get_job(job_id) is None:
            raise HTTPException(404, "Job not found")

        async def stream() -> AsyncIterator[str]:
            last: str | None = None
            while True:
                job = await asyncio.to_thread(db.get_job, job_id)
                if job is None:
                    return
                payload = json.dumps(job_out(job), ensure_ascii=False)
                if payload != last:
                    yield f"data: {payload}\n\n"
                    last = payload
                if job["status"] not in ("queued", "running"):
                    return
                await asyncio.sleep(0.5)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @router.get("/api/jobs/{job_id}/log/download")
    def job_log_download(job_id: int) -> Response:
        """The whole job log plus the error, as a text file the user can send to support."""
        job = db.get_job(job_id)
        if job is None:
            raise HTTPException(404, "Job not found")
        path = log_path(job_id)
        body = (
            path.read_text(encoding="utf-8", errors="replace") if path.is_file() else "(no log)\n"
        )
        header = (
            f"LocalDub Studio job {job_id}  status={job['status']}  stage={job['stage']}\n"
            f"error: {job['error'] or '-'}\n{'=' * 72}\n"
        )
        return Response(
            header + body,
            media_type="text/plain; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="localdub-job-{job_id}.log"'},
        )

    @router.get("/api/jobs/{job_id}/log")
    def job_log(job_id: int, tail: int = 200) -> dict[str, Any]:
        if db.get_job(job_id) is None:
            raise HTTPException(404, "Job not found")
        path = log_path(job_id)
        lines = (
            path.read_text(encoding="utf-8", errors="replace").splitlines()
            if path.is_file()
            else []
        )
        return {"lines": lines[-max(1, min(tail, 2000)) :]}

    return router

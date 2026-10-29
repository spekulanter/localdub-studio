"""FastAPI application: projects, jobs, progress events, segments and downloads.

The server only listens on localhost by default; all media stays on this machine.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
import unicodedata
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from localdub.api.db import Database
from localdub.api.jobs import JobManager
from localdub.config import Settings
from localdub.core.media.ffmpeg import FFmpeg, MediaError
from localdub.pipeline import STAGES

log = logging.getLogger(__name__)

ALLOWED_SUFFIXES = {".mp4", ".m4v", ".mov", ".mkv"}
VOICES = [f"F{i}" for i in range(1, 6)] + [f"M{i}" for i in range(1, 6)]
SOURCE_LANGS = {"en": "English", "auto": "Auto-detect"}
SEGMENT_FILES = ["segments.json", "tts.json", "translation.json", "asr.json"]
_BAD_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


class ProjectOut(BaseModel):
    id: int
    name: str
    original_name: str
    duration: float
    source_lang: str
    voice: str
    llm_model: str
    original_audio: Literal["duck", "mute"]
    keep_original_track: bool
    created_at: float
    latest_job: dict[str, Any] | None = None
    has_output: bool = False


class ProjectPatch(BaseModel):
    name: str | None = None
    voice: str | None = None
    llm_model: str | None = None
    original_audio: Literal["duck", "mute"] | None = None
    keep_original_track: bool | None = None


class JobRequest(BaseModel):
    from_stage: (
        Literal["probe", "extract", "asr", "translate", "tts", "assemble", "export"] | None
    ) = None


def safe_filename(name: str, fallback: str = "video.mp4") -> str:
    """Keep Unicode and spaces; drop path parts, control chars and Windows-reserved characters."""
    base = Path(name.replace("\\", "/")).name
    base = unicodedata.normalize("NFC", _BAD_CHARS.sub("_", base)).strip(" .")
    if len(base) > 120:
        stem, suffix = Path(base).stem[:100], Path(base).suffix
        base = stem + suffix
    return base or fallback


def create_app(settings: Settings | None = None, *, start_queue: bool = True) -> FastAPI:
    settings = settings or Settings()
    db = Database(settings.data_dir / "localdub.sqlite")
    jobs = JobManager(db, settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if start_queue:
            await asyncio.to_thread(jobs.start)
        yield
        if start_queue:
            await asyncio.to_thread(jobs.stop)

    app = FastAPI(title="LocalDub Studio", version="0.1.0", lifespan=lifespan)
    app.state.db, app.state.jobs, app.state.settings = db, jobs, settings

    def project_dir(pid: int) -> Path:
        return settings.data_dir / "projects" / str(pid)

    def require_project(pid: int) -> dict[str, Any]:
        row = db.get_project(pid)
        if row is None:
            raise HTTPException(404, "Project not found")
        return row

    def output_paths(project: dict[str, Any]) -> dict[str, Path]:
        stem = Path(project["input_rel"]).stem
        wd = project_dir(project["id"]) / "work"
        return {
            "video": wd / f"{stem}.sk.mp4",
            "srt": wd / f"{stem}.sk.srt",
            "srt_en": wd / f"{stem}.en.srt",
        }

    def job_out(job: dict[str, Any] | None) -> dict[str, Any] | None:
        if job is None:
            return None
        return {k: v for k, v in job.items() if k not in ("pid", "heartbeat")}

    def project_out(row: dict[str, Any]) -> ProjectOut:
        latest = db.list_jobs(row["id"])[:1]
        out = output_paths(row)
        done = bool(latest) and latest[0]["status"] == "done" and out["video"].is_file()
        return ProjectOut(
            **{k: v for k, v in row.items() if k not in ("input_rel",)},
            latest_job=job_out(latest[0]) if latest else None,
            has_output=done,
        )

    # ----- meta --------------------------------------------------------------------------
    @app.get("/api/health")
    def health() -> dict[str, Any]:
        from localdub.core.translation.ollama_provider import OllamaClient

        client = OllamaClient(settings.ollama_url)
        try:
            models, error = client.list_models(), None
        except Exception as exc:  # noqa: BLE001
            models, error = [], f"{type(exc).__name__}: {exc}"
        finally:
            client.close()
        return {
            "ok": True,
            "ollama": {"reachable": error is None, "error": error, "models": models},
        }

    @app.get("/api/options")
    def options() -> dict[str, Any]:
        return {
            "voices": VOICES,
            "source_languages": SOURCE_LANGS,
            "target_language": "sk",
            "default_voice": settings.tts_voice,
            "default_llm": settings.translation_model,
            "stages": STAGES,
            "max_upload_mb": settings.max_upload_mb,
        }

    # ----- projects ----------------------------------------------------------------------
    @app.get("/api/projects")
    def list_projects() -> list[ProjectOut]:
        return [project_out(r) for r in db.list_projects()]

    @app.post("/api/projects", status_code=201)
    async def create_project(
        file: Annotated[UploadFile, File()],
        name: Annotated[str, Form()] = "",
        source_lang: Annotated[str, Form()] = "en",
        voice: Annotated[str, Form()] = "",
        llm_model: Annotated[str, Form()] = "",
        original_audio: Annotated[Literal["duck", "mute"], Form()] = "duck",
        keep_original_track: Annotated[bool, Form()] = True,
        start: Annotated[bool, Form()] = True,
    ) -> ProjectOut:
        filename = safe_filename(file.filename or "video.mp4")
        if Path(filename).suffix.lower() not in ALLOWED_SUFFIXES:
            raise HTTPException(
                415, f"Unsupported file type; use one of {sorted(ALLOWED_SUFFIXES)}"
            )
        if source_lang not in SOURCE_LANGS:
            raise HTTPException(422, f"Unsupported source language '{source_lang}'")
        voice = voice or settings.tts_voice
        if voice not in VOICES:
            raise HTTPException(422, f"Unknown voice '{voice}'")

        pid = db.create_project(
            name=name.strip() or Path(filename).stem,
            original_name=filename,
            input_rel=f"input/{filename}",
            duration=0.0,
            source_lang=source_lang,
            voice=voice,
            llm_model=llm_model.strip() or settings.translation_model,
            original_audio=original_audio,
            keep_original_track=int(keep_original_track),
        )
        pdir = project_dir(pid)
        dest = pdir / "input" / filename
        dest.parent.mkdir(parents=True, exist_ok=True)
        limit = settings.max_upload_mb * 1024 * 1024
        written = 0
        try:
            with dest.open("wb") as fh:
                while chunk := await file.read(1024 * 1024):
                    written += len(chunk)
                    if written > limit:
                        raise HTTPException(413, f"File exceeds {settings.max_upload_mb} MB")
                    fh.write(chunk)
            info = await asyncio.to_thread(
                FFmpeg(settings.ffmpeg_path, settings.ffprobe_path).probe, dest
            )
            if not info.video_streams or not info.audio_streams:
                raise HTTPException(422, "The file needs both a video and an audio stream")
            db.update_project(pid, duration=info.duration)
        except (HTTPException, MediaError) as exc:
            db.delete_project(pid)
            shutil.rmtree(pdir, ignore_errors=True)
            if isinstance(exc, MediaError):
                raise HTTPException(422, f"Not a readable media file: {exc}") from exc
            raise
        except BaseException:
            db.delete_project(pid)
            shutil.rmtree(pdir, ignore_errors=True)
            raise
        if start:
            jobs.submit(pid)
        return project_out(require_project(pid))

    @app.get("/api/projects/{pid}")
    def get_project(pid: int) -> ProjectOut:
        return project_out(require_project(pid))

    @app.patch("/api/projects/{pid}")
    def patch_project(pid: int, patch: ProjectPatch) -> ProjectOut:
        require_project(pid)
        if db.active_job(pid):
            raise HTTPException(409, "Cannot change settings while a job is queued or running")
        fields = patch.model_dump(exclude_none=True)
        if "voice" in fields and fields["voice"] not in VOICES:
            raise HTTPException(422, f"Unknown voice '{fields['voice']}'")
        if "keep_original_track" in fields:
            fields["keep_original_track"] = int(fields["keep_original_track"])
        if fields:
            db.update_project(pid, **fields)
        return project_out(require_project(pid))

    @app.delete("/api/projects/{pid}", status_code=204)
    def delete_project(pid: int) -> None:
        require_project(pid)
        active = db.active_job(pid)
        if active:
            jobs.cancel(active["id"])
        db.delete_project(pid)
        shutil.rmtree(project_dir(pid), ignore_errors=True)

    # ----- jobs --------------------------------------------------------------------------
    @app.post("/api/projects/{pid}/jobs", status_code=201)
    def start_job(pid: int, req: JobRequest | None = None) -> dict[str, Any]:
        require_project(pid)
        if db.active_job(pid):
            raise HTTPException(409, "A job is already queued or running for this project")
        job_id = jobs.submit(pid, req.from_stage if req else None)
        return job_out(db.get_job(job_id)) or {}

    @app.get("/api/projects/{pid}/jobs")
    def project_jobs(pid: int) -> list[dict[str, Any]]:
        require_project(pid)
        return [j for j in (job_out(x) for x in db.list_jobs(pid)) if j]

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: int) -> dict[str, Any]:
        job = db.get_job(job_id)
        if job is None:
            raise HTTPException(404, "Job not found")
        return job_out(job) or {}

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel_job(job_id: int) -> dict[str, Any]:
        if db.get_job(job_id) is None:
            raise HTTPException(404, "Job not found")
        if not jobs.cancel(job_id):
            raise HTTPException(409, "Job is not queued or running")
        return job_out(db.get_job(job_id)) or {}

    @app.get("/api/jobs/{job_id}/events")
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

    @app.get("/api/jobs/{job_id}/log")
    def job_log(job_id: int, tail: int = 200) -> dict[str, Any]:
        if db.get_job(job_id) is None:
            raise HTTPException(404, "Job not found")
        path = settings.data_dir / "logs" / f"job-{job_id}.log"
        lines = (
            path.read_text(encoding="utf-8", errors="replace").splitlines()
            if path.is_file()
            else []
        )
        return {"lines": lines[-max(1, min(tail, 2000)) :]}

    # ----- results -----------------------------------------------------------------------
    @app.get("/api/projects/{pid}/segments")
    def segments(pid: int) -> dict[str, Any]:
        require_project(pid)
        wd = project_dir(pid) / "work"
        for name in SEGMENT_FILES:
            path = wd / name
            if path.is_file():
                data = json.loads(path.read_text(encoding="utf-8"))
                keep = ("id", "start", "end", "source_text", "translated_text", "fit_status")
                return {
                    "stage": name.removesuffix(".json"),
                    "segments": [{k: s.get(k) for k in keep} for s in data["segments"]],
                }
        return {"stage": None, "segments": []}

    @app.get("/api/projects/{pid}/files/{kind}")
    def download(
        pid: int, kind: Literal["video", "srt", "srt_en"], inline: bool = False
    ) -> FileResponse:
        project = require_project(pid)
        path = output_paths(project)[kind]
        if not path.is_file():
            raise HTTPException(404, "Not generated yet")
        media = {
            "video": "video/mp4",
            "srt": "application/x-subrip",
            "srt_en": "application/x-subrip",
        }
        return FileResponse(
            path,
            media_type=media[kind],
            filename=path.name,
            content_disposition_type="inline" if inline else "attachment",
        )

    @app.get("/api/projects/{pid}/source")
    def source_video(pid: int) -> FileResponse:
        project = require_project(pid)
        path = project_dir(pid) / project["input_rel"]
        return FileResponse(path, filename=path.name, content_disposition_type="inline")

    dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if dist.is_dir():
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
    return app

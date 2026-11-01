"""Projects: list, create from a file or a YouTube link, change settings, delete."""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from localdub.api.common import (
    ALLOWED_SUFFIXES,
    CLONE_CONSENT_MESSAGE,
    SOURCE_LANGS,
    AppContext,
    FromYoutube,
    OriginalAudioChoice,
    ProjectOut,
    ProjectPatch,
    YoutubeInfoRequest,
    safe_filename,
)
from localdub.core.media.ffmpeg import FFmpeg, MediaError
from localdub.core.tts.base import VOICES
from localdub.core.youtube import tools as youtube_tools
from localdub.core.youtube import ytdlp


def youtube_error(exc: ytdlp.YoutubeError) -> HTTPException:
    status = 409 if exc.code == "missing_tools" else 422
    return HTTPException(status, str(exc))


def build(ctx: AppContext) -> APIRouter:
    router = APIRouter()
    settings, db, jobs = ctx.settings, ctx.db, ctx.jobs

    @router.get("/api/projects")
    def list_projects() -> list[ProjectOut]:
        return [ctx.project_out(r) for r in db.list_projects()]

    @router.post("/api/projects", status_code=201)
    async def create_project(
        file: Annotated[UploadFile, File()],
        name: Annotated[str, Form()] = "",
        source_lang: Annotated[str, Form()] = "en",
        voice: Annotated[str, Form()] = "",
        llm_model: Annotated[str, Form()] = "",
        asr_id: Annotated[str, Form()] = "",
        original_audio: Annotated[OriginalAudioChoice, Form()] = "duck",
        keep_original_track: Annotated[bool, Form()] = True,
        diarize: Annotated[bool, Form()] = False,
        clone_voice: Annotated[bool, Form()] = False,
        clone_consent: Annotated[bool, Form()] = False,
        num_speakers: Annotated[int | None, Form(ge=1, le=10)] = None,
        start: Annotated[bool, Form()] = True,
    ) -> ProjectOut:
        filename = safe_filename(file.filename or "video.mp4")
        if Path(filename).suffix.lower() not in ALLOWED_SUFFIXES:
            raise HTTPException(
                415, f"Unsupported file type; use one of {sorted(ALLOWED_SUFFIXES)}"
            )
        if source_lang not in SOURCE_LANGS:
            raise HTTPException(422, f"Unsupported source language '{source_lang}'")
        ctx.check_language(ctx.asr_choice(asr_id), source_lang)
        if start:
            await asyncio.to_thread(
                ctx.require_models, ctx.asr_choice(asr_id), llm_model.strip() or None
            )
        voice = voice or settings.tts_voice
        if voice not in VOICES:
            raise HTTPException(422, f"Unknown voice '{voice}'")
        if clone_voice and not clone_consent:
            raise HTTPException(422, CLONE_CONSENT_MESSAGE)
        pid = db.create_project(
            name=name.strip() or Path(filename).stem,
            original_name=filename,
            input_rel=f"input/{filename}",
            duration=0.0,
            source_lang=source_lang,
            voice=voice,
            llm_model=llm_model.strip() or ctx.default_llm(),
            asr_id=ctx.asr_choice(asr_id),
            original_audio=original_audio,
            keep_original_track=int(keep_original_track),
            diarize=int(diarize),
            clone_voice=int(clone_voice),
            num_speakers=num_speakers,
        )
        pdir = ctx.project_dir(pid)
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
        return ctx.project_out(ctx.require_project(pid))

    # ----- YouTube import ----------------------------------------------------------------
    @router.get("/api/youtube/status")
    async def youtube_status() -> dict[str, Any]:
        st = await asyncio.to_thread(youtube_tools.status)

        def row(info: youtube_tools.ToolInfo) -> dict[str, Any]:
            return {"available": info.available, "version": info.version, "error": info.error}

        return {
            "installed": all(i.available for i in st.values()),
            "yt_dlp": row(st["yt_dlp"]),
            "deno": row(st["deno"]),
            "qualities": list(ytdlp.QUALITIES),
            "browsers": list(ytdlp.COOKIE_BROWSERS),
        }

    @router.post("/api/youtube/info")
    async def youtube_info(req: YoutubeInfoRequest) -> dict[str, Any]:
        try:
            url = ytdlp.validate_youtube_url(req.url)
            ytdlp.validate_options("auto", req.cookies_browser)
            info = await asyncio.to_thread(ytdlp.fetch_info, url, req.cookies_browser)
        except ytdlp.YoutubeError as exc:
            raise youtube_error(exc) from exc
        return {
            "id": info.id,
            "title": info.title,
            "uploader": info.uploader,
            "thumbnail": info.thumbnail,
            "duration": info.duration,
            "is_live": info.is_live,
        }

    @router.post("/api/youtube/update")
    async def youtube_update() -> dict[str, str]:
        if db.any_active():
            raise HTTPException(409, "Wait for the running dubbing job to finish before updating.")
        try:
            text = await asyncio.to_thread(youtube_tools.update_ytdlp)
        except youtube_tools.ToolsError as exc:
            raise HTTPException(502, str(exc)) from exc
        return {"message": text}

    @router.post("/api/projects/from-youtube", status_code=201)
    async def create_from_youtube(body: FromYoutube) -> ProjectOut:
        try:
            url = ytdlp.validate_youtube_url(body.url)
            ytdlp.validate_options(body.quality, body.cookies_browser)
        except ytdlp.YoutubeError as exc:
            raise youtube_error(exc) from exc
        if body.source_lang not in SOURCE_LANGS:
            raise HTTPException(422, f"Unsupported source language '{body.source_lang}'")
        voice = body.voice or settings.tts_voice
        if voice not in VOICES:
            raise HTTPException(422, f"Unknown voice '{voice}'")
        if body.clone_voice and not body.clone_consent:
            raise HTTPException(422, CLONE_CONSENT_MESSAGE)
        ctx.check_language(ctx.asr_choice(body.asr_id), body.source_lang)
        if body.start:
            await asyncio.to_thread(
                ctx.require_models, ctx.asr_choice(body.asr_id), body.llm_model.strip() or None
            )
        try:  # also proves the link works before anything is created
            info = await asyncio.to_thread(ytdlp.fetch_info, url, body.cookies_browser)
        except ytdlp.YoutubeError as exc:
            raise youtube_error(exc) from exc
        if info.is_live:
            raise HTTPException(422, "Live streams cannot be dubbed. Use a finished video.")
        if info.duration and info.duration > ytdlp.MAX_DURATION_S:
            raise HTTPException(422, "This video is longer than 4 hours.")
        pid = db.create_project(
            name=info.title[:200],
            original_name=info.title[:200],
            input_rel="input/source.mp4",
            duration=float(info.duration or 0.0),
            source_lang=body.source_lang,
            voice=voice,
            llm_model=body.llm_model.strip() or ctx.default_llm(),
            asr_id=ctx.asr_choice(body.asr_id),
            original_audio=body.original_audio,
            keep_original_track=int(body.keep_original_track),
            diarize=int(body.diarize),
            clone_voice=int(body.clone_voice),
            num_speakers=body.num_speakers,
            source_url=url,
            download_quality=body.quality,
            cookies_browser=body.cookies_browser,
        )
        (ctx.project_dir(pid) / "input").mkdir(parents=True, exist_ok=True)
        if body.start:
            jobs.submit(pid)
        return ctx.project_out(ctx.require_project(pid))

    # ----- one project -------------------------------------------------------------------
    @router.get("/api/projects/{pid}")
    def get_project(pid: int) -> ProjectOut:
        return ctx.project_out(ctx.require_project(pid))

    @router.patch("/api/projects/{pid}")
    def patch_project(pid: int, patch: ProjectPatch) -> ProjectOut:
        project_row = ctx.require_project(pid)
        if db.active_job(pid):
            raise HTTPException(409, "Cannot change settings while a job is queued or running")
        fields = patch.model_dump(exclude_none=True)
        if "num_speakers" in patch.model_fields_set:
            fields["num_speakers"] = patch.num_speakers  # null = detect automatically
        if "asr_id" in fields:
            fields["asr_id"] = ctx.asr_choice(fields["asr_id"])
            ctx.check_language(fields["asr_id"], str(project_row["source_lang"]))
        if "voice" in fields and fields["voice"] not in VOICES:
            raise HTTPException(422, f"Unknown voice '{fields['voice']}'")
        fields.pop("clone_consent", None)
        if fields.get("clone_voice") and not patch.clone_consent:
            raise HTTPException(422, CLONE_CONSENT_MESSAGE)
        for flag in ("keep_original_track", "diarize", "clone_voice"):
            if flag in fields:
                fields[flag] = int(fields[flag])
        if fields.get("num_speakers") is not None and not 1 <= fields["num_speakers"] <= 10:
            raise HTTPException(422, "num_speakers must be between 1 and 10")
        if fields:
            db.update_project(pid, **fields)
        return ctx.project_out(ctx.require_project(pid))

    @router.delete("/api/projects/{pid}", status_code=204)
    def delete_project(pid: int) -> None:
        ctx.require_project(pid)
        active = db.active_job(pid)
        if active:
            jobs.cancel(active["id"])
        job_ids = [j["id"] for j in db.list_jobs(pid)]
        db.delete_project(pid)
        shutil.rmtree(ctx.project_dir(pid), ignore_errors=True)
        for job_id in job_ids:  # the job logs live outside the project folder
            for log_file in (settings.data_dir / "logs").glob(f"job-{job_id}.log*"):
                log_file.unlink(missing_ok=True)

    return router

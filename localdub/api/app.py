"""FastAPI application: projects, jobs, progress events, segments and downloads.

The server only listens on localhost by default; all media stays on this machine.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import re
import shutil
import threading
import unicodedata
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any, Literal

import soundfile as sf
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from localdub.api.db import Database
from localdub.api.jobs import JobManager
from localdub.config import Settings
from localdub.core.diarize.pitch import load_speaker_genders
from localdub.core.media.ffmpeg import FFmpeg, MediaError
from localdub.core.timeline.edits import (
    SegmentEdit,
    apply_edits,
    load_edits,
    save_edits,
    source_hash,
    validate_timing,
)
from localdub.core.timeline.fit import available_windows
from localdub.core.timeline.models import DialogueSegment, ReviewStatus
from localdub.core.translation.prompts import normalize_punctuation
from localdub.core.tts.base import VOICES, default_speaker_voices
from localdub.pipeline import STAGES, default_providers

log = logging.getLogger(__name__)

ALLOWED_SUFFIXES = {".mp4", ".m4v", ".mov", ".mkv"}
SOURCE_LANGS = {"en": "English", "auto": "Auto-detect"}
SEGMENT_FILES = ["segments.json", "tts.json", "translation.json", "dialogue.json", "asr.json"]
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
    diarize: bool = False
    num_speakers: int | None = None
    created_at: float
    latest_job: dict[str, Any] | None = None
    has_output: bool = False


class ProjectPatch(BaseModel):
    name: str | None = None
    voice: str | None = None
    llm_model: str | None = None
    original_audio: Literal["duck", "mute"] | None = None
    keep_original_track: bool | None = None
    diarize: bool | None = None
    num_speakers: int | None = None


class JobRequest(BaseModel):
    from_stage: (
        Literal["probe", "extract", "asr", "diarize", "translate", "tts", "assemble", "export"]
        | None
    ) = None


class SegmentPatch(BaseModel):
    """Only fields present in the request are changed; sending null clears that field's edit."""

    translated_text: str | None = None
    voice_id: str | None = None
    start: float | None = None
    end: float | None = None
    review_status: Literal["pending", "edited", "approved"] | None = None


class SpeakerVoices(BaseModel):
    voices: dict[str, str]


class PreviewRequest(BaseModel):
    text: str | None = None
    voice: str | None = None


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
        if app.state.preview_tts is not None:
            app.state.preview_tts.close()

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
        diarize: Annotated[bool, Form()] = False,
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
            diarize=int(diarize),
            num_speakers=num_speakers,
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
        if "num_speakers" in patch.model_fields_set:
            fields["num_speakers"] = patch.num_speakers  # null = detect automatically
        if "voice" in fields and fields["voice"] not in VOICES:
            raise HTTPException(422, f"Unknown voice '{fields['voice']}'")
        for flag in ("keep_original_track", "diarize"):
            if flag in fields:
                fields[flag] = int(fields[flag])
        if fields.get("num_speakers") is not None and not 1 <= fields["num_speakers"] <= 10:
            raise HTTPException(422, "num_speakers must be between 1 and 10")
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

    # ----- segments and edits ------------------------------------------------------------
    def base_segments(pid: int) -> tuple[str | None, list[DialogueSegment]]:
        wd = project_dir(pid) / "work"
        for name in SEGMENT_FILES:
            path = wd / name
            if path.is_file():
                data = json.loads(path.read_text(encoding="utf-8"))
                return name.removesuffix(".json"), [
                    DialogueSegment.model_validate(x) for x in data["segments"]
                ]
        return None, []

    def segment_view(pid: int) -> dict[str, Any]:
        wd = project_dir(pid) / "work"
        stage, segs = base_segments(pid)
        edits = load_edits(wd / "edits.json")
        report = apply_edits(segs, edits)
        project = db.get_project(pid)
        speakers = list(dict.fromkeys(x.speaker_id for x in segs))
        defaults = default_speaker_voices(
            speakers,
            project["voice"] if project else "F1",
            load_speaker_genders(wd / "diarization.json"),
        )
        tts_json = wd / "tts.json"
        pending = (
            tts_json.is_file()
            and (wd / "edits.json").is_file()
            and (wd / "edits.json").stat().st_mtime > tts_json.stat().st_mtime
        )

        def own_voice(seg_id: int) -> str | None:
            e = edits.segments.get(seg_id)
            return e.voice_id if e and seg_id in report["applied"] else None

        rows = []
        for seg in segs:
            clip = wd / seg.audio_path if seg.audio_path else None
            rows.append(
                {
                    "id": seg.id,
                    "start": seg.start,
                    "end": seg.end,
                    "source_text": seg.source_text,
                    "translated_text": seg.translated_text,
                    "fit_status": seg.fit_status.value if stage in ("tts", "segments") else None,
                    "speaker_id": seg.speaker_id,
                    "voice_id": own_voice(seg.id),
                    "effective_voice": seg.voice_id or defaults.get(seg.speaker_id),
                    "review_status": seg.review_status.value,
                    "edited": seg.id in report["applied"],
                    "stale_edit": seg.id in report["stale"],
                    "has_audio": bool(clip and clip.is_file()),
                }
            )
        return {
            "stage": stage,
            "segments": rows,
            "edits_pending": pending,
            "speaker_voices": edits.speaker_voices,
            "speaker_defaults": defaults,
            "speaker_gender_estimate": load_speaker_genders(wd / "diarization.json"),
        }

    def require_editable(pid: int) -> tuple[Path, list[DialogueSegment]]:
        require_project(pid)
        if db.active_job(pid):
            raise HTTPException(409, "Cannot edit while a job is queued or running")
        stage, segs = base_segments(pid)
        if stage in (None, "asr"):
            raise HTTPException(409, "Nothing to edit yet: translation has not finished")
        return project_dir(pid) / "work" / "edits.json", segs

    @app.get("/api/projects/{pid}/segments")
    def segments(pid: int) -> dict[str, Any]:
        require_project(pid)
        return segment_view(pid)

    @app.patch("/api/projects/{pid}/segments/{sid}")
    def patch_segment(pid: int, sid: int, patch: SegmentPatch) -> dict[str, Any]:
        project = require_project(pid)
        edits_path, base = require_editable(pid)
        seg = next((x for x in base if x.id == sid), None)
        if seg is None:
            raise HTTPException(404, "Segment not found")
        edits = load_edits(edits_path)
        edit = edits.segments.get(sid)
        if edit is None or edit.source_hash != source_hash(seg.source_text):
            edit = SegmentEdit(source_hash=source_hash(seg.source_text))
        sent = patch.model_fields_set
        if "translated_text" in sent:
            text = (patch.translated_text or "").strip()
            if len(text) > 600:
                raise HTTPException(422, "Translation is too long (max 600 characters)")
            edit.translated_text = text if patch.translated_text is not None else None
        if "voice_id" in sent:
            if patch.voice_id is not None and patch.voice_id not in VOICES:
                raise HTTPException(422, f"Unknown voice '{patch.voice_id}'")
            edit.voice_id = patch.voice_id
        if "review_status" in sent:
            edit.review_status = ReviewStatus(patch.review_status) if patch.review_status else None
        if "start" in sent or "end" in sent:
            effective = [x.model_copy(deep=True) for x in base]
            apply_edits(effective, edits)
            idx = next(i for i, x in enumerate(effective) if x.id == sid)
            cur = effective[idx]
            # A sent null reverts that boundary to the original recognised time.
            start = (
                cur.start
                if "start" not in sent
                else (patch.start if patch.start is not None else seg.start)
            )
            end = (
                cur.end if "end" not in sent else (patch.end if patch.end is not None else seg.end)
            )
            err = validate_timing(
                start,
                end,
                project["duration"],
                (
                    effective[idx - 1].end if idx > 0 else None,
                    effective[idx + 1].start if idx + 1 < len(effective) else None,
                ),
            )
            if err:
                raise HTTPException(422, err)
            edit.start = None if start == seg.start else round(start, 3)
            edit.end = None if end == seg.end else round(end, 3)
        edits.segments[sid] = edit
        save_edits(edits_path, edits)
        view = segment_view(pid)
        row: dict[str, Any] = next(r for r in view["segments"] if r["id"] == sid)
        return row | {"edits_pending": view["edits_pending"]}

    @app.delete("/api/projects/{pid}/segments/{sid}/edit", status_code=204)
    def revert_segment(pid: int, sid: int) -> None:
        edits_path, _ = require_editable(pid)
        edits = load_edits(edits_path)
        edits.segments.pop(sid, None)
        save_edits(edits_path, edits)

    @app.put("/api/projects/{pid}/speakers")
    def set_speaker_voices(pid: int, body: SpeakerVoices) -> dict[str, Any]:
        edits_path, _ = require_editable(pid)
        bad = [v for v in body.voices.values() if v not in VOICES]
        if bad:
            raise HTTPException(422, f"Unknown voice(s): {bad}")
        edits = load_edits(edits_path)
        edits.speaker_voices = dict(body.voices)
        save_edits(edits_path, edits)
        return segment_view(pid)

    @app.get("/api/projects/{pid}/segments/{sid}/audio")
    def segment_audio(pid: int, sid: int) -> FileResponse:
        require_project(pid)
        wd = project_dir(pid) / "work"
        tts_json = wd / "tts.json"
        if not tts_json.is_file():
            raise HTTPException(404, "No audio generated yet")
        data = json.loads(tts_json.read_text(encoding="utf-8"))
        rel = next((x.get("audio_path") for x in data["segments"] if x["id"] == sid), None)
        path = wd / rel if rel else None
        if path is None or not path.is_file():
            raise HTTPException(404, "No audio for this segment")
        return FileResponse(path, media_type="audio/wav", content_disposition_type="inline")

    preview_lock = threading.Lock()
    app.state.preview_tts = None

    def synth_preview(text: str, voice: str, window: float | None) -> tuple[bytes, float]:
        with preview_lock:
            if app.state.preview_tts is None:
                app.state.preview_tts = default_providers(settings).tts()
            tts = app.state.preview_tts
            text = normalize_punctuation(text).strip()
            bad = tts.unsupported_chars(text)
            if bad:
                text = " ".join("".join(c for c in text if c not in bad).split())
            if not text:
                raise HTTPException(422, "Nothing to say: the text is empty")
            speed = settings.tts_base_speed
            wav = tts.synthesize(text, voice=voice, lang="sk", speed=speed)
            dur = wav.size / tts.sample_rate
            if window is not None and dur > window:
                factor = min(dur / window * 1.02, settings.max_speed / speed)
                wav = tts.synthesize(text, voice=voice, lang="sk", speed=speed * factor)
                dur = wav.size / tts.sample_rate
            buf = io.BytesIO()
            sf.write(buf, wav, tts.sample_rate, format="WAV", subtype="PCM_16")
            return buf.getvalue(), dur

    @app.post("/api/projects/{pid}/segments/{sid}/preview")
    async def preview_segment(pid: int, sid: int, req: PreviewRequest) -> Response:
        project = require_project(pid)
        view = await asyncio.to_thread(segment_view, pid)
        rows = view["segments"]
        row = next((r for r in rows if r["id"] == sid), None)
        if row is None:
            raise HTTPException(404, "Segment not found")
        voice = req.voice or row["voice_id"] or settings.tts_voice
        if voice not in VOICES:
            raise HTTPException(422, f"Unknown voice '{voice}'")
        text = req.text if req.text is not None else row["translated_text"]
        segs = [
            DialogueSegment(id=r["id"], start=r["start"], end=r["end"], source_text="")
            for r in rows
        ]
        window = available_windows(segs, project["duration"], settings.segment_gap_s)[
            rows.index(row)
        ]
        data, dur = await asyncio.to_thread(synth_preview, text, voice, window)
        return Response(
            data,
            media_type="audio/wav",
            headers={"X-Audio-Duration": f"{dur:.3f}", "X-Window": f"{window:.3f}"},
        )

    # ----- results -----------------------------------------------------------------------
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

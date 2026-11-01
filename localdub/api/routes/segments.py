"""The timeline editor: segments and their edits, waveforms, clips, previews and voice samples."""

from __future__ import annotations

import asyncio
import io
import json
import threading
from pathlib import Path
from typing import Any, Literal

import soundfile as sf
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, Response

from localdub.api.common import (
    SEGMENT_FILES,
    VOICE_SAMPLE_TEXT,
    AppContext,
    PreviewRequest,
    SegmentPatch,
    SpeakerVoices,
)
from localdub.core.audio.waveform import peaks_payload
from localdub.core.diarize.pitch import load_speaker_genders
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
from localdub.pipeline import default_providers


def build(ctx: AppContext) -> APIRouter:
    router = APIRouter()
    settings, db = ctx.settings, ctx.db
    require_project, project_dir = ctx.require_project, ctx.project_dir

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
                    # where the generated Slovak speech actually sits (can differ from the window)
                    "placed_start": seg.placed_start,
                    "audio_duration": seg.audio_duration if clip and clip.is_file() else None,
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

    @router.get("/api/projects/{pid}/waveform")
    async def waveform(pid: int, kind: Literal["original", "dub"] = "original") -> dict[str, Any]:
        """Peak overview of the original or the dubbed audio for the timeline (cached on disk)."""
        require_project(pid)
        wd = project_dir(pid) / "work"
        source = wd / ("audio_orig.wav" if kind == "original" else "dub.wav")
        if not source.is_file():
            return {"available": False}
        cache = wd / f"waveform-{kind}.json"
        if cache.is_file() and cache.stat().st_mtime >= source.stat().st_mtime:
            cached: dict[str, Any] = json.loads(cache.read_text(encoding="utf-8"))
            return cached
        payload = await asyncio.to_thread(peaks_payload, source)
        cache.write_text(json.dumps(payload), encoding="utf-8")
        return payload

    @router.get("/api/projects/{pid}/segments")
    def segments(pid: int) -> dict[str, Any]:
        require_project(pid)
        return segment_view(pid)

    @router.patch("/api/projects/{pid}/segments/{sid}")
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

    @router.delete("/api/projects/{pid}/segments/{sid}/edit", status_code=204)
    def revert_segment(pid: int, sid: int) -> None:
        edits_path, _ = require_editable(pid)
        edits = load_edits(edits_path)
        edits.segments.pop(sid, None)
        save_edits(edits_path, edits)

    @router.put("/api/projects/{pid}/speakers")
    def set_speaker_voices(pid: int, body: SpeakerVoices) -> dict[str, Any]:
        edits_path, _ = require_editable(pid)
        bad = [v for v in body.voices.values() if v not in VOICES]
        if bad:
            raise HTTPException(422, f"Unknown voice(s): {bad}")
        edits = load_edits(edits_path)
        edits.speaker_voices = dict(body.voices)
        save_edits(edits_path, edits)
        return segment_view(pid)

    @router.get("/api/projects/{pid}/segments/{sid}/audio")
    def segment_audio(pid: int, sid: int) -> FileResponse:
        require_project(pid)
        wd = project_dir(pid) / "work"
        tts_json = wd / "tts.json"
        if not tts_json.is_file():
            raise HTTPException(404, "No audio generated yet")
        data = json.loads(tts_json.read_text(encoding="utf-8"))
        voiced = wd / "voiced.json"
        if voiced.is_file():  # the version that is actually mixed (voice-cloned if enabled)
            data = json.loads(voiced.read_text(encoding="utf-8"))
        rel = next((x.get("audio_path") for x in data["segments"] if x["id"] == sid), None)
        path = wd / rel if rel else None
        if path is None or not path.is_file():
            raise HTTPException(404, "No audio for this segment")
        return FileResponse(path, media_type="audio/wav", content_disposition_type="inline")

    # ----- speech made on the spot: previews and voice samples ---------------------------------
    preview_lock = threading.Lock()
    voice_samples: dict[str, bytes] = {}

    def synth_preview(text: str, voice: str, window: float | None) -> tuple[bytes, float]:
        with preview_lock:
            if ctx.preview_tts is None:
                ctx.preview_tts = default_providers(settings).tts()
            tts = ctx.preview_tts
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

    @router.get("/api/voices/{voice}/sample")
    async def voice_sample(voice: str) -> Response:
        """A short Slovak sentence in this voice, so you can choose by ear (made once per voice)."""
        if voice not in VOICES:
            raise HTTPException(404, "Unknown voice")
        if voice not in voice_samples:
            tts_model = ctx.mgr.catalog.default_of("tts")
            if tts_model is not None and not await asyncio.to_thread(
                ctx.model_installed, tts_model.id
            ):
                raise HTTPException(
                    409, "Download the Slovak voice on the AI models page to hear the samples."
                )
            data, _ = await asyncio.to_thread(synth_preview, VOICE_SAMPLE_TEXT, voice, None)
            voice_samples[voice] = data
        return Response(voice_samples[voice], media_type="audio/wav")

    @router.post("/api/projects/{pid}/segments/{sid}/preview")
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

    return router

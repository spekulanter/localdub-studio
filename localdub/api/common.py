"""What the route modules share: constants, request/response models and the application context."""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Any, Literal

from fastapi import HTTPException
from pydantic import BaseModel, Field

from localdub import extras
from localdub.api.db import Database
from localdub.api.jobs import JobManager
from localdub.config import Settings
from localdub.core import usersettings
from localdub.core.modelmgr.manager import ModelManager

ALLOWED_SUFFIXES = {".mp4", ".m4v", ".mov", ".mkv"}
SOURCE_LANGS = {
    "en": "English", "de": "German", "it": "Italian", "es": "Spanish", "ja": "Japanese",
    "zh": "Chinese", "ru": "Russian", "uk": "Ukrainian", "pl": "Polish", "hu": "Hungarian",
    "auto": "Auto-detect",
}  # fmt: skip
SEGMENT_FILES = [
    "segments.json",
    "voiced.json",
    "tts.json",
    "translation.json",
    "dialogue.json",
    "asr.json",
]
VOICE_SAMPLE_TEXT = "Dobrý deň, toto je ukážka môjho hlasu. Takto bude znieť vaše dabovanie."
CLONE_CONSENT_MESSAGE = "Voice cloning needs your confirmation that you may imitate these voices"
_BAD_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

OriginalAudioChoice = Literal["duck", "mute", "background"]


class ProjectOut(BaseModel):
    id: int
    name: str
    original_name: str
    duration: float
    source_lang: str
    voice: str
    llm_model: str
    asr_id: str = "whisper-large-v3"
    original_audio: OriginalAudioChoice
    keep_original_track: bool
    diarize: bool = False
    clone_voice: bool = False
    num_speakers: int | None = None
    source_url: str | None = None
    download_quality: str = "auto"
    has_input: bool = True
    created_at: float
    latest_job: dict[str, Any] | None = None
    has_output: bool = False


class InstallBody(BaseModel):
    force: bool = False


class SettingsPatch(BaseModel):
    max_upload_mb: int | None


class ProjectPatch(BaseModel):
    name: str | None = None
    voice: str | None = None
    llm_model: str | None = None
    asr_id: str | None = None
    original_audio: OriginalAudioChoice | None = None
    keep_original_track: bool | None = None
    diarize: bool | None = None
    clone_voice: bool | None = None
    clone_consent: bool = False
    num_speakers: int | None = None


class JobRequest(BaseModel):
    from_stage: (
        Literal[
            "probe",
            "extract",
            "asr",
            "diarize",
            "translate",
            "tts",
            "separate",
            "convert",
            "assemble",
            "export",
        ]
        | None
    ) = None


class SegmentPatch(BaseModel):
    """Only fields present in the request are changed; sending null clears that field's edit."""

    translated_text: str | None = None
    voice_id: str | None = None
    start: float | None = None
    end: float | None = None
    review_status: Literal["pending", "edited", "approved"] | None = None


class YoutubeInfoRequest(BaseModel):
    url: str
    cookies_browser: str = "none"


class FromYoutube(BaseModel):
    """Create a project from a YouTube link (same dubbing options as an upload)."""

    url: str
    quality: str = "auto"
    cookies_browser: str = "none"
    source_lang: str = "en"
    voice: str = ""
    llm_model: str = ""
    asr_id: str = ""
    original_audio: OriginalAudioChoice = "duck"
    keep_original_track: bool = True
    diarize: bool = False
    num_speakers: int | None = Field(default=None, ge=1, le=10)
    clone_voice: bool = False
    clone_consent: bool = False
    start: bool = True


class SpeakerVoices(BaseModel):
    voices: dict[str, str]


class PreviewRequest(BaseModel):
    text: str | None = None
    voice: str | None = None


def separation_available() -> bool:
    """True when the optional PyTorch + Demucs packages are installed."""
    return extras.packages_available()


def safe_filename(name: str, fallback: str = "video.mp4") -> str:
    """Keep Unicode and spaces; drop path parts, control chars and Windows-reserved characters."""
    base = Path(name.replace("\\", "/")).name
    base = unicodedata.normalize("NFC", _BAD_CHARS.sub("_", base)).strip(" .")
    if len(base) > 120:
        stem, suffix = Path(base).stem[:100], Path(base).suffix
        base = stem + suffix
    return base or fallback


class AppContext:
    """The parts of the program every route needs, and the checks they all make."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.default_upload_mb = settings.max_upload_mb
        self.user_settings_path = settings.data_dir / "user-settings.json"
        stored = usersettings.load(self.user_settings_path)
        settings.max_upload_mb = stored.get("max_upload_mb", self.default_upload_mb)
        self.db = Database(settings.data_dir / "localdub.sqlite")
        self.jobs = JobManager(self.db, settings)
        self.mgr = ModelManager(settings, self.db.any_active)
        self.preview_tts: Any = None  # made on first use, closed when the server stops

    # ----- projects --------------------------------------------------------------------------
    def project_dir(self, pid: int) -> Path:
        return self.settings.data_dir / "projects" / str(pid)

    def require_project(self, pid: int) -> dict[str, Any]:
        row = self.db.get_project(pid)
        if row is None:
            raise HTTPException(404, "Project not found")
        return row

    def output_paths(self, project: dict[str, Any]) -> dict[str, Path]:
        stem = Path(project["input_rel"]).stem
        wd = self.project_dir(project["id"]) / "work"
        return {
            "video": wd / f"{stem}.sk.mp4",
            "srt": wd / f"{stem}.sk.srt",
            "srt_en": wd / f"{stem}.en.srt",
        }

    @staticmethod
    def job_out(job: dict[str, Any] | None) -> dict[str, Any] | None:
        if job is None:
            return None
        return {k: v for k, v in job.items() if k not in ("pid", "heartbeat")}

    def project_out(self, row: dict[str, Any]) -> ProjectOut:
        latest = self.db.list_jobs(row["id"])[:1]
        out = self.output_paths(row)
        done = bool(latest) and latest[0]["status"] == "done" and out["video"].is_file()
        return ProjectOut(
            **{k: v for k, v in row.items() if k not in ("input_rel",)},
            latest_job=self.job_out(latest[0]) if latest else None,
            has_output=done,
            has_input=(self.project_dir(row["id"]) / row["input_rel"]).is_file(),
        )

    # ----- models ----------------------------------------------------------------------------
    def default_llm(self) -> str:
        """The translation model new dubs start with: the user's pick, else the setting."""
        picked = self.mgr.state.selected("translation")
        entry = next((e for e in self.mgr.entries() if e.id == picked), None) if picked else None
        return str(entry.source["tag"]) if entry else self.settings.translation_model

    def check_language(self, asr_id: str, source_lang: str) -> None:
        """Some recognition models only know some languages: say so before a job is created."""
        entry = next((e for e in self.mgr.entries() if e.id == asr_id), None)
        if entry is not None and entry.source_langs and source_lang not in entry.source_langs:
            raise HTTPException(
                422,
                f"{entry.title} does not support '{source_lang}'. "
                "Pick another speech recognition model (for example Whisper large-v3).",
            )

    def asr_choice(self, requested: str) -> str:
        """The catalogue id for a new dub: the request, else the user's default model."""
        if requested:
            found = next(
                (e for e in self.mgr.entries() if e.id == requested and e.role == "asr"), None
            )
            if found is None:
                raise HTTPException(422, f"Unknown speech recognition model '{requested}'")
            return requested
        default = self.mgr.default_entry("asr")
        return default.id if default else self.settings.asr_id

    def require_models(self, asr_id: str | None = None, llm_model: str | None = None) -> None:
        if self.mgr.installing("packages"):
            raise HTTPException(
                409, "The optional packages are being installed. Wait until that has finished."
            )
        if not self.settings.require_models_before_jobs:
            return
        missing = self.mgr.missing_for(asr_id, llm_model)
        if missing:
            what = "; ".join(missing)
            raise HTTPException(
                409, f"Models are missing: {what}. Download them first (Models page)."
            )

    def model_installed(self, entry_id: str) -> bool:
        e = self.mgr.get(entry_id)
        return self.mgr.handler(e).installed(e, self.mgr.ctx())

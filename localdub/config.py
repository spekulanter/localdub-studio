"""Application settings. Override with LOCALDUB_* environment variables or a .env file."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LOCALDUB_", env_file=".env", extra="ignore")

    # External tools. None means "look up on PATH".
    ffmpeg_path: Path | None = None
    ffprobe_path: Path | None = None

    models_dir: Path = REPO_ROOT / "models"
    work_dir: Path = REPO_ROOT / "work"
    # API server: project database, uploads and per-project work directories.
    data_dir: Path = REPO_ROOT / "data"
    api_host: str = "127.0.0.1"  # local only; never bind a public address by default
    api_port: int = 8765
    max_upload_mb: int = 4096
    max_job_attempts: int = 3

    # ASR
    asr_model: str = "large-v3"
    asr_device: str = "cuda"
    asr_compute_type: str = "float16"
    asr_beam_size: int = 5
    segment_min_s: float = 1.5
    segment_max_s: float = 8.0
    segment_max_gap_s: float = 0.6

    # Speaker diarization (optional, experimental). Threshold is used when the count is unknown.
    diarization_enabled: bool = False
    diarization_num_speakers: int | None = None
    diarization_threshold: float = 0.85

    # Translation (Ollama is local-only; the URL must point at a local server by default)
    ollama_url: str = "http://127.0.0.1:11434"
    translation_model: str = "translategemma:4b"
    translation_context_before: int = 2
    translation_context_after: int = 1
    # Slovak speech rate used to derive a per-segment character budget.
    chars_per_second: float = 17.0  # measured Supertonic sk rate: ~16 cps at 1.05x, ~19 at 1.25x

    # TTS
    tts_model: str = "supertonic-3"
    tts_voice: str = "F1"
    tts_steps: int = 8
    tts_base_speed: float = 1.05
    tts_threads: int | None = 4  # ONNX "auto" (all 24 logical cores) is 2.5x slower on i7-13700HX

    # Timing
    max_speed: float = 1.25
    segment_gap_s: float = 0.05
    sample_rate: int = 48000

    # Voice-over mix
    # "duck": original audio stays audible at duck_db under the dub (keeps music and effects).
    # "mute": the mix contains only the dub; the original is silent in the dubbed track.
    # "background": experimental; Demucs removes the original speech, music/effects stay.
    original_audio: Literal["duck", "mute", "background"] = "duck"
    # Also store the untouched original audio as a second (non-default) track in the MP4.
    keep_original_track: bool = True
    duck_db: float = -14.0
    duck_ramp_s: float = 0.15
    background_duck_db: float = -3.0  # music/effects under the dub in "background" mode
    dub_target_dbfs: float = -18.0
    # Raise or lower the whole dub so its integrated loudness (LUFS) is close to the original
    # audio's, within these bounds. Keeps the dub as audible as the speech it replaces.
    match_original_loudness: bool = True
    loudness_target_range_lufs: tuple[float, float] = (-23.0, -14.0)
    loudness_max_adjust_db: float = 8.0
    # The final mix is turned down (never up) if it is louder than this.
    max_mix_lufs: float = -14.0
    output_audio_bitrate: str = "192k"

    languages: dict[str, str] = Field(default_factory=lambda: {"en": "English", "sk": "Slovak"})


def get_settings() -> Settings:
    return Settings()

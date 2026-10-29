"""Application settings. Override with LOCALDUB_* environment variables or a .env file."""

from __future__ import annotations

from pathlib import Path

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

    # ASR
    asr_model: str = "large-v3"
    asr_device: str = "cuda"
    asr_compute_type: str = "float16"
    asr_beam_size: int = 5
    segment_min_s: float = 1.5
    segment_max_s: float = 8.0
    segment_max_gap_s: float = 0.6

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
    duck_db: float = -14.0
    duck_ramp_s: float = 0.15
    dub_target_dbfs: float = -18.0
    output_audio_bitrate: str = "192k"

    languages: dict[str, str] = Field(default_factory=lambda: {"en": "English", "sk": "Slovak"})


def get_settings() -> Settings:
    return Settings()

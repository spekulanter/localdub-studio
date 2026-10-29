"""Download the model weights the app needs, ahead of the first job.

Sources (all listed in docs/LICENSES.md): Hugging Face (faster-whisper large-v3, Supertonic 3 at
the revision pinned by the `supertonic` package), the sherpa-onnx GitHub release (diarization,
sha256-pinned) and the Demucs CDN (separation). Only data files are downloaded, never programs.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from localdub.config import Settings

log = logging.getLogger(__name__)
Say = Callable[[str], None]


def fetch_whisper(settings: Settings, say: Say) -> Path:
    from faster_whisper.utils import download_model

    cache = settings.models_dir / "whisper"
    say(f"Speech recognition model '{settings.asr_model}' (about 3 GB)...")
    path = Path(download_model(settings.asr_model, cache_dir=str(cache)))
    say(f"  ready: {path}")
    return path


def fetch_supertonic(settings: Settings, say: Say) -> None:
    from localdub.core.tts.supertonic_provider import SupertonicProvider

    say("Slovak voice model Supertonic 3 (about 400 MB)...")
    tts = SupertonicProvider(
        model_dir=settings.models_dir / settings.tts_model.replace("-", ""),
        threads=settings.tts_threads,
    )
    say(f"  ready ({len(tts.list_voices())} voices)")
    tts.close()


def fetch_diarization(settings: Settings, say: Say) -> None:
    from localdub.core.diarize.sherpa_diarizer import EMBEDDING, SEGMENTATION
    from localdub.core.models import ensure_model

    say("Speaker detection models (about 46 MB, checksum-verified)...")
    for model in (SEGMENTATION, EMBEDDING):
        ensure_model(model, settings.models_dir)
    say("  ready")


def fetch_separation(settings: Settings, say: Say) -> None:
    from localdub.core.separation.demucs_separator import DemucsSeparator

    say("Speech/music separation model htdemucs (about 80 MB)...")
    DemucsSeparator(settings.models_dir, device="cpu").close()
    say("  ready")


def fetch_models(
    settings: Settings, *, diarization: bool = False, separation: bool = False, say: Say = print
) -> None:
    fetch_whisper(settings, say)
    fetch_supertonic(settings, say)
    if diarization:
        fetch_diarization(settings, say)
    if separation:
        fetch_separation(settings, say)

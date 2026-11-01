"""Download the model weights the app needs, ahead of the first job.

Sources (all listed in docs/LICENSES.md): Hugging Face (faster-whisper large-v3, Supertonic 3 at
the revision pinned by the `supertonic` package), the sherpa-onnx GitHub release (diarization,
sha256-pinned) and the Demucs CDN (separation). Only data files are downloaded, never programs.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Callable
from pathlib import Path

from localdub.config import Settings

log = logging.getLogger(__name__)
Say = Callable[[str], None]


def fetch_whisper(settings: Settings, say: Say) -> Path:
    if sys.platform == "darwin":  # the MLX Whisper of the catalogue instead of faster-whisper
        from localdub.core.modelmgr.catalog import load_catalog
        from localdub.core.modelmgr.handlers import HANDLERS, Ctx

        entry = load_catalog().entry(settings.asr_id)
        if entry is None or entry.source["type"] != "mlx-whisper":
            raise SystemExit(f"'{settings.asr_id}' is not a speech model for this Mac")
        say(f"Speech recognition model '{entry.title}' (about {entry.size_bytes / 1e9:.1f} GB)...")
        HANDLERS["mlx-whisper"].download(entry, Ctx(settings), lambda *_: None)
        path = settings.models_dir / "whisper"
        say(f"  ready: {path}")
        return path
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


def fetch_voice_cloning(settings: Settings, say: Say) -> None:
    from localdub.core.voice.openvoice_converter import OpenVoiceConverter

    say("Voice cloning model OpenVoice V2 converter (about 130 MB)...")
    OpenVoiceConverter(settings.models_dir, device="cpu").close()
    say("  ready")


def fetch_models(
    settings: Settings, *, diarization: bool = False, experimental: bool = False, say: Say = print
) -> None:
    fetch_whisper(settings, say)
    fetch_supertonic(settings, say)
    if diarization:
        fetch_diarization(settings, say)
    if experimental:
        fetch_separation(settings, say)
        fetch_voice_cloning(settings, say)


if __name__ == "__main__":
    # `python -m localdub.core.model_fetch separation|cloning`: used by the app to download the
    # PyTorch-based models in a child process.
    jobs = {
        "separation": fetch_separation,
        "cloning": fetch_voice_cloning,
        "supertonic": fetch_supertonic,
    }
    if len(sys.argv) != 2 or sys.argv[1] not in jobs:
        raise SystemExit(f"usage: model_fetch {'|'.join(jobs)}")
    jobs[sys.argv[1]](Settings(), print)

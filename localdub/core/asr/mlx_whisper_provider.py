"""Whisper on Apple Silicon through MLX (the GPU of an M-series Mac).

faster-whisper (CTranslate2) has no Metal backend, so on a Mac it would run on the processor only.
MLX is Apple's array framework; `mlx-whisper` runs the same Whisper weights on the GPU, which shares
the Mac's memory with the processor ("unified memory").

Not measured on a real Mac yet: see docs/QUALITY.md.
"""

from __future__ import annotations

import gc
import logging
import time
from pathlib import Path
from typing import Any

import soundfile as sf

from localdub.core.asr.base import AsrResult
from localdub.core.timeline.models import Word

log = logging.getLogger(__name__)


class MlxWhisperProvider:
    def __init__(
        self,
        repo: str,
        revision: str | None = None,
        name: str = "large-v3-mlx",
        download_root: Path | None = None,
        device: str | None = None,
    ) -> None:
        self.repo = repo
        self.revision = revision
        self.model_name = name
        self.download_root = download_root
        self.device = device  # None = the default (the GPU); "cpu" forces the processor
        self.engine = f"mlx-whisper:{name}"
        self._path: str | None = None

    def _local_snapshot(self) -> str:
        from huggingface_hub import snapshot_download

        root = str(self.download_root) if self.download_root else None
        try:
            return str(
                snapshot_download(
                    self.repo, revision=self.revision, cache_dir=root, local_files_only=True,
                    allow_patterns=["config.json", "weights.*"],
                )
            )  # fmt: skip
        except Exception as exc:  # noqa: BLE001
            raise FileNotFoundError(
                f"The speech recognition model {self.repo} is not downloaded. "
                "Download it on the AI models page."
            ) from exc

    def _prepare(self) -> str:
        if self._path is None:
            import mlx.core as mx

            if self.device == "cpu":
                mx.set_default_device(mx.cpu)
            self._path = self._local_snapshot()
            self.engine = f"mlx-whisper:{self.model_name}:{mx.default_device()}"
        return self._path

    def transcribe(self, audio_path: Path, language: str | None = None) -> AsrResult:
        path = self._prepare()
        import mlx_whisper

        # Decode ourselves: the pipeline already extracted 16 kHz mono PCM.
        audio, sr = sf.read(str(audio_path), dtype="float32", always_2d=True)
        if sr != 16000:
            raise ValueError(f"ASR input must be 16 kHz, got {sr} Hz: {audio_path}")
        mono = audio.mean(axis=1)
        t0 = time.perf_counter()
        result: dict[str, Any] = mlx_whisper.transcribe(
            mono,
            path_or_hf_repo=path,
            language=language,
            word_timestamps=True,
            condition_on_previous_text=False,
            # Whisper invents text in long silences; with word times it can skip those stretches.
            hallucination_silence_threshold=2.0,
            verbose=None,
        )
        duration = len(mono) / 16000
        elapsed = time.perf_counter() - t0
        words = [
            Word(
                start=float(w["start"]),
                end=float(w["end"]),
                text=str(w["word"]),
                probability=float(w.get("probability", 1.0)),
            )
            for seg in result.get("segments", [])
            for w in seg.get("words", [])
        ]
        log.info(
            "Transcribed %.1fs audio in %.1fs (RTF %.3f) with %s",
            duration, elapsed, elapsed / max(duration, 1e-6), self.engine,
        )  # fmt: skip
        return AsrResult(
            language=str(result.get("language") or language or "en"),
            language_probability=None,  # mlx-whisper does not report it
            duration=duration,
            words=words,
            engine=self.engine,
        )

    def close(self) -> None:
        self._path = None
        try:
            from mlx_whisper.transcribe import ModelHolder

            ModelHolder.model = None
            ModelHolder.model_path = None
        except Exception:  # noqa: BLE001 - the cache holder moved in some version: not fatal
            log.debug("Could not clear the mlx-whisper model cache", exc_info=True)
        gc.collect()
        try:
            import mlx.core as mx

            clear = getattr(mx, "clear_cache", None) or mx.metal.clear_cache
            clear()
        except Exception:  # noqa: BLE001
            log.debug("Could not clear the MLX cache", exc_info=True)

"""faster-whisper (CTranslate2) ASR provider with an explicit, logged fallback chain."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

import soundfile as sf

from localdub.core.asr.base import AsrResult
from localdub.core.gpu import register_cuda_dlls, release_memory
from localdub.core.timeline.models import Word

log = logging.getLogger(__name__)


class FasterWhisperProvider:
    def __init__(
        self,
        model: str = "large-v3",
        device: str = "cuda",
        compute_type: str = "float16",
        download_root: Path | None = None,
        beam_size: int = 5,
        allow_fallback: bool = True,
        repo: str | None = None,
    ) -> None:
        self.model_name = model
        self.repo = repo
        self.device = device
        self.compute_type = compute_type
        self.download_root = download_root
        self.beam_size = beam_size
        self.allow_fallback = allow_fallback
        self._model: Any = None
        self.engine = ""
        self.attempt_errors: list[str] = []

    def _local_snapshot(self, cache_dir: str | None) -> str:
        from huggingface_hub import snapshot_download

        try:
            return str(
                snapshot_download(
                    str(self.repo), cache_dir=cache_dir, local_files_only=True,
                    allow_patterns=["config.json", "preprocessor_config.json", "model.bin",
                                    "tokenizer.json", "vocabulary.*"],
                )
            )  # fmt: skip
        except Exception as exc:  # noqa: BLE001
            raise FileNotFoundError(
                f"The speech recognition model {self.repo} is not downloaded. "
                "Download it on the AI models page."
            ) from exc

    def _candidates(self) -> list[tuple[str, str]]:
        first = (self.device, self.compute_type)
        if not self.allow_fallback:
            return [first]
        chain = [first]
        if self.device == "cuda":
            chain += [("cuda", "int8_float16"), ("cpu", "int8")]
        return list(dict.fromkeys(chain))

    def _load(self) -> Any:
        if self._model is not None:
            return self._model
        register_cuda_dlls()
        from faster_whisper import WhisperModel

        root = str(self.download_root) if self.download_root else None
        model_ref = self.model_name
        if self.repo:  # a model chosen in the catalogue: use exactly its downloaded files
            model_ref = self._local_snapshot(root)
        for device, ctype in self._candidates():
            try:
                t0 = time.perf_counter()
                model = WhisperModel(
                    model_ref, device=device, compute_type=ctype, download_root=root
                )
                self.engine = f"faster-whisper:{self.model_name}:{device}:{ctype}"
                log.info("Loaded %s in %.1fs", self.engine, time.perf_counter() - t0)
                self._model = model
                return model
            except Exception as exc:  # noqa: BLE001 - every failure is recorded and retried
                msg = f"{device}/{ctype}: {type(exc).__name__}: {exc}"
                self.attempt_errors.append(msg)
                log.warning("faster-whisper load failed (%s); trying next fallback", msg)
        raise RuntimeError("Could not load faster-whisper: " + " | ".join(self.attempt_errors))

    def transcribe(self, audio_path: Path, language: str | None = None) -> AsrResult:
        model = self._load()
        # Decode ourselves: the pipeline already extracted 16 kHz mono PCM, and this avoids
        # faster-whisper's PyAV decoder (PyAV 17 dropped an argument faster-whisper 1.2.1 uses).
        audio, sr = sf.read(str(audio_path), dtype="float32", always_2d=True)
        if sr != 16000:
            raise ValueError(f"ASR input must be 16 kHz, got {sr} Hz: {audio_path}")
        t0 = time.perf_counter()
        failure: str | None = None
        words: list[Word] = []
        try:
            segments, info = model.transcribe(
                audio.mean(axis=1),
                language=language,
                beam_size=self.beam_size,
                vad_filter=True,
                word_timestamps=True,
                condition_on_previous_text=False,
            )
            words = [
                Word(start=w.start, end=w.end, text=w.word, probability=w.probability)
                for seg in segments
                for w in (seg.words or [])
            ]
        except RuntimeError as exc:
            # CUDA kernel errors only surface at inference time; fall back to CPU once.
            if not self.allow_fallback or "cpu" in self.engine:
                raise
            failure = f"{self.engine} inference: {exc}"
        if failure is not None:
            # Retry outside the except block so the traceback no longer pins the GPU model.
            self.attempt_errors.append(failure)
            log.warning("GPU inference failed (%s); retrying on CPU int8", failure)
            model = None
            self.close()
            self.device, self.compute_type, self.allow_fallback = "cpu", "int8", False
            return self.transcribe(audio_path, language)
        elapsed = time.perf_counter() - t0
        log.info(
            "Transcribed %.1fs audio in %.1fs (RTF %.3f) with %s",
            info.duration, elapsed, elapsed / max(info.duration, 1e-6), self.engine,
        )  # fmt: skip
        return AsrResult(
            language=info.language,
            language_probability=info.language_probability,
            duration=info.duration,
            words=words,
            engine=self.engine,
        )

    def close(self) -> None:
        self._model = None
        release_memory()

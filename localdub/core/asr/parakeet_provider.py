"""NVIDIA Parakeet TDT 0.6B v3 through sherpa-onnx (int8, CPU, no PyTorch). Experimental.

The model returns text as sub-word tokens with a start time and a duration each. Words are rebuilt
from them (a token that starts with a space begins a new word, anything else continues it), which is
less precise at word edges than Whisper's alignment; docs/QUALITY.md has the measured difference.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
import soundfile as sf

from localdub.core.asr.base import AsrResult
from localdub.core.timeline.models import Word

log = logging.getLogger(__name__)
SAMPLE_RATE = 16000
MAX_WORD_S = 1.2  # a word never lasts longer than this: durations can swallow the pause after it


def plan_chunks(
    audio: npt.NDArray[np.float32], sr: int, max_s: float = 40.0, search_s: float = 4.0
) -> list[tuple[int, int]]:
    """Split long audio into pieces of at most `max_s`, cutting at the quietest moment near the end.

    The model's cost grows quickly with length, and cutting in the middle of a word would damage it.
    """
    n = len(audio)
    limit = int(max_s * sr)
    if n <= limit:
        return [(0, n)]
    frame = int(0.02 * sr)
    out: list[tuple[int, int]] = []
    start = 0
    while n - start > limit:
        lo, hi = start + limit - int(search_s * sr), start + limit
        window = audio[lo:hi]
        usable = (len(window) // frame) * frame
        energy = np.sqrt((window[:usable].reshape(-1, frame) ** 2).mean(axis=1))
        cut = lo + int(np.argmin(energy)) * frame + frame // 2
        out.append((start, cut))
        start = cut
    out.append((start, n))
    return out


def tokens_to_words(
    tokens: list[str], starts: list[float], durations: list[float], offset: float = 0.0
) -> list[Word]:
    words: list[Word] = []
    text, first, last_end = "", 0.0, 0.0
    for tok, ts, du in zip(tokens, starts, durations, strict=False):
        if tok.startswith("<") and tok.endswith(">"):  # <unk>, <pad>, ...
            continue
        if tok.startswith((" ", "▁")) or not text:
            if text:
                words.append(_word(text, first, last_end, offset))
            text, first = tok.lstrip(" ▁"), ts
        else:
            text += tok
        last_end = ts + du
    if text:
        words.append(_word(text, first, last_end, offset))
    # a word ends no later than the next one starts
    for a, b in zip(words, words[1:], strict=False):
        if a.end > b.start:
            a.end = b.start
    return words


def _word(text: str, start: float, end: float, offset: float) -> Word:
    return Word(
        start=round(start + offset, 3),
        end=round(start + offset + min(max(end - start, 0.04), MAX_WORD_S), 3),
        text=" " + text,
    )


class ParakeetProvider:
    local_only = True

    def __init__(self, model_dir: Path, num_threads: int = 4, chunk_s: float = 40.0) -> None:
        self.model_dir = model_dir
        self.num_threads = num_threads
        self.chunk_s = chunk_s
        self.engine = "parakeet-tdt-0.6b-v3-int8:sherpa-onnx:cpu"
        self._rec: Any = None

    def _load(self) -> Any:
        if self._rec is not None:
            return self._rec
        files = {
            n: self.model_dir / n
            for n in ("encoder.int8.onnx", "decoder.int8.onnx", "joiner.int8.onnx", "tokens.txt")
        }
        missing = [n for n, p in files.items() if not p.is_file()]
        if missing:
            raise FileNotFoundError(
                f"The Parakeet model is not downloaded ({', '.join(missing)} missing in "
                f"{self.model_dir}). Download it on the AI models page."
            )
        import sherpa_onnx

        t0 = time.perf_counter()
        self._rec = sherpa_onnx.OfflineRecognizer.from_transducer(
            encoder=str(files["encoder.int8.onnx"]), decoder=str(files["decoder.int8.onnx"]),
            joiner=str(files["joiner.int8.onnx"]), tokens=str(files["tokens.txt"]),
            num_threads=self.num_threads, sample_rate=SAMPLE_RATE, feature_dim=128,
            decoding_method="greedy_search", model_type="nemo_transducer",
        )  # fmt: skip
        log.info("Loaded %s in %.1fs", self.engine, time.perf_counter() - t0)
        return self._rec

    def transcribe(self, audio_path: Path, language: str | None = None) -> AsrResult:
        rec = self._load()
        audio, sr = sf.read(str(audio_path), dtype="float32", always_2d=True)
        if sr != SAMPLE_RATE:
            raise ValueError(f"ASR input must be 16 kHz, got {sr} Hz: {audio_path}")
        mono = np.ascontiguousarray(audio.mean(axis=1), dtype=np.float32)
        t0 = time.perf_counter()
        words: list[Word] = []
        detected = ""
        for a, b in plan_chunks(mono, sr, self.chunk_s):
            stream = rec.create_stream()
            stream.accept_waveform(sr, mono[a:b])
            rec.decode_stream(stream)
            r = stream.result
            detected = detected or str(getattr(r, "lang", "") or "")
            words += tokens_to_words(list(r.tokens), list(r.timestamps), list(r.durations), a / sr)
        duration = len(mono) / sr
        elapsed = time.perf_counter() - t0
        log.info(
            "Transcribed %.1fs audio in %.1fs (RTF %.3f) with %s",
            duration, elapsed, elapsed / max(duration, 1e-6), self.engine,
        )  # fmt: skip
        return AsrResult(
            language=language or detected or "en",
            language_probability=None,
            duration=duration,
            words=words,
            engine=self.engine,
        )

    def close(self) -> None:
        self._rec = None

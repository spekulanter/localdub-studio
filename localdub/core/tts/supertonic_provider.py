"""Supertonic 3 (ONNX Runtime) TTS provider.

The weights are fetched from Hugging Face at the revision pinned by the `supertonic`
package (model data only; no executables). Upstream development stopped in July 2026,
so the package and revision are pinned and should not be upgraded blindly.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np

from localdub.core.gpu import release_memory
from localdub.core.tts.base import Audio

log = logging.getLogger(__name__)


class SupertonicProvider:
    local_only = True

    def __init__(
        self,
        model: str = "supertonic-3",
        model_dir: Path | None = None,
        steps: int = 8,
        threads: int | None = None,
        auto_download: bool = True,
    ) -> None:
        from supertonic import TTS

        self.model_name = model
        self.steps = steps
        self._tts: Any = TTS(
            model=model,
            model_dir=model_dir,
            auto_download=auto_download,
            intra_op_num_threads=threads,
        )
        self.sample_rate: int = int(self._tts.sample_rate)
        self._styles: dict[str, Any] = {}
        log.info("Loaded %s (sample rate %d Hz) from %s", model, self.sample_rate, model_dir)

    def list_voices(self) -> list[str]:
        return sorted(self._tts.voice_style_names)

    def unsupported_chars(self, text: str) -> list[str]:
        ok, bad = self._tts.model.text_processor.validate_text(text)
        return [] if ok else list(bad)

    def _style(self, voice: str) -> Any:
        if voice not in self._styles:
            if voice not in self._tts.voice_style_names:
                raise ValueError(f"Unknown voice '{voice}'. Available: {self.list_voices()}")
            self._styles[voice] = self._tts.get_voice_style(voice_name=voice)
        return self._styles[voice]

    def synthesize(self, text: str, *, voice: str, lang: str, speed: float = 1.0) -> Audio:
        wav, _ = self._tts.synthesize(
            text,
            voice_style=self._style(voice),
            total_steps=self.steps,
            speed=speed,
            lang=lang,
            silence_duration=0.15,
        )
        return np.asarray(wav, dtype=np.float32).reshape(-1)

    def close(self) -> None:
        self._tts = None
        self._styles.clear()
        release_memory()

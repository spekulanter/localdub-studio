"""Speech recognition provider interface."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from pydantic import BaseModel

from localdub.core.timeline.models import Word


class AsrResult(BaseModel):
    language: str
    language_probability: float | None
    duration: float
    words: list[Word]
    # Engine/model actually used, after any fallback.
    engine: str


class ASRProvider(Protocol):
    def transcribe(self, audio_path: Path, language: str | None = None) -> AsrResult: ...

    def close(self) -> None:
        """Free model memory (VRAM) so the next stage can use the GPU."""
        ...

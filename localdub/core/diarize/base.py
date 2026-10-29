"""Diarizer interface."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from localdub.core.diarize.assign import SpeakerTurn


class Diarizer(Protocol):
    local_only: bool

    def diarize(self, wav_path: Path) -> list[SpeakerTurn]:
        """Speech turns of a 16 kHz mono WAV; speaker indexes are 0-based."""
        ...

    def close(self) -> None: ...

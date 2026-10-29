"""Translation provider interface."""

from __future__ import annotations

from typing import Protocol

from localdub.core.timeline.models import DialogueSegment


class TranslationProvider(Protocol):
    #: True if the provider runs entirely on this machine.
    local_only: bool

    def translate_segments(
        self, segments: list[DialogueSegment], source_lang: str, target_lang: str
    ) -> list[str]:
        """Return one translation per segment, in order."""
        ...

    def close(self) -> None:
        """Release model memory (e.g. unload from VRAM)."""
        ...

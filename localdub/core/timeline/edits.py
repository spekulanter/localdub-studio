"""Manual edits layered on top of pipeline output.

Edits live in `edits.json` next to the stage files, keyed by segment id. Each edit remembers a hash
of the source text it was made for, so if a re-run of ASR changes that segment the stale edit is
ignored instead of being applied to the wrong sentence.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from localdub.core.jobs.checkpoints import atomic_write_json
from localdub.core.timeline.models import DialogueSegment, ReviewStatus

MIN_SEGMENT_S = 0.3


def source_hash(text: str) -> str:
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()[:16]


class SegmentEdit(BaseModel):
    source_hash: str
    translated_text: str | None = None
    voice_id: str | None = None
    start: float | None = None
    end: float | None = None
    review_status: ReviewStatus | None = None

    def is_empty(self) -> bool:
        return all(
            getattr(self, f) is None
            for f in ("translated_text", "voice_id", "start", "end", "review_status")
        )


class Edits(BaseModel):
    segments: dict[int, SegmentEdit] = Field(default_factory=dict)
    # Default voice per speaker id ("S1" -> "M2"); a segment's own voice_id wins.
    speaker_voices: dict[str, str] = Field(default_factory=dict)


def load_edits(path: Path) -> Edits:
    if not path.is_file():
        return Edits()
    try:
        return Edits.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except (ValueError, OSError):
        return Edits()


def save_edits(path: Path, edits: Edits) -> None:
    edits.segments = {k: v for k, v in edits.segments.items() if not v.is_empty()}
    atomic_write_json(path, edits.model_dump(mode="json"))


def ensure_edits_file(path: Path) -> None:
    if not path.is_file():
        save_edits(path, Edits())


def apply_edits(segments: list[DialogueSegment], edits: Edits) -> dict[str, Any]:
    """Apply edits in place. Returns {"applied": [ids], "stale": [ids]}."""
    applied: list[int] = []
    stale: list[int] = []
    for seg in segments:
        edit = edits.segments.get(seg.id)
        if edit is not None:
            if edit.source_hash != source_hash(seg.source_text):
                stale.append(seg.id)
            else:
                if edit.translated_text is not None:
                    seg.translated_text = edit.translated_text
                if edit.voice_id is not None:
                    seg.voice_id = edit.voice_id
                if edit.start is not None:
                    seg.start = edit.start
                if edit.end is not None:
                    seg.end = edit.end
                if edit.review_status is not None:
                    seg.review_status = edit.review_status
                applied.append(seg.id)
                if edit.voice_id is not None:
                    continue
        if seg.voice_id is None or seg.voice_id == "":
            seg.voice_id = edits.speaker_voices.get(seg.speaker_id)
    return {"applied": applied, "stale": stale}


def validate_timing(
    start: float, end: float, duration: float, neighbours: tuple[float | None, float | None]
) -> str | None:
    """Return an error message, or None if the timing is acceptable."""
    if start < 0 or end > duration + 0.01:
        return f"Timing must stay within the video (0 to {duration:.2f} s)"
    if end - start < MIN_SEGMENT_S:
        return f"A segment must last at least {MIN_SEGMENT_S} s"
    prev_end, next_start = neighbours
    if prev_end is not None and start < prev_end - 0.001:
        return f"Start overlaps the previous segment (ends at {prev_end:.2f} s)"
    if next_start is not None and end > next_start + 0.001:
        return f"End overlaps the next segment (starts at {next_start:.2f} s)"
    return None

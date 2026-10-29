"""Typed dialogue-segment model shared by all pipeline stages."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class FitStatus(StrEnum):
    PENDING = "pending"
    OK = "ok"
    STRETCHED = "stretched"
    SHIFTED = "shifted"  # placed later than its anchor because the previous line overran
    OVERFLOW = "overflow"  # does not fit its window even at maximum speed


class ReviewStatus(StrEnum):
    PENDING = "pending"
    EDITED = "edited"
    APPROVED = "approved"


class Word(BaseModel):
    start: float
    end: float
    text: str
    probability: float | None = None


class DialogueSegment(BaseModel):
    id: int
    start: float = Field(ge=0)
    end: float = Field(ge=0)
    source_text: str
    translated_text: str = ""
    speaker_id: str = "S1"
    voice_id: str | None = None
    audio_path: str | None = None
    audio_duration: float | None = None
    # Final tempo applied relative to the raw synthesis (1.0 = unchanged).
    stretch_ratio: float = 1.0
    tts_speed: float | None = None
    placed_start: float | None = None
    fit_status: FitStatus = FitStatus.PENDING
    review_status: ReviewStatus = ReviewStatus.PENDING
    words: list[Word] = Field(default_factory=list)

    @property
    def duration(self) -> float:
        return self.end - self.start


class Transcript(BaseModel):
    language: str
    language_probability: float | None = None
    duration: float
    segments: list[DialogueSegment]

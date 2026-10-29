"""Decide how each synthesized line fits its time window."""

from __future__ import annotations

from dataclasses import dataclass

from localdub.core.timeline.models import DialogueSegment, FitStatus


def available_windows(
    segments: list[DialogueSegment], total_duration: float, gap_s: float = 0.05
) -> list[float]:
    """Seconds available to each line: from its start to the next line's start (or video end)."""
    out: list[float] = []
    for i, seg in enumerate(segments):
        nxt = segments[i + 1].start if i + 1 < len(segments) else total_duration
        out.append(max(nxt - seg.start - gap_s, 0.05))
    return out


@dataclass(frozen=True)
class FitDecision:
    #: Extra speed-up to apply to audio synthesized at the base speed (1.0 = none).
    speed_factor: float
    status: FitStatus


def decide(natural_duration: float, window: float, max_speed: float) -> FitDecision:
    """natural_duration: length of speech at the base TTS speed."""
    if natural_duration <= window:
        return FitDecision(1.0, FitStatus.OK)
    ratio = natural_duration / window
    if ratio <= max_speed:
        return FitDecision(ratio, FitStatus.STRETCHED)
    return FitDecision(max_speed, FitStatus.OVERFLOW)


@dataclass(frozen=True)
class Placement:
    start: float
    shifted_by: float


def place(anchors: list[float], durations: list[float], gap_s: float = 0.05) -> list[Placement]:
    """Keep each line on its original start unless the previous line is still speaking;
    then start it right after (never overlap speech, never truncate it)."""
    out: list[Placement] = []
    prev_end = float("-inf")
    for anchor, dur in zip(anchors, durations, strict=True):
        start = max(anchor, prev_end + gap_s)
        out.append(Placement(start=start, shifted_by=max(start - anchor, 0.0)))
        prev_end = start + dur
    return out

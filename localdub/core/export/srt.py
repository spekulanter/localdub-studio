"""SubRip (SRT) writing and parsing."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from localdub.core.timeline.models import DialogueSegment


@dataclass(frozen=True)
class Cue:
    index: int
    start: float
    end: float
    text: str


def format_timestamp(seconds: float) -> str:
    ms = max(int(round(seconds * 1000)), 0)
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def parse_timestamp(ts: str) -> float:
    h, m, rest = ts.strip().split(":")
    s, ms = rest.split(",")
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


def wrap_text(text: str, max_line: int = 42, max_lines: int = 2) -> str:
    """Wrap into at most `max_lines` lines, balancing two-line cues around the middle.
    Lines may exceed max_line rather than dropping text."""
    words = text.split()
    if len(text) <= max_line or max_lines < 2 or len(words) < 2:
        return " ".join(words)
    best: tuple[int, int] | None = None
    for i in range(1, len(words)):
        a, b = " ".join(words[:i]), " ".join(words[i:])
        score = max(len(a), len(b))
        if best is None or score < best[0]:
            best = (score, i)
    assert best is not None
    i = best[1]
    return " ".join(words[:i]) + "\n" + " ".join(words[i:])


def segments_to_cues(segments: list[DialogueSegment], use_translation: bool = True) -> list[Cue]:
    cues: list[Cue] = []
    for seg in segments:
        text = seg.translated_text if use_translation else seg.source_text
        if not text.strip():
            continue
        cues.append(Cue(len(cues) + 1, seg.start, max(seg.end, seg.start + 0.3), wrap_text(text)))
    # Never let a cue overlap the next one.
    fixed: list[Cue] = []
    for i, c in enumerate(cues):
        end = min(c.end, cues[i + 1].start - 0.001) if i + 1 < len(cues) else c.end
        fixed.append(Cue(c.index, c.start, max(end, c.start + 0.001), c.text))
    return fixed


def render_srt(cues: list[Cue]) -> str:
    blocks = [
        f"{c.index}\n{format_timestamp(c.start)} --> {format_timestamp(c.end)}\n{c.text}\n"
        for c in cues
    ]
    return "\n".join(blocks)


def write_srt(segments: list[DialogueSegment], path: Path, use_translation: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # UTF-8 with BOM is the most compatible choice for Windows players and editors.
    path.write_text(render_srt(segments_to_cues(segments, use_translation)), encoding="utf-8-sig")


_BLOCK = re.compile(
    r"(\d+)\s*\n(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})\s*\n(.*?)(?:\n\s*\n|\Z)",
    re.S,
)


def parse_srt(text: str) -> list[Cue]:
    text = text.lstrip("﻿").replace("\r\n", "\n")
    return [
        Cue(int(m[1]), parse_timestamp(m[2]), parse_timestamp(m[3]), m[4].strip())
        for m in _BLOCK.finditer(text)
    ]

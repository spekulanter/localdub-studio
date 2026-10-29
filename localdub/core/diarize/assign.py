"""Attach diarization turns to recognised words and split segments where the speaker changes."""

from __future__ import annotations

from dataclasses import dataclass

from localdub.core.timeline.models import DialogueSegment, Word


@dataclass(frozen=True)
class SpeakerTurn:
    start: float
    end: float
    speaker: int


def _overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def speaker_of(start: float, end: float, turns: list[SpeakerTurn]) -> int | None:
    """Speaker whose turns overlap [start, end] the most; the nearest turn if none overlaps."""
    if not turns:
        return None
    totals: dict[int, float] = {}
    for t in turns:
        ov = _overlap(start, end, t.start, t.end)
        if ov > 0:
            totals[t.speaker] = totals.get(t.speaker, 0.0) + ov
    if totals:
        return max(totals, key=lambda k: totals[k])
    mid = (start + end) / 2
    nearest = min(turns, key=lambda t: min(abs(mid - t.start), abs(mid - t.end)))
    return nearest.speaker


def _runs(words: list[Word], labels: list[int]) -> list[tuple[int, list[Word]]]:
    runs: list[tuple[int, list[Word]]] = []
    for w, lab in zip(words, labels, strict=True):
        if runs and runs[-1][0] == lab:
            runs[-1][1].append(w)
        else:
            runs.append((lab, [w]))
    return runs


def _smooth(runs: list[tuple[int, list[Word]]], min_run_s: float) -> list[tuple[int, list[Word]]]:
    """Merge runs shorter than min_run_s into their neighbour (the longer one if both exist)."""
    changed = True
    while changed and len(runs) > 1:
        changed = False
        for i, (_, ws) in enumerate(runs):
            if ws[-1].end - ws[0].start >= min_run_s:
                continue
            if i == 0:
                j = 1
            elif i == len(runs) - 1:
                j = i - 1
            else:
                left, right = runs[i - 1][1], runs[i + 1][1]
                j = (
                    i - 1
                    if (left[-1].end - left[0].start) >= (right[-1].end - right[0].start)
                    else i + 1
                )
            lab = runs[j][0]
            merged = sorted([*ws, *runs[j][1]], key=lambda w: w.start)
            lo, hi = sorted((i, j))
            runs[lo : hi + 1] = [(lab, merged)]
            changed = True
            break
    # adjacent runs with the same label (after merging) become one
    out: list[tuple[int, list[Word]]] = []
    for lab, ws in runs:
        if out and out[-1][0] == lab:
            out[-1][1].extend(ws)
        else:
            out.append((lab, list(ws)))
    return out


def assign_speakers(
    segments: list[DialogueSegment], turns: list[SpeakerTurn], *, min_run_s: float = 0.8
) -> list[DialogueSegment]:
    """Return new segments (ids renumbered from 1) with speaker_id set to S1, S2, ...

    A segment is split where the speaker changes, unless one side would be shorter than
    `min_run_s` (those words stay with the neighbouring speaker).
    """
    out: list[DialogueSegment] = []
    for seg in segments:
        if not seg.words:
            sp = speaker_of(seg.start, seg.end, turns)
            out.append(seg.model_copy(update={"speaker_id": f"S{(sp or 0) + 1}"}))
            continue
        labels = [speaker_of(w.start, w.end, turns) or 0 for w in seg.words]
        for lab, ws in _smooth(_runs(seg.words, labels), min_run_s):
            text = "".join(w.text for w in ws).strip()
            if not text:
                continue
            out.append(
                seg.model_copy(
                    update={
                        "start": ws[0].start,
                        "end": ws[-1].end,
                        "source_text": text,
                        "speaker_id": f"S{lab + 1}",
                        "words": ws,
                    }
                )
            )
    return [s.model_copy(update={"id": i}) for i, s in enumerate(out, start=1)]

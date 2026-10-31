"""Group word timestamps into dialogue segments suitable for dubbing."""

from __future__ import annotations

from localdub.core.timeline.models import DialogueSegment, Word

_SENTENCE_END = (".", "?", "!", "…", '."', '?"', '!"', "。", "！", "？")
_CLAUSE_END = (",", ";", ":", "—", "-", "，", "、", "；", "：")


def _ends(word: Word, suffixes: tuple[str, ...]) -> bool:
    return word.text.strip().endswith(suffixes)


def _join(words: list[Word]) -> str:
    return "".join(w.text for w in words).strip()


def group_words(
    words: list[Word],
    *,
    min_s: float = 1.5,
    max_s: float = 8.0,
    max_gap_s: float = 0.6,
) -> list[DialogueSegment]:
    """Greedy grouping: break on long pauses, on sentence ends once a segment is long enough,
    and before exceeding max_s (preferably at a clause boundary)."""
    groups: list[list[Word]] = []
    cur: list[Word] = []

    for w in words:
        if not w.text.strip():
            continue
        if cur:
            gap = w.start - cur[-1].end
            if gap > max_gap_s:
                groups.append(cur)
                cur = []
            elif w.end - cur[0].start > max_s:
                split = _clause_split(cur)
                groups.append(cur[:split])
                cur = cur[split:]
        cur.append(w)
        if _ends(w, _SENTENCE_END) and cur[-1].end - cur[0].start >= min_s:
            groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)

    return [
        DialogueSegment(
            id=i + 1,
            start=round(g[0].start, 3),
            end=round(g[-1].end, 3),
            source_text=_join(g),
            words=g,
        )
        for i, g in enumerate(groups)
        if _join(g)
    ]


def _clause_split(cur: list[Word]) -> int:
    """Index after the last sentence/clause boundary, or the whole list if none."""
    for suffixes in (_SENTENCE_END, _CLAUSE_END):
        for i in range(len(cur) - 1, 0, -1):
            if _ends(cur[i - 1], suffixes):
                return i
    return len(cur)

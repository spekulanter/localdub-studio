import pytest

from localdub.core.export.srt import (
    Cue,
    format_timestamp,
    parse_srt,
    parse_timestamp,
    render_srt,
    segments_to_cues,
    wrap_text,
    write_srt,
)
from localdub.core.timeline.models import DialogueSegment


def seg(i, start, end, text):
    return DialogueSegment(id=i, start=start, end=end, source_text=text, translated_text=text)


@pytest.mark.parametrize("value", [0, 1.234, 3661.2345, 86399.999])
def test_timestamp_round_trip(value):
    assert parse_timestamp(format_timestamp(value)) == pytest.approx(round(value, 3))


def test_wrap_balanced_and_preserves_words():
    text = "one two three four five six seven eight nine ten eleven twelve"
    result = wrap_text(text)
    lines = result.splitlines()
    assert len(lines) == 2
    assert abs(len(lines[0]) - len(lines[1])) <= 10
    assert " ".join(lines) == text
    assert wrap_text("short line") == "short line"


def test_cues_skip_empty_enforce_minimum_and_no_overlap():
    cues = segments_to_cues([seg(1, 0, 0, " "), seg(2, 1, 1.1, "hello"), seg(3, 1.2, 2, "world")])
    assert len(cues) == 2
    assert cues[0].end <= cues[1].start
    assert cues[1].end - cues[1].start >= 0.3


def test_srt_round_trip_diacritics_and_bom(tmp_path):
    text = "ľščťžýáíéúäôň"
    cues = [Cue(1, 3661.234, 3662.5, text)]
    assert parse_srt(render_srt(cues)) == cues
    path = tmp_path / "out.srt"
    write_srt([seg(1, 0, 1, text)], path)
    assert path.read_bytes().startswith(b"\xef\xbb\xbf")
    assert text in path.read_text(encoding="utf-8-sig")

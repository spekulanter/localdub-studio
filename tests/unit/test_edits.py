from __future__ import annotations

from localdub.core.timeline.edits import (
    Edits,
    SegmentEdit,
    apply_edits,
    load_edits,
    save_edits,
    source_hash,
    validate_timing,
)
from localdub.core.timeline.models import DialogueSegment, ReviewStatus


def seg(i: int, text: str = "Hello", speaker: str = "S1") -> DialogueSegment:
    return DialogueSegment(
        id=i,
        start=i * 2.0,
        end=i * 2.0 + 1.5,
        source_text=text,
        translated_text="Ahoj",
        speaker_id=speaker,
    )


def test_apply_edits_overrides_fields_and_reports_ids():
    segs = [seg(1), seg(2)]
    edits = Edits(
        segments={
            2: SegmentEdit(
                source_hash=source_hash("Hello"),
                translated_text="Čau",
                voice_id="M2",
                start=4.1,
                end=5.2,
                review_status=ReviewStatus.APPROVED,
            )
        }
    )
    report = apply_edits(segs, edits)
    assert report == {"applied": [2], "stale": []}
    assert segs[0].translated_text == "Ahoj" and segs[0].voice_id is None
    s2 = segs[1]
    assert (s2.translated_text, s2.voice_id, s2.start, s2.end) == ("Čau", "M2", 4.1, 5.2)
    assert s2.review_status is ReviewStatus.APPROVED


def test_edit_for_changed_source_text_is_stale_and_ignored():
    segs = [seg(1, text="Something else now")]
    edits = Edits(
        segments={1: SegmentEdit(source_hash=source_hash("Hello"), translated_text="Čau")}
    )
    assert apply_edits(segs, edits) == {"applied": [], "stale": [1]}
    assert segs[0].translated_text == "Ahoj"


def test_speaker_voice_default_and_segment_voice_wins():
    segs = [seg(1, speaker="S1"), seg(2, speaker="S2"), seg(3, speaker="S2")]
    edits = Edits(
        speaker_voices={"S2": "M3"},
        segments={3: SegmentEdit(source_hash=source_hash("Hello"), voice_id="F5")},
    )
    apply_edits(segs, edits)
    assert [s.voice_id for s in segs] == [None, "M3", "F5"]


def test_save_drops_empty_edits_and_roundtrips(tmp_path):
    path = tmp_path / "edits.json"
    edits = Edits(
        segments={
            1: SegmentEdit(source_hash="x"),
            2: SegmentEdit(source_hash="y", translated_text="Áno"),
        }
    )
    save_edits(path, edits)
    loaded = load_edits(path)
    assert list(loaded.segments) == [2] and loaded.segments[2].translated_text == "Áno"


def test_load_edits_survives_missing_and_corrupt_file(tmp_path):
    assert load_edits(tmp_path / "nope.json") == Edits()
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert load_edits(bad) == Edits()


def test_validate_timing():
    ok = validate_timing(1.0, 2.0, 10.0, (0.5, 3.0))
    assert ok is None
    assert "within the video" in (validate_timing(-0.1, 2.0, 10.0, (None, None)) or "")
    assert "within the video" in (validate_timing(9.0, 10.5, 10.0, (None, None)) or "")
    assert "at least" in (validate_timing(1.0, 1.1, 10.0, (None, None)) or "")
    assert "previous" in (validate_timing(0.4, 2.0, 10.0, (0.5, None)) or "")
    assert "next" in (validate_timing(1.0, 3.5, 10.0, (None, 3.0)) or "")

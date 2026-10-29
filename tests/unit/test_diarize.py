from __future__ import annotations

from localdub.core.diarize.assign import SpeakerTurn, assign_speakers, speaker_of
from localdub.core.timeline.models import DialogueSegment, Word
from localdub.core.tts.base import default_speaker_voices


def seg(i: int, words: list[tuple[float, float, str]]) -> DialogueSegment:
    ws = [Word(start=a, end=b, text=t) for a, b, t in words]
    return DialogueSegment(
        id=i,
        start=ws[0].start,
        end=ws[-1].end,
        source_text="".join(w.text for w in ws).strip(),
        words=ws,
    )


T = [SpeakerTurn(0, 5, 0), SpeakerTurn(5, 10, 1)]


def test_speaker_of_prefers_overlap_and_falls_back_to_nearest_turn():
    assert speaker_of(0.5, 1.0, T) == 0
    assert speaker_of(4.5, 6.5, T) == 1  # 1.5 s vs 0.5 s overlap
    assert speaker_of(12, 13, T) == 1  # no overlap: nearest
    assert speaker_of(1, 2, []) is None


def test_segment_is_split_where_speaker_changes():
    s = seg(
        1, [(0.5, 1.5, " Hello"), (1.5, 2.5, " there."), (5.2, 6.2, " Hi"), (6.2, 7.5, " you.")]
    )
    out = assign_speakers([s], T)
    assert [(x.speaker_id, x.source_text) for x in out] == [
        ("S1", "Hello there."),
        ("S2", "Hi you."),
    ]
    assert [x.id for x in out] == [1, 2]
    assert (out[1].start, out[1].end) == (5.2, 7.5)


def test_short_flicker_is_absorbed_by_the_neighbour():
    words = [(0.0, 1.0, " one"), (1.0, 2.0, " two"), (5.0, 5.3, " oops"), (2.1, 3.0, " three")]
    s = seg(1, sorted(words))
    out = assign_speakers([s], T)
    assert len(out) == 1 and out[0].speaker_id == "S1"
    assert out[0].source_text == "one two three oops"


def test_segments_without_words_get_whole_segment_speaker():
    s = DialogueSegment(id=7, start=6.0, end=8.0, source_text="No words")
    out = assign_speakers([s], T)
    assert out[0].speaker_id == "S2" and out[0].id == 1


def test_default_speaker_voices_alternate_genders_and_stay_distinct():
    v = default_speaker_voices(["S1", "S2", "S3", "S4"], "F1")
    assert v["S1"] == "F1" and v["S2"].startswith("M")
    assert len(set(v.values())) == 4
    assert default_speaker_voices([], "F1") == {}
    big = default_speaker_voices([f"S{i}" for i in range(1, 12)], "M2")
    assert big["S1"] == "M2" and len(big) == 11
    assert len(set(big.values())) == 10 and big["S11"] == "M2"  # extras reuse the project voice


def test_default_voices_follow_estimated_gender():
    v = default_speaker_voices(
        ["S1", "S2", "S3", "S4"], "F2", {"S1": "M", "S2": "F", "S3": "M", "S4": "F"}
    )
    assert v["S1"].startswith("M") and v["S3"].startswith("M") and v["S1"] != v["S3"]
    assert v["S2"] == "F2"  # first female speaker keeps the project voice
    assert v["S4"].startswith("F") and v["S4"] != "F2"
    assert len(set(v.values())) == 4


def test_unknown_gender_falls_back_to_alternation():
    v = default_speaker_voices(["S1", "S2"], "F1", {"S2": "M"})
    assert v == {"S1": "F1", "S2": "M1"}


def test_median_f0_recovers_pitch_and_gender():
    import numpy as np

    from localdub.core.diarize.pitch import gender_of, median_f0

    sr = 16000
    t = np.arange(sr * 2) / sr
    for hz, gender in ((110.0, "M"), (220.0, "F")):
        tone = (0.3 * np.sin(2 * np.pi * hz * t) + 0.1 * np.sin(2 * np.pi * 2 * hz * t)).astype(
            np.float32
        )
        f0 = median_f0(tone, sr)
        assert f0 is not None and abs(f0 - hz) < 4
        assert gender_of(f0) == gender
    assert median_f0(np.zeros(sr, np.float32), sr) is None  # silence


def test_load_speaker_genders(tmp_path):
    import json

    from localdub.core.diarize.pitch import load_speaker_genders

    p = tmp_path / "diarization.json"
    assert load_speaker_genders(p) == {}
    p.write_text(json.dumps({"speaker_f0": {"S1": 118.0, "S2": 205.5}}), encoding="utf-8")
    assert load_speaker_genders(p) == {"S1": "M", "S2": "F"}

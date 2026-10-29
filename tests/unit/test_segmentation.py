from localdub.core.asr.segmentation import group_words
from localdub.core.timeline.models import Word


def words(*items):
    return [Word(start=a, end=b, text=t) for a, b, t in items]


def test_gap_sentence_end_and_leading_space_join():
    result = group_words(
        words((0, 0.3, " Hello"), (0.4, 0.7, " world."), (2, 2.2, " Next!")), min_s=0.5
    )
    assert [x.id for x in result] == [1, 2]
    assert [x.source_text for x in result] == ["Hello world.", "Next!"]


def test_max_duration_prefers_clause_boundary():
    result = group_words(
        words((0, 1, "One,"), (1.1, 2, " two"), (2.1, 3, " three"), (3.1, 4, " four")),
        min_s=10,
        max_s=2.5,
    )
    assert result[0].source_text == "One,"
    assert [x.source_text for x in result[1:]] == ["two three", "four"]

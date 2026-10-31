from localdub.core.asr.segmentation import group_words
from localdub.core.timeline.models import Word


def test_japanese_and_chinese_sentences_end_at_their_own_punctuation():
    words = [
        Word(start=i * 1.0, end=i * 1.0 + 0.9, text=t)
        for i, t in enumerate(["今日は", "いい", "天気です。", "散歩に", "行きます。"])
    ]
    segs = group_words(words)
    assert [s.source_text for s in segs] == ["今日はいい天気です。", "散歩に行きます。"]

import pytest

from localdub.core.timeline.fit import available_windows, decide, place
from localdub.core.timeline.models import DialogueSegment, FitStatus


def s(start, end):
    return DialogueSegment(id=1, start=start, end=end, source_text="x")


def test_available_windows_next_last_gap_and_floor():
    assert available_windows([s(1, 2), s(3, 4)], 8) == pytest.approx([1.95, 4.95])
    assert available_windows([s(2, 3)], 2) == [0.05]


def test_decide_boundaries():
    assert decide(2, 2, 1.5).status == FitStatus.OK
    d = decide(3, 2, 1.5)
    assert d.speed_factor == 1.5 and d.status == FitStatus.STRETCHED
    d = decide(3.02, 2, 1.5)
    assert d.speed_factor == 1.5 and d.status == FitStatus.OVERFLOW


def test_place_preserves_anchors_and_shifts_overrun():
    p = place([1, 2, 4], [1, 2, 1], gap_s=0.1)
    assert [x.start for x in p] == pytest.approx([1, 2.1, 4.2])
    assert [x.shifted_by for x in p] == pytest.approx([0, 0.1, 0.2])

"""How far a model deep inside a pipeline stage has got, without every provider taking a callback.

The pipeline opens `reporting(fn)` around a stage; code inside the stage (a speech model working
through the audio, the translator going line by line) calls `report(done, total)`. Outside such a
block `report` does nothing, so providers and test fakes work the same with or without it.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar

Sink = Callable[[float, float], None]  # (units done, units in total)

_sink: ContextVar[Sink | None] = ContextVar("localdub_progress", default=None)


@contextmanager
def reporting(sink: Sink) -> Iterator[None]:
    token = _sink.set(sink)
    try:
        yield
    finally:
        _sink.reset(token)


def report(done: float, total: float) -> None:
    sink = _sink.get()
    if sink is not None and total > 0:
        sink(min(max(done, 0.0), total), total)


def percent_reporter(emit: Callable[[str], None]) -> Sink:
    """A sink that passes on "37%" whenever the whole percentage changes (not every word)."""
    last = [-1]

    def sink(done: float, total: float) -> None:
        pct = int(100 * done / total)
        if pct != last[0]:
            last[0] = pct
            emit(f"{pct}%")

    return sink

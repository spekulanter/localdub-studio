"""Remaining-time estimate for a running dub, and the progress bar that goes with it.

Each stage is expected to take `overhead + rate * seconds of audio`. The rates start from what was
measured on the development laptop (RTX 5060, 5.7-minute sample; see docs/QUALITY.md) and are
replaced by this computer's own speed after each finished dub (data/timings.json): a computer
without an NVIDIA card learns that speech recognition runs on its processor. While a stage reports
how far it is ("37%", "120/400"), its remaining time comes from its own pace instead.

It is a guess and is shown as one ("about 25 min left"), rounded.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from localdub.core.jobs.checkpoints import atomic_write_json

log = logging.getLogger(__name__)

# stage: (fixed seconds, e.g. loading a model; seconds per second of audio)
DEFAULTS: dict[str, tuple[float, float]] = {
    "download": (0.0, 0.0),  # paced by its own percentage only
    "probe": (0.2, 0.0005),
    "extract": (0.5, 0.0015),
    "asr": (8.0, 0.059),  # measured: 28.1 s for 342.7 s of audio
    "diarize": (12.0, 0.42),  # docs/QUALITY.md: about 0.4x real time plus 10-14 s loading
    "translate": (5.0, 0.092),  # measured: 36.6 s (TranslateGemma 4B)
    "tts": (5.0, 0.244),  # measured: 88.5 s
    "separate": (10.0, 0.1),  # not measured as a whole stage; learned after the first run
    "convert": (10.0, 0.5),  # docs/QUALITY.md: RTF 0.5 plus loading
    "assemble": (1.0, 0.0146),  # measured: 6.0 s
    "export": (1.0, 0.0131),  # measured: 5.5 s
}
MIN_AUDIO_TO_LEARN_S = 60.0  # short clips are mostly model loading; they would teach wrong rates
WARMUP = 0.02  # a stage's own pace counts once it has done this much since its first report
# Share of a stage after which only its own pace counts (replayed on two recorded runs of the
# 5.7-minute sample: mean error 6.7 s with the laptop's numbers, 3.5 s with learned ones).
RAMP_DEFAULT = 0.2
RAMP_LEARNED = 0.5


def rate_key(stage: str, asr_id: str = "", llm_model: str = "") -> str:
    """Speed depends on the model for these stages, so each model learns its own rate."""
    if stage == "asr" and asr_id:
        return f"asr:{asr_id}"
    if stage == "translate" and llm_model:
        return f"translate:{llm_model}"
    return stage


class Rates:
    """This computer's learned seconds per second of audio, per stage (and model)."""

    def __init__(self, path: Path | None) -> None:
        self.path = path
        self.learned: dict[str, float] = {}
        if path is not None and path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                self.learned = {
                    str(k): float(v)
                    for k, v in data.get("rates", {}).items()
                    if isinstance(v, int | float) and v >= 0
                }
            except (OSError, ValueError, AttributeError):
                log.warning("Ignoring unreadable %s", path)

    def expected(self, stage: str, key: str, audio_s: float) -> float:
        overhead, rate = DEFAULTS.get(stage, (0.0, 0.0))
        return overhead + self.learned.get(key, rate) * audio_s

    def learn(self, stage: str, key: str, elapsed: float, audio_s: float) -> None:
        if audio_s < MIN_AUDIO_TO_LEARN_S or stage not in DEFAULTS or stage == "download":
            return
        seen = max(elapsed - DEFAULTS[stage][0], 0.0) / audio_s
        old = self.learned.get(key)
        # the first run here replaces the laptop's number; later runs move it halfway
        self.learned[key] = seen if old is None else (old + seen) / 2

    def save(self) -> None:
        if self.path is None:
            return
        try:
            atomic_write_json(self.path, {"version": 1, "rates": self.learned})
        except OSError:
            log.warning("Could not save %s", self.path, exc_info=True)


def fraction_of(state: str) -> float | None:
    """How far a stage is from its message: "37%", "37.5% - 2MiB/s" or "3/10" (item 3 started)."""
    if m := re.match(r"\s*(\d+(?:\.\d+)?)%", state):
        return min(float(m.group(1)) / 100.0, 1.0)
    if m := re.fullmatch(r"(\d+)/(\d+)", state):
        return min((int(m.group(1)) - 1) / max(int(m.group(2)), 1), 1.0)
    return None


@dataclass
class _Current:
    stage: str
    started: float
    fraction: float = 0.0
    first: tuple[float, float] | None = None  # (time, fraction) of the first progress report


@dataclass
class Estimator:
    """Follows one job's progress messages; says how far it is and how long it still needs.

    `plan` is every stage this job may run, in order; stages that will do nothing (speaker
    detection when it is off, ...) are left out so they take no share of the bar or the time.
    """

    plan: list[str]
    audio_s: float
    rates: Rates
    keys: dict[str, str] = field(default_factory=dict)
    clock: Callable[[], float] = time.monotonic
    _done: set[str] = field(default_factory=set)
    _current: _Current | None = None
    _ran: dict[str, float] = field(default_factory=dict)  # stage -> seconds, run in this job

    def key(self, stage: str) -> str:
        return self.keys.get(stage, stage)

    def expected(self, stage: str) -> float:
        return self.rates.expected(stage, self.key(stage), self.audio_s)

    def update(self, stage: str, state: str) -> None:
        now = self.clock()
        if stage not in self.plan:
            return
        if self._current is None or self._current.stage != stage:
            # a new stage: every earlier one is finished or was skipped (still valid)
            self._done.update(self.plan[: self.plan.index(stage)])
            self._current = _Current(stage, now)
        cur = self._current
        if state == "done":
            self._ran[stage] = now - cur.started
            self._done.add(stage)
            self._current = None
            return
        f = fraction_of(state)
        if f is not None:
            cur.fraction = max(cur.fraction, f)
            if cur.first is None:
                cur.first = (now, cur.fraction)

    def _current_remaining(self, now: float) -> tuple[float, float]:
        """(seconds still needed, seconds expected in all) for the stage that is running."""
        cur = self._current
        if cur is None:
            return 0.0, 0.0
        expected = self.expected(cur.stage)
        elapsed = now - cur.started
        prior = expected * (1 - cur.fraction) if cur.fraction > 0 else max(expected - elapsed, 0.0)
        if cur.first is None:
            return prior, expected
        t0, f0 = cur.first
        moved = cur.fraction - f0
        if moved < WARMUP or now <= t0:
            return prior, expected
        own = (now - t0) / moved * (1 - cur.fraction)  # its own pace since it started reporting
        # Early on a stage's pace is noisy (the first sentences may be short), so the expectation
        # still counts; more so when it was learned on this computer than when it is the laptop's.
        ramp = RAMP_LEARNED if self.key(cur.stage) in self.rates.learned else RAMP_DEFAULT
        weight = min(moved / ramp, 1.0)
        return weight * own + (1 - weight) * prior, expected

    def remaining(self) -> float:
        """Seconds until the job should be finished."""
        current, _ = self._current_remaining(self.clock())
        start = self.plan.index(self._current.stage) + 1 if self._current else 0
        later = [s for s in self.plan[start:] if s not in self._done]
        return current + sum(self.expected(s) for s in later)

    def progress(self) -> float:
        """Share of the expected work that is done, 0..1 (for the progress bar)."""
        weights = {s: max(self.expected(s), 0.1) for s in self.plan}
        total = sum(weights.values())
        done = sum(w for s, w in weights.items() if s in self._done)
        if self._current is not None:
            done += weights[self._current.stage] * self._current.fraction
        return min(done / total, 1.0) if total else 0.0

    def learn(self) -> None:
        """Remember how long the stages of this job took on this computer."""
        for stage, seconds in self._ran.items():
            self.rates.learn(stage, self.key(stage), seconds, self.audio_s)
        self.rates.save()

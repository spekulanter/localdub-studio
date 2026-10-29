"""Speech synthesis provider interface."""

from __future__ import annotations

from typing import Protocol

import numpy as np
import numpy.typing as npt

Audio = npt.NDArray[np.float32]


VOICES = [f"F{i}" for i in range(1, 6)] + [f"M{i}" for i in range(1, 6)]


def default_speaker_voices(
    speakers: list[str], base_voice: str, genders: dict[str, str] | None = None
) -> dict[str, str]:
    """Pick a distinct default voice per speaker.

    With estimated genders ('F'/'M') a speaker gets a voice of that gender (the project voice for
    the first speaker of its gender). Without, speakers alternate between the opposite and the same
    gender as the project voice, so neighbours sound different. Extra speakers beyond the 10
    voices reuse the project voice.
    """
    speakers = sorted(set(speakers), key=lambda s: (len(s), s))  # S1, S2, ... S10
    if not speakers:
        return {}
    genders = genders or {}
    base_gender = base_voice[:1]
    other = "M" if base_gender == "F" else "F"
    used: set[str] = set()
    out: dict[str, str] = {}
    for k, sp in enumerate(speakers):
        want = genders.get(sp)
        if want is None:
            want = base_gender if k == 0 else (other if k % 2 == 1 else base_gender)
        pool = [f"{want}{i}" for i in range(1, 6)]
        if want == base_gender and base_voice not in used:
            pool = [base_voice, *[v for v in pool if v != base_voice]]
        free = [v for v in pool if v not in used]
        if not free:
            free = [v for v in VOICES if v not in used]
        voice = free[0] if free else base_voice
        used.add(voice)
        out[sp] = voice
    return out


class TTSProvider(Protocol):
    sample_rate: int
    local_only: bool

    def list_voices(self) -> list[str]: ...

    def unsupported_chars(self, text: str) -> list[str]:
        """Characters of `text` the engine cannot speak (empty if all supported)."""
        ...

    def synthesize(self, text: str, *, voice: str, lang: str, speed: float = 1.0) -> Audio:
        """Return mono float32 samples at self.sample_rate. `speed` > 1 speaks faster."""
        ...

    def close(self) -> None: ...

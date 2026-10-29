"""Speech synthesis provider interface."""

from __future__ import annotations

from typing import Protocol

import numpy as np
import numpy.typing as npt

Audio = npt.NDArray[np.float32]


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

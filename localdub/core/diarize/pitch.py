"""Rough speaker gender from median fundamental frequency (a heuristic, not a classifier).

Typical speaking F0: men 85-155 Hz, women 165-255 Hz. Children, singing, whispering and strong
audio effects break this, so the result is only used to choose a *default* voice, which the user
can change per speaker.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import numpy.typing as npt

from localdub.core.diarize.assign import SpeakerTurn

FEMALE_MIN_HZ = 165.0


def median_f0(samples: npt.NDArray[np.float32], sr: int) -> float | None:
    """Median F0 of voiced frames (autocorrelation); None if there is too little voiced audio."""
    n, hop = int(0.04 * sr), int(0.02 * sr)
    lo, hi = int(sr / 400), int(sr / 70)
    if samples.size < n * 5:
        return None
    window = np.hanning(n).astype(np.float32)
    found: list[float] = []
    for i in range(0, samples.size - n, hop):
        w = samples[i : i + n]
        w = (w - w.mean()) * window
        energy = float(np.dot(w, w))
        if energy < 1e-4 * n * 0.01:
            continue
        spec = np.fft.rfft(w, 2 * n)
        ac = np.fft.irfft(spec * np.conj(spec))[:n]
        k = lo + int(np.argmax(ac[lo:hi]))
        if ac[k] / ac[0] > 0.45:
            found.append(sr / k)
    return float(np.median(found)) if len(found) >= 10 else None


def estimate_speaker_f0(
    samples: npt.NDArray[np.float32], sr: int, turns: list[SpeakerTurn]
) -> dict[str, float]:
    """Median F0 per speaker label ('S1', ...) from that speaker's turns."""
    by_speaker: dict[int, list[npt.NDArray[np.float32]]] = {}
    for t in turns:
        by_speaker.setdefault(t.speaker, []).append(samples[int(t.start * sr) : int(t.end * sr)])
    out: dict[str, float] = {}
    for spk, parts in by_speaker.items():
        f0 = median_f0(np.concatenate(parts), sr)
        if f0 is not None:
            out[f"S{spk + 1}"] = round(f0, 1)
    return out


def gender_of(f0: float) -> str:
    return "F" if f0 >= FEMALE_MIN_HZ else "M"


def load_speaker_genders(diarization_json: Path) -> dict[str, str]:
    """{'S1': 'M', ...} from the diarize stage output; empty if unavailable."""
    try:
        data = json.loads(diarization_json.read_text(encoding="utf-8"))
        return {k: gender_of(float(v)) for k, v in data.get("speaker_f0", {}).items()}
    except (OSError, ValueError, TypeError):
        return {}

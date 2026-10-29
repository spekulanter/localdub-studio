"""Build a dialogue-only track on the original video timeline."""

from __future__ import annotations

import numpy as np

from localdub.core.tts.base import Audio


def db_to_gain(db: float) -> float:
    return float(10 ** (db / 20))


def normalize_rms(x: Audio, target_dbfs: float, peak_limit: float = 0.95) -> Audio:
    rms = float(np.sqrt(np.mean(np.square(x)))) if x.size else 0.0
    if rms < 1e-6:
        return x
    y = x * (db_to_gain(target_dbfs) / rms)
    peak = float(np.max(np.abs(y)))
    if peak > peak_limit:
        y *= peak_limit / peak
    return y.astype(np.float32)


def build_timeline(clips: list[tuple[float, Audio]], duration: float, sample_rate: int) -> Audio:
    """Silence everywhere except where clips are placed (start seconds, mono samples).

    The result has exactly round(duration * sample_rate) samples; a clip running past the
    end of the video is cut at the video end (callers flag this as overflow beforehand).
    """
    n = int(round(duration * sample_rate))
    track = np.zeros(n, dtype=np.float32)
    for start, clip in clips:
        i = int(round(start * sample_rate))
        if i >= n:
            continue
        j = min(i + clip.size, n)
        track[i:j] += clip[: j - i]
    np.clip(track, -1.0, 1.0, out=track)
    return track


def trim_silence(
    x: Audio, sample_rate: int, threshold_db: float = -45.0, pad_s: float = 0.03
) -> Audio:
    """Remove leading/trailing near-silence, keeping a short pad."""
    if x.size == 0:
        return x
    loud = np.flatnonzero(np.abs(x) > db_to_gain(threshold_db))
    if loud.size == 0:
        return x[:0]
    pad = int(pad_s * sample_rate)
    return x[max(loud[0] - pad, 0) : min(loud[-1] + pad + 1, x.size)]

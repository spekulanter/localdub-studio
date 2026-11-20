"""Voice-over mixing: duck the original audio under the dub."""

from __future__ import annotations

import numpy as np
import numpy.typing as npt

from localdub.core.audio.assemble import db_to_gain
from localdub.core.tts.base import Audio


def duck_envelope(
    n_samples: int,
    regions: list[tuple[float, float]],
    sample_rate: int,
    duck_db: float,
    ramp_s: float,
    offset: int = 0,
) -> Audio:
    """Gain curve: 1.0 outside regions, duck gain inside, linear ramps of ramp_s at edges.

    Covers samples [offset, offset + n_samples) of the whole timeline, so a long track can be
    processed block by block with the same result as in one piece.
    """
    low = db_to_gain(duck_db)
    depth = np.zeros(n_samples, dtype=np.float32)  # 0 = no ducking, 1 = fully ducked
    ramp = max(int(ramp_s * sample_rate), 1)
    for start, end in regions:
        a = int(start * sample_rate) - offset
        b = int(end * sample_rate) - offset
        lo, hi = max(a - ramp, 0), min(b + ramp, n_samples)
        if lo >= hi:
            continue
        idx = np.arange(lo, hi)
        d = np.ones(hi - lo, dtype=np.float32)
        d = np.minimum(d, np.clip((idx - (a - ramp)) / ramp, 0, 1))
        d = np.minimum(d, np.clip(((b + ramp) - idx) / ramp, 0, 1))
        depth[lo:hi] = np.maximum(depth[lo:hi], d)
    return (1.0 - depth * (1.0 - low)).astype(np.float32)


def duck_and_add(
    original: npt.NDArray[np.float32], dub: Audio, env: Audio | None
) -> npt.NDArray[np.float32]:
    """original * env + dub (same length); env None = the original muted (dub alone)."""
    if env is None:
        if original.ndim == 2:
            return np.broadcast_to(dub[:, None], original.shape).copy()
        return dub.copy()
    if original.ndim == 2:
        out: npt.NDArray[np.float32] = original * env[:, None] + dub[:, None]
        return out
    return original * env + dub


def voice_over_mix(
    original: npt.NDArray[np.float32],
    dub: Audio,
    regions: list[tuple[float, float]],
    sample_rate: int,
    duck_db: float = -14.0,
    ramp_s: float = 0.15,
    mute_original: bool = False,
) -> npt.NDArray[np.float32]:
    """original: (n,) or (n, channels); dub: (n,) mono. Returns the shape of `original`.

    With `mute_original` the result is the dub alone (copied to every channel).
    """
    n = original.shape[0]
    if dub.size != n:
        dub = np.pad(dub, (0, max(n - dub.size, 0)))[:n]
    env = None if mute_original else duck_envelope(n, regions, sample_rate, duck_db, ramp_s)
    out = duck_and_add(original, dub, env)
    peak = float(np.max(np.abs(out))) if out.size else 0.0
    if peak > 0.99:
        out *= 0.99 / peak
    return out.astype(np.float32)

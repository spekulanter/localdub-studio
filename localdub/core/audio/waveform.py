"""Waveform overview for the timeline: peak amplitude per 10 ms, as one byte each."""

from __future__ import annotations

import base64
from pathlib import Path

import numpy as np
import soundfile as sf

BINS_PER_SECOND = 100


def compute_peaks(path: Path, bins_per_second: int = BINS_PER_SECOND) -> bytes:
    """Max absolute amplitude (all channels) of every 1/bins_per_second s, scaled to 0..255.

    Reads the file in blocks, so a one-hour recording needs no more memory than a short one.
    The scaling is relative to full scale (not normalised) so quiet audio looks quiet.
    """
    with sf.SoundFile(str(path)) as f:
        per_bin = max(f.samplerate // bins_per_second, 1)
        block = per_bin * 4096
        out = bytearray()
        carry = np.zeros(0, np.float32)
        for chunk in f.blocks(blocksize=block, dtype="float32", always_2d=True):
            mono = np.abs(chunk).max(axis=1)
            data = np.concatenate([carry, mono]) if carry.size else mono
            usable = (data.size // per_bin) * per_bin
            if usable:
                peaks = data[:usable].reshape(-1, per_bin).max(axis=1)
                out += np.minimum(peaks * 255.0 + 0.5, 255.0).astype(np.uint8).tobytes()
            carry = data[usable:]
        if carry.size:
            out.append(int(min(float(carry.max()) * 255.0 + 0.5, 255.0)))
    return bytes(out)


def peaks_payload(path: Path, bins_per_second: int = BINS_PER_SECOND) -> dict[str, object]:
    peaks = compute_peaks(path, bins_per_second)
    with sf.SoundFile(str(path)) as f:
        duration = f.frames / f.samplerate
    return {
        "available": True,
        "duration": round(duration, 3),
        "bins_per_second": bins_per_second,
        "peaks": base64.b64encode(peaks).decode("ascii"),
    }

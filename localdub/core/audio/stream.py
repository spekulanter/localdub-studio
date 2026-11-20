"""Block-wise versions of the assemble steps, for videos too long to hold in memory.

A 6-hour video is about 1.1 billion samples per channel at 48 kHz: the dub track alone is
4.6 GB as float32 and the stereo original twice that. These functions read and write WAV
files in blocks of about a second, so memory use does not depend on the length of the video.
Each gives the same samples as its in-memory counterpart (`build_timeline`, `voice_over_mix`).
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import numpy.typing as npt
import soundfile as sf

from localdub.core.audio.mix import duck_and_add, duck_envelope
from localdub.core.tts.base import Audio

BLOCK_FRAMES = 1 << 16  # about 1.4 s at 48 kHz (small blocks measured faster than big ones)
WAV_LIMIT = 0xFFFF_0000  # bytes of audio a plain RIFF/WAV header can describe (4 GB)


def pcm16_writer(path: Path, sample_rate: int, channels: int, frames: int) -> sf.SoundFile:
    """16-bit WAV writer; RF64 when the data would not fit the 4 GB WAV limit."""
    fmt = "RF64" if frames * channels * 2 >= WAV_LIMIT else "WAV"
    return sf.SoundFile(
        str(path), "w", samplerate=sample_rate, channels=channels, subtype="PCM_16", format=fmt
    )


@dataclass(frozen=True)
class ClipRef:
    start: int  # first sample on the timeline
    frames: int  # length in samples
    path: Path


def write_timeline(
    dst: Path,
    clips: list[ClipRef],
    n_frames: int,
    sample_rate: int,
    load: Callable[[Path], Audio],
    block: int = BLOCK_FRAMES,
) -> None:
    """Like build_timeline, but clips are loaded only while a block overlaps them.

    `load` returns a clip's mono samples (normalised as the caller wishes; same length as
    `frames`). The track is cut at n_frames and clipped to [-1, 1].
    """
    order = sorted((c for c in clips if c.start < n_frames and c.frames > 0), key=lambda c: c.start)
    loaded: dict[int, Audio] = {}
    nxt = 0  # first clip in `order` not loaded yet
    with pcm16_writer(dst, sample_rate, 1, n_frames) as out:
        for b0 in range(0, n_frames, block):
            b1 = min(b0 + block, n_frames)
            while nxt < len(order) and order[nxt].start < b1:
                loaded[nxt] = load(order[nxt].path)
                nxt += 1
            track = np.zeros(b1 - b0, dtype=np.float32)
            for k in list(loaded):
                clip, ref = loaded[k], order[k]
                i, j = max(ref.start, b0), min(ref.start + clip.size, b1)
                if i < j:
                    track[i - b0 : j - b0] += clip[i - ref.start : j - ref.start]
                if ref.start + clip.size <= b1:
                    del loaded[k]  # finished: free it
            np.clip(track, -1.0, 1.0, out=track)
            out.write(track)


def fit_length(src: Path, dst: Path, n_frames: int, block: int = BLOCK_FRAMES) -> None:
    """Copy a mono WAV to 16-bit PCM of exactly n_frames (cut, or padded with silence)."""
    with sf.SoundFile(str(src)) as f, pcm16_writer(dst, f.samplerate, 1, n_frames) as out:
        done = 0
        while done < n_frames:
            want = min(block, n_frames - done)
            data = f.read(want, dtype="float32", always_2d=True)[:, 0]
            if data.size < want:
                data = np.pad(data, (0, want - data.size))
            out.write(data)
            done += want


@dataclass(frozen=True)
class MixSpec:
    original: Path  # (n,) or (n, channels) at the dub's sample rate
    dub: Path  # mono; its length is the length of the mix
    regions: list[tuple[float, float]]
    duck_db: float
    ramp_s: float
    mute_original: bool = False


def _mix_blocks(spec: MixSpec, block: int) -> Iterator[npt.NDArray[np.float32]]:
    """The un-normalised voice-over mix, block by block, shaped (frames, channels)."""
    with sf.SoundFile(str(spec.original)) as orig, sf.SoundFile(str(spec.dub)) as dub_f:
        sr, n, channels = dub_f.samplerate, dub_f.frames, orig.channels
        if orig.samplerate != sr:
            raise ValueError(f"Original audio has {orig.samplerate} Hz, expected {sr}")
        starts = np.array([r[0] for r in spec.regions], dtype=np.float64)
        ends = np.array([r[1] for r in spec.regions], dtype=np.float64)
        ramp = max(int(spec.ramp_s * sr), 1)
        for b0 in range(0, n, block):
            m = min(block, n - b0)
            dub = dub_f.read(m, dtype="float32", always_2d=True)[:, 0]
            dub = np.pad(dub, (0, m - dub.size)) if dub.size < m else dub
            if spec.mute_original:
                original = np.zeros((m, channels), np.float32)
                env = None
            else:
                original = orig.read(m, dtype="float32", always_2d=True)
                if original.shape[0] < m:  # the original ends early: silence after it
                    original = np.pad(original, ((0, m - original.shape[0]), (0, 0)))
                near = ((starts * sr).astype(np.int64) - ramp < b0 + m) & (
                    (ends * sr).astype(np.int64) + ramp > b0
                )
                regions = [spec.regions[i] for i in np.flatnonzero(near)]
                env = duck_envelope(m, regions, sr, spec.duck_db, spec.ramp_s, offset=b0)
            yield duck_and_add(original, dub, env)


def mix_peak(spec: MixSpec, block: int = BLOCK_FRAMES) -> float:
    """Largest absolute sample of the un-normalised mix."""
    peak = 0.0
    for out in _mix_blocks(spec, block):
        if out.size:
            peak = max(peak, float(np.max(np.abs(out))))
    return peak


def write_mix(spec: MixSpec, dst: Path, gain: float, block: int = BLOCK_FRAMES) -> None:
    """Write the mix times `gain` as 16-bit PCM (same channels as the original)."""
    with sf.SoundFile(str(spec.original)) as f:
        channels = f.channels
    info = sf.info(str(spec.dub))
    with pcm16_writer(dst, info.samplerate, channels, info.frames) as out:
        for data in _mix_blocks(spec, block):
            out.write(np.clip(data * np.float32(gain), -1.0, 1.0))

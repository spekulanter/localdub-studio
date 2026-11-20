"""Block-wise assemble (dub track and voice-over mix) gives the same audio as the in-memory code.

Blocks are made tiny (a few hundred samples) so clips, ducking ramps and the end of the file
all fall across block edges.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from localdub.core.audio.assemble import build_timeline, normalize_rms
from localdub.core.audio.mix import voice_over_mix
from localdub.core.audio.stream import (
    ClipRef,
    MixSpec,
    fit_length,
    mix_peak,
    pcm16_writer,
    write_mix,
    write_timeline,
)

SR = 1000
PCM16 = 1.0 / 32768


def _pcm(x: np.ndarray) -> np.ndarray:
    """Full-scale clipping, as 16-bit PCM does (the rounding is left to the tolerance)."""
    return np.clip(x, -1.0, 1.0)


def _clip(path: Path, frames: int, freq: float, amp: float = 0.5) -> np.ndarray:
    t = np.arange(frames) / SR
    data = (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    sf.write(path, data, SR, subtype="PCM_16")
    return sf.read(str(path), dtype="float32")[0]


@pytest.fixture
def clips(tmp_path):
    dirs = tmp_path / "klipy ľšč"
    dirs.mkdir()
    spec = [(0.0, 300, 7.0), (0.25, 500, 11.0), (1.4, 900, 5.0), (2.9, 400, 3.0), (9.0, 50, 2.0)]
    out = []
    for i, (start, frames, freq) in enumerate(spec):
        path = dirs / f"seg_{i}.wav"
        out.append((start, _clip(path, frames, freq), path))
    return out  # (start s, samples as on disk, path); clip 1 overlaps 0, clip 3 runs past 3 s


def _load(path: Path) -> np.ndarray:
    return normalize_rms(sf.read(str(path), dtype="float32")[0].reshape(-1), -20.0)


@pytest.mark.parametrize("block", [64, 333, 1 << 20])
def test_timeline_matches_build_timeline(tmp_path, clips, block):
    duration = 3.0
    expected = build_timeline([(s, _load(p)) for s, _, p in clips], duration, SR)
    loaded: list[Path] = []

    def load(path: Path) -> np.ndarray:
        loaded.append(path)
        return _load(path)

    refs = [ClipRef(int(round(s * SR)), d.size, p) for s, d, p in clips]
    write_timeline(tmp_path / "dub.wav", refs, int(round(duration * SR)), SR, load, block=block)
    got = sf.read(str(tmp_path / "dub.wav"), dtype="float32")[0]
    assert got.shape == expected.shape == (3000,)
    np.testing.assert_allclose(got, _pcm(expected), atol=2 * PCM16)
    assert len(loaded) == 4  # each clip read once; the one after the end never


def test_timeline_releases_finished_clips(tmp_path):
    """Memory: a clip is dropped once the blocks have passed it (not all held to the end)."""
    import gc
    import weakref

    refs = []
    for i in range(50):
        path = tmp_path / f"c{i}.wav"
        _clip(path, 80, 5.0)
        refs.append(ClipRef(i * 100, 80, path))
    issued: list[weakref.ref[np.ndarray]] = []
    alive_at_load: list[int] = []

    def load(path: Path) -> np.ndarray:
        gc.collect()
        alive_at_load.append(sum(r() is not None for r in issued))
        data = sf.read(str(path), dtype="float32")[0]
        issued.append(weakref.ref(data))
        return data

    write_timeline(tmp_path / "dub.wav", refs, 5000, SR, load, block=100)
    assert len(issued) == 50
    assert max(alive_at_load) <= 2


def test_fit_length_pads_and_cuts(tmp_path):
    src = tmp_path / "in.wav"
    data = _clip(src, 250, 4.0)
    fit_length(src, tmp_path / "long.wav", 400, block=64)
    fit_length(src, tmp_path / "short.wav", 100, block=64)
    long = sf.read(str(tmp_path / "long.wav"), dtype="float32")[0]
    short = sf.read(str(tmp_path / "short.wav"), dtype="float32")[0]
    np.testing.assert_allclose(long[:250], data, atol=PCM16)
    assert long.size == 400 and not long[250:].any()
    np.testing.assert_allclose(short, data[:100], atol=PCM16)


def _original(path: Path, frames: int, channels: int, amp: float) -> np.ndarray:
    rng = np.random.default_rng(1)
    data = (amp * rng.uniform(-1, 1, (frames, channels))).astype(np.float32)
    sf.write(path, data, SR, subtype="PCM_16")
    return sf.read(str(path), dtype="float32", always_2d=True)[0]


@pytest.mark.parametrize("channels", [1, 2])
@pytest.mark.parametrize("orig_frames", [3000, 2500, 3600])  # same, shorter, longer than dub
@pytest.mark.parametrize("mute", [False, True])
@pytest.mark.parametrize("block", [64, 1 << 20])
def test_mix_matches_voice_over_mix(tmp_path, channels, orig_frames, mute, block):
    dub_path = tmp_path / "dub.wav"
    dub = _clip(dub_path, 3000, 9.0, amp=0.9)
    original = _original(tmp_path / "orig.wav", orig_frames, channels, amp=0.6)
    regions = [(0.1, 0.6), (0.65, 1.2), (2.7, 3.4)]  # touching ramps; one past the end
    spec = MixSpec(tmp_path / "orig.wav", dub_path, regions, -14.0, 0.15, mute_original=mute)

    padded = np.pad(original, ((0, max(3000 - orig_frames, 0)), (0, 0)))[:3000]
    expected = voice_over_mix(padded, dub, regions, SR, -14.0, 0.15, mute_original=mute)

    peak = mix_peak(spec, block=block)
    gain = 0.99 / peak if peak > 0.99 else 1.0
    write_mix(spec, tmp_path / "mix.wav", gain * 0.8, block=block)  # 0.8: a loudness cap
    got = sf.read(str(tmp_path / "mix.wav"), dtype="float32", always_2d=True)[0]
    assert got.shape == (3000, channels)
    np.testing.assert_allclose(got, _pcm(expected * 0.8), atol=2 * PCM16)


def test_mix_rejects_a_wrong_sample_rate(tmp_path):
    _clip(tmp_path / "dub.wav", 100, 3.0)
    sf.write(tmp_path / "orig.wav", np.zeros(100, np.float32), 2 * SR)
    spec = MixSpec(tmp_path / "orig.wav", tmp_path / "dub.wav", [], -14.0, 0.15)
    with pytest.raises(ValueError, match="2000 Hz"):
        mix_peak(spec)


def test_large_files_switch_to_rf64(tmp_path):
    with pcm16_writer(tmp_path / "small.wav", SR, 2, 1000):
        pass
    with pcm16_writer(tmp_path / "big.wav", SR, 2, 1_100_000_000):  # 6.4 h at 48 kHz stereo
        pass
    assert sf.info(str(tmp_path / "small.wav")).format == "WAV"
    assert sf.info(str(tmp_path / "big.wav")).format == "RF64"

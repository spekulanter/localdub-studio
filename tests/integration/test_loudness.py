from __future__ import annotations

import numpy as np
import pytest
import soundfile as sf

from localdub.core.media.ffmpeg import FFmpeg


@pytest.fixture(scope="module")
def tone(tmp_path_factory):
    path = tmp_path_factory.mktemp("loud") / "tone ľš.wav"
    t = np.arange(48000 * 4) / 48000
    sf.write(path, (0.1 * np.sin(2 * np.pi * 440 * t)).astype(np.float32), 48000, subtype="PCM_16")
    return path


def test_measure_lufs_matches_the_known_level_of_a_sine(tone):
    # A 0.1-amplitude sine is about -23 LUFS (20 dB below full scale, less K-weighting).
    lufs = FFmpeg().measure_lufs(tone)
    assert lufs is not None and -26.0 < lufs < -22.0


def test_measure_lufs_of_silence_is_none(tmp_path):
    path = tmp_path / "silence.wav"
    sf.write(path, np.zeros(48000, np.float32), 48000, subtype="PCM_16")
    assert FFmpeg().measure_lufs(path) is None


def test_gain_with_limiter_raises_level_without_exceeding_the_limit(tone, tmp_path):
    ff = FFmpeg()
    out = tmp_path / "louder.wav"
    before = ff.measure_lufs(tone)
    ff.gain_with_limiter(tone, out, gain_db=+12.0, limit=0.95)
    data, sr = sf.read(out, dtype="float32")
    assert sr == 48000 and abs(data).max() <= 0.951
    after = ff.measure_lufs(out)
    assert before is not None and after is not None and after > before + 5

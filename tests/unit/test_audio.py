import numpy as np
import pytest

from localdub.core.audio.assemble import build_timeline, normalize_rms, trim_silence
from localdub.core.audio.mix import duck_envelope, voice_over_mix


def test_build_timeline_exact_placement_padding_cut_and_ignore():
    out = build_timeline(
        [
            (0.2, np.array([0.2, 0.3], np.float32)),
            (0.8, np.ones(5, np.float32)),
            (2, np.ones(2, np.float32)),
        ],
        1,
        10,
    )
    assert out.shape == (10,)
    assert np.allclose(out[2:4], [0.2, 0.3])
    assert np.allclose(out[:2], 0) and np.allclose(out[4:8], 0)
    assert np.allclose(out[8:], 1)


def test_normalize_rms_and_peak_limit():
    x = np.full(100, 0.1, np.float32)
    y = normalize_rms(x, -20, 0.5)
    assert np.sqrt(np.mean(y**2)) == pytest.approx(0.1)
    z = normalize_rms(np.array([0.1, 1], np.float32), 0, 0.5)
    assert np.max(np.abs(z)) == pytest.approx(0.5)


def test_trim_silence_with_padding():
    x = np.array([0, 0, 0.5, 0.5, 0], np.float32)
    assert np.array_equal(trim_silence(x, 10, pad_s=0.1), x[1:5])


def test_duck_envelope_and_mix_shapes_padding_and_peak():
    env = duck_envelope(100, [(0.3, 0.7)], 100, -20, 0.1)
    assert env[0] == pytest.approx(1)
    assert env[25] < env[20] and env[30] == pytest.approx(10 ** (-20 / 20))
    assert env[60] == pytest.approx(10 ** (-20 / 20))
    assert env[80] > env[70] and env[-1] == pytest.approx(1)
    mono = voice_over_mix(np.ones(100, np.float32), np.ones(20, np.float32), [], 100)
    stereo = voice_over_mix(np.ones((100, 2), np.float32), np.ones(20, np.float32), [], 100)
    assert mono.shape == (100,) and stereo.shape == (100, 2)
    assert np.max(np.abs(mono)) <= 0.99 and np.max(np.abs(stereo)) <= 0.99

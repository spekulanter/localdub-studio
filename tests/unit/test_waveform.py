from __future__ import annotations

import base64

import numpy as np
import soundfile as sf

from localdub.core.audio.waveform import BINS_PER_SECOND, compute_peaks, peaks_payload


def write(path, data, sr=8000):
    sf.write(path, data.astype(np.float32), sr, subtype="FLOAT")


def test_peaks_follow_the_loudness_of_each_10_ms(tmp_path):
    sr = 8000
    quiet = 0.1 * np.sin(np.linspace(0, 200, sr))  # 1 s at 0.1
    loud = 0.8 * np.sin(np.linspace(0, 200, sr))  # 1 s at 0.8
    path = tmp_path / "a.wav"
    write(path, np.concatenate([quiet, np.zeros(sr), loud]))
    peaks = np.frombuffer(compute_peaks(path), np.uint8)
    assert len(peaks) == 3 * BINS_PER_SECOND
    assert 20 <= peaks[:100].max() <= 27 and peaks[100:200].max() == 0
    assert 195 <= peaks[200:].max() <= 205


def test_uses_the_loudest_channel_and_never_exceeds_255(tmp_path):
    sr = 8000
    left = np.full(sr, 0.2)
    right = np.full(sr, 1.0)
    path = tmp_path / "s.wav"
    write(path, np.stack([left, right], axis=1))
    peaks = np.frombuffer(compute_peaks(path), np.uint8)
    assert peaks.min() == 255 and peaks.max() == 255
    over = tmp_path / "o.wav"
    write(over, np.full(sr, 1.7))  # float WAV may exceed full scale
    assert np.frombuffer(compute_peaks(over), np.uint8).max() == 255


def test_block_boundaries_do_not_change_the_result(tmp_path):
    sr = 16000
    rng = np.random.default_rng(1)
    data = rng.uniform(-0.5, 0.5, sr * 30)  # long enough for several read blocks
    path = tmp_path / "r.wav"
    write(path, data, sr)
    peaks = np.frombuffer(compute_peaks(path), np.uint8)
    per_bin = sr // BINS_PER_SECOND
    expected = np.abs(data.astype(np.float32)).reshape(-1, per_bin).max(axis=1)
    assert np.array_equal(peaks, np.minimum(expected * 255 + 0.5, 255).astype(np.uint8))


def test_a_partial_last_bin_is_kept_and_payload_is_base64(tmp_path):
    sr = 8000
    path = tmp_path / "p.wav"
    write(path, np.concatenate([np.zeros(sr), np.full(40, 0.5)]))  # 1 s + 5 ms
    payload = peaks_payload(path)
    peaks = base64.b64decode(str(payload["peaks"]))
    assert len(peaks) == BINS_PER_SECOND + 1 and peaks[-1] == 128
    assert payload["available"] is True and payload["duration"] == 1.005

"""Block-wise Demucs separation: memory stays bounded and the blocks join without seams.

The model is replaced by a linear stand-in (vocals = 0.3 * mix, background = 0.7 * mix):
for a linear map the cross-fade must give back exactly the unchunked result.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from localdub.core.separation.demucs_separator import audio_stats, separate_in_chunks

RATE = 1000
PCM16 = 1.0 / 32768  # one 16-bit step


def _write(path: Path, data: np.ndarray) -> np.ndarray:
    sf.write(path, data, RATE, subtype="PCM_16")
    return sf.read(str(path), dtype="float32", always_2d=True)[0]  # as quantised on disk


def _signal(frames: int, channels: int = 2, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    t = np.arange(frames)[:, None] / RATE
    tone = 0.4 * np.sin(2 * np.pi * 3.0 * t + np.arange(channels))
    return (tone + 0.1 * rng.standard_normal((frames, channels))).astype(np.float32)


def _run(tmp_path: Path, mix: np.ndarray, chunk: int, overlap: int):
    src = _write(tmp_path / "in ľšč.wav", mix)
    calls: list[int] = []
    progress: list[tuple[int, int]] = []

    def fake_model(block: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        assert block.ndim == 2 and block.shape[1] == 2
        calls.append(block.shape[0])
        return 0.3 * block, 0.7 * block

    voc, bg = tmp_path / "vocals.wav", tmp_path / "background.wav"
    frames = separate_in_chunks(
        tmp_path / "in ľšč.wav",
        voc,
        bg,
        fake_model,
        chunk_frames=chunk,
        overlap_frames=overlap,
        on_progress=lambda d, t: progress.append((d, t)),
    )
    stereo = src if src.shape[1] == 2 else np.repeat(src, 2, axis=1)
    return stereo, frames, calls, progress, sf.read(str(voc))[0], sf.read(str(bg))[0]


@pytest.mark.parametrize(
    ("frames", "chunk", "overlap"),
    [
        (500, 1000, 100),  # shorter than one block
        (3000, 1000, 100),  # exact multiple of the block
        (3456, 1000, 100),  # ragged last block
        (3050, 1000, 100),  # last block shorter than the overlap
        (2500, 1000, 0),  # no cross-fade
    ],
)
def test_chunks_join_without_seams(tmp_path, frames, chunk, overlap):
    stereo, n, calls, progress, voc, bg = _run(tmp_path, _signal(frames), chunk, overlap)
    assert n == frames
    assert voc.shape == bg.shape == (frames, 2)
    np.testing.assert_allclose(voc, 0.3 * stereo, atol=2 * PCM16)
    np.testing.assert_allclose(bg, 0.7 * stereo, atol=2 * PCM16)
    assert max(calls) <= chunk + overlap  # the model never sees more than one block
    assert progress == [(i + 1, len(calls)) for i in range(len(calls))]  # ends at n/n


def test_mono_input_becomes_stereo(tmp_path):
    stereo, _, _, _, voc, _ = _run(tmp_path, _signal(1800, channels=1), 1000, 100)
    np.testing.assert_allclose(voc[:, 0], voc[:, 1])
    np.testing.assert_allclose(voc, 0.3 * stereo, atol=2 * PCM16)


def test_outputs_are_clipped_not_wrapped(tmp_path):
    _write(tmp_path / "in.wav", np.full((1200, 2), 0.9, np.float32))
    voc, bg = tmp_path / "v.wav", tmp_path / "b.wav"
    separate_in_chunks(
        tmp_path / "in.wav", voc, bg, lambda b: (2 * b, -2 * b), chunk_frames=500, overlap_frames=50
    )
    assert sf.read(str(voc))[0].min() > 0.99
    assert sf.read(str(bg))[0].max() < -0.99


def test_outputs_are_rf64(tmp_path):
    _write(tmp_path / "in.wav", _signal(100))
    voc, bg = tmp_path / "v.wav", tmp_path / "b.wav"
    separate_in_chunks(
        tmp_path / "in.wav", voc, bg, lambda b: (b, b), chunk_frames=50, overlap_frames=5
    )
    assert sf.info(str(voc)).format == "RF64"  # no 4 GB limit on long videos


def test_bad_block_sizes_are_rejected(tmp_path):
    _write(tmp_path / "in.wav", _signal(100))
    with pytest.raises(ValueError):
        separate_in_chunks(
            tmp_path / "in.wav", tmp_path / "v.wav", tmp_path / "b.wav", lambda b: (b, b),
            chunk_frames=100, overlap_frames=100,
        )  # fmt: skip


def test_audio_stats_match_numpy(tmp_path, monkeypatch):
    import localdub.core.separation.demucs_separator as mod

    monkeypatch.setattr(mod, "STATS_BLOCK", 333)  # several blocks
    data = _write(tmp_path / "in.wav", _signal(2000) + 0.05)
    mean, std = audio_stats(tmp_path / "in.wav")
    assert mean == pytest.approx(float(data.mean()), abs=1e-6)
    assert std == pytest.approx(float(data.std(ddof=1)), rel=1e-5)

"""Dialogue/background separation with Demucs (htdemucs). Experimental, optional, needs PyTorch.

Installed from inside the app (see localdub/extras.py). The model weights (about 80 MB,
safetensors) are downloaded on first use from the Hugging Face repository `adefossez/HTDemucs`
(the `main` branch: the revision is not pinned by Demucs 4.1.0). Code is MIT-licensed
(facebookresearch/demucs).

The audio is separated in blocks of a few minutes that are written straight to disk, so memory
use does not grow with the length of the video (a 6-hour recording held whole needs >30 GB).
Neighbouring blocks overlap by a few seconds and are cross-faded, which hides the edges where
the model had no context.
"""

from __future__ import annotations

import gc
import logging
import os
from collections.abc import Callable
from pathlib import Path

import numpy as np
import numpy.typing as npt
import soundfile as sf

log = logging.getLogger(__name__)

Audio = npt.NDArray[np.float32]  # (samples, 2)
ChunkFn = Callable[[Audio], tuple[Audio, Audio]]  # stereo block -> (vocals, background)
ProgressFn = Callable[[int, int], None]  # (blocks done, blocks total)

CHUNK_S = 180.0  # seconds of audio per block given to the model
OVERLAP_S = 5.0  # cross-fade between neighbouring blocks
STATS_BLOCK = 1 << 20  # frames read at a time while measuring the whole file


class SeparationUnavailable(RuntimeError):
    """PyTorch/Demucs are not installed."""


def _stereo(block: npt.NDArray[np.float32]) -> Audio:
    if block.shape[1] >= 2:
        return np.ascontiguousarray(block[:, :2])
    return np.repeat(block, 2, axis=1)


def audio_stats(path: Path) -> tuple[float, float]:
    """Mean and (sample) standard deviation of all stereo samples, read in blocks."""
    total = 0.0
    total_sq = 0.0
    n = 0
    with sf.SoundFile(str(path)) as f:
        for block in f.blocks(blocksize=STATS_BLOCK, dtype="float32", always_2d=True):
            x = _stereo(block).astype(np.float64)
            total += float(x.sum())
            total_sq += float(np.square(x).sum())
            n += x.size
    if n == 0:
        return 0.0, 1e-8
    mean = total / n
    var = max(total_sq - n * mean * mean, 0.0) / max(n - 1, 1)
    return mean, float(np.sqrt(var)) + 1e-8


def _writer(path: Path, sample_rate: int) -> sf.SoundFile:
    # RF64: a plain WAV cannot hold more than 4 GB (about 6.7 h of 16-bit stereo at 44.1 kHz).
    return sf.SoundFile(
        str(path), "w", samplerate=sample_rate, channels=2, subtype="PCM_16", format="RF64"
    )


def separate_in_chunks(
    src: Path,
    vocals_path: Path,
    background_path: Path,
    run_chunk: ChunkFn,
    *,
    chunk_frames: int,
    overlap_frames: int,
    on_progress: ProgressFn | None = None,
) -> int:
    """Separate `src` block by block into two 16-bit stereo RF64 WAVs; returns the frame count.

    Block i covers [i*C, (i+1)*C + O). Its last O frames are kept back and cross-faded
    (linear, the two weights add up to 1) with the first O frames of block i+1.
    """
    if chunk_frames <= 0 or not 0 <= overlap_frames < chunk_frames:
        raise ValueError("need chunk_frames > overlap_frames >= 0")
    with sf.SoundFile(str(src)) as f:
        total, rate = f.frames, f.samplerate
        # the last block also covers the overlap, so it may reach the end one block early
        n_chunks = max(1, -(-(total - overlap_frames) // chunk_frames))
        tail: list[Audio] = []  # per output: the frames still waiting for their cross-fade
        with _writer(vocals_path, rate) as w_voc, _writer(background_path, rate) as w_bg:
            for i in range(n_chunks):
                start = i * chunk_frames
                end = min(start + chunk_frames + overlap_frames, total)
                f.seek(start)
                block = _stereo(f.read(end - start, dtype="float32", always_2d=True))
                if block.shape[0] == 0:
                    break
                stems = run_chunk(block)
                head = tail[0].shape[0] if tail else 0
                fade_in = np.linspace(0.0, 1.0, head + 2, dtype=np.float32)[1:-1, None]
                last = end >= total
                keep = block.shape[0] if last else chunk_frames
                new_tail: list[Audio] = []
                for k, (w, stem) in enumerate(zip((w_voc, w_bg), stems, strict=True)):
                    if head:
                        mixed = tail[k] * (1.0 - fade_in) + stem[:head] * fade_in
                        w.write(np.clip(mixed, -1.0, 1.0))
                    w.write(np.clip(stem[head:keep], -1.0, 1.0))
                    if not last:
                        new_tail.append(stem[keep:].copy())
                tail = new_tail
                del stems, block
                if on_progress:
                    on_progress(i + 1, n_chunks)
                if last:
                    break
    return int(total)


class DemucsSeparator:
    local_only = True
    MODEL = "htdemucs"

    def __init__(self, models_dir: Path, device: str | None = None) -> None:
        os.environ.setdefault("TORCH_HOME", str(models_dir / "torch"))  # unused by 4.1.0 (HF cache)
        try:
            import torch
            from demucs.pretrained import get_model
        except ImportError as exc:
            raise SeparationUnavailable(
                "Dialogue separation needs the optional PyTorch packages. "
                "In LocalDub Studio choose this option and click 'Install now' (or use the AI "
                "models page). From a source checkout: uv sync --extra experimental"
            ) from exc
        self._torch = torch
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self._model = get_model(self.MODEL)
        self._model.to(self.device).eval()
        self.sample_rate = int(self._model.samplerate)
        self._sources = list(self._model.sources)

    def separate(
        self,
        wav_path: Path,
        vocals_path: Path,
        background_path: Path,
        *,
        on_progress: ProgressFn | None = None,
        chunk_s: float = CHUNK_S,
        overlap_s: float = OVERLAP_S,
    ) -> None:
        """Write the dialogue and the background (drums + bass + other) of `wav_path` as WAVs."""
        from demucs.apply import apply_model

        torch = self._torch
        info = sf.info(str(wav_path))
        if info.samplerate != self.sample_rate:
            raise ValueError(f"Expected {self.sample_rate} Hz audio, got {info.samplerate}")
        mean, std = audio_stats(wav_path)
        voc = self._sources.index("vocals")
        rest = [i for i in range(len(self._sources)) if i != voc]

        def run_chunk(block: Audio) -> tuple[Audio, Audio]:
            mix = torch.from_numpy(np.ascontiguousarray(block.T))[None]
            with torch.no_grad():
                out = apply_model(
                    self._model,
                    (mix - mean) / std,
                    device=self.device,
                    split=True,
                    overlap=0.25,
                    progress=False,
                )[0]
            out.mul_(std).add_(mean)
            stems = out.cpu().numpy()  # (sources, 2, samples)
            vocals = np.ascontiguousarray(stems[voc].T, dtype=np.float32)
            background = np.ascontiguousarray(stems[rest].sum(axis=0).T, dtype=np.float32)
            return vocals, background

        frames = separate_in_chunks(
            wav_path,
            vocals_path,
            background_path,
            run_chunk,
            chunk_frames=int(chunk_s * self.sample_rate),
            overlap_frames=int(overlap_s * self.sample_rate),
            on_progress=on_progress,
        )
        log.info("separated %.1f s of audio", frames / self.sample_rate)

    def close(self) -> None:
        self._model = None
        gc.collect()
        if self._torch.cuda.is_available():
            self._torch.cuda.empty_cache()

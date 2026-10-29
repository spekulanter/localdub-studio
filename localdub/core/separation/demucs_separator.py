"""Dialogue/background separation with Demucs (htdemucs). Experimental, optional, needs PyTorch.

Install with `uv sync --extra experimental`. The model weights (about 80 MB, safetensors) are
downloaded on first use from the Hugging Face repository `adefossez/HTDemucs` (the `main` branch:
the revision is not pinned by Demucs 4.1.0). Code is MIT-licensed (facebookresearch/demucs).
"""

from __future__ import annotations

import gc
import logging
import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import numpy.typing as npt
import soundfile as sf

log = logging.getLogger(__name__)


class SeparationUnavailable(RuntimeError):
    """PyTorch/Demucs are not installed."""


@dataclass
class Stems:
    vocals: npt.NDArray[np.float32]  # (samples, 2)
    background: npt.NDArray[np.float32]  # drums + bass + other, (samples, 2)
    sample_rate: int


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
                "Install them with: uv sync --extra experimental"
            ) from exc
        self._torch = torch
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self._model = get_model(self.MODEL)
        self._model.to(self.device).eval()
        self.sample_rate = int(self._model.samplerate)
        self._sources = list(self._model.sources)

    def separate(self, wav_path: Path) -> Stems:
        from demucs.apply import apply_model

        torch = self._torch
        data, sr = sf.read(str(wav_path), dtype="float32", always_2d=True)
        if sr != self.sample_rate:
            raise ValueError(f"Expected {self.sample_rate} Hz audio, got {sr}")
        stereo = data if data.shape[1] >= 2 else np.repeat(data, 2, axis=1)
        mix = torch.from_numpy(np.ascontiguousarray(stereo[:, :2].T))[None]
        ref = mix.mean(0)
        mean, std = ref.mean(), ref.std() + 1e-8
        with torch.no_grad():
            out = apply_model(
                self._model,
                (mix - mean) / std,
                device=self.device,
                split=True,
                overlap=0.25,
                progress=False,
            )[0]
        out = out * std + mean
        stems = {name: out[i].cpu().numpy().T for i, name in enumerate(self._sources)}
        vocals = stems.pop("vocals")
        background = sum(stems.values())
        return Stems(
            vocals.astype(np.float32), np.asarray(background, np.float32), self.sample_rate
        )

    def close(self) -> None:
        self._model = None
        gc.collect()
        if self._torch.cuda.is_available():
            self._torch.cuda.empty_cache()

"""Voice conversion with OpenVoice V2's tone-colour converter. Experimental, optional, PyTorch.

It changes the *timbre* of a synthesised clip towards a reference speaker while keeping the words,
rhythm and language of the clip, so Slovak TTS output can sound like the original speaker.

Only use it on voices you have the right to imitate. Code: MIT (vendored in
localdub/vendor/openvoice). Weights: Hugging Face `myshell-ai/OpenVoiceV2` (MIT), pinned revision.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

from localdub.core.separation.demucs_separator import SeparationUnavailable

log = logging.getLogger(__name__)

REPO = "myshell-ai/OpenVoiceV2"
REVISION = "f36e7edfe1684461a8343844af60babc2efbb727"
FILES = ("converter/config.json", "converter/checkpoint.pth")

Audio = npt.NDArray[np.float32]


class OpenVoiceConverter:
    local_only = True

    def __init__(self, models_dir: Path, device: str | None = None) -> None:
        try:
            import torch
            from huggingface_hub import hf_hub_download
        except ImportError as exc:
            raise SeparationUnavailable(
                "Voice cloning needs the optional PyTorch packages. "
                "In LocalDub Studio choose this option and click 'Install now' (or use the AI "
                "models page). From a source checkout: uv sync --extra experimental"
            ) from exc
        from localdub.vendor.openvoice import utils
        from localdub.vendor.openvoice.models import SynthesizerTrn

        self._torch = torch
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        target = models_dir / "openvoice"
        paths = {
            name: hf_hub_download(REPO, name, revision=REVISION, local_dir=str(target))
            for name in FILES
        }
        hps = utils.get_hparams_from_file(  # type: ignore[no-untyped-call]
            paths["converter/config.json"]
        )
        model = SynthesizerTrn(  # type: ignore[no-untyped-call]
            len(getattr(hps, "symbols", [])),
            hps.data.filter_length // 2 + 1,
            n_speakers=hps.data.n_speakers,
            **hps.model,
        )
        # weights_only: the checkpoint must be plain tensors, never arbitrary pickled objects.
        state = torch.load(paths["converter/checkpoint.pth"], map_location="cpu", weights_only=True)
        missing, unexpected = model.load_state_dict(state["model"], strict=False)
        if missing:
            log.warning(
                "OpenVoice checkpoint: %d missing keys (e.g. %s)", len(missing), missing[:2]
            )
        self._model: Any = model.to(self.device).eval()
        self._hps = hps
        self.sample_rate = int(hps.data.sampling_rate)

    def _spec(self, audio: Audio) -> Any:
        from localdub.vendor.openvoice.mel_processing import spectrogram_torch

        torch, hps = self._torch, self._hps
        y = torch.from_numpy(np.ascontiguousarray(audio, dtype=np.float32)).to(self.device)[None]
        return spectrogram_torch(  # type: ignore[no-untyped-call]
            y, hps.data.filter_length, hps.data.sampling_rate, hps.data.hop_length,
            hps.data.win_length, center=False,
        ).to(self.device)  # fmt: skip

    def extract_se(self, audios: list[Audio]) -> Any:
        """Speaker embedding ("tone colour") averaged over clips at `self.sample_rate`."""
        torch = self._torch
        gs = []
        with torch.no_grad():
            for audio in audios:
                spec = self._spec(audio)
                gs.append(self._model.ref_enc(spec.transpose(1, 2)).unsqueeze(-1).detach())
        return torch.stack(gs).mean(0)

    def convert(self, audio: Audio, src_se: Any, tgt_se: Any, tau: float = 0.3) -> Audio:
        torch = self._torch
        with torch.no_grad():
            spec = self._spec(audio)
            lengths = torch.LongTensor([spec.size(-1)]).to(self.device)
            out = self._model.voice_conversion(
                spec, lengths, sid_src=src_se, sid_tgt=tgt_se, tau=tau
            )[0][0, 0]
        return np.asarray(out.data.cpu().float().numpy(), dtype=np.float32)

    def close(self) -> None:
        import gc

        self._model = None
        gc.collect()
        if self._torch.cuda.is_available():
            self._torch.cuda.empty_cache()

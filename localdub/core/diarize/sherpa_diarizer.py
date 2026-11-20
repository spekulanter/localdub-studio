"""Speaker diarization with sherpa-onnx (pyannote segmentation + 3D-Speaker embeddings).

Runs on the CPU and needs no PyTorch.

Experimental: quality is only measured on the samples listed in docs/QUALITY.md.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import soundfile as sf

from localdub.core import progress
from localdub.core.diarize.assign import SpeakerTurn
from localdub.core.models import RemoteModel, ensure_model

log = logging.getLogger(__name__)

# Both files come from sherpa-onnx's Hugging Face repositories at a fixed commit. Upstream replaced
# the embedding file in its GitHub release (and on Hugging Face `main`) on 2026-11-19, which broke
# every new download against the pinned checksum; a commit URL can never change under us. They
# are the same bytes LocalDub has always installed, so existing copies stay valid.
_HF = "https://huggingface.co/csukuangfj"
SEGMENTATION = RemoteModel(
    name="pyannote segmentation 3.0 (ONNX, via sherpa-onnx)",
    url=f"{_HF}/sherpa-onnx-pyannote-segmentation-3-0/resolve/"
    "9403a6902bb58e3d5ae8c7e77c3422de279db2e0/model.onnx",
    sha256="220ad67ca923bef2fa91f2390c786097bf305bceb5e261d4af67b38e938e1079",
    dest="diarization/pyannote-segmentation-3-0.onnx",
)
EMBEDDING = RemoteModel(
    name="3D-Speaker ERes2Net base speaker embedding (ONNX)",
    url=f"{_HF}/speaker-embedding-models/resolve/0743f301363dec56491a490f6d6cbc9d67f9a3bf/"
    "3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx",
    sha256="1a331345f04805badbb495c775a6ddffcdd1a732567d5ec8b3d5749e3c7a5e4b",
    dest="diarization/3dspeaker-eres2net-base.onnx",
)
SIZES = (5_992_913, 39_593_761)  # bytes, for download progress


class SherpaDiarizer:
    local_only = True

    def __init__(
        self,
        models_dir: Path,
        *,
        num_speakers: int | None = None,
        threshold: float = 0.5,
        threads: int = 4,
    ) -> None:
        import sherpa_onnx

        seg = ensure_model(SEGMENTATION, models_dir)
        emb = ensure_model(EMBEDDING, models_dir)
        config = sherpa_onnx.OfflineSpeakerDiarizationConfig(
            segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
                pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(model=str(seg)),
                num_threads=threads,
                provider="cpu",
            ),
            embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(
                model=str(emb), num_threads=threads, provider="cpu"
            ),
            clustering=sherpa_onnx.FastClusteringConfig(
                num_clusters=num_speakers if num_speakers else -1, threshold=threshold
            ),
            min_duration_on=0.3,
            min_duration_off=0.5,
        )
        if not config.validate():
            raise RuntimeError("Invalid diarization configuration (model files unreadable?)")
        self._sd = sherpa_onnx.OfflineSpeakerDiarization(config)

    def diarize(self, wav_path: Path) -> list[SpeakerTurn]:
        data, sr = sf.read(str(wav_path), dtype="float32", always_2d=True)
        samples = np.ascontiguousarray(data[:, 0])
        if sr != self._sd.sample_rate:
            raise ValueError(f"Expected {self._sd.sample_rate} Hz audio, got {sr}")
        def on_chunks(done: int, total: int) -> int:
            progress.report(done, total)
            return 0  # non-zero would abort

        result = self._sd.process(samples, callback=on_chunks).sort_by_start_time()
        order: dict[int, int] = {}
        turns: list[SpeakerTurn] = []
        for r in result:
            idx = order.setdefault(int(r.speaker), len(order))
            turns.append(SpeakerTurn(round(float(r.start), 3), round(float(r.end), 3), idx))
        log.info("Diarization: %d turns, %d speakers", len(turns), len(order))
        return turns

    def close(self) -> None:
        self._sd = None

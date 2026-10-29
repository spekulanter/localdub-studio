"""Speaker diarization with sherpa-onnx (pyannote segmentation + 3D-Speaker embeddings).

Runs on the CPU and needs no PyTorch.

Experimental: quality is only measured on the samples listed in docs/QUALITY.md.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import soundfile as sf

from localdub.core.diarize.assign import SpeakerTurn
from localdub.core.models import RemoteModel, ensure_model

log = logging.getLogger(__name__)

SEGMENTATION = RemoteModel(
    name="pyannote segmentation 3.0 (ONNX, via sherpa-onnx)",
    url="https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-segmentation-models/"
    "sherpa-onnx-pyannote-segmentation-3-0.tar.bz2",
    sha256="24615ee884c897d9d2ba09bb4d30da6bb1b15e685065962db5b02e76e4996488",
    dest="diarization/pyannote-segmentation-3-0.onnx",
    member="sherpa-onnx-pyannote-segmentation-3-0/model.onnx",
)
EMBEDDING = RemoteModel(
    name="3D-Speaker ERes2Net base speaker embedding (ONNX)",
    url="https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/"
    "3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx",
    sha256="1a331345f04805badbb495c775a6ddffcdd1a732567d5ec8b3d5749e3c7a5e4b",
    dest="diarization/3dspeaker-eres2net-base.onnx",
)


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
        result = self._sd.process(samples).sort_by_start_time()
        order: dict[int, int] = {}
        turns: list[SpeakerTurn] = []
        for r in result:
            idx = order.setdefault(int(r.speaker), len(order))
            turns.append(SpeakerTurn(round(float(r.start), 3), round(float(r.end), 3), idx))
        log.info("Diarization: %d turns, %d speakers", len(turns), len(order))
        return turns

    def close(self) -> None:
        self._sd = None

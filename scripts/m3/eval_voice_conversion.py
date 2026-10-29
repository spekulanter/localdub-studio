"""Measure OpenVoice conversion on finished projects.

Speaker similarity = cosine of 3D-Speaker embeddings (the diarization model), original speaker
reference vs the Slovak dub clips, before and after conversion. A different speaker is the control.
Intelligibility = character similarity of a Slovak Whisper transcript to the intended text.

Usage: python scripts/m3/eval_voice_conversion.py PROJECT_ID [PROJECT_ID ...]
"""

from __future__ import annotations

import json
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path

import numpy as np
import soundfile as sf

from localdub.config import Settings
from localdub.core.diarize.sherpa_diarizer import EMBEDDING
from localdub.core.gpu import register_cuda_dlls
from localdub.core.media.ffmpeg import FFmpeg
from localdub.core.models import ensure_model
from localdub.core.voice.openvoice_converter import OpenVoiceConverter
from localdub.pipeline import default_providers

SR16 = 16000


def embedding(extractor, audio: np.ndarray) -> np.ndarray:
    stream = extractor.create_stream()
    stream.accept_waveform(sample_rate=SR16, waveform=audio.astype(np.float32))
    stream.input_finished()
    return np.asarray(extractor.compute(stream), dtype=np.float32)


def cos(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


def norm(text: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", text.lower()).split())


def main(ids: list[int]) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    import sherpa_onnx

    settings = Settings()
    ff = FFmpeg()
    register_cuda_dlls()
    model = ensure_model(EMBEDDING, settings.models_dir)
    ex = sherpa_onnx.SpeakerEmbeddingExtractor(
        sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(model), num_threads=4, provider="cpu")
    )
    vc = OpenVoiceConverter(settings.models_dir)
    tmp = Path("work/vc_eval")
    tmp.mkdir(parents=True, exist_ok=True)

    def to_sr(src: Path, sr: int) -> np.ndarray:
        dst = tmp / "x.wav"
        ff.convert_audio(src, dst, sample_rate=sr)
        return sf.read(dst, dtype="float32")[0]

    data = {}
    for pid in ids:
        wd = Path(f"data/projects/{pid}/work")
        segs = json.loads((wd / "tts.json").read_text("utf-8"))["segments"]
        voiced = [s for s in segs if s.get("audio_path")][:12]
        ref = np.concatenate(
            [
                to_sr(wd / "audio_orig.wav", SR16)[int(s["start"] * SR16) : int(s["end"] * SR16)]
                for s in voiced
            ]
        )[: 30 * SR16]
        clips = [to_sr(wd / s["audio_path"], vc.sample_rate) for s in voiced]
        data[pid] = (segs, voiced, ref, clips)

    asr = default_providers(settings).asr()
    results = {}
    for pid, (_segs, voiced, ref, clips) in data.items():
        src_se = vc.extract_se(clips[:8])
        tgt_se = vc.extract_se([_resample(ref, SR16, vc.sample_rate, ff, tmp)])
        converted = [vc.convert(c, src_se, tgt_se, tau=0.3) for c in clips]

        def emb_of(audios: list[np.ndarray], sr: int) -> np.ndarray:
            joined = np.concatenate(audios)[: 30 * sr]
            return embedding(ex, _resample(joined, sr, SR16, ff, tmp))

        e_ref = embedding(ex, ref)
        results[pid] = {
            "ref": e_ref,
            "plain": emb_of(clips, vc.sample_rate),
            "conv": emb_of(converted, vc.sample_rate),
            "text": norm(" ".join(s["translated_text"] for s in voiced)),
            "converted": converted,
            "clips": clips,
        }
    for pid, r in results.items():
        others = [o for o in results if o != pid]
        print(f"project {pid}: similarity to the ORIGINAL speaker")
        print(f"   plain Slovak TTS : {cos(r['ref'], r['plain']):.3f}")
        print(f"   converted        : {cos(r['ref'], r['conv']):.3f}")
        for o in others:
            control = cos(results[o]["ref"], r["conv"])
            print(f"   control - converted vs speaker of project {o}: {control:.3f}")
        for label in ("clips", "converted"):
            audio = np.concatenate(r[label])
            wav = tmp / f"{label}_{pid}.wav"
            sf.write(wav, audio, vc.sample_rate)
            w16 = tmp / f"{label}_{pid}_16k.wav"
            ff.convert_audio(wav, w16, sample_rate=SR16)
            words = asr.transcribe(w16, language="sk").words
            heard = norm(" ".join(w.text for w in words))
            ratio = SequenceMatcher(None, r["text"], heard, autojunk=False).ratio()
            print(f"   intelligibility ({label:9}): {ratio:.3f}")
    asr.close()
    vc.close()
    return 0


def _resample(a: np.ndarray, sr_in: int, sr_out: int, ff: FFmpeg, tmp: Path) -> np.ndarray:
    if sr_in == sr_out:
        return a
    src, dst = tmp / "r_in.wav", tmp / "r_out.wav"
    sf.write(src, a, sr_in)
    ff.convert_audio(src, dst, sample_rate=sr_out)
    return sf.read(dst, dtype="float32")[0]


if __name__ == "__main__":
    raise SystemExit(main([int(x) for x in sys.argv[1:]]))

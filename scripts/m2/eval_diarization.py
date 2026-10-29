"""Measure diarization on a synthetic dialogue with known speakers (Supertonic voices, English).

Ground truth is exact, but TTS voices are cleaner and more distinct than real recordings, so this
is an upper bound, not a promise for real videos.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import soundfile as sf

from localdub.core.diarize.sherpa_diarizer import SherpaDiarizer
from localdub.core.media.ffmpeg import FFmpeg
from localdub.core.platform import disable_power_throttling
from localdub.core.tts.supertonic_provider import SupertonicProvider

LINES = [
    ("M1", "Good morning everyone, thank you for joining us today."),
    ("F1", "Thanks for having me. I have prepared a short presentation."),
    ("F1", "It covers the results of the last quarter."),
    ("M1", "Great, please go ahead whenever you are ready."),
    ("M2", "Before we start, can I ask a quick question about the budget?"),
    ("F1", "Of course, go ahead."),
    ("M2", "Is the travel cost included in these numbers?"),
    ("M1", "Yes, it is included, and so is the equipment."),
    ("F1", "I can share the detailed spreadsheet after the meeting."),
    ("M2", "That would be perfect, thank you very much."),
]
SR = 16000
OUT = Path("work/diar_eval")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    disable_power_throttling()
    OUT.mkdir(parents=True, exist_ok=True)
    ff = FFmpeg()
    tts = SupertonicProvider(model_dir=Path("models/supertonic3"), threads=4)
    chunks: list[np.ndarray] = []
    truth: list[tuple[float, float, str]] = []
    t = 0.0
    for voice, text in LINES:
        wav = tts.synthesize(text, voice=voice, lang="en", speed=1.0)
        raw = OUT / "raw.wav"
        sf.write(raw, wav, tts.sample_rate)
        res = OUT / "res.wav"
        ff.convert_audio(raw, res, sample_rate=SR)
        data, _ = sf.read(res, dtype="float32")
        truth.append((t, t + data.size / SR, voice))
        chunks.append(data)
        gap = np.zeros(int(0.6 * SR), np.float32)
        chunks.append(gap)
        t += data.size / SR + 0.6
    tts.close()
    audio = np.concatenate(chunks)
    wav_path = OUT / "dialogue.wav"
    sf.write(wav_path, audio, SR)

    configs = [(None, 0.5), (None, 0.7), (None, 0.8), (None, 0.9), (3, 0.5)]
    for num, thr in configs:
        evaluate(wav_path, audio, truth, voices_all=sorted({v for v, _ in LINES}), num=num, thr=thr)
    return 0


def evaluate(wav_path, audio, truth, voices_all, num, thr) -> None:
    diar = SherpaDiarizer(Path("models"), num_speakers=num, threshold=thr)
    turns = diar.diarize(wav_path)
    n = len(audio) // 160
    ref = np.full(n, -1)
    voices = voices_all
    for s, e, v in truth:
        ref[int(s * 100) : int(e * 100)] = voices.index(v)
    hyp = np.full(n, -1)
    for tr in turns:
        hyp[int(tr.start * 100) : int(tr.end * 100)] = tr.speaker
    speech = ref >= 0
    # Best one-to-one mapping from hypothesis speakers to reference speakers (greedy by overlap).
    hyp_ids = sorted({int(h) for h in hyp[speech] if h >= 0})
    mapping: dict[int, int] = {}
    taken: set[int] = set()
    pairs = sorted(
        ((int(((hyp == h) & (ref == r)).sum()), h, r) for h in hyp_ids for r in range(len(voices))),
        reverse=True,
    )
    for _, h, r in pairs:
        if h not in mapping and r not in taken:
            mapping[h] = r
            taken.add(r)
    correct = sum(1 for i in np.flatnonzero(speech) if mapping.get(int(hyp[i]), -2) == ref[i])
    acc = correct / int(speech.sum())
    print(
        f"--- num_speakers={num} threshold={thr}: reference {len(voices)}, detected {len(hyp_ids)}"
    )
    covered = speech & (hyp >= 0)
    right = sum(1 for i in np.flatnonzero(covered) if mapping.get(int(hyp[i]), -2) == ref[i])
    print(
        f"  frame accuracy {acc:.3f} = coverage {covered.sum() / speech.sum():.3f} x "
        f"precision-when-covered {right / max(int(covered.sum()), 1):.3f}"
    )
    mains = []
    for s, e, _v in truth:
        mid = hyp[int(s * 100) : int(e * 100)]
        mid = mid[mid >= 0]
        mains.append(int(np.bincount(mid).argmax()) if mid.size else -1)
    print("  truth   :", " ".join(v for _, _, v in truth))
    print("  detected:", " ".join(f"{m:>2}" for m in mains))


if __name__ == "__main__":
    raise SystemExit(main())

# Quality measurements and known limitations

Every number here was measured; anything not measured is listed under **Unverified**.
Hardware: RTX 5060 Laptop 8 GB, i7-13700HX, Windows 11 (see ENVIRONMENT.md).

## M0 pipeline run: synthetic clip, manual translation (2026-10-29)
Input: `work/m0_checks/syn tést ✓/anglický klip.mp4`. It is 19.3 s of English speech made with
Supertonic, over an H.264 test pattern. The path has spaces and Unicode on purpose.
Translation: a **hand-written Slovak reference**, injected through the `TranslationProvider`
interface (`work/m0_checks/manual_translate_run.py`), because Ollama is not installed yet.

| Check (`localdub-m0 verify --back-transcribe`) | Result |
|---|---|
| Output MP4 probes, duration delta | PASS, 0.000 s |
| Video stream copied (streamhash sha256 equal) | PASS |
| Audio: dub first (`slk`, default) + original second | PASS |
| Slovak SRT valid (UTF-8 BOM, 4 cues) | PASS |
| TTS clips non-silent | PASS, min RMS −24.8 dBFS |
| Dub length = source length @ 48 kHz | PASS |
| Fit report | 4/4 ok |
| Back-transcription (Whisper sk on the dub vs the SK text) | PASS, char similarity **0.993** |

Retry check: after editing `translation.json`, only `tts`, `assemble` and `export` re-ran.
The earlier stages were skipped because their checkpoints were still valid.

Overflow handling: a deliberately long line (4.4 s of speech for a 4.2 s window) reached the
speed cap (×1.25 Supertonic, ×1.275 effective). It was marked `overflow` in `fit_report.json`.
The next segment was shifted 0.35 s later instead of overlapping. The audio is not sped up past
the cap. Shortening the line is a translation or review job (the Ollama shorten-retry, M2
editing).

Stage timings (19 s clip, warm disk): ASR ≈ 5 s including model load; TTS 5.6 s with 4 threads
(it was 11.1 s with ONNX "auto" threads); assemble 0.1 s; export 0.4 s.

## Known limitations (by design in M0)
- Voice-over mix: the original audio is ducked by 14 dB, not removed. There is no
  dialogue/background separation yet (M3, experimental).
- One voice for all speakers; no diarization (M2).
- Supertonic is not bit-deterministic. Re-synthesis changes a clip's length by about 1–2 %.
- The ASR segmentation is heuristic (gap and punctuation), so very long sentences without
  pauses are split at clause boundaries.
- `file_digest` uses size+mtime for files over 64 MB. A same-size in-place edit with a preserved
  mtime would not invalidate the checkpoints.

## Unverified (do not claim)
- LLM translation quality: translategemma:4b vs qwen3:8b. Pending Ollama
  (`scripts/m0/bench_translation.py`).
- A real, human-recorded English clip: noise, music, overlapping speakers.
- Subjective naturalness of the Slovak voice and the mix. This needs the user's listening check.
- Long videos (5 min+), desktop RTX 5070 Ti: these belong to M1.

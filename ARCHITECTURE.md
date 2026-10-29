# Architecture

## Pipeline

```
input.mp4
  │ probe      ffprobe → probe.json (duration, streams, codecs)
  │ extract    ffmpeg → audio_16k.wav (ASR) + audio_orig.wav (48 kHz, mixing)
  │ asr        faster-whisper (VAD + word timestamps) → word groups → asr.json
  │ translate  Ollama, per segment with context + character budget → translation.json
  │ tts        Supertonic 3 per segment; fit to window → tts/raw/*.wav, tts/clips/*.wav, tts.json
  │ assemble   place clips on the original timeline, voice-over mix → dub.wav, mix.wav,
  │            segments.json, fit_report.json
  └ export     <name>.sk.srt, <name>.en.srt, <name>.sk.mp4 (video stream-copied)
```

All stage outputs live in `work/<video-stem>/`. `localdub/pipeline.py` runs the stages in order.

## Checkpoints and restart safety
`core/jobs/checkpoints.py` stores `state.json` with one record per stage: a fingerprint of the
stage parameters plus digests of its input files, and the list of outputs. A stage is skipped
when the fingerprint matches and the outputs exist. Because each stage's inputs are the previous
stage's outputs, editing e.g. `translation.json` automatically re-runs `tts` and later stages
only. All JSON writes are atomic (temp file + `os.replace`), so a killed process never leaves a
half-written checkpoint. `--from-stage X` forces X and later stages.

## Provider interfaces (swap engines without touching the pipeline)
| Interface | Module | M0 implementation | Locality |
|---|---|---|---|
| `ASRProvider` | `core/asr/base.py` | `FasterWhisperProvider` (CTranslate2, CUDA fp16 → int8_fp16 → CPU int8 fallback, logged) | local |
| `TranslationProvider` | `core/translation/base.py` | `OllamaTranslator` (HTTP to local Ollama; warns if URL is not loopback) | local |
| `TTSProvider` | `core/tts/base.py` | `SupertonicProvider` (ONNX Runtime CPU) | local |

Each provider has `local_only` (where applicable) and `close()`. Providers are created through
factories (`pipeline.Providers`) so a model is only loaded when its stage runs.

## GPU scheduling
Only one large model is resident at a time: ASR runs, then `close()` drops the CTranslate2 model
(VRAM measured back to ~100 MiB). Translation then calls Ollama, and `close()` sends
`keep_alive: 0` to evict the LLM. TTS runs on CPU (Supertonic is small; onnxruntime-gpu would
conflict with the CPU onnxruntime that faster-whisper's VAD needs).

## Timing / synchronization
- Window of a line = next line's start − its start − 50 ms gap (last line: until video end).
- Synthesize at base speed; trim leading/trailing silence.
- If too long: re-synthesize with Supertonic's own `speed` (≤ `max_speed`, default 1.25),
  then a residual ≤ 10 % pitch-preserving FFmpeg `rubberband` stretch.
- Still too long → `overflow`; the clip is kept whole and the next line is shifted later
  (`shifted`) instead of overlapping. Speech is never truncated, except at the very end of the
  video, where it is flagged as `overflow`. All flagged lines are listed in `fit_report.json`.
- Assembly: float32 timeline of exactly `round(duration × 48000)` samples, silence elsewhere.
- Voice-over mix: original audio ducked −14 dB under dub regions with 150 ms ramps.

## Data model
`core/timeline/models.py: DialogueSegment` — id, start, end, source_text, translated_text,
speaker_id, voice_id, audio_path, audio_duration, stretch_ratio, tts_speed, placed_start,
fit_status (pending/ok/stretched/shifted/overflow), review_status (pending/edited/approved), words.

## Media handling
`core/media/ffmpeg.py`: all FFmpeg/FFprobe calls go through `run_tool()` with list arguments,
`shell=False`, `CREATE_NO_WINDOW` on Windows, UTF-8 stderr captured into `MediaError`.
Mux: `-map 0:v:0 -c:v copy` (refuses codecs MP4 cannot hold rather than silently re-encoding),
Slovak AAC track default, original audio kept as the second track, `-t <source duration>`,
`comment` metadata discloses AI generation.

## Windows specifics
- `core/platform.disable_power_throttling()` opts the process out of EcoQoS. Without it,
  processes without a foreground window ran Supertonic 5–10× slower on E-cores.
- `core/gpu.register_cuda_dlls()` adds the `nvidia-cublas-cu12` / `nvidia-cudnn-cu12` wheel DLL
  directories (no system CUDA toolkit needed).

## Module map
`core/media`, `core/asr`, `core/translation`, `core/tts`, `core/timeline`, `core/audio`,
`core/export`, `core/jobs`, `api` (M1), `frontend` (M1), `tests/unit`, `tests/integration`.

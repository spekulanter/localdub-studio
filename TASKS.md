# Tasks

Legend: [x] done and verified · [~] implemented, not yet verified on real data · [ ] open

## M0 — Feasibility
- [x] Planning docs: PLAN.md, ARCHITECTURE.md, TASKS.md, AGENTS.md
- [x] Project init: git, uv, Python 3.12 (Windows), pinned deps, ruff/mypy strict clean
- [x] Environment report (`localdub-m0 env`), see docs/ENVIRONMENT.md
- [x] CUDA on Blackwell via CTranslate2 4.8.4 + nvidia wheels (no PyTorch needed)
- [x] faster-whisper large-v3 GPU fp16 inference (RTF 0.058 warm, VRAM released on close)
- [x] Supertonic 3 Slovak synthesis, all diacritics, 10 voices
- [x] Windows EcoQoS throttling found and fixed (`core/platform.py`)
- [x] Supertonic ONNX threads fixed at 4 (auto was 2.5x slower)
- [x] Ollama EN→SK translation (translategemma:4b default; guards for script leaks, shortening)
- [x] Translation model comparison (docs/translation_benchmark.md): translategemma:4b is the default
- [x] Pipeline stages probe→extract→asr→translate→tts→assemble→export with checkpoints
- [x] Integration test: synthetic video in a Unicode path, stream copy, duration, restart
- [x] End-to-end run on 3 real 44–53 s clips: verify PASS (docs/QUALITY.md)
- [x] Objective verification (`localdub-m0 verify`): duration, stream hash, SRT, non-silent clips, back-transcription 0.993
- [x] Retry check: only the stages after the edit re-run (synthetic clip, and `--from-stage translate` on real clips)
- [ ] Human listening check of the output (user)
- [x] docs/LICENSES.md (worker-drafted; reviewed)
- [x] docs/QUALITY.md with measured limitations (updated as data arrives)
- [x] Git commit for M0

## M1 — MVP
- [ ] SQLite project store (projects, jobs, segments)
- [ ] Job queue in a worker process: progress, cancellation, restart recovery from checkpoints
- [ ] FastAPI: projects CRUD, upload/import, start/cancel job, progress (SSE), segment list, downloads
- [ ] Call `disable_power_throttling()` at server start
- [ ] React + TS (strict) + Vite + Tailwind: import, language/voice selection, progress, errors, preview player, export
- [ ] 5-minute video test without crash; kill-and-resume test
- [ ] Desktop (5070 Ti) verification

## M2 — Editing and quality
- [ ] Editable transcript and translation; mark segments edited/approved
- [ ] Per-segment audio preview; regenerate selected segments only
- [ ] Manual timing adjustment
- [ ] Voice presets per segment or speaker
- [ ] Optional diarization (WhisperX + pyannote; PyTorch cu128+)
- [x] Original audio: duck (default) or mute, optional drop of the original track (M0, CLI/env)
- [ ] Mixing: loudness normalization (EBU R128), smarter ducking; UI toggle in M1 settings

## M3 — Experimental
- [ ] Voice conversion (OpenVoice V2)
- [ ] Dialogue/background separation (e.g. Demucs) → replace-dialogue mode
- [ ] Speaker → voice mapping
- [ ] Batch processing
- [ ] Tauri packaging (FFmpeg GPL obligations; see docs/LICENSES.md)

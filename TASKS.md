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
- [x] SQLite project store (projects, jobs; segments stay in the project work dir) — `localdub/api/db.py`
- [x] Job queue in a worker process: progress, cancellation, restart recovery (verified live: kill server mid-TTS, restart, resumes)
- [x] FastAPI: projects CRUD, upload/import, start/cancel job, progress (SSE), segment list, downloads (28 tests)
- [x] `disable_power_throttling()` at CLI start (server and worker)
- [x] React + TS (strict) + Vite + Tailwind: import, language/voice/model/original-audio selection, live progress, errors with log, preview, export, re-render (10 component/unit tests; not yet driven by a real browser session)
- [x] 5.7-minute video via API: done, verify PASS; kill-and-resume verified (docs/QUALITY.md)
- [ ] Desktop (5070 Ti) verification

## M2 — Editing and quality
- [x] Editable translation per segment; edited/approved marks (edits.json overlay, stale-edit detection)
- [x] Per-segment audio preview (rendered clip + try-unsaved-text); only changed segments are re-synthesised (clip cache; 1 edited line = 4.4 s)
- [x] Manual timing adjustment (start/end, overlap and range validation)
- [x] Voice per segment and per speaker (speaker→voice map)
- [~] Optional diarization: sherpa-onnx (pyannote segmentation + 3D-Speaker, CPU, no PyTorch) instead of WhisperX; 10/10 on a synthetic 3-voice dialogue, real recordings unverified (docs/QUALITY.md)
- [x] Original audio: duck (default) or mute, optional drop of the original track (M0, CLI/env)
- [x] Mixing: dub loudness matched to the original (EBU R128 measured, limiter, mix capped at -14 LUFS); duck/mute already in M1
- [ ] UI toggle for loudness matching (env var only for now)

## M3 — Experimental
- [~] Voice conversion (OpenVoice V2, vendored MIT code, optional extra, consent required): speaker-embedding similarity 0.05->0.51 and 0.30->0.44, intelligibility unchanged; naturalness unjudged
- [~] Dialogue/background separation (Demucs, optional extra) → "background" original-audio mode: speech removed measurably (-94 dB in mix); tested on one clip with music
- [x] Speaker → voice mapping (done in M2: per-speaker and per-line voices, gender-aware defaults)
- [x] Batch processing: several videos in one upload, queued and dubbed one after another (UI test; real multi-job queue only tested with a fake worker)
- [x] Desktop window (pywebview/WebView2, icon, close-confirm while a job runs, browser fallback): run and screenshot-verified
- [~] Windows installer: Inno Setup wizard script written (packaging/localdub.iss) but NOT compiled/tested (Inno Setup not installed); PowerShell installer + ZIP tested
- [x] In-app model manager: required models downloaded inside the app with progress (installer no longer downloads models); failed jobs: copy error / copy log / download log
- [x] Optional PyTorch packages install from inside the app (Install now button + AI models page; no commands, no admin rights): tested as a normal user from the Program Files Python
- [x] Timeline editor: waveform of the original, English lines (drag/resize/keyboard, snapping, neighbour limits) and the Slovak dub lane that shows speech running past its window; verified in real Edge (`npm run e2e:timeline`)
- [x] YouTube import: link tab, tools installed on request (SHA-256), download as the first pipeline stage; tested with a real CC video end to end and in real Edge (`npm run e2e:youtube`)
- [x] UI redesign ("dubbing booth": paper/ink light theme, console dark theme, signal accent, Fraunces + IBM Plex, meter-style progress, new shell); checked on screenshots in light and dark in real Edge
- [x] Release 0.2.0 prepared: CHANGELOG-driven release notes (the build fails if the section is missing), upgrade-from-0.1.x tests, uninstall removes the YouTube tools

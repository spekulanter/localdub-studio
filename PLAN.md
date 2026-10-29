# LocalDub Studio — Plan

Local-first Windows application that translates and dubs English videos into Slovak.
No mandatory paid APIs; all media stays on the machine.

Target hardware: Windows 11; RTX 5070 Ti 16 GB (desktop) / RTX 5060 Laptop 8 GB; Blackwell sm_120; 32 GB RAM.

## Milestones

Each milestone ends with: tests run, artifacts inspected, TASKS.md + docs updated, a written
report of what works / failed / is unverified, and a git commit. The next milestone starts only
after the current one passes its acceptance criteria.

### M0 — Feasibility (headless)
Verify the environment and every engine on real hardware, then dub one 30–60 s clip end to end
from the CLI (`localdub-m0 run`).

Acceptance:
- Environment report (Python, FFmpeg, driver, CUDA, Ollama models) recorded in docs/ENVIRONMENT.md.
- faster-whisper large-v3 runs on the GPU (or a documented fallback).
- Supertonic 3 produces audible Slovak speech.
- Ollama translates EN→SK with at least one local model.
- Output MP4 plays, duration within 50 ms of the source, video stream bit-identical (stream copy).
- Valid UTF-8 Slovak SRT with monotonic, non-overlapping cues.
- Re-running resumes from checkpoints; editing an intermediate file re-runs only later stages.

### M1 — MVP
FastAPI backend + minimal React/TypeScript/Vite/Tailwind UI.
MP4 import, source-language selection, Slovak target, voice selection, job progress and errors,
video preview, SRT and MP4 export, persistent projects (SQLite), restart-safe job queue with
cancellation.

Acceptance: the first-release criteria below, including a 5-minute video without crashing and
recovery from a killed job.

### M2 — Editing and quality
Editable transcript/translation segments, per-segment audio preview, regenerate selected lines,
manual timing adjustment, multiple preset voices, optional diarization (WhisperX + pyannote),
mixing improvements.

### M3 — Advanced (experimental)
Local voice conversion (OpenVoice V2), dialogue/background separation, speaker→voice mapping,
batch processing, Tauri packaging. Nothing here is called production-ready without measured
quality tests.

## First-release acceptance criteria
- Imports a real English MP4; dialogue recognized with reasonable timestamps.
- Editable Slovak text; audible Slovak speech; valid synchronized SRT.
- Playable MP4 whose duration matches the original; original video stream preserved when compatible.
- 5-minute test processes without crashing; interrupted jobs recover safely.
- Quality limitations documented (docs/QUALITY.md).

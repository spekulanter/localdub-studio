# LocalDub Studio

Local-first English → Slovak video dubbing for Windows. Speech recognition (faster-whisper),
translation (Ollama) and Slovak speech (Supertonic 3) all run on your computer; no media is
uploaded anywhere and no paid API is used. Plan: [PLAN.md](PLAN.md), status: [TASKS.md](TASKS.md),
measured quality and limits: [docs/QUALITY.md](docs/QUALITY.md), licences: [docs/LICENSES.md](docs/LICENSES.md).

## Requirements (native Windows)
- Windows 10/11, an NVIDIA GPU with 8 GB+ VRAM (CPU works but is slow), current NVIDIA driver
- [uv](https://docs.astral.sh/uv/) and FFmpeg (full build) on `PATH`
- [Ollama](https://ollama.com) with a translation model: `ollama pull translategemma:4b`
- Node.js 20+ (only to build the web UI)

## Install (Windows)
See [docs/INSTALL.md](docs/INSTALL.md): download the setup, run it, start *LocalDub Studio* from the Start menu.
Build the setup yourself with `uv run python packaging/build_release.py`.

## First run from a source checkout
```powershell
uv sync
uv run localdub-m0 env          # environment report: GPU, FFmpeg, Ollama, models
cd frontend; npm install; npm run build; cd ..
uv run localdub serve           # then open http://127.0.0.1:8765
```
Model weights (Whisper large-v3, Supertonic 3) download from Hugging Face on first use into
`models/`. Projects, uploads and results are stored in `data/` (git-ignored).

## Using the web UI
Choose an MP4, pick the Slovak voice, translation model and what happens to the original voice
(quiet under the dub, or muted completely), then start. Progress is live; you can cancel, and a
job that is interrupted (crash, restart) resumes from its finished steps. When done, preview the
dub, download the MP4 and the Slovak/English `.srt`, or change settings and re-render (only the
affected steps re-run).

## Command line
```powershell
uv run localdub-m0 run "samples/clip.mp4" --original-audio mute --drop-original-track
uv run localdub-m0 verify "samples/clip.mp4" --back-transcribe   # objective output checks
```

## Development
```powershell
uv run pytest -q; uv run ruff check .; uv run mypy localdub
cd frontend; npm test; npm run build
npm run dev                     # UI on :5173, proxies /api to the server on :8765
```
The server listens on `127.0.0.1` only. Agents working from WSL: see [AGENTS.md](AGENTS.md).

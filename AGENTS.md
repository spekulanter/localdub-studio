# Agent operating rules

## Runtime: native Windows
The project runs on **Windows Python 3.12** in a Windows venv (`.venv`) created by `uv.exe`.
Agents working from WSL must call Windows binaries:

| Task | From WSL (cwd `/mnt/c/dev-elevenlabs`) | From PowerShell (`C:\dev-elevenlabs`) |
|---|---|---|
| Install deps | `uv.exe sync` | `uv sync` |
| Tests | `uv.exe run pytest -q` | `uv run pytest -q` |
| Lint/types | `uv.exe run ruff check . && uv.exe run mypy localdub` | same without `.exe` |
| Env report | `uv.exe run localdub-m0 env` | `uv run localdub-m0 env` |
| Dub a video | `uv.exe run localdub-m0 run "samples/clip.mp4"` | same |
| Windows localhost | `curl.exe http://127.0.0.1:11434/api/tags` | `curl ...` |

Never use the Linux `python3`/`uv` on this repo (it would clobber `.venv`). Some sandboxed agents
cannot reach Windows interop; they should say so and not claim test results.

## macOS build
The Mac app (`packaging/build_macos.py`) can only be built and tested on a macOS runner (the `macos` job of
`.github/workflows/build.yml`); agents working from WSL cannot run it and must not claim it works on a Mac.
Mac-specific code paths are unit-tested from any system by monkeypatching `sys.platform` (see
`tests/unit/test_macos.py`). Do not call the Mac version tested beyond what docs/INSTALL-macOS.md lists.

## Rules
- Work one milestone at a time (see PLAN.md / TASKS.md). Do not start the next one until the
  current one's acceptance tests pass.
- Run tests before committing; report failures with output, never hide them.
- FFmpeg/FFprobe only through `localdub.core.media.ffmpeg` (list args, no shell strings).
- Paths: `pathlib.Path`; test with spaces and Unicode (see tests/integration).
- Never download executables silently. Model weights download only from documented sources
  (Hugging Face, Ollama registry) at pinned revisions; record them in docs/LICENSES.md.
- No paid/cloud APIs by default. Any cloud provider must be opt-in and marked `local_only = False`.
- Load one large GPU model at a time; call `close()` after each stage.
- New engines go behind the provider interfaces in `core/*/base.py`.
- Experimental features (voice conversion, separation) must not be described as production-ready
  without measured quality tests.
- Do not upgrade `supertonic` or its model revision blindly: upstream is archived.
- Generated media must keep the AI-disclosure metadata (OpenRAIL-M requirement).

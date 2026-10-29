# Installing LocalDub Studio on Windows

LocalDub Studio is an *online* installer: the package is small (about 0.2 MB) and downloads what it
needs while installing. Nothing is installed or downloaded without asking first (use `-Yes` to
accept every prompt).

## What you need
- Windows 10 or 11, 64-bit, and about 6 GB of free disk space (9 GB with speech removal)
- An NVIDIA GPU with 8 GB or more of video memory and a current driver (without it the app runs on
  the CPU, which is much slower)
- An internet connection during installation (afterwards everything runs offline)

## Install
1. Download `LocalDub-Studio-0.1.0-Setup.exe` (or the `.zip`, unpack it and double-click
   `Install LocalDub Studio.cmd`). The files are **not code-signed**, so Windows SmartScreen shows
   "Windows protected your PC": choose *More info → Run anyway*. Compare the SHA-256 in the
   `.sha256` file with `Get-FileHash` if you want to be sure.
2. A console window walks through these steps and asks before each one:

| Step | Source | Size |
|---|---|---|
| uv (Python manager), FFmpeg, Ollama, if missing | `winget` (`astral-sh.uv`, `Gyan.FFmpeg`, `Ollama.Ollama`) | 20-200 MB each |
| Python 3.12 and the app libraries | `uv sync` (python-build-standalone, PyPI) | about 2.5 GB |
| Speech recognition model (faster-whisper large-v3) and Slovak voice (Supertonic 3) | Hugging Face | about 3.4 GB |
| Translation model `translategemma:4b` | Ollama registry | about 3.3 GB |
| Optional: speaker detection | GitHub release, SHA-256 verified | 46 MB |
| Optional: speech removal (PyTorch + Demucs) | PyTorch index, Hugging Face | about 3 GB + 80 MB |

3. Start **LocalDub Studio** from the Start menu. A console window shows the log and the app opens
   in your browser at <http://127.0.0.1:8765>. Close the console window to quit.

Command-line options of `install.ps1`: `-InstallDir`, `-ModelsDir` (share models with another
copy), `-Yes`, `-NoShortcuts`, `-SkipModels`, `-SkipOllamaModel`, `-SkipPrerequisites`,
`-WithDiarization`, `-WithSeparation`.

## Where things are
Default install folder: `%LOCALAPPDATA%\Programs\LocalDub Studio`. Your projects and results are in
its `data` folder and the models in `models`; both survive an upgrade (install the new version into
the same folder). The server only listens on `127.0.0.1`; nothing is uploaded.

## Uninstall
Run `uninstall.ps1` in the install folder (right-click → *Run with PowerShell*). It asks whether to
delete your data and the models. uv, FFmpeg and Ollama are left installed.

## What has and has not been tested
Tested on the developer's Windows 11 machine (RTX 5060 Laptop): the installer script from an
unzipped package into a fresh folder (prerequisites already present, models shared), a full dubbing
job from the installed copy, the start script, the uninstall script, and extraction of `Setup.exe`.
**Not tested:** a clean Windows without uv/FFmpeg/Ollama (the `winget` prompts), a machine without an
NVIDIA GPU, the interactive `Setup.exe` run end to end, Windows 10, and a different GPU than the
RTX 5060 (the desktop RTX 5070 Ti is untested).

# Installing LocalDub Studio on Windows

LocalDub Studio is a normal Windows program: a setup wizard installs it, it opens in its own
window (Microsoft Edge WebView2, included in Windows 11), has a Start-menu entry and appears in
*Settings → Apps*. Everything runs on your computer; your videos are never uploaded.

## Requirements
- Windows 10 or 11, 64-bit; about 6 GB of free space (9 GB with the experimental features)
- An NVIDIA GPU with 8 GB or more of video memory and a current driver. Without it the app runs on
  the CPU, which is much slower.
- Internet during setup (afterwards it works offline)

## Install
1. Run `LocalDub-Studio-<version>-Setup.exe`. It is **not code-signed**, so Windows SmartScreen shows
   "Windows protected your PC": choose *More info → Run anyway*. (Compare the SHA-256 in the
   `.sha256` file with `Get-FileHash` if you want to be sure.)
2. The wizard asks for the install folder (default `%LOCALAPPDATA%\Programs\LocalDub Studio`, no
   administrator rights needed), which parts to install, and which downloads to do now:

| Step | Source | Size |
|---|---|---|
| FFmpeg and Ollama, if missing (asks first) | `winget` (`Gyan.FFmpeg`, `Ollama.Ollama`) | 100-200 MB each |
| Python 3.12 and the app libraries | uv (bundled), python-build-standalone, PyPI | about 2.5 GB |
| Speech recognition (faster-whisper large-v3) and Slovak voice (Supertonic 3) | Hugging Face | about 3.4 GB |
| Translation model `translategemma:4b` | Ollama registry | about 3.3 GB |
| Optional: speaker detection | GitHub release, SHA-256 verified | 46 MB |
| Optional: speech removal and voice cloning (PyTorch, Demucs, OpenVoice) | PyTorch index, Hugging Face | about 3 GB + 210 MB |

3. Start **LocalDub Studio** from the Start menu or the desktop shortcut. The program opens in its
   own window; closing the window quits it. If a dubbing job is running you are asked first: the
   job is paused and continues the next time you open the program.

## Where things are
Projects and results are in the `data` folder of the install folder and the models in `models`;
both survive an upgrade (run the new setup and keep the same folder). Logs: `data\logs`. The
program only listens on `127.0.0.1`.

## Uninstall
*Settings → Apps → LocalDub Studio → Uninstall*. It asks whether to delete your data and the
downloaded models. FFmpeg and Ollama are left installed.

## Without the wizard
`LocalDub-Studio-<version>-win64.zip` contains the same program with PowerShell scripts
(`Install LocalDub Studio.cmd`); see `packaging/install.ps1` for its options. For development:
`uv sync`, then `uv run localdub-app` (own window) or `uv run localdub serve` (browser).

## Building the installer
`uv run python packaging/build_release.py` builds the ZIP and, if Inno Setup 6 is installed
(`winget install --id JRSoftware.InnoSetup -e`), the wizard `Setup.exe` in `release/`.

## What has and has not been tested
**Tested** on the developer's Windows 11 machine (RTX 5060 Laptop): the app window (starts, shows
the UI, icon in title bar and taskbar, closing it stops the server), the PowerShell installer from
an unzipped package into a fresh folder (including `-WithExperimental`), a full dubbing job from the
installed copy, and the uninstall script.

**Not tested:** the Inno Setup wizard itself. The script `packaging/localdub.iss` was written, but
Inno Setup was not installed on the build machine, so it has not been compiled or run; expect to fix
small errors on the first build. Also untested: a clean Windows without FFmpeg/Ollama (the winget
prompts), a PC without an NVIDIA GPU, Windows 10, a PC without the WebView2 runtime (the program
then opens in the browser; that path is coded but not run), and the desktop RTX 5070 Ti.

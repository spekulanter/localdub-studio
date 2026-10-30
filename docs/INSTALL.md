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
2. The wizard asks for administrator rights (it installs into `C:\Program Files\LocalDub Studio`),
   the install folder, which parts to install, and which downloads to do now:

| Step | Source | Size |
|---|---|---|
| FFmpeg and Ollama, if missing (asks first) | `winget` (`Gyan.FFmpeg`, `Ollama.Ollama`) | 100-200 MB each |
| Python 3.12 and the app libraries | uv (bundled), python-build-standalone, PyPI | about 2.5 GB |

   **The AI models and the optional packages are not part of the setup.** On first start the program shows a notice and an
   *AI models* page where you download them with a progress bar, under your own account:

| Model | Source | Size |
|---|---|---|
| Speech recognition (faster-whisper large-v3), required | Hugging Face | about 3.1 GB |
| Slovak voice (Supertonic 3), required | Hugging Face | about 0.4 GB |
| Translation model `translategemma:4b`, required | Ollama registry (Ollama must be running) | about 3.3 GB |
| Speaker detection, optional | GitHub release, SHA-256 verified | 46 MB |
| Optional packages for speech removal and voice cloning (PyTorch 2.9 with CUDA 12.8, Demucs) | pytorch.org and PyPI; every file is checked against the SHA-256 in `uv.lock` | about 2.9 GB (about 4.5 GB on disk) |
| Speech removal (htdemucs), optional | Hugging Face | 80 MB |
| Voice cloning (OpenVoice V2), optional | Hugging Face | 131 MB |

3. Start **LocalDub Studio** from the Start menu or the desktop shortcut. The program opens in its
   own window; closing the window quits it. If a dubbing job is running you are asked first: the
   job is paused and continues the next time you open the program.

### Optional features (speech removal, voice cloning)
Choosing one of them in the form shows an **Install now** button with a progress bar. It downloads
PyTorch and Demucs (about 2.9 GB, resumable if the connection drops) and installs them into
`%LOCALAPPDATA%\LocalDub Studio\extras` under your own account: no administrator rights, no
commands, no restart. The same can be done from the *AI models* page. Needs about 9 GB of free disk
space while installing (about 4.5 GB afterwards). It cannot run while a dubbing job is running.

### YouTube links
*New dub → YouTube link* accepts a link instead of a file. The first time it offers **Install now** for two
small programs, yt-dlp and Deno (about 70 MB, from their official GitHub pages, checked against the
publishers' SHA-256, installed into `%LOCALAPPDATA%\LocalDub Studio\youtube-tools`). After that you paste a
link, press *Check link* (it shows the title, channel, length and thumbnail), choose a quality (default: up
to 1080p) and start. Downloading is the first step of the job, so it has progress, can be cancelled and is
resumed after a crash. For age-restricted or members-only videos you can let yt-dlp read the sign-in of your
own Edge, Chrome or Firefox (*Age-restricted or members-only video?*). If downloads suddenly stop working,
*Update yt-dlp* in the same form usually fixes it. Only YouTube https links are accepted; playlists and live
streams are not.

## Where things are
The program (with its own Python) is in the install folder, which is read-only for normal users.
Your projects and results are in `%LOCALAPPDATA%\LocalDub Studio\data`, the models in
`...\models` and the optional packages in `...\extras`; both survive an upgrade. Logs: `...\data\logs`. The
program only listens on `127.0.0.1`.

## Uninstall
*Settings → Apps → LocalDub Studio → Uninstall*. It asks whether to delete your data, the
downloaded models and the optional packages. The small YouTube tools are removed without asking. FFmpeg and
Ollama are left installed.

## Without the wizard
`LocalDub-Studio-<version>-win64.zip` contains the same program with PowerShell scripts
(`Install LocalDub Studio.cmd`); see `packaging/install.ps1` for its options. For development:
`uv sync`, then `uv run localdub-app` (own window) or `uv run localdub serve` (browser).

## Building the installer
`uv run python packaging/build_release.py` builds the ZIP and, if Inno Setup 6 is installed
(`winget install --id JRSoftware.InnoSetup -e`), the wizard `Setup.exe` in `release/`.

## What has and has not been tested
**Tested automatically on every release build** (GitHub Actions, a clean Windows runner without any GPU, FFmpeg
or Ollama): the Inno Setup script compiles; the installer is run silently; the program and its own Python are
there; the server starts and serves the UI; user data lands in `%LOCALAPPDATA%` and nothing is written into
Program Files; the uninstaller removes the program. The Python (260+) and UI (70+) test suites run first.

**Tested by hand on the developer's Windows 11 PC (RTX 5060 Laptop):** the app window (title-bar and taskbar icon,
closing it stops the server), a full dubbing job from the installed copy, in-app installation of the PyTorch
packages as a normal user, a real YouTube download and dub, and real-browser (Edge) click-throughs of the
timeline and the YouTube form. Updating from 0.1.x is covered by automated tests on the database and work
folders. Running the wizard interactively on that PC found the Program Files / error 448 and error 13
problems, fixed in 0.1.1 and 0.1.2.

**Not tested:** that a person has clicked through the current wizard from start to finish (the CI run is silent,
so the wizard pages, the winget prompts for FFmpeg/Ollama and the messages shown are unconfirmed), a PC without
an NVIDIA GPU, Windows 10, a PC without the WebView2 runtime (the program then opens in the browser; the path is
coded, not run), age-restricted YouTube videos and the browser-cookie option, and the desktop RTX 5070 Ti.

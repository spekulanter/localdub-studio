# Installing LocalDub Studio on a Mac (experimental)

LocalDub Studio runs on Apple Silicon Macs (M1 and newer, macOS 15 Sequoia or newer). It opens in its
own window and keeps everything on your Mac; your videos are never uploaded.

> **Status: experimental.** The Mac version is built and checked automatically on a macOS runner in
> GitHub Actions. That runner has no GPU and no screen you can look at, so **nobody has dubbed a
> video with it on a real Mac yet**: speed, quality and the look of the window are unmeasured. The
> Windows version is the one that was tested end to end.

## Requirements
- A Mac with an M-series chip (not an Intel Mac) and macOS 15 or newer
- 8 GB of memory works for the smaller models; 16 GB or more is comfortable
- About 8 GB of free disk space for the app (1.5 GB) and the models
- Internet while downloading models (afterwards it works offline)
- [Ollama](https://ollama.com) for translation. Install it yourself; LocalDub does not install it.

## Install
1. Open `LocalDub-Studio-<version>-macOS-arm64.dmg` and drag **LocalDub Studio** onto **Applications**.
2. **The first start needs one extra step**, because the app is not signed with an Apple Developer ID
   (that costs 99 USD a year, and this is a free project). Either:
   - in *Applications*, right-click (or Control-click) **LocalDub Studio**, choose **Open**, then
     **Open** again; or
   - if macOS only offers "Move to Bin": open *System Settings → Privacy & Security*, scroll down and
     press **Open Anyway** next to LocalDub Studio; or
   - in Terminal: `xattr -dr com.apple.quarantine "/Applications/LocalDub Studio.app"`.
   You only do this once. You can compare the download with the `.sha256` file:
   `shasum -a 256 LocalDub-Studio-*.dmg`.
3. In the app open **AI models** and press *Download the required models*:

| Model | Source | Size |
|---|---|---|
| FFmpeg (`ffmpeg`, `ffprobe`), required, unless you already have it from Homebrew | ffmpeg.martin-riedl.de, SHA-256 pinned in the program | about 57 MB |
| Speech recognition, Whisper large-v3 for MLX, required | Hugging Face `mlx-community`, pinned revision | about 3.1 GB |
| Slovak voice (Supertonic 3), required | Hugging Face | about 0.4 GB |
| Translation model `translategemma:4b`, required | Ollama registry (Ollama must be running) | about 3.3 GB |
| Speech removal (Demucs, optional) | PyPI, SHA-256 from `uv.lock`; then the model from Hugging Face | about 60 MB + 80 MB |

   Nothing is downloaded until you press the button.

## Where things are
- The app: `/Applications/LocalDub Studio.app` (it carries its own Python; nothing else is installed)
- Your projects, models and settings: `~/Library/Application Support/LocalDub Studio`
- Logs: `~/Library/Logs/LocalDub Studio/launch.log` and `.../Application Support/LocalDub Studio/data/logs/app.log`

## Update
Drag the new app onto Applications and choose *Replace*. Projects, models and settings stay.

## Uninstall
Move the app to the Bin. To remove your data as well, delete
`~/Library/Application Support/LocalDub Studio` (several GB of models) and
`~/Library/Logs/LocalDub Studio`. Ollama and its models are separate: remove them with Ollama.

## What is different from Windows
- Speech recognition uses Apple's MLX on the Mac's GPU instead of faster-whisper on an NVIDIA card.
  NVIDIA Parakeet (processor, experimental) is available on both.
- PyTorch is already part of the app, so speech removal only needs the small Demucs download.
  Demucs runs on the processor.
- Voice cloning (OpenVoice) is experimental and was not tried on a Mac.
- The Mac has no "Start menu" entry or installer wizard: the app is the single `.app` file.

## What was and was not checked
Checked on every build, on a macOS 15 runner (Apple M1 virtual machine, no GPU):
- the unit tests and type checks pass on macOS;
- the app builds, signs ad hoc, goes into a disk image, and installs from it;
- the app's own Python imports every library, detects Apple Silicon and offers the Mac models;
- the pinned FFmpeg, yt-dlp and Deno downloads match their checksums and start;
- the local server starts from the installed app, serves the interface and keeps data outside the app;
- starting the installed app the way Finder does (`open`) runs the window code and the app logs that it
  loaded the interface in its window (nobody saw that window);
- Whisper tiny through the same MLX code transcribed a spoken sentence word for word on the processor
  (about 11 s for a short sentence on the runner's 3 virtual cores; this says nothing about the GPU or
  about large-v3).

**Not checked** (needs a real Mac): that the window really appears and looks right, the Dock icon and menu, saving a
downloaded video, Whisper large-v3 speed and memory on the GPU, a complete dub, Ollama on the Mac,
the first-start prompts of macOS, sleep and battery behaviour during a long dub.

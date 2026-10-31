# Changelog

All notable changes to LocalDub Studio. Versions are pre-releases: see docs/QUALITY.md for what has and
has not been tested before relying on a feature.

## [Unreleased]

### Changed
- Downloaded video and subtitles are named after the video (the YouTube title or the project name), for example
  "My film.sk.mp4", "My film.sk.srt", "My film.en.srt", instead of "source.sk.mp4".
- Deleting a project now also removes its job logs, and the project database wipes deleted text instead of
  leaving it in free pages, so nothing of the project stays behind.

## [0.4.5] - 2026-10-31

### Fixed
- Slovak typo in the description of Whisper large-v3 turbo ("polovičná").

## [0.4.4] - 2026-10-31

### Added
- The largest accepted video file can be changed on the New dub page ("Largest file: 4 GB, Change"). The
  default stays 4 GB; the choice is kept in the data folder and survives updates.

## [0.4.3] - 2026-10-31

### Changed
- Dark mode uses a cool blue-slate palette with a blue accent instead of orange.

## [0.4.2] - 2026-10-31

### Changed
- AI models page: the model that the "Download the required models" button fetches for each required
  step now carries a "Required" label instead of "Recommended".
- AI models page: the disk space of every downloaded model is shown on its card, plus the total of all
  downloaded models, measured automatically (no need to press a button).
- Qwen3 8B removed from the model list (not recommended for Slovak; it can still be added by name).

## [0.4.1] - 2026-10-31

### Fixed
- After downloading a model, the pickers on the New dub page kept saying "(not downloaded)" until the page was
  reloaded. They now refresh when a download ends and when another page is opened.
- The desktop and Start-menu icon stayed violet after updating because Windows caches icons by file name.
  The icon file has a new name and Setup asks Windows to refresh its icon cache.

### Added
- **Updating an installed copy.** When Setup finds an existing installation it asks what to do: update
  (default), repair (reinstall the program and its libraries from scratch) or remove the old version first and
  then install the new one. Projects, downloaded models and settings are kept in every case. Silent setups
  can choose with `/MODE=update|repair|fresh`. Files of the old version that the new one no longer ships are
  removed during an update. The installer test now also runs an update and a remove-and-install.

## [0.4.0] - 2026-10-31

### Added
- **More spoken languages.** Besides English: German, Italian, Spanish, Japanese, Chinese, Russian,
  Ukrainian, Polish and Hungarian (or detect automatically). No extra download: Whisper already knows them.
  Models that do not know a language (Whisper small.en, Parakeet for Japanese/Chinese) are greyed out and
  refused by the server. Only English has been tested end to end; the other languages are unverified.
- **Dark mode switch.** Theme: Automatic (follows Windows) / Light / Dark, remembered.
- **Several YouTube links at once** (one per line); each becomes its own dub. Several video files could
  already be added together. Dubs are processed one after another; the project list numbers the waiting ones.
- **Slovak interface.** A language switch (English / Slovenčina) in the sidebar. It follows the Windows
  language on first start and remembers your choice. Model descriptions are translated too. The Slovak
  texts are first drafts: tell us what reads badly.
- **Voice samples.** A "Listen" button next to the Slovak voice picks a short sample of the selected voice,
  so you can choose by ear.
- **Cancel a download.** Every model download (and the optional packages and YouTube tools) can be cancelled
  while it runs, or while it waits in the queue; half-downloaded files are removed. Only the unpacking step of
  the optional packages cannot be interrupted.

### Changed
- The program and installer icon is orange, like the interface (it was violet).
- Hugging Face downloads use plain HTTP (not the Xet transfer engine) so that they can be cancelled.

## [0.3.0] - 2026-10-31

### Added
- **AI model library.** The AI models page is now a library: every model has a description, who should
  choose it and who should skip it, what it needs, whether it fits *your* graphics card, its licence and
  what we actually measured. Download only what you want; make an installed model the default for new dubs.
- **More models.** TranslateGemma 12B and 27B (for bigger graphics cards), Whisper large-v3 turbo and
  small.en, and NVIDIA Parakeet TDT 0.6B v3 (experimental; runs on the processor). Any Ollama model can be
  added by name.
- **Speech recognition per dub.** Each dub remembers its recognition model; changing it re-runs from that step.
- **Managing models.** Check for updates on request (nothing is checked in the background), update,
  re-download a damaged model, open its folder, delete with a confirmation, see where everything is stored
  and how much space it takes.

### Changed
- Models are looked up from a shipped catalogue (`catalog.json`), so new models can arrive with updates.
- Hugging Face downloads now go to the program's own models folder.
- Parakeet vs Whisper on 4 English clips: 0 to 6% of words differ, mostly punctuation, and it misheard rare
  names; speed on our laptop was similar. Whisper large-v3 stays the default.

## [0.2.0] - 2026-10-30

### Added
- **Timeline editor.** The original audio as a waveform, the English lines as blocks you can drag, resize
  (by the edges) and nudge with the arrow keys (Shift = 0.5 s), and a second lane showing where the Slovak
  speech really sits, red where it runs past its window. Snaps to neighbouring lines and the playhead,
  never overlaps, zooms with Ctrl + wheel, follows the preview video.
- **YouTube import.** A "YouTube link" tab: paste a link, check it (title, channel, length, thumbnail), pick
  a quality and start. The first use offers a one-click install of yt-dlp and Deno (about 70 MB, checked
  against the publishers' SHA-256). Downloading is the first step of the job, so it shows progress, can be
  cancelled and survives a crash. Only YouTube https links; no playlists or live streams. Optional cookies
  from your own Edge/Chrome/Firefox for age-restricted or members-only videos. "Update yt-dlp" button.
- **New look.** A redesigned interface ("dubbing booth"): light and dark themes, level-meter progress,
  step pills, new sidebar. Fonts and icons are bundled, so it works offline.
- Failed jobs: copy the error, copy the full log or download it.

### Changed
- Optional PyTorch packages (speech removal, voice cloning) and all AI models are installed from inside the
  app with visible progress; the installer itself downloads no models.
- Uninstalling also removes the YouTube tools; it still asks before deleting your projects, models and the
  optional packages.

### Fixed
- Found by an independent code review and by real-browser tests: a slow answer for an old link could replace
  the card of a newer link; preview audio kept playing after leaving the page and its memory was never freed;
  a cancelled drag left a block displaced; a download could be left running after cancelling a job; the
  package installer could fail with a half-deleted folder or move its progress bar backwards; no job can start
  while the optional packages are being installed; links with spaces or line breaks are refused.
- The progress bar no longer jumps back to 0 on text-only statuses ("Merging formats").

### Not tested (please report problems)
- The setup wizard itself on a clean Windows without FFmpeg/Ollama, Windows 10, PCs without an NVIDIA GPU,
  and the desktop RTX 5070 Ti.
- YouTube: age-restricted/members-only videos and the cookie option, PO-token videos, region locks.
  If downloads stop working, use "Update yt-dlp".
- How the dub, the voice cloning and the speech removal *sound* (only measured numbers exist).
- Updating from 0.1.x is covered by automated tests (database and work folders), not by a manual upgrade.

## [0.1.3] - 2026-10-30
- Optional PyTorch packages install from inside the app with one click (no commands, no administrator).

## [0.1.2] - 2026-10-30
- AI models are downloaded in the app with progress. Fixes "system error number 13" (a model written by the
  elevated installer was unreadable for the normal user). Download of the job log.

## [0.1.1] - 2026-10-30
- Installs into Program Files (fixes "untrusted mount point" error 448). Superseded by 0.1.2.

## [0.1.0] - 2026-10-29
- First pre-release. Its installer could leave the program without its libraries; do not use it.

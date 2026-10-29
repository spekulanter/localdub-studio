# Quality measurements and known limitations

Every number here was measured; anything not measured is listed under **Unverified**.
Hardware: RTX 5060 Laptop 8 GB, i7-13700HX, Windows 11 (see ENVIRONMENT.md).

## M0 pipeline run: synthetic clip, manual translation (2026-10-29)
Input: `work/m0_checks/syn tést ✓/anglický klip.mp4`. It is 19.3 s of English speech made with
Supertonic, over an H.264 test pattern. The path has spaces and Unicode on purpose.
Translation: a **hand-written Slovak reference**, injected through the `TranslationProvider`
interface (`work/m0_checks/manual_translate_run.py`), because Ollama is not installed yet.

| Check (`localdub-m0 verify --back-transcribe`) | Result |
|---|---|
| Output MP4 probes, duration delta | PASS, 0.000 s |
| Video stream copied (streamhash sha256 equal) | PASS |
| Audio: dub first (`slk`, default) + original second | PASS |
| Slovak SRT valid (UTF-8 BOM, 4 cues) | PASS |
| TTS clips non-silent | PASS, min RMS −24.8 dBFS |
| Dub length = source length @ 48 kHz | PASS |
| Fit report | 4/4 ok |
| Back-transcription (Whisper sk on the dub vs the SK text) | PASS, char similarity **0.993** |

Retry check: after editing `translation.json`, only `tts`, `assemble` and `export` re-ran.
The earlier stages were skipped because their checkpoints were still valid.

Overflow handling: a deliberately long line (4.4 s of speech for a 4.2 s window) reached the
speed cap (×1.25 Supertonic, ×1.275 effective). It was marked `overflow` in `fit_report.json`.
The next segment was shifted 0.35 s later instead of overlapping. The audio is not sped up past
the cap. Shortening the line is a translation or review job (the Ollama shorten-retry, M2
editing).

Stage timings (19 s clip, warm disk): ASR ≈ 5 s including model load; TTS 5.6 s with 4 threads
(it was 11.1 s with ONNX "auto" threads); assemble 0.1 s; export 0.4 s.

## M0 real-clip runs (2026-10-29, translategemma:4b, voice F1)
Three real English clips (about 44–53 s each) from `samples/`. Their filenames contain
spaces, a fullwidth colon (`：`), brackets and an emoji. Full pipeline, no manual edits:

| Clip | Segments | Fit ok / stretched / shifted / overflow | Back-transcription similarity | Verify |
|---|---|---|---|---|
| Conversation role play (50.0 s) | 10 | 7 / 1 / 1 / 1 | 1.000 | PASS |
| Atomic Habits interview (52.8 s) | 12 | 6 / 3 / 1 / 2 | 0.993 | PASS |
| Cuisine vlog (43.6 s) | 10 | 2 / 4 / 2 / 2 | 0.976 | PASS |

All three: duration delta 0.000 s, video stream hash identical, the Slovak track first (`slk`).
Wall time for the whole pipeline: 46 s for the 50 s clip, 75 s for the 53 s clip (including model
loads and Ollama).

Objective checks cover **intelligibility and timing only**, not translation correctness or
voice naturalness. A human must judge those.

### Defects found by the real clips (and fixed)
1. The LLM leaked a Cyrillic word into a Slovak sentence. The Slovak TTS also rejects `„`. Fixed:
   typographic punctuation is normalised, foreign-script output is retried and finally stripped
   (but the model is deterministic, so retries rarely help), and unsupported characters are removed
   before TTS (with a warning).
2. translategemma ignored the length budget, so 8 of 12 segments overflowed on the fast speaker.
   Fixed: the shorten pass now applies to every model, and the budget is 17 cps (measured TTS rate).
   Overflow went from 8/12 to 2/12 on that clip.
3. The back-transcription check scored 0.539 on a dub that was in fact intelligible, because
   `difflib.SequenceMatcher` auto-junks strings over 200 characters. Fixed with `autojunk=False`
   (true value 0.993).

### Known translation-quality problems seen in these runs
- Shortening sometimes drops meaning: "carbonation" became "obsah CO2"; "plant-based" disappeared.
- Gender is guessed: "Rástol som" (masculine) and "rád/a" were produced for a speaker of unknown
  gender; "rád/a" is not natural to speak.
- Odd literal phrasing ("vnímané", "zbieranie"). The Slovak is understandable but not polished.
- Fast speakers still overflow (up to 20 % of segments); the next segment is shifted, so the
  dub can lag the video by up to a second or so.

## Translation model comparison (12 lines, `docs/translation_benchmark.md`)
Both models ran on the laptop RTX 5060 (8 GB).

| Model | Time (12 lines) | Over budget | Serious mistranslations |
|---|---|---|---|
| translategemma:4b | 47 s (incl. 43 s load) | 8 | none: idioms rendered plainly |
| qwen3:8b | 128 s (incl. 120 s load) | 4 | "Trať odchádza", "pršie ako z krygu", "mačku v košíku", "show" |

Decision: **translategemma:4b is the default**. qwen3:8b produced shorter lines but several wrong
or nonsensical ones. Ratings by Claude, not by a native speaker: please check the human-rating
column in the benchmark file.

## Known limitations (by design in M0)
- Voice-over mix: by default the original audio is ducked by 14 dB, not removed (`--original-audio
  mute` makes the dubbed track dub-only, which also removes music and effects). There is no
  dialogue/background separation yet (M3, experimental).
- One voice for all speakers; no diarization (M2).
- Supertonic is not bit-deterministic. Re-synthesis changes a clip's length by about 1–2 %.
- The ASR segmentation is heuristic (gap and punctuation), so very long sentences without
  pauses are split at clause boundaries.
- `file_digest` uses size+mtime for files over 64 MB. A same-size in-place edit with a preserved
  mtime would not invalidate the checkpoints.

## Unverified (do not claim)
- Translation correctness as judged by a native Slovak speaker (the benchmark's rating column).
- Clips with music, noise or several speakers. All three real clips have one speaker.
- Subjective naturalness of the Slovak voice and the mix. This needs the user's listening check.
- Long videos (5 min+), desktop RTX 5070 Ti: these belong to M1.

## Original-audio options (verified 2026-10-29)
`localdub-m0 run ... --original-audio mute` (or `LOCALDUB_ORIGINAL_AUDIO=mute`) writes a dub-only
track; `--drop-original-track` (or `LOCALDUB_KEEP_ORIGINAL_TRACK=false`) omits the untouched
original from the MP4. Tested on the role-play clip: the mixed track equals the dub sample for
sample, the MP4 has one audio stream (`slk`), verify PASS (back-transcription 0.990). Changing
either option re-runs only `assemble` and `export`.

## M1 backend acceptance (2026-10-29, laptop RTX 5060 8 GB)
Run through the HTTP API (`localdub serve`) with the real worker process.

| Test | Result |
|---|---|
| Upload 50 s clip, progress over SSE, download MP4/SRT | done in 36 s; verify PASS, back-transcription 1.000 |
| **5.7-minute video** (342.7 s, the three samples repeated, 720p) | done in **186 s** (RTF 0.54), no crash; verify PASS: duration delta 0.000 s, video stream identical, 68 valid cues, similarity 0.976 |
| Resources during the 5.7-min run | peak VRAM **4.2 GB** (one model at a time), peak worker RSS 3.1 GB |
| Kill the server process during TTS | worker exited by itself within ~1 s ("Server gone"); on restart the job was re-queued, skipped probe/extract/asr/translate, finished (attempts=2) |
| Cancel during TTS | worker killed, status `cancelled`, no leftover python/ffmpeg process, Ollama model unloaded, VRAM 0 MiB; the next job resumed from checkpoints |
| Fit on the 5.7-min video | ok 40 / stretched 14 / shifted 7 / overflow 7 of 68 (10 %) |

The 5-minute clip repeats the same three recordings, so it stresses duration, memory and stability,
not translation variety. Not yet tested: the desktop RTX 5070 Ti, a job killed *during ASR or
translation* (those stages restart from the beginning, by design), and several queued jobs
back to back on real media (covered only by unit tests with a fake worker).

### Frontend (2026-10-29)
Built with React 19, TypeScript 5.9 (strict), Vite 8 and Tailwind 4. Verified: `tsc` strict, 10
vitest tests (upload form, progress/cancel/retry, segments table, restart-stage logic), and a
headless-Edge screenshot of the new-dub and finished-project pages with real data from the 5.7-min
run. Live API check of "Apply and re-render": switching to muted audio re-ran only assemble and
export in 1.6 s, leaving one `slk` audio track.

**Not verified:** a real click-through in a browser (file chooser, drag-and-drop, SSE in the browser,
video playback of the dub). The API behind them is covered by tests and live runs; the UI wiring is
covered by component tests only.

Also fixed after reading the 5.7-min dialogue: slash gender forms from the LLM ("stretol/a",
"rád/a") are now reduced to the masculine form before TTS. The speaker's gender is still guessed;
a per-project "speaker gender" option is a candidate for M2.

## M2 editing and diarization (2026-10-29)
**Editing (verified):** editing one line of a 10-line project and re-rendering took 4.4 s (9 clips
reused from the cache, 1 synthesised); verify PASS afterwards (similarity 1.000). An edit made for a
sentence whose recognised English later changes is ignored and flagged, never applied to the wrong
line. Editing is blocked while a job runs.

**Diarization (experimental, opt-in):** sherpa-onnx, CPU, about 0.4x real time (21 s for 50 s of
audio) plus a 10-14 s model load.
- Synthetic 3-voice English dialogue (Supertonic M1/F1/M2, 10 lines, exact ground truth, full
  pipeline via the API): **10 of 10 lines attributed to the right speaker** with the count given
  (3). Without the count, the default threshold 0.5 found 6-7 speakers; 0.8-0.9 found 3-4. The
  default is now 0.85 and the UI asks for the speaker count; results varied slightly between runs
  because the synthetic audio differs on every run.
- Voice gender from median pitch (heuristic): the three synthetic speakers were classified
  correctly (126 Hz, 184 Hz, 97 Hz -> M, F, M), and default voices follow it.
- **Real recordings: not verified.** The only two-person-looking clip (role play) gave a single
  speaker when told to find two and two speakers when told to find three, and its pitch difference
  between the two groups was small (184 vs 213 Hz). I do not know its ground truth, so I cannot say
  whether the split is right. Treat diarization as experimental until tested on real multi-speaker
  video with a known speaker count.
- Synthetic TTS voices are far more distinct than real people, so 10/10 is an upper bound.

## Loudness matching (M2 mixing, 2026-10-29)
The dub used to sit 2-5 LU below the original speech (it was normalised to a fixed -18 dBFS RMS).
Now the dub is raised or lowered (max ±8 dB, through an FFmpeg look-ahead limiter at 0.95 so it
never clips) to the integrated loudness of the original audio (clamped to -23...-14 LUFS), and the
final mix is turned down to at most -14 LUFS. Measured with EBU R128 (`ebur128`) on the three real
clips:

| Clip | Original | Dub before -> after | Mix before -> after |
|---|---|---|---|
| Role play | -13.7 LUFS | -18.8 -> -14.4 | -15.7 -> -14.0 |
| Interview | -16.4 LUFS | -18.7 -> -16.4 | -15.6 -> -14.0 |
| Cuisine vlog | -17.9 LUFS | -18.7 -> -17.9 | -15.8 -> -15.0 |

All three still pass `verify` (back-transcription 1.000 / 0.991 / 0.974). Loudness is measured over
the whole programme including music, so a very music-heavy original raises the dub target; the
clamp limits that. Turn it off with `LOCALDUB_MATCH_ORIGINAL_LOUDNESS=false`. Whether it *sounds*
better is a listening judgement that has not been made by a human.

## Dialogue/background separation (experimental, 2026-10-29)
`original_audio = background`: Demucs (`htdemucs`, GPU) splits the original audio, the speech stem
is dropped, the background (drums + bass + other) stays 3 dB under the dub. RTX 5060 laptop: model
load 6-13 s, 23 s for 43 s of audio (RTF 0.5), peak VRAM 0.58 GB, 9.6 MB left after `close()`.

Measured on the cuisine vlog (the only sample with background music, -29.3 LUFS background stem):
- Whisper transcribes **120 words** from the speech stem and **0 words** from the background stem.
- Regressing the final mix on {original speech, background, dub}: original speech weight
  duck mode -13.0 dB, mute mode 0, **background mode -94 dB (none)**; background -2.7 dB (as
  configured); dub 1.0; 2 % unexplained.
- The role-play clip has no music: its background stem is -61 LUFS (silence), so "background" mode
  there equals "mute". That is correct, not a failure.

Limits (not tested): singing, music with vocals, speech over loud music, mono sources, long videos
(memory use grows with `split` chunks but was only measured on 43 s), tracks where dialogue and
effects overlap. A first-use download of about 80 MB and 3 GB of PyTorch is required.

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

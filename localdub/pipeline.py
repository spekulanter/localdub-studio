"""Stage runner for the dubbing pipeline.

Each stage reads the previous stage's files from the work directory and writes its own,
so any stage can be retried independently. See ARCHITECTURE.md for the file layout.
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf

from localdub.config import Settings
from localdub.core.asr.base import ASRProvider
from localdub.core.asr.segmentation import group_words
from localdub.core.audio.assemble import build_timeline, db_to_gain, normalize_rms, trim_silence
from localdub.core.audio.mix import voice_over_mix
from localdub.core.diarize.base import Diarizer
from localdub.core.diarize.pitch import load_speaker_genders
from localdub.core.export.srt import write_srt
from localdub.core.jobs.checkpoints import CheckpointStore, atomic_write_json, fingerprint
from localdub.core.media.ffmpeg import FFmpeg, MediaError, MediaInfo
from localdub.core.modelmgr.resolve import resolve_asr
from localdub.core.timeline.edits import apply_edits, ensure_edits_file, load_edits
from localdub.core.timeline.fit import available_windows, decide, place
from localdub.core.timeline.models import DialogueSegment, FitStatus, Transcript
from localdub.core.translation.base import TranslationProvider
from localdub.core.translation.prompts import normalize_punctuation
from localdub.core.tts.base import TTSProvider, default_speaker_voices

log = logging.getLogger(__name__)

STAGES = [
    "download",
    "probe",
    "extract",
    "asr",
    "diarize",
    "translate",
    "tts",
    "separate",
    "convert",
    "assemble",
    "export",
]

ProgressFn = Callable[[str, str], None]


class PipelineError(RuntimeError):
    def __init__(self, stage: str, message: str) -> None:
        super().__init__(f"[{stage}] {message}")
        self.stage = stage


@dataclass(frozen=True)
class RemoteSource:
    """A video that must be fetched before processing (e.g. from YouTube)."""

    key: str  # goes into the stage fingerprint (link, quality): a different link downloads again
    fetch: Callable[[Path, Callable[[str], None]], None]  # (destination file, say(progress text))


@dataclass
class Providers:
    """Factories, so a model is only loaded when its stage actually runs."""

    asr: Callable[[], ASRProvider]
    translator: Callable[[], TranslationProvider]
    tts: Callable[[], TTSProvider]
    diarizer: Callable[[], Diarizer] | None = None  # None -> sherpa-onnx (built when needed)


def default_providers(settings: Settings) -> Providers:
    def asr() -> ASRProvider:
        choice = resolve_asr(settings)
        if choice.engine == "parakeet":
            from localdub.core.asr.parakeet_provider import ParakeetProvider

            assert choice.folder is not None
            return ParakeetProvider(choice.folder, num_threads=settings.tts_threads or 4)
        if choice.engine == "mlx":
            from localdub.core.asr.mlx_whisper_provider import MlxWhisperProvider

            assert choice.repo is not None
            return MlxWhisperProvider(
                choice.repo,
                choice.revision,
                choice.name,
                download_root=settings.models_dir / "whisper",
                device="cpu" if settings.asr_device == "cpu" else None,
            )
        from localdub.core.asr.faster_whisper_provider import FasterWhisperProvider

        return FasterWhisperProvider(
            choice.name,
            device=settings.asr_device,
            compute_type=settings.asr_compute_type,
            download_root=settings.models_dir / "whisper",
            beam_size=settings.asr_beam_size,
            repo=choice.repo,
        )

    def translator() -> TranslationProvider:
        from localdub.core.translation.ollama_provider import OllamaClient, OllamaTranslator

        return OllamaTranslator(
            OllamaClient(settings.ollama_url),
            settings.translation_model,
            chars_per_second=settings.chars_per_second,
            context_before=settings.translation_context_before,
            context_after=settings.translation_context_after,
        )

    def tts() -> TTSProvider:
        from localdub.core.tts.supertonic_provider import SupertonicProvider

        return SupertonicProvider(
            settings.tts_model,
            model_dir=settings.models_dir / settings.tts_model.replace("-", ""),
            steps=settings.tts_steps,
            threads=settings.tts_threads,
        )

    return Providers(asr=asr, translator=translator, tts=tts)


def load_segments(path: Path) -> list[DialogueSegment]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return [DialogueSegment.model_validate(s) for s in data["segments"]]


def save_segments(path: Path, segments: list[DialogueSegment], **extra: Any) -> None:
    atomic_write_json(path, {**extra, "segments": [s.model_dump(mode="json") for s in segments]})


class Pipeline:
    def __init__(
        self,
        input_path: Path,
        workdir: Path,
        settings: Settings,
        *,
        source_lang: str | None = "en",
        target_lang: str = "sk",
        voice: str | None = None,
        providers: Providers | None = None,
        ffmpeg: FFmpeg | None = None,
        on_progress: ProgressFn | None = None,
        remote: RemoteSource | None = None,
    ) -> None:
        self.remote = remote
        self.input = input_path.resolve()
        self.wd = workdir.resolve()
        self.wd.mkdir(parents=True, exist_ok=True)
        self.s = settings
        self.source_lang = source_lang
        self.target_lang = target_lang
        self.voice = voice or settings.tts_voice
        self.providers = providers or default_providers(settings)
        self.ff = ffmpeg or FFmpeg(settings.ffmpeg_path, settings.ffprobe_path)
        self.store = CheckpointStore(self.wd)
        self.on_progress = on_progress or (lambda stage, msg: None)
        self._rubberband: bool | None = None

    # ----- file layout -------------------------------------------------------------------
    def p(self, name: str) -> Path:
        return self.wd / name

    @property
    def output_video(self) -> Path:
        return self.p(f"{self.input.stem}.{self.target_lang}.mp4")

    @property
    def output_srt(self) -> Path:
        return self.p(f"{self.input.stem}.{self.target_lang}.srt")

    def info(self) -> MediaInfo:
        return MediaInfo.model_validate_json(self.p("probe.json").read_text(encoding="utf-8"))

    # ----- runner ------------------------------------------------------------------------
    def run(self, from_stage: str | None = None, to_stage: str | None = None) -> dict[str, str]:
        """Run stages in order; completed, unchanged stages are skipped.

        Returns {stage: "ran" | "skipped"}.
        """
        if self.remote is None and not self.input.is_file():
            raise PipelineError("probe", f"Input video not found: {self.input}")
        if from_stage is not None:
            self.store.invalidate(STAGES[STAGES.index(from_stage) :])
        last = STAGES.index(to_stage) if to_stage else len(STAGES) - 1
        ensure_edits_file(self.p("edits.json"))
        result: dict[str, str] = {}
        for stage in STAGES[: last + 1]:
            params, inputs, fn = self._spec(stage)
            missing = [str(i) for i in inputs if not i.is_file()]
            if missing:
                raise PipelineError(
                    stage, f"Missing input file(s) {missing}; re-run earlier stages"
                )
            fp = fingerprint(params, inputs)
            if self.store.is_complete(stage, fp):
                log.info("stage %-9s skipped (checkpoint valid)", stage)
                result[stage] = "skipped"
                continue
            log.info("stage %-9s running", stage)
            self.on_progress(stage, "running")
            t0 = time.perf_counter()
            try:
                outputs = fn()
            except PipelineError:
                raise
            except Exception as exc:
                log.exception("stage %s failed", stage)
                raise PipelineError(stage, f"{type(exc).__name__}: {exc}") from exc
            elapsed = time.perf_counter() - t0
            self.store.mark_complete(stage, fp, outputs, elapsed)
            log.info("stage %-9s done in %.1fs", stage, elapsed)
            self.on_progress(stage, "done")
            result[stage] = "ran"
        return result

    def _spec(self, stage: str) -> tuple[dict[str, Any], list[Path], Callable[[], list[Path]]]:
        s = self.s
        asr = resolve_asr(s)
        specs: dict[str, tuple[dict[str, Any], list[Path], Callable[[], list[Path]]]] = {
            "download": ({"source": self.remote.key if self.remote else None}, [], self._download),
            "probe": ({}, [self.input], self._probe),
            "extract": ({"sr": s.sample_rate}, [self.input], self._extract),
            "asr": (
                {
                    # "large-v3" for the default keeps the fingerprints of older work folders valid
                    "model": asr.name,
                    **({"engine": asr.engine} if asr.engine != "whisper" else {}),
                    "beam": s.asr_beam_size,
                    "compute": [s.asr_device, s.asr_compute_type],
                    "lang": self.source_lang,
                    "seg": [s.segment_min_s, s.segment_max_s, s.segment_max_gap_s],
                },
                [self.p("audio_16k.wav")],
                self._asr,
            ),
            "diarize": (
                {
                    "enabled": s.diarization_enabled,
                    "speakers": s.diarization_num_speakers,
                    "threshold": s.diarization_threshold,
                },
                [self.p("audio_16k.wav"), self.p("asr.json")],
                self._diarize,
            ),
            "translate": (
                {
                    "model": s.translation_model,
                    "target": self.target_lang,
                    "ctx": [s.translation_context_before, s.translation_context_after],
                    "cps": s.chars_per_second,
                },
                [self.p("dialogue.json")],
                self._translate,
            ),
            "tts": (
                {
                    "model": s.tts_model,
                    "voice": self.voice,
                    "steps": s.tts_steps,
                    "speed": [s.tts_base_speed, s.max_speed],
                    "gap": s.segment_gap_s,
                    "sr": s.sample_rate,
                },
                [self.p("translation.json"), self.p("probe.json"), self.p("edits.json")],
                self._tts,
            ),
            "separate": (
                {"enabled": s.original_audio == "background"},
                [self.p("audio_orig.wav")],
                self._separate,
            ),
            "convert": (
                {"enabled": s.voice_cloning_enabled, "tau": s.voice_cloning_tau},
                [
                    self.p("tts.json"),
                    self.p("audio_orig.wav"),
                    *([self.p("vocals.wav")] if s.original_audio == "background" else []),
                ],
                self._convert,
            ),
            "assemble": (
                {
                    "duck": [s.duck_db, s.duck_ramp_s],
                    "original": s.original_audio,
                    "loudness": [
                        s.match_original_loudness,
                        s.loudness_target_range_lufs,
                        s.loudness_max_adjust_db,
                        s.max_mix_lufs,
                    ],
                    "target": s.dub_target_dbfs,
                    "gap": s.segment_gap_s,
                },
                [
                    self.p("voiced.json"),
                    self.p("audio_orig.wav"),
                    *([self.p("background.wav")] if s.original_audio == "background" else []),
                ],
                self._assemble,
            ),
            "export": (
                {
                    "bitrate": s.output_audio_bitrate,
                    "lang": self.target_lang,
                    "keep_original_track": s.keep_original_track,
                },
                [self.p("segments.json"), self.p("mix.wav"), self.input],
                self._export,
            ),
        }
        return specs[stage]

    # ----- stages ------------------------------------------------------------------------
    def _download(self) -> list[Path]:
        """Fetch the video when the project came from a link; a no-op for uploaded files."""
        if self.remote is None:
            return []
        if self.input.is_file():
            try:
                self.ff.probe(self.input)
                return []  # an earlier attempt already finished the download
            except MediaError:
                log.warning("%s is not a playable video; downloading it again", self.input.name)
                self.input.unlink(missing_ok=True)
        self.input.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.remote.fetch(self.input, lambda text: self.on_progress("download", text))
        except PipelineError:
            raise
        except Exception as exc:
            raise PipelineError("download", str(exc)) from exc
        if not self.input.is_file():
            raise PipelineError("download", "The download finished but the video file is missing")
        return []  # the file is outside the work folder; probe fails clearly if it disappears

    def _probe(self) -> list[Path]:
        info = self.ff.probe(self.input)
        if not info.video_streams:
            raise PipelineError("probe", f"No video stream found in {self.input}")
        if not info.audio_streams:
            raise PipelineError("probe", f"No audio stream found in {self.input}; nothing to dub")
        out = self.p("probe.json")
        atomic_write_json(out, info.model_dump())
        return [out]

    def _extract(self) -> list[Path]:
        info = self.info()
        a16, orig = self.p("audio_16k.wav"), self.p("audio_orig.wav")
        self.ff.extract_audio(self.input, a16, sample_rate=16000, channels=1)
        channels = min(info.audio_streams[0].channels or 2, 2)
        self.ff.extract_audio(self.input, orig, sample_rate=self.s.sample_rate, channels=channels)
        return [a16, orig]

    def _asr(self) -> list[Path]:
        asr = self.providers.asr()
        try:
            res = asr.transcribe(self.p("audio_16k.wav"), language=self.source_lang)
        finally:
            asr.close()
        segs = group_words(
            res.words,
            min_s=self.s.segment_min_s,
            max_s=self.s.segment_max_s,
            max_gap_s=self.s.segment_max_gap_s,
        )
        if not segs:
            raise PipelineError("asr", "No speech was recognized in the audio")
        tr = Transcript(
            language=res.language,
            language_probability=res.language_probability,
            duration=self.info().duration,
            segments=segs,
        )
        out = self.p("asr.json")
        atomic_write_json(out, {"engine": res.engine, **tr.model_dump(mode="json")})
        log.info("ASR: %d words -> %d segments (%s)", len(res.words), len(segs), res.engine)
        return [out]

    def _make_diarizer(self) -> Diarizer:
        if self.providers.diarizer is not None:
            return self.providers.diarizer()
        from localdub.core.diarize.sherpa_diarizer import SherpaDiarizer

        return SherpaDiarizer(
            self.s.models_dir,
            num_speakers=self.s.diarization_num_speakers,
            threshold=self.s.diarization_threshold,
            threads=self.s.tts_threads or 4,
        )

    def _diarize(self) -> list[Path]:
        """Optional: label speakers and split segments at speaker changes -> dialogue.json."""
        segs = load_segments(self.p("asr.json"))
        asr = json.loads(self.p("asr.json").read_text("utf-8"))
        out = self.p("dialogue.json")
        if not self.s.diarization_enabled:
            self.p("diarization.json").unlink(missing_ok=True)
            save_segments(out, segs, language=asr["language"])
            return [out]
        from localdub.core.diarize.assign import assign_speakers

        diarizer = self._make_diarizer()
        try:
            turns = diarizer.diarize(self.p("audio_16k.wav"))
        finally:
            diarizer.close()
        from localdub.core.diarize.pitch import estimate_speaker_f0

        samples, sr = sf.read(str(self.p("audio_16k.wav")), dtype="float32")
        atomic_write_json(
            self.p("diarization.json"),
            {
                "turns": [{"start": t.start, "end": t.end, "speaker": t.speaker} for t in turns],
                "speaker_f0": estimate_speaker_f0(samples, sr, turns),
            },
        )
        split = assign_speakers(segs, turns)
        save_segments(out, split, language=asr["language"])
        speakers = sorted({s.speaker_id for s in split})
        log.info("Diarize: %d segments -> %d, speakers %s", len(segs), len(split), speakers)
        return [out, self.p("diarization.json")]

    def _translate(self) -> list[Path]:
        segs = load_segments(self.p("dialogue.json"))
        src = self.source_lang or json.loads(self.p("dialogue.json").read_text("utf-8"))["language"]
        tr = self.providers.translator()
        try:
            texts = tr.translate_segments(segs, src, self.target_lang)
        finally:
            tr.close()
        for seg, text in zip(segs, texts, strict=True):
            seg.translated_text = text
        out = self.p("translation.json")
        save_segments(out, segs, model=self.s.translation_model, source_lang=src)
        return [out]

    def _uses_rubberband(self) -> bool:
        if self._rubberband is None:
            self._rubberband = self.ff.has_filter("rubberband")
            if not self._rubberband:
                log.warning("FFmpeg lacks the rubberband filter; using atempo for time-stretching")
        return self._rubberband

    def _tts_key(self, text: str, voice: str, window: float) -> str:
        """Everything that changes a clip: if this is unchanged the cached clip is reused."""
        s = self.s
        payload = [
            text, voice, self.target_lang, s.tts_model, s.tts_steps, s.tts_base_speed,
            s.max_speed, round(window, 2), s.sample_rate, self._uses_rubberband(),
        ]  # fmt: skip
        return hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode()).hexdigest()[:20]

    def _tts(self) -> list[Path]:
        segs = load_segments(self.p("translation.json"))
        edits = load_edits(self.p("edits.json"))
        speakers = list(dict.fromkeys(s.speaker_id for s in segs))
        genders = load_speaker_genders(self.p("diarization.json"))
        for sp, v in default_speaker_voices(speakers, self.voice, genders).items():
            edits.speaker_voices.setdefault(sp, v)
        report = apply_edits(segs, edits)
        if report["stale"]:
            log.warning(
                "Ignoring edits for segments whose source text changed: %s", report["stale"]
            )
        duration = self.info().duration
        windows = available_windows(segs, duration, self.s.segment_gap_s)
        raw_dir, clip_dir = self.p("tts/raw"), self.p("tts/clips")
        raw_dir.mkdir(parents=True, exist_ok=True)
        clip_dir.mkdir(parents=True, exist_ok=True)
        cache_path = self.p("tts/cache.json")
        cache: dict[str, dict[str, Any]] = {}
        if cache_path.is_file():
            try:
                cache = json.loads(cache_path.read_text(encoding="utf-8"))
            except ValueError:
                cache = {}
        base = self.s.tts_base_speed
        tts: TTSProvider | None = None  # loaded lazily: an all-cached run never loads the model
        reused = 0
        try:
            for n, (seg, window) in enumerate(zip(segs, windows, strict=True), start=1):
                self.on_progress("tts", f"{n}/{len(segs)}")
                voice = seg.voice_id or self.voice
                text = normalize_punctuation(seg.translated_text).strip()
                key = self._tts_key(text, voice, window)
                hit = cache.get(str(seg.id))
                if text and hit and hit["key"] == key and (self.wd / hit["audio_path"]).is_file():
                    seg.audio_path = hit["audio_path"]
                    seg.audio_duration = hit["audio_duration"]
                    seg.tts_speed = hit["tts_speed"]
                    seg.stretch_ratio = hit["stretch_ratio"]
                    seg.fit_status = FitStatus(hit["fit_status"])
                    seg.voice_id = voice
                    reused += 1
                    continue
                if tts is None:
                    tts = self.providers.tts()
                if text:
                    bad = tts.unsupported_chars(text)
                    if bad:
                        log.warning(
                            "seg %s: removing characters unsupported by TTS: %s", seg.id, bad
                        )
                        text = " ".join("".join(c for c in text if c not in bad).split())
                if not text:
                    seg.fit_status, seg.audio_path = FitStatus.OK, None
                    cache.pop(str(seg.id), None)
                    continue
                sr = tts.sample_rate
                wav = trim_silence(
                    tts.synthesize(text, voice=voice, lang=self.target_lang, speed=base), sr
                )
                decision = decide(wav.size / sr, window, self.s.max_speed)
                speed = base
                if decision.speed_factor > 1.0:
                    # Prefer the model's own rate control; it sounds better than DSP stretching.
                    speed = base * decision.speed_factor * 1.02
                    wav = trim_silence(
                        tts.synthesize(text, voice=voice, lang=self.target_lang, speed=speed), sr
                    )
                dur = wav.size / sr
                tempo = 1.0
                if dur > window and decision.status is not FitStatus.OVERFLOW:
                    tempo = min(dur / window, 1.10)  # small residual correction
                raw = raw_dir / f"seg_{seg.id:04d}.wav"
                clip = clip_dir / f"seg_{seg.id:04d}.wav"
                sf.write(raw, wav, sr, subtype="PCM_16")
                self.ff.convert_audio(
                    raw, clip, sample_rate=self.s.sample_rate, tempo=tempo,
                    rubberband=self._uses_rubberband(),
                )  # fmt: skip
                final = sf.info(str(clip)).duration
                seg.audio_path = str(clip.relative_to(self.wd))
                seg.audio_duration = round(final, 3)
                seg.tts_speed = round(speed, 4)
                seg.stretch_ratio = round(speed / base * tempo, 4)
                seg.voice_id = voice
                over = final > window + 0.02
                seg.fit_status = (
                    FitStatus.OVERFLOW
                    if over
                    else FitStatus.STRETCHED
                    if seg.stretch_ratio > 1.001
                    else FitStatus.OK
                )
                cache[str(seg.id)] = {
                    "key": key,
                    "audio_path": seg.audio_path,
                    "audio_duration": seg.audio_duration,
                    "tts_speed": seg.tts_speed,
                    "stretch_ratio": seg.stretch_ratio,
                    "fit_status": seg.fit_status.value,
                }
                log.info(
                    "seg %d: %.2fs in %.2fs window, x%.3f -> %s",
                    seg.id, final, window, seg.stretch_ratio, seg.fit_status.value,
                )  # fmt: skip
        finally:
            if tts is not None:
                tts.close()
        atomic_write_json(cache_path, cache)
        log.info("TTS: %d clips reused from cache, %d synthesised", reused, len(segs) - reused)
        out = self.p("tts.json")
        save_segments(out, segs)
        return [out]

    def _separate(self) -> list[Path]:
        """Optional: split the original audio into dialogue and background (Demucs, GPU)."""
        out_bg, out_voc = self.p("background.wav"), self.p("vocals.wav")
        if self.s.original_audio != "background":
            out_bg.unlink(missing_ok=True)
            out_voc.unlink(missing_ok=True)
            return []
        from localdub.core.separation.demucs_separator import DemucsSeparator, SeparationUnavailable

        try:
            separator = DemucsSeparator(self.s.models_dir)
        except SeparationUnavailable as exc:
            raise PipelineError("separate", str(exc)) from exc
        try:
            src = self.p("separate_in.wav")
            self.ff.run(["-i", self.p("audio_orig.wav"), "-ar", str(separator.sample_rate),
                         "-c:a", "pcm_s16le", src])  # fmt: skip
            stems = separator.separate(src)
        finally:
            separator.close()
        for name, data, dst in (
            ("background", stems.background, out_bg),
            ("vocals", stems.vocals, out_voc),
        ):
            raw = self.p(f"separate_{name}.wav")
            sf.write(raw, data, stems.sample_rate, subtype="FLOAT")
            self.ff.run(["-i", raw, "-ar", str(self.s.sample_rate), "-c:a", "pcm_s16le", dst])
            raw.unlink()
        src.unlink()
        return [out_bg, out_voc]

    def _convert(self) -> list[Path]:
        """Optional: make the Slovak clips sound like the original speakers (OpenVoice V2)."""
        segs = load_segments(self.p("tts.json"))
        out = self.p("voiced.json")
        conv_dir = self.p("tts/converted")
        if not self.s.voice_cloning_enabled:
            shutil.rmtree(conv_dir, ignore_errors=True)
            save_segments(out, segs)
            return [out]
        from localdub.core.separation.demucs_separator import SeparationUnavailable
        from localdub.core.voice.openvoice_converter import OpenVoiceConverter

        try:
            conv = OpenVoiceConverter(self.s.models_dir)
        except SeparationUnavailable as exc:
            raise PipelineError("convert", str(exc)) from exc
        conv_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.p("tts/convert_tmp")
        tmp.mkdir(parents=True, exist_ok=True)
        rate = conv.sample_rate

        def load(path: Path) -> np.ndarray:
            wav = tmp / "in.wav"
            self.ff.convert_audio(path, wav, sample_rate=rate)
            return np.asarray(sf.read(str(wav), dtype="float32")[0], dtype=np.float32)

        try:
            vocals = self.p("vocals.wav")
            reference = load(vocals if vocals.is_file() else self.p("audio_orig.wav"))
            by_speaker: dict[str, list[DialogueSegment]] = {}
            for seg in segs:
                if seg.audio_path:
                    by_speaker.setdefault(seg.speaker_id, []).append(seg)
            converted = 0
            for speaker, members in by_speaker.items():
                # Reference timbre: the speaker's longest original lines, up to 30 s.
                lines = sorted(members, key=lambda s: s.end - s.start, reverse=True)
                parts: list[np.ndarray] = []
                for s in lines:
                    parts.append(reference[int(s.start * rate) : int(s.end * rate)])
                    if sum(p.size for p in parts) >= 30 * rate:
                        break
                ref = np.concatenate(parts) if parts else np.zeros(0, np.float32)
                if ref.size < 5 * rate:
                    log.warning(
                        "Speaker %s: under 5 s of reference speech, voice kept as is", speaker
                    )
                    continue
                clips = {s.id: load(self.wd / str(s.audio_path)) for s in members}
                src_se = conv.extract_se(list(clips.values())[:10])
                tgt_se = conv.extract_se([ref[: 30 * rate]])
                for s in members:
                    audio = conv.convert(clips[s.id], src_se, tgt_se, tau=self.s.voice_cloning_tau)
                    raw = tmp / f"seg_{s.id:04d}.wav"
                    dst = conv_dir / f"seg_{s.id:04d}.wav"
                    sf.write(raw, audio, rate, subtype="FLOAT")
                    self.ff.run(["-i", raw, "-ar", str(self.s.sample_rate), "-ac", "1",
                                 "-c:a", "pcm_s16le", dst])  # fmt: skip
                    s.audio_path = str(dst.relative_to(self.wd))
                    s.audio_duration = round(sf.info(str(dst)).duration, 3)
                    converted += 1
            log.info("Voice cloning: %d clips converted", converted)
        finally:
            conv.close()
            shutil.rmtree(tmp, ignore_errors=True)
        save_segments(out, segs)
        return [out]

    def _dub_loudness_gain(self, dub: np.ndarray, sr: int) -> float:
        """dB to add to the dub so its loudness matches the original audio (0 when disabled)."""
        if not self.s.match_original_loudness:
            return 0.0
        with tempfile.TemporaryDirectory(prefix="localdub-loud-") as tmp:
            dub_path = Path(tmp) / "dub.wav"
            sf.write(dub_path, dub, sr, subtype="PCM_16")
            dub_lufs = self.ff.measure_lufs(dub_path)
        orig_lufs = self.ff.measure_lufs(self.p("audio_orig.wav"))
        if dub_lufs is None or orig_lufs is None:
            return 0.0
        lo, hi = self.s.loudness_target_range_lufs
        target = min(max(orig_lufs, lo), hi)
        gain = min(
            max(target - dub_lufs, -self.s.loudness_max_adjust_db), self.s.loudness_max_adjust_db
        )
        log.info(
            "Loudness: original %.1f LUFS, dub %.1f LUFS, target %.1f -> %+.1f dB",
            orig_lufs, dub_lufs, target, gain,
        )  # fmt: skip
        return round(gain, 2)

    def _cap_mix_loudness(self, mix: np.ndarray, sr: int) -> np.ndarray:
        """Turn the mix down if it is louder than max_mix_lufs (keeps the dub/original balance)."""
        with tempfile.TemporaryDirectory(prefix="localdub-mix-") as tmp:
            path = Path(tmp) / "mix.wav"
            sf.write(path, mix, sr, subtype="PCM_16")
            lufs = self.ff.measure_lufs(path)
        if lufs is None or lufs <= self.s.max_mix_lufs:
            return mix
        gain_db = self.s.max_mix_lufs - lufs
        log.info(
            "Mix loudness %.1f LUFS exceeds %.1f: %+.1f dB", lufs, self.s.max_mix_lufs, gain_db
        )
        return (mix * db_to_gain(gain_db)).astype(np.float32)

    def _assemble(self) -> list[Path]:
        segs = load_segments(self.p("voiced.json"))
        duration = self.info().duration
        sr = self.s.sample_rate
        voiced = [s for s in segs if s.audio_path]
        clips = []
        for seg in voiced:
            assert seg.audio_path is not None
            data, clip_sr = sf.read(str(self.wd / seg.audio_path), dtype="float32")
            if clip_sr != sr:
                raise PipelineError(
                    "assemble", f"Clip {seg.audio_path} has {clip_sr} Hz, expected {sr}"
                )
            clips.append(normalize_rms(data.reshape(-1), self.s.dub_target_dbfs))

        placements = place(
            [s.start for s in voiced], [c.size / sr for c in clips], self.s.segment_gap_s
        )
        for seg, pl, clip in zip(voiced, placements, clips, strict=True):
            seg.placed_start = round(pl.start, 3)
            if pl.start + clip.size / sr > duration + 1e-3:
                seg.fit_status = FitStatus.OVERFLOW
            elif pl.shifted_by > 0.02 and seg.fit_status is not FitStatus.OVERFLOW:
                seg.fit_status = FitStatus.SHIFTED

        dub = build_timeline(
            [(pl.start, c) for pl, c in zip(placements, clips, strict=True)], duration, sr
        )
        dub_gain_db = self._dub_loudness_gain(dub, sr)
        if dub_gain_db:
            n_dub = dub.size
            with tempfile.TemporaryDirectory(prefix="localdub-gain-") as tmp:
                before, after = Path(tmp) / "in.wav", Path(tmp) / "out.wav"
                sf.write(before, dub, sr, subtype="PCM_16")
                self.ff.gain_with_limiter(before, after, dub_gain_db)  # limiter: no clipping
                louder = sf.read(str(after), dtype="float32")[0].reshape(-1)
            dub = np.pad(louder, (0, max(n_dub - louder.size, 0)))[:n_dub].astype(np.float32)
        background_mode = self.s.original_audio == "background"
        original, orig_sr = sf.read(
            str(self.p("background.wav" if background_mode else "audio_orig.wav")),
            dtype="float32",
            always_2d=True,
        )
        if orig_sr != sr:
            raise PipelineError("assemble", f"Original audio has {orig_sr} Hz, expected {sr}")
        n = dub.size
        original = np.pad(original, ((0, max(n - original.shape[0], 0)), (0, 0)))[:n]
        regions = [
            (pl.start, pl.start + c.size / sr) for pl, c in zip(placements, clips, strict=True)
        ]
        mix = voice_over_mix(
            original,
            dub,
            regions,
            sr,
            self.s.background_duck_db if background_mode else self.s.duck_db,
            self.s.duck_ramp_s,
            mute_original=self.s.original_audio == "mute",
        )

        mix = self._cap_mix_loudness(mix, sr)
        dub_path, mix_path = self.p("dub.wav"), self.p("mix.wav")
        sf.write(dub_path, dub, sr, subtype="PCM_16")
        sf.write(mix_path, mix, sr, subtype="PCM_16")

        windows = available_windows(segs, duration, self.s.segment_gap_s)
        flagged = [
            {
                "id": s.id,
                "start": s.start,
                "placed_start": s.placed_start,
                "window": round(w, 3),
                "audio_duration": s.audio_duration,
                "stretch_ratio": s.stretch_ratio,
                "status": s.fit_status.value,
                "text": s.translated_text,
            }
            for s, w in zip(segs, windows, strict=True)
            if s.fit_status in (FitStatus.OVERFLOW, FitStatus.SHIFTED)
        ]
        report = {
            "duration": duration,
            "segments": len(segs),
            "counts": {st.value: sum(1 for s in segs if s.fit_status is st) for st in FitStatus},
            "flagged": flagged,
        }
        atomic_write_json(self.p("fit_report.json"), report)
        if flagged:
            log.warning(
                "%d segment(s) need review (overflow/shifted); see fit_report.json", len(flagged)
            )
        seg_path = self.p("segments.json")
        save_segments(seg_path, segs)
        return [dub_path, mix_path, seg_path, self.p("fit_report.json")]

    def _export(self) -> list[Path]:
        segs = load_segments(self.p("segments.json"))
        info = self.info()
        write_srt(segs, self.output_srt, use_translation=True)
        src_srt = self.p(f"{self.input.stem}.{self.source_lang or 'src'}.srt")
        write_srt(segs, src_srt, use_translation=False)
        try:
            self.ff.mux(
                self.input,
                self.p("mix.wav"),
                self.output_video,
                duration=info.duration,
                info=info,
                audio_bitrate=self.s.output_audio_bitrate,
                keep_original_audio=self.s.keep_original_track,
                dub_language="slk" if self.target_lang == "sk" else self.target_lang,
                # Supertonic's OpenRAIL-M licence requires disclosing machine-generated content.
                comment=(
                    "AI-generated dub (LocalDub Studio): faster-whisper "
                    f"{resolve_asr(self.s).name}, {self.s.translation_model}, {self.s.tts_model}"
                ),
            )
        except MediaError as exc:
            raise PipelineError("export", str(exc)) from exc
        return [self.output_srt, src_srt, self.output_video]

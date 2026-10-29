"""Stage runner for the dubbing pipeline.

Each stage reads the previous stage's files from the work directory and writes its own,
so any stage can be retried independently. See ARCHITECTURE.md for the file layout.
"""

from __future__ import annotations

import json
import logging
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
from localdub.core.audio.assemble import build_timeline, normalize_rms, trim_silence
from localdub.core.audio.mix import voice_over_mix
from localdub.core.export.srt import write_srt
from localdub.core.jobs.checkpoints import CheckpointStore, atomic_write_json, fingerprint
from localdub.core.media.ffmpeg import FFmpeg, MediaError, MediaInfo
from localdub.core.timeline.fit import available_windows, decide, place
from localdub.core.timeline.models import DialogueSegment, FitStatus, Transcript
from localdub.core.translation.base import TranslationProvider
from localdub.core.translation.prompts import normalize_punctuation
from localdub.core.tts.base import TTSProvider

log = logging.getLogger(__name__)

STAGES = ["probe", "extract", "asr", "translate", "tts", "assemble", "export"]

ProgressFn = Callable[[str, str], None]


class PipelineError(RuntimeError):
    def __init__(self, stage: str, message: str) -> None:
        super().__init__(f"[{stage}] {message}")
        self.stage = stage


@dataclass
class Providers:
    """Factories, so a model is only loaded when its stage actually runs."""

    asr: Callable[[], ASRProvider]
    translator: Callable[[], TranslationProvider]
    tts: Callable[[], TTSProvider]


def default_providers(settings: Settings) -> Providers:
    def asr() -> ASRProvider:
        from localdub.core.asr.faster_whisper_provider import FasterWhisperProvider

        return FasterWhisperProvider(
            settings.asr_model,
            device=settings.asr_device,
            compute_type=settings.asr_compute_type,
            download_root=settings.models_dir / "whisper",
            beam_size=settings.asr_beam_size,
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
    ) -> None:
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
        if not self.input.is_file():
            raise PipelineError("probe", f"Input video not found: {self.input}")
        if from_stage is not None:
            self.store.invalidate(STAGES[STAGES.index(from_stage) :])
        last = STAGES.index(to_stage) if to_stage else len(STAGES) - 1
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
        specs: dict[str, tuple[dict[str, Any], list[Path], Callable[[], list[Path]]]] = {
            "probe": ({}, [self.input], self._probe),
            "extract": ({"sr": s.sample_rate}, [self.input], self._extract),
            "asr": (
                {
                    "model": s.asr_model,
                    "beam": s.asr_beam_size,
                    "compute": [s.asr_device, s.asr_compute_type],
                    "lang": self.source_lang,
                    "seg": [s.segment_min_s, s.segment_max_s, s.segment_max_gap_s],
                },
                [self.p("audio_16k.wav")],
                self._asr,
            ),
            "translate": (
                {
                    "model": s.translation_model,
                    "target": self.target_lang,
                    "ctx": [s.translation_context_before, s.translation_context_after],
                    "cps": s.chars_per_second,
                },
                [self.p("asr.json")],
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
                [self.p("translation.json"), self.p("probe.json")],
                self._tts,
            ),
            "assemble": (
                {
                    "duck": [s.duck_db, s.duck_ramp_s],
                    "target": s.dub_target_dbfs,
                    "gap": s.segment_gap_s,
                },
                [self.p("tts.json"), self.p("audio_orig.wav")],
                self._assemble,
            ),
            "export": (
                {"bitrate": s.output_audio_bitrate, "lang": self.target_lang},
                [self.p("segments.json"), self.p("mix.wav"), self.input],
                self._export,
            ),
        }
        return specs[stage]

    # ----- stages ------------------------------------------------------------------------
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

    def _translate(self) -> list[Path]:
        segs = load_segments(self.p("asr.json"))
        src = self.source_lang or json.loads(self.p("asr.json").read_text("utf-8"))["language"]
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

    def _tts(self) -> list[Path]:
        segs = load_segments(self.p("translation.json"))
        duration = self.info().duration
        windows = available_windows(segs, duration, self.s.segment_gap_s)
        raw_dir, clip_dir = self.p("tts/raw"), self.p("tts/clips")
        raw_dir.mkdir(parents=True, exist_ok=True)
        clip_dir.mkdir(parents=True, exist_ok=True)
        base = self.s.tts_base_speed
        tts = self.providers.tts()
        try:
            sr = tts.sample_rate
            for n, (seg, window) in enumerate(zip(segs, windows, strict=True), start=1):
                self.on_progress("tts", f"{n}/{len(segs)}")
                text = normalize_punctuation(seg.translated_text).strip()
                bad = tts.unsupported_chars(text) if text else []
                if bad:
                    log.warning("seg %s: removing characters unsupported by TTS: %s", seg.id, bad)
                    text = " ".join("".join(c for c in text if c not in bad).split())
                if not text:
                    seg.fit_status, seg.audio_path = FitStatus.OK, None
                    continue
                voice = seg.voice_id or self.voice
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
                log.info(
                    "seg %d: %.2fs in %.2fs window, x%.3f -> %s",
                    seg.id, final, window, seg.stretch_ratio, seg.fit_status.value,
                )  # fmt: skip
        finally:
            tts.close()
        out = self.p("tts.json")
        save_segments(out, segs)
        return [out]

    def _assemble(self) -> list[Path]:
        segs = load_segments(self.p("tts.json"))
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
        original, orig_sr = sf.read(str(self.p("audio_orig.wav")), dtype="float32", always_2d=True)
        if orig_sr != sr:
            raise PipelineError("assemble", f"Original audio has {orig_sr} Hz, expected {sr}")
        n = dub.size
        original = np.pad(original, ((0, max(n - original.shape[0], 0)), (0, 0)))[:n]
        regions = [
            (pl.start, pl.start + c.size / sr) for pl, c in zip(placements, clips, strict=True)
        ]
        mix = voice_over_mix(original, dub, regions, sr, self.s.duck_db, self.s.duck_ramp_s)

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
                dub_language="slk" if self.target_lang == "sk" else self.target_lang,
                # Supertonic's OpenRAIL-M licence requires disclosing machine-generated content.
                comment=(
                    "AI-generated dub (LocalDub Studio): faster-whisper "
                    f"{self.s.asr_model}, {self.s.translation_model}, {self.s.tts_model}"
                ),
            )
        except MediaError as exc:
            raise PipelineError("export", str(exc)) from exc
        return [self.output_srt, src_srt, self.output_video]

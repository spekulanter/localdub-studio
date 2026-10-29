"""Integration tests: FFmpeg probe + full Pipeline run with fake providers.

Skipped when ffmpeg is not on PATH (Windows dev machines without Gyan build).
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from localdub.config import Settings
from localdub.core.asr.base import AsrResult
from localdub.core.export.srt import parse_srt
from localdub.core.jobs.checkpoints import atomic_write_json
from localdub.core.media.ffmpeg import FFmpeg, MediaError, MediaInfo, StreamInfo
from localdub.core.timeline.models import Word
from localdub.pipeline import Pipeline, Providers

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not on PATH")

SLOVAK_DIACRITICS = "ľščťžýáíéňôřďůűĽŠČŤŽÝÁÍÉŇÔŘĎŮŰ"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def video_dir(tmp_path_factory):
    return tmp_path_factory.mktemp("tést dir ✓ s medzerami")


@pytest.fixture(scope="module")
def video_path(video_dir):
    p = video_dir / "vstup video ľšč.mp4"
    ff = FFmpeg()
    ff.run(
        [
            "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
            "-pix_fmt", "yuv420p", "-c:v", "libx264", "-c:a", "aac",
            "-ac", "2", "-t", "10",
            str(p),
        ]
    )  # fmt: skip
    assert p.is_file()
    return p


class FakeTTS:
    """Sine-tone TTS at 44100 Hz; duration = 0.07 * len(text) / speed."""

    sample_rate = 44100
    local_only = True

    def unsupported_chars(self, text: str) -> list[str]:
        return []

    def list_voices(self) -> list[str]:
        return ["F1", "M1"]

    def synthesize(self, text: str, *, voice: str, lang: str, speed: float = 1.0) -> np.ndarray:
        dur = max(0.07 * len(text) / speed, 0.01)
        n = int(dur * self.sample_rate)
        t = np.arange(n, dtype=np.float32) / self.sample_rate
        return (0.3 * np.sin(2 * np.pi * 300 * t)).astype(np.float32)

    def close(self) -> None:
        pass


class FakeASR:
    """Returns fixed Word timestamps producing 3 segments via group_words."""

    def transcribe(self, audio_path: Path, language: str | None = None) -> AsrResult:
        return AsrResult(
            language=language or "en",
            language_probability=0.99,
            duration=10.0,
            words=[
                Word(start=1.0, end=1.5, text=" Hello"),
                Word(start=1.5, end=2.0, text=" there."),
                Word(start=4.0, end=4.5, text=" How"),
                Word(start=4.5, end=5.0, text=" are"),
                Word(start=5.0, end=5.5, text=" you"),
                Word(start=5.5, end=6.0, text=" today?"),
                Word(start=7.0, end=7.4, text=" Hi"),
                Word(start=7.4, end=7.8, text=" there"),
                Word(start=7.8, end=8.2, text=" my"),
                Word(start=8.2, end=8.6, text=" dear"),
                Word(start=8.6, end=9.0, text=" how"),
                Word(start=9.0, end=9.4, text=" are"),
                Word(start=9.4, end=9.8, text=" you?"),
            ],
            engine="fake",
        )

    def close(self) -> None:
        pass


class FakeTranslator:
    """Fixed Slovak translations; segment 3 is deliberately very long."""

    local_only = True

    _TRANSLATIONS = {
        1: "Ahoj tam.",
        2: "Ako sa máš dnes?",
        # Long enough to overflow the ~2.75 s window at base speed 1.05.
        3: (
            "Privítanie slovenského diváka v tomto krásnom "
            "pondelok večer je naozaj úžasné a fantastické"
        ),
    }

    def translate_segments(self, segments: list, source_lang: str, target_lang: str) -> list[str]:
        return [self._TRANSLATIONS.get(s.id, s.source_text) for s in segments]

    def close(self) -> None:
        pass


@pytest.fixture(scope="module")
def providers():
    return Providers(asr=FakeASR, translator=FakeTranslator, tts=FakeTTS)


@pytest.fixture(scope="module")
def settings(tmp_path_factory):
    return Settings(
        work_dir=tmp_path_factory.mktemp("work"),
        models_dir=tmp_path_factory.mktemp("models"),
    )


# ---------------------------------------------------------------------------
# Test 2: FFmpeg.probe
# ---------------------------------------------------------------------------


class TestFFmpegProbe:
    def test_duration_and_streams(self, video_path):
        ff = FFmpeg()
        info = ff.probe(video_path)
        assert info.duration == pytest.approx(10.0, abs=0.1)
        assert len(info.video_streams) == 1
        assert info.video_streams[0].codec_name == "h264"
        assert len(info.audio_streams) == 1


# ---------------------------------------------------------------------------
# Test 3: full Pipeline run
# ---------------------------------------------------------------------------


class TestPipelineRun:
    @pytest.fixture(autouse=True)
    def _run(self, video_path, tmp_path_factory, settings, providers):
        self.wd = tmp_path_factory.mktemp("pipeline-out")
        self.pipe = Pipeline(
            video_path,
            self.wd,
            settings,
            providers=providers,
        )
        self.result = self.pipe.run()

    def test_all_stages_ran(self):
        for stage in ("probe", "extract", "asr", "translate", "tts", "assemble", "export"):
            assert self.result[stage] == "ran"

    def test_output_exists(self):
        assert self.pipe.output_video.is_file()

    def test_duration_matches_input(self):
        ff = FFmpeg()
        out_info = ff.probe(self.pipe.output_video)
        in_info = ff.probe(self.pipe.input)
        assert out_info.duration == pytest.approx(in_info.duration, abs=0.05)

    def test_video_stream_copied_bit_exact(self):
        ff = FFmpeg()
        assert ff.stream_hash(self.pipe.input, "v:0") == ff.stream_hash(
            self.pipe.output_video, "v:0"
        )

    def test_two_audio_streams_first_is_default_slk(self):
        ff = FFmpeg()
        info = ff.probe(self.pipe.output_video)
        assert len(info.audio_streams) == 2
        assert info.audio_streams[0].language == "slk"
        # disposition:default is reported as 1 in the raw probe output
        raw = ff.probe_raw(self.pipe.output_video)
        audio_streams = [s for s in raw["streams"] if s["codec_type"] == "audio"]
        assert int(audio_streams[0].get("disposition", {}).get("default", 0)) == 1

    def test_slovak_srt_parses_with_diacritics(self):
        srt_text = self.pipe.output_srt.read_text(encoding="utf-8")
        cues = parse_srt(srt_text)
        assert len(cues) >= 3
        # Monotonic non-overlapping cues within duration
        info = FFmpeg().probe(self.pipe.output_video)
        for i, c in enumerate(cues):
            assert c.start < c.end
            if i + 1 < len(cues):
                assert c.end <= cues[i + 1].start
            assert c.end <= info.duration + 0.1
        # Diacritics intact
        full_text = " ".join(c.text for c in cues)
        assert any(ch in full_text for ch in SLOVAK_DIACRITICS)

    def test_fit_report_flags_long_line(self):
        report = json.loads((self.wd / "fit_report.json").read_text("utf-8"))
        flagged = report.get("flagged", [])
        assert flagged, "expected at least one stretched/overflow segment"
        assert any(f["status"] in ("stretched", "overflow") for f in flagged)

    def test_dub_wav_length(self):
        info = FFmpeg().probe(self.pipe.input)
        dub, sr = sf.read(str(self.wd / "dub.wav"), dtype="float32")
        assert sr == 48000
        assert dub.size == round(info.duration * 48000)


# ---------------------------------------------------------------------------
# Test 4: restart safety
# ---------------------------------------------------------------------------


class TestRestartSafety:
    @pytest.fixture(autouse=True)
    def _setup(self, video_path, tmp_path_factory, settings, providers):
        self.wd = tmp_path_factory.mktemp("restart-out")
        self.pipe = Pipeline(video_path, self.wd, settings, providers=providers)
        self.pipe.run()

    def test_rerun_all_skipped(self):
        result = self.pipe.run()
        for stage in result:
            assert result[stage] == "skipped"

    def test_edit_translation_reruns_tts_assemble_export(self):
        tr = json.loads((self.wd / "translation.json").read_text("utf-8"))
        tr["segments"][0]["translated_text"] = "Nazdar tam."
        atomic_write_json(self.wd / "translation.json", tr)

        result = self.pipe.run()
        for stage in ("probe", "extract", "asr", "translate"):
            assert result[stage] == "skipped"
        for stage in ("tts", "assemble", "export"):
            assert result[stage] == "ran"

    def test_from_stage_assemble(self):
        # Invalidate from assemble so it actually runs
        self.pipe.store.invalidate(["assemble", "export"])
        result = self.pipe.run(from_stage="assemble")
        for stage in ("probe", "extract", "asr", "translate", "tts"):
            assert result[stage] == "skipped"
        assert result["assemble"] == "ran"
        assert result["export"] == "ran"


# ---------------------------------------------------------------------------
# Test 5: unsupported codec -> clear MediaError
# ---------------------------------------------------------------------------


class TestUnsupportedCodec:
    def test_mux_rejects_theora(self, tmp_path):
        ff = FFmpeg()
        fake_info = MediaInfo(
            path="fake.mp4",
            duration=10.0,
            format_name="mp4",
            streams=[
                StreamInfo(index=0, codec_type="video", codec_name="theora"),
                StreamInfo(
                    index=1,
                    codec_type="audio",
                    codec_name="aac",
                    sample_rate=48000,
                    channels=2,
                ),
            ],
        )
        with pytest.raises(MediaError, match="[Tt]heora|cannot be stream-copied"):
            ff.mux(
                Path("fake.mp4"),
                Path("fake.wav"),
                tmp_path / "out.mp4",
                duration=10.0,
                info=fake_info,
            )


# ---------------------------------------------------------------------------
# Edits and per-segment TTS cache
# ---------------------------------------------------------------------------


class CountingTTS(FakeTTS):
    calls: list[tuple[str, str]] = []

    def synthesize(self, text, *, voice, lang, speed=1.0):
        CountingTTS.calls.append((text, voice))
        return super().synthesize(text, voice=voice, lang=lang, speed=speed)


class TestEditsAndCache:
    @pytest.fixture(autouse=True)
    def _setup(self, video_path, tmp_path, settings):
        CountingTTS.calls = []
        self.wd = tmp_path / "wd"
        self.providers = Providers(asr=FakeASR, translator=FakeTranslator, tts=CountingTTS)
        self.pipe = Pipeline(video_path, self.wd, settings, providers=self.providers)
        self.pipe.run()
        self.first_calls = len(CountingTTS.calls)
        CountingTTS.calls = []

    def _edit(self, segments: dict[int, dict]):
        from localdub.core.timeline.edits import Edits, SegmentEdit, save_edits, source_hash

        src = {
            s["id"]: s["source_text"]
            for s in json.loads((self.wd / "asr.json").read_text("utf-8"))["segments"]
        }
        save_edits(
            self.wd / "edits.json",
            Edits(
                segments={
                    i: SegmentEdit(source_hash=source_hash(src[i]), **kw)
                    for i, kw in segments.items()
                }
            ),
        )

    def test_unchanged_rerun_skips_everything(self):
        result = self.pipe.run()
        assert set(result.values()) == {"skipped"}

    def test_forced_tts_rerun_reuses_all_clips_without_loading_model(self):
        self.pipe.run(from_stage="tts")
        assert CountingTTS.calls == []

    def test_editing_one_line_resynthesises_only_that_line(self):
        self._edit({2: {"translated_text": "Ako sa dnes máte, priatelia?"}})
        result = self.pipe.run()
        assert result["translate"] == "skipped" and result["tts"] == "ran"
        texts = {t for t, _ in CountingTTS.calls}
        assert "Ako sa dnes máte, priatelia?" in texts
        assert len(CountingTTS.calls) <= 2  # the edited line (+ a speed-up retry if it overflowed)
        assert all(t == "Ako sa dnes máte, priatelia?" for t in texts)
        srt = self.pipe.output_srt.read_text(encoding="utf-8")
        assert "Ako sa dnes máte, priatelia?" in srt and "Ahoj tam." in srt

    def test_voice_edit_changes_only_that_segment_voice(self):
        self._edit({1: {"voice_id": "M1"}})
        self.pipe.run()
        assert CountingTTS.calls and all(v == "M1" for _, v in CountingTTS.calls)
        voices = {
            s["id"]: s["voice_id"]
            for s in json.loads((self.wd / "segments.json").read_text("utf-8"))["segments"]
        }
        assert voices[1] == "M1" and voices[2] == "F1"

    def test_timing_edit_moves_the_segment(self):
        self._edit({1: {"start": 2.0, "end": 3.5}})
        self.pipe.run()
        seg1 = json.loads((self.wd / "segments.json").read_text("utf-8"))["segments"][0]
        assert seg1["start"] == 2.0 and seg1["end"] == 3.5 and seg1["placed_start"] >= 2.0

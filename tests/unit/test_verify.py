import json
from pathlib import Path

import numpy as np
import soundfile as sf

from localdub.core.asr.base import AsrResult
from localdub.core.export.srt import Cue, render_srt, write_srt
from localdub.core.media.ffmpeg import MediaInfo, StreamInfo
from localdub.core.timeline.models import DialogueSegment, Word
from localdub.verify import verify_workdir


class FakeFFmpeg:
    def __init__(self, duration: float = 2.0, output_duration: float | None = None) -> None:
        self.duration = duration
        self.output_duration = output_duration if output_duration is not None else duration

    def probe(self, path: Path) -> MediaInfo:
        duration = self.output_duration if path.name.endswith(".sk.mp4") else self.duration
        streams = [StreamInfo(index=0, codec_type="video", codec_name="h264")]
        if path.name.endswith(".sk.mp4"):
            streams.append(
                StreamInfo(index=1, codec_type="audio", codec_name="aac", language="slk")
            )
        return MediaInfo(path=str(path), duration=duration, format_name="mp4", streams=streams)

    def stream_hash(self, path: Path, stream: str = "v:0") -> str:
        return "same-video-hash"

    def convert_audio(
        self,
        src: Path,
        dst: Path,
        *,
        sample_rate: int,
        tempo: float = 1.0,
        rubberband: bool = True,
    ) -> None:
        samples, _ = sf.read(src, dtype="float32")
        sf.write(dst, samples[::3], sample_rate)


class FakeASR:
    def __init__(self, text: str) -> None:
        self.text = text
        self.closed = False

    def transcribe(self, audio_path: Path, language: str | None = None) -> AsrResult:
        assert language == "sk"
        return AsrResult(
            language="sk",
            language_probability=1.0,
            duration=2.0,
            words=[Word(start=0, end=1, text=f" {self.text}")],
            engine="fake",
        )

    def close(self) -> None:
        self.closed = True


def make_workdir(
    tmp_path: Path,
    *,
    silent_clip: bool = False,
    overlap: bool = False,
) -> tuple[Path, Path, FakeFFmpeg]:
    workdir = tmp_path / "work"
    workdir.mkdir()
    (workdir / "tts" / "clips").mkdir(parents=True)
    source = tmp_path / "movie.mp4"
    source.write_bytes(b"fake video")
    ff = FakeFFmpeg()
    (workdir / "probe.json").write_text(json.dumps({"duration": 2.0}), encoding="utf-8")
    amplitude = 0.0 if silent_clip else 0.2
    clip = np.full(100, amplitude, dtype=np.float32)
    sf.write(workdir / "tts" / "clips" / "line.wav", clip, 48000)
    segment = DialogueSegment(
        id=1,
        start=0,
        end=1,
        source_text="Hello there",
        translated_text="Ahoj, ľudia!",
        audio_path="tts/clips/line.wav",
    )
    (workdir / "segments.json").write_text(
        json.dumps({"segments": [segment.model_dump(mode="json")]}),
        encoding="utf-8",
    )
    (workdir / "fit_report.json").write_text(
        json.dumps({"counts": {"ok": 1, "stretched": 0, "shifted": 0, "overflow": 0}}),
        encoding="utf-8",
    )
    sf.write(workdir / "dub.wav", np.zeros(96000, dtype=np.float32), 48000)
    sf.write(workdir / "mix.wav", np.zeros(96000, dtype=np.float32), 48000)
    (workdir / "movie.sk.mp4").write_bytes(b"fake output")
    if overlap:
        cues = [Cue(1, 0, 1.2, "Ahoj, ľudia"), Cue(2, 1, 1.5, "Ďakujem")]
        (workdir / "movie.sk.srt").write_text(render_srt(cues), encoding="utf-8")
    else:
        write_srt([segment], workdir / "movie.sk.srt")
    return workdir, source, ff


def test_verify_workdir_passes_and_runs_optional_asr(tmp_path: Path) -> None:
    workdir, source, ff = make_workdir(tmp_path)
    asr = FakeASR("Ahoj ľudia")
    report = verify_workdir(workdir, source, ff, asr=asr)
    assert report.passed
    assert asr.closed
    assert any(check.name == "intelligibility" and check.passed for check in report.checks)
    assert "# LocalDub verification" in report.to_markdown()


def test_verify_fails_for_silent_clip(tmp_path: Path) -> None:
    workdir, source, ff = make_workdir(tmp_path, silent_clip=True)
    report = verify_workdir(workdir, source, ff)
    clips = next(check for check in report.checks if check.name == "tts_clips")
    assert not clips.passed
    assert "silent" in clips.detail


def test_verify_fails_for_overlapping_srt(tmp_path: Path) -> None:
    workdir, source, ff = make_workdir(tmp_path, overlap=True)
    report = verify_workdir(workdir, source, ff)
    srt = next(check for check in report.checks if check.name == "slovak_srt")
    assert not srt.passed
    assert "overlaps" in srt.detail


def test_verify_fails_for_duration_mismatch(tmp_path: Path) -> None:
    workdir, source, _ = make_workdir(tmp_path)
    ff = FakeFFmpeg(output_duration=2.2)
    report = verify_workdir(workdir, source, ff)
    duration = next(check for check in report.checks if check.name == "duration")
    assert not duration.passed


def test_verify_fails_for_low_intelligibility(tmp_path: Path) -> None:
    workdir, source, ff = make_workdir(tmp_path)
    asr = FakeASR("completely different words")
    report = verify_workdir(workdir, source, ff, asr=asr)
    similarity = next(check for check in report.checks if check.name == "intelligibility")
    assert not similarity.passed
    assert asr.closed

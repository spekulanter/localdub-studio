"""Objective acceptance checks for a completed LocalDub work directory."""

from __future__ import annotations

import json
import tempfile
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf
from pydantic import BaseModel

from localdub.core.asr.base import ASRProvider
from localdub.core.export.srt import parse_srt
from localdub.core.media.ffmpeg import FFmpeg

_DURATION_TOLERANCE_S = 0.05
_SLOVAK_DIACRITICS = set("áäčďéíĺľňóôŕšťúýž")
_FIT_STATUSES = ("ok", "stretched", "shifted", "overflow")


class Check(BaseModel):
    name: str
    passed: bool
    detail: str
    value: float | str | None = None


class VerifyReport(BaseModel):
    checks: list[Check]

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)

    def to_markdown(self) -> str:
        result = "PASS" if self.passed else "FAIL"
        lines = ["# LocalDub verification", "", f"**Result:** {result}", ""]
        lines.extend(("| Check | Result | Detail |", "| --- | --- | --- |"))
        for check in self.checks:
            result = "PASS" if check.passed else "FAIL"
            detail = check.detail.replace("|", "\\|").replace("\n", " ")
            lines.append(f"| {check.name} | {result} | {detail} |")
        return "\n".join(lines)


def _read_segments(path: Path) -> list[dict[str, Any]]:
    raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    segments = raw["segments"]
    if not isinstance(segments, list):
        raise ValueError("segments must be a list")
    return segments


def _normalized_text(text: str) -> str:
    chars = [
        char.lower() if not unicodedata.category(char).startswith("P") else " " for char in text
    ]
    return " ".join("".join(chars).split())


def _media_check(workdir: Path, source_video: Path, ff: FFmpeg) -> list[Check]:
    output = workdir / f"{source_video.stem}.sk.mp4"
    checks: list[Check] = []
    if not output.is_file():
        checks.append(Check(name="output_mp4", passed=False, detail=f"Missing {output.name}"))
        return checks

    try:
        source_info = ff.probe(source_video)
        output_info = ff.probe(output)
    except Exception as exc:
        checks.append(Check(name="output_mp4", passed=False, detail=f"Probe failed: {exc}"))
        return checks

    checks.append(
        Check(name="output_mp4", passed=True, detail="File exists and probes successfully")
    )
    delta = abs(output_info.duration - source_info.duration)
    checks.append(
        Check(
            name="duration",
            passed=delta <= _DURATION_TOLERANCE_S,
            detail=(
                f"source={source_info.duration:.3f}s output={output_info.duration:.3f}s "
                f"delta={delta:.3f}s"
            ),
            value=delta,
        )
    )

    source_video_streams = source_info.video_streams
    output_video_streams = output_info.video_streams
    codec_ok = bool(source_video_streams and output_video_streams)
    codec_detail = "Missing source or output video stream"
    if codec_ok:
        source_codec = source_video_streams[0].codec_name
        output_codec = output_video_streams[0].codec_name
        codec_ok = source_codec == output_codec
        codec_detail = f"source={source_codec} output={output_codec}"
    hash_ok = False
    hash_detail = "Video stream hash unavailable"
    try:
        source_hash = ff.stream_hash(source_video, "v:0")
        output_hash = ff.stream_hash(output, "v:0")
        hash_ok = source_hash == output_hash
        hash_detail = "video stream hashes match" if hash_ok else "video stream hashes differ"
    except Exception as exc:
        hash_detail = f"Stream hash failed: {exc}"
    checks.append(
        Check(
            name="video_stream_copy",
            passed=codec_ok and hash_ok,
            detail=f"{codec_detail}; {hash_detail}",
        )
    )

    audio_streams = output_info.audio_streams
    has_dub = bool(audio_streams)
    language_ok = has_dub and audio_streams[0].language == "slk"
    checks.append(
        Check(
            name="output_audio",
            passed=language_ok,
            detail=(
                f"{len(audio_streams)} audio stream(s); first language="
                f"{audio_streams[0].language if has_dub else 'missing'}"
            ),
        )
    )
    return checks


def _srt_check(workdir: Path, source_video: Path, duration: float | None) -> Check:
    path = workdir / f"{source_video.stem}.sk.srt"
    try:
        cues = parse_srt(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        return Check(name="slovak_srt", passed=False, detail=f"Could not parse SRT: {exc}")

    valid = bool(cues)
    problems: list[str] = []
    if not cues:
        problems.append("no cues")
    if [cue.index for cue in cues] != list(range(1, len(cues) + 1)):
        valid = False
        problems.append("indices are not sequential")
    previous_end = float("-inf")
    for cue in cues:
        if cue.start >= cue.end:
            valid = False
            problems.append(f"cue {cue.index} has start >= end")
        if cue.start < previous_end:
            valid = False
            problems.append(f"cue {cue.index} overlaps or is out of order")
        if duration is not None and (cue.start < 0 or cue.end > duration + _DURATION_TOLERANCE_S):
            valid = False
            problems.append(f"cue {cue.index} is outside media duration")
        previous_end = cue.end
    has_diacritic = any(char in _SLOVAK_DIACRITICS for cue in cues for char in cue.text.lower())
    if not has_diacritic:
        valid = False
        problems.append("no Slovak diacritic found")
    detail = f"{len(cues)} cue(s); " + ("; ".join(problems) if problems else "valid")
    return Check(name="slovak_srt", passed=valid, detail=detail, value=float(len(cues)))


def _clip_check(workdir: Path, segments: list[dict[str, Any]]) -> Check:
    count = 0
    min_rms_dbfs = float("inf")
    missing: list[str] = []
    silent: list[str] = []
    for segment in segments:
        relpath = segment.get("audio_path")
        if not relpath:
            continue
        count += 1
        path = workdir / str(relpath)
        if not path.is_file():
            missing.append(str(relpath))
            continue
        try:
            samples, _ = sf.read(path, dtype="float32", always_2d=True)
        except Exception:
            missing.append(str(relpath))
            continue
        rms = float(np.sqrt(np.mean(np.square(samples)))) if samples.size else 0.0
        dbfs = 20.0 * np.log10(rms) if rms > 0 else float("-inf")
        min_rms_dbfs = min(min_rms_dbfs, float(dbfs))
        if dbfs <= -45.0:
            silent.append(str(relpath))
    passed = not missing and not silent
    min_value = min_rms_dbfs if min_rms_dbfs != float("inf") else None
    detail = f"{count} clip(s); min RMS={min_value if min_value is not None else 'n/a'} dBFS"
    if missing:
        detail += f"; missing/unreadable: {', '.join(missing)}"
    if silent:
        detail += f"; silent (<= -45 dBFS): {', '.join(silent)}"
    return Check(name="tts_clips", passed=passed, detail=detail, value=min_value)


def _dub_check(workdir: Path, duration: float) -> Check:
    path = workdir / "dub.wav"
    try:
        info = sf.info(path)
    except Exception as exc:
        return Check(name="dub_length", passed=False, detail=f"Could not inspect dub.wav: {exc}")
    expected = round(duration * 48000)
    passed = info.frames == expected
    return Check(
        name="dub_length",
        passed=passed,
        detail=f"{info.frames} samples; expected {expected} at 48000 Hz",
        value=float(info.frames),
    )


def _fit_check(workdir: Path) -> Check:
    path = workdir / "fit_report.json"
    try:
        report: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        counts = {status: int(report.get("counts", {}).get(status, 0)) for status in _FIT_STATUSES}
    except Exception as exc:
        return Check(name="fit_report", passed=False, detail=f"Could not read fit report: {exc}")
    total = sum(counts.values())
    ratio = counts["overflow"] / total if total else 1.0
    detail = ", ".join(f"{status}={counts[status]}" for status in _FIT_STATUSES)
    detail += f"; overflow ratio={ratio:.3f}"
    return Check(
        name="fit_report",
        passed=ratio <= 0.2,
        detail=detail,
        value=ratio,
    )


def _source_duration(workdir: Path, source_video: Path, ff: FFmpeg) -> float | None:
    try:
        probe_data: dict[str, Any] = json.loads(
            (workdir / "probe.json").read_text(encoding="utf-8")
        )
        return float(probe_data["duration"])
    except Exception:
        try:
            return ff.probe(source_video).duration
        except Exception:
            return None


def _intelligibility_check(
    workdir: Path, segments: list[dict[str, Any]], ff: FFmpeg, asr: ASRProvider
) -> Check:
    target = _normalized_text(" ".join(str(s.get("translated_text", "")) for s in segments))
    temp_path: Path | None = None
    try:
        with tempfile.TemporaryDirectory(prefix="localdub-verify-") as temp_dir:
            temp_path = Path(temp_dir) / "dub_16k.wav"
            ff.convert_audio(workdir / "dub.wav", temp_path, sample_rate=16000)
            result = asr.transcribe(temp_path, language="sk")
        recognized = _normalized_text(" ".join(word.text for word in result.words))
        ratio = SequenceMatcher(None, target, recognized, autojunk=False).ratio()
        return Check(
            name="intelligibility",
            passed=ratio >= 0.6,
            detail=f"character similarity={ratio:.3f}",
            value=ratio,
        )
    except Exception as exc:
        return Check(name="intelligibility", passed=False, detail=f"ASR check failed: {exc}")
    finally:
        asr.close()


def verify_workdir(
    workdir: Path,
    source_video: Path,
    ff: FFmpeg,
    *,
    asr: ASRProvider | None = None,
) -> VerifyReport:
    """Run M0 acceptance checks over artifacts produced by ``Pipeline``."""
    workdir = workdir.resolve()
    source_video = source_video.resolve()
    checks = _media_check(workdir, source_video, ff)
    duration = _source_duration(workdir, source_video, ff)
    checks.append(_srt_check(workdir, source_video, duration))

    try:
        segments = _read_segments(workdir / "segments.json")
    except Exception as exc:
        segments = []
        checks.append(
            Check(name="segments", passed=False, detail=f"Could not read segments: {exc}")
        )
    else:
        checks.append(
            Check(
                name="segments",
                passed=bool(segments),
                detail=f"{len(segments)} segment(s)",
            )
        )
    checks.append(_clip_check(workdir, segments))

    if duration is None:
        checks.append(
            Check(
                name="dub_length",
                passed=False,
                detail="Could not determine source duration",
            )
        )
    else:
        checks.append(_dub_check(workdir, duration))
    checks.append(_fit_check(workdir))
    if asr is not None:
        checks.append(_intelligibility_check(workdir, segments, ff, asr))
    return VerifyReport(checks=checks)

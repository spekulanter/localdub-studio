"""FFmpeg/FFprobe wrappers. Arguments are always passed as a list; no shell is involved."""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel

log = logging.getLogger(__name__)

# Video codecs that can be stream-copied into an MP4 container.
MP4_VIDEO_CODECS = {"h264", "hevc", "av1", "mpeg4", "vp9", "mjpeg"}
# Audio codecs that can be stream-copied into an MP4 container.
MP4_AUDIO_CODECS = {"aac", "mp3", "ac3", "eac3", "opus", "alac", "flac"}

_CREATE_NO_WINDOW = 0x08000000


class MediaError(RuntimeError):
    def __init__(self, message: str, args: Sequence[str] = (), stderr: str = "") -> None:
        tail = "\n".join(stderr.strip().splitlines()[-15:])
        super().__init__(f"{message}\n{tail}" if tail else message)
        self.command = list(args)
        self.stderr = stderr


class StreamInfo(BaseModel):
    index: int
    codec_type: str
    codec_name: str
    duration: float | None = None
    sample_rate: int | None = None
    channels: int | None = None
    width: int | None = None
    height: int | None = None
    language: str | None = None


class MediaInfo(BaseModel):
    path: str
    duration: float
    format_name: str
    streams: list[StreamInfo]

    @property
    def video_streams(self) -> list[StreamInfo]:
        return [s for s in self.streams if s.codec_type == "video"]

    @property
    def audio_streams(self) -> list[StreamInfo]:
        return [s for s in self.streams if s.codec_type == "audio"]


def find_tool(name: str, configured: Path | None = None) -> Path:
    if configured is not None:
        if not configured.is_file():
            raise MediaError(f"Configured {name} not found at {configured}")
        return configured
    found = shutil.which(name)
    if not found:
        raise MediaError(
            f"{name} not found on PATH. Install FFmpeg (e.g. `winget install Gyan.FFmpeg`) "
            f"or set LOCALDUB_{name.upper()}_PATH."
        )
    return Path(found)


def run_tool(args: Sequence[str | Path], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    cmd = [str(a) for a in args]
    log.debug("exec: %s", cmd)
    flags = _CREATE_NO_WINDOW if sys.platform == "win32" else 0
    proc = subprocess.run(  # noqa: S603 - fixed executable, list arguments, no shell
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=flags,
        check=False,
    )
    if check and proc.returncode != 0:
        raise MediaError(
            f"{Path(cmd[0]).name} exited with code {proc.returncode}", cmd, proc.stderr
        )
    return proc


class FFmpeg:
    def __init__(self, ffmpeg: Path | None = None, ffprobe: Path | None = None) -> None:
        self.ffmpeg = find_tool("ffmpeg", ffmpeg)
        self.ffprobe = find_tool("ffprobe", ffprobe)

    def version(self) -> str:
        return run_tool([self.ffmpeg, "-hide_banner", "-version"]).stdout.splitlines()[0]

    def has_filter(self, name: str) -> bool:
        out = run_tool([self.ffmpeg, "-hide_banner", "-filters"]).stdout
        return any(line.split()[1:2] == [name] for line in out.splitlines() if line.strip())

    def run(self, args: Sequence[str | Path]) -> None:
        run_tool([self.ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error", "-y", *args])

    def gain_with_limiter(self, src: Path, dst: Path, gain_db: float, limit: float = 0.95) -> None:
        """Apply `gain_db`, then a look-ahead limiter so peaks never exceed `limit` (linear)."""
        flt = f"volume={gain_db:.2f}dB,alimiter=limit={limit}:attack=5:release=60:level=disabled"
        self.run(["-i", src, "-af", flt, "-c:a", "pcm_s16le", dst])

    def measure_lufs(self, path: Path) -> float | None:
        """Integrated loudness (EBU R128, LUFS) of an audio file, or None for silence."""
        proc = run_tool(
            [self.ffmpeg, "-hide_banner", "-nostdin", "-nostats", "-i", path,
             "-af", "ebur128=peak=true", "-f", "null", "-"]
        )  # fmt: skip
        summary = proc.stderr.rsplit("Summary:", 1)[-1]
        match = re.search(r"^\s*I:\s*(-?\d+(?:\.\d+)?)\s*LUFS", summary, re.MULTILINE)
        if match is None:
            return None
        value = float(match.group(1))
        return value if value > -69 else None

    def probe_raw(self, path: Path) -> dict[str, Any]:
        out = run_tool(
            [self.ffprobe, "-v", "error", "-show_format", "-show_streams", "-of", "json", path]
        ).stdout
        data: dict[str, Any] = json.loads(out)
        return data

    def probe(self, path: Path) -> MediaInfo:
        if not path.is_file():
            raise MediaError(f"Input file not found: {path}")
        raw = self.probe_raw(path)
        fmt = raw.get("format", {})
        streams = []
        for s in raw.get("streams", []):
            streams.append(
                StreamInfo(
                    index=s["index"],
                    codec_type=s.get("codec_type", "unknown"),
                    codec_name=s.get("codec_name", "unknown"),
                    duration=_float(s.get("duration")),
                    sample_rate=_int(s.get("sample_rate")),
                    channels=s.get("channels"),
                    width=s.get("width"),
                    height=s.get("height"),
                    language=s.get("tags", {}).get("language"),
                )
            )
        duration = _float(fmt.get("duration"))
        if duration is None:
            raise MediaError(f"Could not determine duration of {path}")
        return MediaInfo(
            path=str(path),
            duration=duration,
            format_name=fmt.get("format_name", ""),
            streams=streams,
        )

    def extract_audio(
        self, src: Path, dst: Path, *, sample_rate: int, channels: int, stream: int = 0
    ) -> None:
        """Decode one audio stream to 16-bit PCM WAV."""
        dst.parent.mkdir(parents=True, exist_ok=True)
        self.run(
            [
                "-i", src,
                "-map", f"0:a:{stream}",
                "-vn", "-ac", str(channels), "-ar", str(sample_rate),
                "-c:a", "pcm_s16le",
                dst,
            ]
        )  # fmt: skip

    def convert_audio(
        self, src: Path, dst: Path, *, sample_rate: int, tempo: float = 1.0, rubberband: bool = True
    ) -> None:
        """Resample to mono PCM and optionally change tempo without changing pitch."""
        filters: list[str] = []
        if abs(tempo - 1.0) > 1e-3:
            if rubberband:
                filters.append(f"rubberband=tempo={tempo:.4f}:pitchq=quality")
            else:
                filters.append(f"atempo={tempo:.4f}")
        filters.append(f"aresample={sample_rate}")
        dst.parent.mkdir(parents=True, exist_ok=True)
        self.run(["-i", src, "-af", ",".join(filters), "-ac", "1", "-c:a", "pcm_s16le", dst])

    def mux(
        self,
        video: Path,
        dub_audio: Path,
        dst: Path,
        *,
        duration: float,
        info: MediaInfo,
        audio_bitrate: str = "192k",
        dub_language: str = "slk",
        keep_original_audio: bool = True,
        comment: str | None = None,
    ) -> None:
        """Stream-copy the video and add the dub as the default audio track."""
        if not info.video_streams:
            raise MediaError(f"No video stream in {video}")
        vcodec = info.video_streams[0].codec_name
        if vcodec not in MP4_VIDEO_CODECS:
            raise MediaError(
                f"Video codec '{vcodec}' cannot be stream-copied into MP4. "
                "Re-encoding is not enabled in this version; "
                "convert the source to H.264/HEVC first."
            )
        args: list[str | Path] = [
            "-i", video, "-i", dub_audio,
            "-map", "0:v:0", "-map", "1:a:0",
            "-c:v", "copy",
            "-c:a:0", "aac", "-b:a:0", audio_bitrate,
            "-metadata:s:a:0", f"language={dub_language}",
            "-disposition:a:0", "default",
        ]  # fmt: skip
        orig = info.audio_streams[0] if info.audio_streams else None
        if keep_original_audio and orig is not None:
            args += ["-map", "0:a:0"]
            if orig.codec_name in MP4_AUDIO_CODECS:
                args += ["-c:a:1", "copy"]
            else:
                args += ["-c:a:1", "aac", "-b:a:1", audio_bitrate]
            args += [
                "-metadata:s:a:1", f"language={orig.language or 'eng'}",
                "-disposition:a:1", "0",
            ]  # fmt: skip
        if comment:
            args += ["-metadata", f"comment={comment}"]
        args += ["-t", f"{duration:.3f}", "-movflags", "+faststart", dst]
        dst.parent.mkdir(parents=True, exist_ok=True)
        self.run(args)

    def stream_hash(self, path: Path, stream: str = "v:0") -> str:
        """Hash of the encoded packets of one stream; equal hashes mean an exact stream copy."""
        out = run_tool(
            [
                self.ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin",
                "-i", path, "-map", f"0:{stream}", "-c", "copy",
                "-f", "streamhash", "-hash", "sha256", "-",
            ]
        ).stdout  # fmt: skip
        return out.strip().split("=", 1)[-1]


def _float(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _int(v: Any) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None

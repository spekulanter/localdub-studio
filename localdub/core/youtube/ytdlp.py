"""Run yt-dlp for the YouTube import (ported from the YouTube Downloader app's Rust layer).

Rules kept from there: only YouTube HTTPS links, every choice is an enumerated value, yt-dlp is
started with an argument list (never through a shell) and `--no-config`, and the user can not add
flags. yt-dlp stays the only extractor: nothing here talks to YouTube itself.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from localdub.core.platform import kill_tree
from localdub.core.youtube import tools

log = logging.getLogger(__name__)

PROGRESS_PREFIX = "__LD_PROGRESS__"
FILE_PREFIX = "__LD_FILE__"
QUALITIES = ("auto", "720", "1080", "1440", "2160")
COOKIE_BROWSERS = ("none", "edge", "chrome", "firefox")
MAX_DURATION_S = 4 * 3600
CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
PROCESSING = ("[Merger]", "[ExtractAudio]", "[VideoRemuxer]", "[Fixup")

# percent (0..100), human text of speed/ETA, status message
# yt-dlp processes started by this process, so they can be stopped if the worker has to exit
_active: set[subprocess.Popen[bytes]] = set()
_active_lock = threading.Lock()


def terminate_active() -> None:
    """Stop every yt-dlp (and its ffmpeg/Deno children) started by this process."""
    with _active_lock:
        procs = list(_active)
    for proc in procs:
        if proc.poll() is None:
            kill_tree(proc.pid)


OnProgress = Callable[[float | None, str | None, str | None], None]


class YoutubeError(RuntimeError):
    """A link or download problem with a message meant for the user."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class VideoInfo:
    id: str
    title: str
    uploader: str | None
    thumbnail: str | None
    duration: float | None
    is_live: bool
    webpage_url: str


def validate_youtube_url(value: str) -> str:
    """Return the normalised URL or raise YoutubeError. HTTPS and YouTube hosts only."""
    value = value.strip()
    if any(ch.isspace() or ord(ch) < 32 for ch in value):
        raise YoutubeError("invalid_url", "The link must not contain spaces or line breaks.")
    try:
        parsed = urlparse(value)
        host = (parsed.hostname or "").lower()
    except ValueError as exc:
        raise YoutubeError("invalid_url", "Enter a valid YouTube link.") from exc
    if parsed.scheme != "https":
        raise YoutubeError("invalid_url", "Only https:// links are accepted.")
    if parsed.username or parsed.password:
        raise YoutubeError("invalid_url", "Links with a user name or password are not accepted.")
    allowed = (
        host in ("youtu.be", "youtube.com", "youtube-nocookie.com")
        or host.endswith(".youtube.com")
        or host.endswith(".youtube-nocookie.com")
    )
    if not allowed:
        raise YoutubeError("invalid_url", "Only YouTube links are accepted.")
    return parsed.geturl()


def validate_options(quality: str, cookies_browser: str) -> None:
    if quality not in QUALITIES:
        raise YoutubeError("invalid_option", f"Unknown quality '{quality}'.")
    if cookies_browser not in COOKIE_BROWSERS:
        raise YoutubeError("invalid_option", f"Unknown browser '{cookies_browser}'.")


def format_selector(quality: str) -> str:
    """Best video + best audio up to a height cap. The dub does not need more than 1080p."""
    cap = "1080" if quality == "auto" else quality
    return f"bv*[height<={cap}]+ba/b[height<={cap}]/bv*+ba/b"


def _command(*args: str) -> list[str]:
    path = tools.find_ytdlp()
    if path is None:
        raise YoutubeError(
            "missing_tools", "yt-dlp is not installed. Install the YouTube tools first."
        )
    return [str(path), *args]


def common_args(cookies_browser: str) -> list[str]:
    args = ["--no-config", "--encoding", "utf-8", "--no-playlist"]
    deno = tools.find_deno()
    if deno is not None:
        args += ["--js-runtimes", f"deno:{deno}"]
    if cookies_browser != "none":
        args += ["--cookies-from-browser", cookies_browser]
    return args


def build_download_args(
    url: str, dest: Path, quality: str, cookies_browser: str, ffmpeg_dir: Path | None
) -> list[str]:
    """Arguments for one download into `dest` (e.g. .../input/source.mp4)."""
    args = [
        *common_args(cookies_browser),
        "--newline", "--progress", "--no-quiet", "--no-simulate",
        "--windows-filenames",
        "--progress-template",
        f"download:{PROGRESS_PREFIX}%(progress._percent_str)s|%(progress._speed_str)s|%(progress._eta_str)s",
        "--print", f"after_move:{FILE_PREFIX}%(filepath)s",
        "-P", str(dest.parent),
        "-o", f"{dest.stem}.%(ext)s",
        "-f", format_selector(quality),
        "--merge-output-format", "mp4",
        "--remux-video", "mp4",
    ]  # fmt: skip
    if ffmpeg_dir is not None:
        args += ["--ffmpeg-location", str(ffmpeg_dir)]
    return [*args, "--", url]  # "--": whatever follows is a link, never an option


def parse_progress(line: str) -> tuple[float | None, str | None, str | None] | None:
    """(percent, speed, eta) from one of our progress lines, or None for any other line."""
    if not line.startswith(PROGRESS_PREFIX):
        return None
    fields = line[len(PROGRESS_PREFIX) :].split("|", 2)
    fields += [""] * (3 - len(fields))

    def text(v: str) -> str | None:
        v = v.strip()
        return None if not v or v == "NA" else v

    try:
        percent: float | None = float(fields[0].strip().rstrip("%").strip())
    except ValueError:
        percent = None
    return percent, text(fields[1]), text(fields[2])


def classify_error(detail: str) -> str:
    low = detail.lower()
    if "po token" in low or "proof of origin" in low:
        return "po_token"
    if "age-restricted" in low or "age restricted" in low or "confirm your age" in low:
        return "age_restricted"
    if "not a bot" in low or "sign in" in low or "login required" in low:
        return "login_required"
    if "members-only" in low or "private video" in low:
        return "login_required"
    if "cookie" in low:
        return "cookies_required"
    if "403" in low or "forbidden" in low:
        return "forbidden"
    if "ffmpeg" in low and ("not found" in low or "not installed" in low):
        return "missing_ffmpeg"
    if (
        "javascript runtime" in low
        or "no supported javascript" in low
        or ("deno" in low and "not found" in low)
    ):
        return "missing_js_runtime"
    if "unsupported url" in low or "invalid url" in low:
        return "unsupported"
    if "video unavailable" in low or "is unavailable" in low or "is not available" in low:
        return "unavailable"
    return "unknown"


_FRIENDLY = {
    "po_token": "YouTube asks for a PO token, which this app does not generate. "
    "Try again later or update yt-dlp",
    "age_restricted": "This video is age-restricted. "
    "Choose a browser where you are signed in under 'Use cookies from'",
    "login_required": "YouTube wants a signed-in session for this video. "
    "Choose a browser under 'Use cookies from'",
    "cookies_required": "The browser cookies could not be used. "
    "Close the browser or pick another one",
    "forbidden": "YouTube refused the request (403). Updating yt-dlp usually fixes it",
    "missing_ffmpeg": "FFmpeg was not found",
    "missing_js_runtime": "The JavaScript runtime (Deno) is missing. "
    "Install the YouTube tools again",
    "unsupported": "This link is not supported",
    "unavailable": "This video is unavailable (removed, private or blocked in your country)",
    "unknown": "yt-dlp reported an error",
}


def friendly_error(detail: str) -> YoutubeError:
    code = classify_error(detail)
    last = next((ln.strip() for ln in reversed(detail.splitlines()) if ln.strip()), "unknown error")
    return YoutubeError(code, f"{_FRIENDLY[code]}: {last[:400]}")


def fetch_info(url: str, cookies_browser: str = "none", timeout: float = 90.0) -> VideoInfo:
    """Title, length and thumbnail of a video (no download)."""
    url = validate_youtube_url(url)
    validate_options("auto", cookies_browser)
    cmd = [
        *_command(
            *common_args(cookies_browser), "--skip-download", "--dump-single-json", "--no-warnings"
        ),
        "--",
        url,
    ]
    try:
        proc = subprocess.run(  # noqa: S603 - list arguments, no shell, validated URL
            cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout, creationflags=CREATE_NO_WINDOW, stdin=subprocess.DEVNULL, check=False,
        )  # fmt: skip
    except subprocess.TimeoutExpired as exc:
        raise YoutubeError("timeout", "YouTube did not answer in time. Try again.") from exc
    except OSError as exc:
        raise YoutubeError("cannot_start", f"yt-dlp could not be started: {exc}") from exc
    if proc.returncode != 0:
        raise friendly_error(proc.stderr)
    try:
        data = json.loads(proc.stdout)
    except ValueError as exc:
        raise YoutubeError(
            "bad_answer", "yt-dlp returned an answer that could not be read."
        ) from exc
    duration = data.get("duration")
    return VideoInfo(
        id=str(data.get("id") or ""),
        title=str(data.get("title") or "YouTube video"),
        uploader=data.get("uploader"),
        thumbnail=data.get("thumbnail"),
        duration=float(duration) if isinstance(duration, int | float) else None,
        is_live=bool(data.get("is_live")),
        webpage_url=str(data.get("webpage_url") or url),
    )


def download(
    url: str,
    dest: Path,
    quality: str,
    cookies_browser: str,
    ffmpeg_dir: Path | None,
    on_progress: OnProgress,
    *,
    launcher: list[str] | None = None,
) -> Path:
    """Download the video to `dest` (an .mp4 path). Blocking; returns the finished file."""
    url = validate_youtube_url(url)
    validate_options(quality, cookies_browser)
    dest.parent.mkdir(parents=True, exist_ok=True)
    args = build_download_args(url, dest, quality, cookies_browser, ffmpeg_dir)
    cmd = [*launcher, *args] if launcher else _command(*args)
    on_progress(None, None, "Starting yt-dlp...")
    try:
        proc = subprocess.Popen(  # noqa: S603 - list arguments, no shell, validated URL and options
            cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            creationflags=CREATE_NO_WINDOW,
        )  # fmt: skip
    except OSError as exc:
        raise YoutubeError("cannot_start", f"yt-dlp could not be started: {exc}") from exc

    with _active_lock:
        _active.add(proc)
    captured: list[str] = []

    def read_stderr() -> None:
        assert proc.stderr is not None
        for raw in iter(proc.stderr.readline, b""):
            line = raw.decode("utf-8", errors="replace").rstrip()
            if line.strip():
                captured.append(line)
                del captured[:-80]

    reader = threading.Thread(target=read_stderr, daemon=True)
    reader.start()
    final: str | None = None
    stream, last_pct = (
        0,
        -1.0,
    )  # yt-dlp fetches video and audio one after the other, 0 -> 100 % each
    assert proc.stdout is not None
    for raw in iter(proc.stdout.readline, b""):  # undecodable bytes must never stop the draining
        line = raw.decode("utf-8", errors="replace").rstrip()
        progress = parse_progress(line)
        if progress is not None:
            pct, speed, eta = progress
            if pct is not None:
                if pct < last_pct - 5:
                    stream += 1  # the next stream started
                last_pct = pct
                # the video is most of the data: 0-90 %, then the audio: 90-100 %
                pct = pct * 0.9 if stream == 0 else min(90.0 + pct * 0.1, 99.9)
            on_progress(pct, speed, eta)
        elif line.startswith(FILE_PREFIX):
            final = line[len(FILE_PREFIX) :].strip()
        elif any(p in line for p in PROCESSING):
            on_progress(None, None, line.strip()[:120])
    code = proc.wait()
    with _active_lock:
        _active.discard(proc)
    reader.join(timeout=5)
    if code != 0:
        raise friendly_error("\n".join(captured))
    found = Path(final) if final else dest
    if not found.is_file():
        raise YoutubeError("no_file", "yt-dlp finished but the video file was not found.")
    if found != dest:
        dest.unlink(missing_ok=True)
        found.replace(dest)
    return dest

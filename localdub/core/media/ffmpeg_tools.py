"""FFmpeg and FFprobe for macOS: LocalDub's own copy, downloaded on request and checksum-verified.

On Windows the installer asks winget for FFmpeg. macOS has no such tool, and Homebrew is not
something a Mac user is expected to have, so the AI models page can fetch a static build instead.
Nothing is downloaded unless the user presses the button. The build comes from Martin Riedl's
build server (https://ffmpeg.martin-riedl.de, GPL v3, checked: no `--enable-nonfree`), a pinned
version with the SHA-256 of each file recorded here; Homebrew's FFmpeg is found too and preferred
when present on PATH.
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import stat
import subprocess
import zipfile
from collections.abc import Callable
from pathlib import Path

import httpx

from localdub.paths import user_dir

log = logging.getLogger(__name__)

TOOLS_ENV = "LOCALDUB_FFMPEG_TOOLS_DIR"
BASE_URL = "https://ffmpeg.martin-riedl.de/download/macos/arm64/1789931890_9.0.2"
VERSION = "9.0.2"
# name -> (zip file, SHA-256 of the zip), as published next to each file on the build server
FILES = {
    "ffmpeg": ("ffmpeg.zip", "c8ed4c4e6978a03c485edbfe4e0a5dc2380f8a30bba5150531b31b094492d924"),
    "ffprobe": ("ffprobe.zip", "fcbe839537485eaee7a7a8bc5cbc0f90d53617e80943e8a5b2e31cb851197ea6"),
}
Progress = Callable[[int, int, str], None]  # (bytes done, bytes total, message)


class FfmpegToolsError(RuntimeError):
    """FFmpeg could not be installed (the message is shown to the user)."""


def tools_dir() -> Path:
    override = os.environ.get(TOOLS_ENV)
    return Path(override) if override else user_dir("tools")


def managed_paths() -> dict[str, Path]:
    return {name: tools_dir() / name for name in FILES}


def managed_installed() -> bool:
    return all(p.is_file() and os.access(p, os.X_OK) for p in managed_paths().values())


def _sha256_stream(
    client: httpx.Client, url: str, dest: Path, on_bytes: Callable[[int], None]
) -> str:
    h = hashlib.sha256()
    with client.stream("GET", url, follow_redirects=True) as resp:
        resp.raise_for_status()
        done = 0
        with dest.open("wb") as fh:
            for chunk in resp.iter_bytes(1 << 20):
                fh.write(chunk)
                h.update(chunk)
                done += len(chunk)
                on_bytes(done)
    return h.hexdigest()


def _must_start(name: str, path: Path) -> None:
    try:
        proc = subprocess.run(  # noqa: S603 - the file we just installed, no shell
            [str(path), "-version"], capture_output=True, text=True, timeout=30,
            stdin=subprocess.DEVNULL, check=False,
        )  # fmt: skip
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise FfmpegToolsError(f"{name} was installed but does not start: {exc}") from exc
    if proc.returncode != 0:
        raise FfmpegToolsError(
            f"{name} was installed but does not start (exit code {proc.returncode})."
        )


def install(
    progress: Progress,
    *,
    client: httpx.Client | None = None,
    check: Callable[[str, Path], None] = _must_start,
) -> None:
    """Download, verify and unpack ffmpeg and ffprobe into the managed folder. Blocking."""
    own = client is None
    client = client or httpx.Client(timeout=httpx.Timeout(30.0, read=120.0))
    target = tools_dir()
    target.mkdir(parents=True, exist_ok=True)
    stage = target / ".download"
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir()
    total_guess = 57_000_000
    base = 0
    try:
        try:
            for name, (zip_name, digest) in FILES.items():
                part = stage / zip_name

                def on_bytes(n: int, b: int = base, label: str = name) -> None:
                    progress(b + n, total_guess, f"Downloading {label}")

                got = _sha256_stream(client, f"{BASE_URL}/{zip_name}", part, on_bytes)
                if got != digest:
                    raise FfmpegToolsError(
                        f"{zip_name}: checksum mismatch (expected {digest[:12]}..., got "
                        f"{got[:12]}...); nothing was installed. Try again."
                    )
                base += part.stat().st_size
        except httpx.HTTPError as exc:
            raise FfmpegToolsError(
                f"Download failed: {exc}. Check your internet connection and try again."
            ) from exc
        progress(base, max(base, 1), "Installing...")
        for name, (zip_name, _) in FILES.items():
            with zipfile.ZipFile(stage / zip_name) as z:
                try:
                    info = z.getinfo(name)  # exact member name: no path traversal possible
                except KeyError as exc:
                    raise FfmpegToolsError(f"{zip_name} does not contain {name}") from exc
                with z.open(info) as src, (stage / name).open("wb") as out:
                    shutil.copyfileobj(src, out)
            (stage / name).chmod((stage / name).stat().st_mode | stat.S_IXUSR | stat.S_IXGRP)
        for name in FILES:
            (stage / name).replace(target / name)
    finally:
        shutil.rmtree(stage, ignore_errors=True)
        if own:
            client.close()
    for name, path in managed_paths().items():
        check(name, path)
    progress(base, base, "Done")


def remove() -> bool:
    """Delete only the copies LocalDub installed. True if something was removed."""
    removed = False
    for path in managed_paths().values():
        if path.is_file() and not path.is_symlink():
            path.unlink()
            removed = True
    return removed

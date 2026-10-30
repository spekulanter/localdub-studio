"""yt-dlp and Deno for the YouTube import: where they live, how they are installed and updated.

Nothing here runs unless the user asks for it. The tools are downloaded from the projects' official
GitHub release pages and checked against the SHA-256 the publisher ships next to each file (this
protects against corrupted or truncated downloads; it cannot protect against a compromised
release). Deno is needed because current yt-dlp solves YouTube's JavaScript challenges with an
external runtime. FFmpeg is the one LocalDub already uses.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import sys
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from localdub.paths import user_dir

log = logging.getLogger(__name__)

TOOLS_ENV = "LOCALDUB_YOUTUBE_TOOLS_DIR"
YTDLP_URL = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"
YTDLP_SUMS_URL = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/SHA2-256SUMS"
DENO_ZIP = "deno-x86_64-pc-windows-msvc.zip"
DENO_URL = f"https://github.com/denoland/deno/releases/latest/download/{DENO_ZIP}"
DENO_SUM_URL = f"{DENO_URL}.sha256sum"
# only used for the size shown before the download starts
ESTIMATED_BYTES = 70_000_000
CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

Progress = Callable[[int, int, str], None]  # (bytes done, bytes total, message)


class ToolsError(RuntimeError):
    """A tool could not be installed or run (the message is shown to the user)."""


@dataclass(frozen=True)
class ToolInfo:
    available: bool
    path: Path | None = None
    version: str | None = None
    error: str | None = None


def tools_dir() -> Path:
    override = os.environ.get(TOOLS_ENV)
    return Path(override) if override else user_dir("youtube-tools")


def _candidate(name: str, file: str) -> Path | None:
    managed = tools_dir() / file
    if managed.is_file():
        return managed
    found = shutil.which(name)
    return Path(found) if found else None


def find_ytdlp() -> Path | None:
    return _candidate("yt-dlp", "yt-dlp.exe")


def find_deno() -> Path | None:
    return _candidate("deno", "deno.exe")


def _version(path: Path | None, arg: str) -> ToolInfo:
    if path is None:
        return ToolInfo(False)
    try:
        proc = subprocess.run(  # noqa: S603 - a program we located, list arguments, no shell
            [str(path), arg],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            creationflags=CREATE_NO_WINDOW,
            stdin=subprocess.DEVNULL,
            check=False,
        )
    except OSError as exc:
        hint = ""
        if getattr(exc, "winerror", None) in (1260, 577):
            hint = " (a Windows policy blocked it)"
        return ToolInfo(False, path, error=f"{path.name} could not be started{hint}: {exc}")
    except subprocess.TimeoutExpired:
        return ToolInfo(False, path, error=f"{path.name} did not answer in 30 s")
    text = (proc.stdout or proc.stderr).strip().splitlines()
    ok = proc.returncode == 0 and bool(text)
    return ToolInfo(
        ok, path, text[0].strip() if ok else None, None if ok else f"exit code {proc.returncode}"
    )


def status() -> dict[str, ToolInfo]:
    return {
        "yt_dlp": _version(find_ytdlp(), "--version"),
        "deno": _version(find_deno(), "--version"),
    }


def is_installed() -> bool:
    s = status()
    return s["yt_dlp"].available and s["deno"].available


# ----- installation --------------------------------------------------------------------------

_HASH = re.compile(r"\b([a-fA-F0-9]{64})\b")


def parse_checksum(text: str, filename: str | None = None) -> str:
    """The SHA-256 for `filename` from a publisher's checksum file (or the only hash in it)."""
    for line in text.splitlines():
        m = _HASH.search(line)
        if m and (filename is None or line.strip().endswith(filename) or filename in line.split()):
            return str(m.group(1)).lower()
    # A checksum file for ONE file may put hash and name on different lines (Deno publishes the
    # output of Windows' Get-FileHash: "Hash : ..." and "Path : ...\\file.zip"), or give no name.
    # That is only unambiguous when the whole file holds exactly one distinct hash.
    distinct = {h.lower() for h in _HASH.findall(text)}
    if len(distinct) == 1 and (
        filename is None or filename in text or len(text.strip().splitlines()) == 1
    ):
        return str(next(iter(distinct)))
    raise ToolsError(
        f"No SHA-256 for {filename or 'the file'} was found in the publisher's checksum file"
    )


def _get_text(client: httpx.Client, url: str) -> str:
    resp = client.get(url, follow_redirects=True)
    resp.raise_for_status()
    return str(resp.text)


def _mismatch(name: str, expected: str, got: str) -> ToolsError:
    return ToolsError(
        f"{name}: checksum mismatch (expected {expected[:12]}..., got {got[:12]}...); "
        "nothing was installed. Try again."
    )


def _download(
    client: httpx.Client, url: str, dest: Path, on_bytes: Callable[[int, int], None]
) -> str:
    """Stream `url` into `dest`; return its SHA-256."""
    import hashlib

    h = hashlib.sha256()
    with client.stream("GET", url, follow_redirects=True) as resp:
        resp.raise_for_status()
        total = int(resp.headers.get("content-length") or 0)
        done = 0
        with dest.open("wb") as fh:
            for chunk in resp.iter_bytes(1 << 20):
                fh.write(chunk)
                h.update(chunk)
                done += len(chunk)
                on_bytes(done, total)
    return h.hexdigest()


def install(progress: Progress, *, client: httpx.Client | None = None) -> None:
    """Download and verify yt-dlp.exe and Deno into the managed folder. Blocking."""
    own = client is None
    client = client or httpx.Client(timeout=httpx.Timeout(30.0, read=120.0))
    target = tools_dir()
    target.mkdir(parents=True, exist_ok=True)
    stage = target / ".download"
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir()
    sizes = {"yt": 0, "deno": 0}

    def report(part: str, base: int, message: str) -> Callable[[int, int], None]:
        def on_bytes(done: int, total: int) -> None:
            sizes[part] = total or sizes[part]
            progress(base + done, max(sum(sizes.values()), ESTIMATED_BYTES), message)

        return on_bytes

    try:
        try:
            progress(0, ESTIMATED_BYTES, "Reading the checksums...")
            ytdlp_sum = parse_checksum(_get_text(client, YTDLP_SUMS_URL), "yt-dlp.exe")
            deno_sum = parse_checksum(_get_text(client, DENO_SUM_URL), DENO_ZIP)

            ytdlp_tmp = stage / "yt-dlp.exe"
            got = _download(client, YTDLP_URL, ytdlp_tmp, report("yt", 0, "Downloading yt-dlp"))
            if got != ytdlp_sum:
                raise _mismatch("yt-dlp.exe", ytdlp_sum, got)

            zip_tmp = stage / DENO_ZIP
            got = _download(
                client, DENO_URL, zip_tmp, report("deno", sizes["yt"], "Downloading Deno")
            )
            if got != deno_sum:
                raise _mismatch(DENO_ZIP, deno_sum, got)
        except httpx.HTTPError as exc:
            raise ToolsError(
                f"Download failed: {exc}. Check your internet connection and try again."
            ) from exc

        progress(sum(sizes.values()), max(sum(sizes.values()), 1), "Installing...")
        with zipfile.ZipFile(zip_tmp) as z:
            try:
                info = z.getinfo("deno.exe")  # exact member name: no path traversal possible
            except KeyError as exc:
                raise ToolsError("The Deno archive does not contain deno.exe") from exc
            with z.open(info) as src, (stage / "deno.exe").open("wb") as out:
                shutil.copyfileobj(src, out)
        for name in ("yt-dlp.exe", "deno.exe"):
            (stage / name).replace(target / name)
    finally:
        shutil.rmtree(stage, ignore_errors=True)
        if own:
            client.close()
    s = status()
    bad = [k for k, v in s.items() if not v.available]
    if bad:
        details = "; ".join(f"{k}: {s[k].error}" for k in bad)
        raise ToolsError(f"The tools were installed but do not start ({details})")
    done = sum(sizes.values())
    progress(done, done, "Done")


def update_ytdlp() -> str:
    """`yt-dlp --update-to stable` (yt-dlp's own, signed update mechanism)."""
    path = find_ytdlp()
    if path is None:
        raise ToolsError("yt-dlp is not installed")
    proc: Any = subprocess.run(  # noqa: S603
        [str(path), "--no-config", "--encoding", "utf-8", "--update-to", "stable"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
        creationflags=CREATE_NO_WINDOW,
        stdin=subprocess.DEVNULL,
        check=False,
    )
    text = ((proc.stdout or "") + (proc.stderr or "")).strip()
    if proc.returncode != 0:
        last = [ln for ln in text.splitlines() if ln.strip()][-1:] or ["unknown error"]
        raise ToolsError(f"Update failed: {last[0][:300]}")
    return text

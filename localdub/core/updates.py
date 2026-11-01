"""Look for a newer LocalDub Studio on GitHub, download it and start its installer.

Only the newest *normal* release counts: GitHub's `releases/latest` never returns a pre-release or a
draft. The check sends nothing but an ordinary request for that public page; the user can switch
it off. The download comes from this project's own release URLs only and is checked against the
`.sha256` file published next to it (this catches a damaged download, not a compromised release).
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import shutil
import subprocess
import sys
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from packaging.version import InvalidVersion, Version

from localdub.paths import REPO_ROOT

log = logging.getLogger(__name__)

REPO = "spekulanter/localdub-studio"
API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
DOWNLOAD_PREFIX = f"https://github.com/{REPO}/releases/download/"
Progress = Callable[[int, int], None]  # (bytes done, bytes total)


class UpdateError(RuntimeError):
    """The update could not be looked up, downloaded or started (shown to the user)."""


@dataclass(frozen=True)
class Update:
    version: str
    notes: str
    page: str
    asset: str
    url: str
    size: int
    sha_url: str


def current_version() -> str:
    try:
        data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        return str(data["project"]["version"])
    except (OSError, KeyError, ValueError):
        pass
    try:
        from importlib.metadata import version

        return version("localdub")
    except Exception:  # noqa: BLE001
        return "0"


def is_newer(candidate: str, current: str) -> bool:
    try:
        return Version(candidate.lstrip("v")) > Version(current.lstrip("v"))
    except InvalidVersion:
        return False


def pick_assets(
    assets: list[dict[str, Any]], platform: str | None = None
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """The installer of this system and the file with its checksum."""
    platform = platform or sys.platform
    pattern = (
        r"^LocalDub-Studio-[\d.]+-Setup\.exe$"
        if platform == "win32"
        else r"^LocalDub-Studio-[\d.]+-macOS-arm64\.dmg$"
    )
    by_name = {str(a.get("name")): a for a in assets}
    main = next((a for n, a in by_name.items() if re.match(pattern, n)), None)
    if main is None:
        return None
    sha = by_name.get(f"{main['name']}.sha256")
    return (main, sha) if sha is not None else None


def parse_release(data: dict[str, Any], platform: str | None = None) -> Update | None:
    if data.get("draft") or data.get("prerelease"):
        return None
    picked = pick_assets(list(data.get("assets") or []), platform)
    if picked is None:
        return None
    main, sha = picked
    for a in (main, sha):
        if not str(a.get("browser_download_url", "")).startswith(DOWNLOAD_PREFIX):
            return None
    return Update(
        version=str(data.get("tag_name", "")).lstrip("v"),
        notes=str(data.get("body") or ""),
        page=str(data.get("html_url") or f"https://github.com/{REPO}/releases"),
        asset=str(main["name"]),
        url=str(main["browser_download_url"]),
        size=int(main.get("size") or 0),
        sha_url=str(sha["browser_download_url"]),
    )


def check(client: httpx.Client | None = None, platform: str | None = None) -> Update | None:
    """The newest normal release if it is newer than this program, else None."""
    own = client is None
    client = client or httpx.Client(timeout=httpx.Timeout(10.0))
    try:
        resp = client.get(
            API_URL,
            headers={"Accept": "application/vnd.github+json", "User-Agent": "LocalDub-Studio"},
            follow_redirects=True,
        )
        if resp.status_code == 404:  # no normal release yet
            return None
        resp.raise_for_status()
        found = parse_release(resp.json(), platform)
    except (httpx.HTTPError, ValueError) as exc:
        raise UpdateError(f"Could not ask GitHub about a new version: {exc}") from exc
    finally:
        if own:
            client.close()
    return found if found is not None and is_newer(found.version, current_version()) else None


def download(
    update: Update, folder: Path, progress: Progress, client: httpx.Client | None = None
) -> Path:
    """Fetch the installer into `folder` and verify it. Blocking."""
    for u in (update.url, update.sha_url):
        if not u.startswith(DOWNLOAD_PREFIX):
            raise UpdateError("The update is not hosted where it should be; it was not downloaded.")
    own = client is None
    client = client or httpx.Client(timeout=httpx.Timeout(30.0, read=120.0))
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    target, part = folder / update.asset, folder / (update.asset + ".part")
    try:
        try:
            sums = client.get(update.sha_url, follow_redirects=True)
            sums.raise_for_status()
            match = re.search(r"\b([a-fA-F0-9]{64})\b", sums.text)
            if match is None:
                raise UpdateError("The checksum file of the update is unreadable.")
            expected = match.group(1).lower()
            h = hashlib.sha256()
            with client.stream("GET", update.url, follow_redirects=True) as resp:
                resp.raise_for_status()
                total = int(resp.headers.get("content-length") or update.size or 0)
                done = 0
                with part.open("wb") as fh:
                    for chunk in resp.iter_bytes(1 << 20):
                        fh.write(chunk)
                        h.update(chunk)
                        done += len(chunk)
                        progress(done, total)
        except httpx.HTTPError as exc:
            raise UpdateError(
                f"Download failed: {exc}. Check your internet connection and try again."
            ) from exc
        if h.hexdigest() != expected:
            raise UpdateError(
                "The downloaded update is damaged (checksum mismatch); it was discarded."
            )
        part.replace(target)
    except BaseException:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    finally:
        if own:
            client.close()
    return target


def launch_installer(path: Path) -> None:
    """Windows: the setup wizard (it asks for administrator rights). Mac: opens the disk image."""
    try:
        if sys.platform == "win32":
            os.startfile(str(path))  # type: ignore[attr-defined,unused-ignore]  # noqa: S606
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])  # noqa: S603,S607 - Finder, list args
        else:
            raise UpdateError("Updates are installed by hand on this system.")
    except OSError as exc:
        raise UpdateError(f"The installer could not be started: {exc}") from exc

"""Install and start Ollama for the user, when they press the button.

Translation runs inside Ollama. On Windows the program installs it with `winget` (the same way the
setup wizard does, package Ollama.Ollama from the winget repository). On a Mac it downloads
Ollama's own `Ollama-darwin.zip` from its GitHub release, checks it against the `sha256sum.txt`
published with that release (this protects against corrupted downloads, not against a
compromised release) and unpacks it into `~/Applications`, which needs no administrator password.
Nothing here runs unless the user asks for it.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

import httpx

from localdub.core.youtube.tools import parse_checksum
from localdub.paths import user_dir

log = logging.getLogger(__name__)

RELEASE = "https://github.com/ollama/ollama/releases/latest/download"
MAC_ZIP = "Ollama-darwin.zip"
SUMS = "sha256sum.txt"
WINGET_ID = "Ollama.Ollama"
Progress = Callable[[int, int, str], None]  # (bytes done, bytes total, message)
_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
_DETACHED = 0x00000008 if sys.platform == "win32" else 0


class OllamaSetupError(RuntimeError):
    """Ollama could not be installed or started (the message is shown to the user)."""


# ----- where it is -----------------------------------------------------------------------------


def mac_app_candidates() -> list[Path]:
    return [Path("/Applications/Ollama.app"), Path.home() / "Applications" / "Ollama.app"]


def windows_program() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    return base / "Programs" / "Ollama"


def find_cli() -> Path | None:
    """The `ollama` command, from PATH or the usual install places."""
    extra: list[str] = []
    if sys.platform == "darwin":
        extra = ["/opt/homebrew/bin", "/usr/local/bin"]
        extra += [str(a / "Contents" / "Resources") for a in mac_app_candidates()]
    elif sys.platform == "win32":
        extra = [str(windows_program())]
    found = shutil.which("ollama") or shutil.which("ollama", path=os.pathsep.join(extra))
    return Path(found) if found else None


def find_mac_app() -> Path | None:
    return next((a for a in mac_app_candidates() if a.is_dir()), None)


def is_present() -> bool:
    return find_cli() is not None or find_mac_app() is not None


def is_running(base_url: str, timeout: float = 2.0) -> bool:
    try:
        return httpx.get(f"{base_url}/api/tags", timeout=timeout).status_code == 200
    except httpx.HTTPError:
        return False


# ----- installing ------------------------------------------------------------------------------


def _extract_app(zip_path: Path, dest: Path) -> None:
    """`ditto` keeps the links and permissions an .app needs (Python's zipfile does not)."""
    dest.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(  # noqa: S603
        ["ditto", "-x", "-k", str(zip_path), str(dest)],  # noqa: S607
        capture_output=True, text=True, timeout=600, check=False,
    )  # fmt: skip
    if proc.returncode != 0:
        raise OllamaSetupError(f"Could not unpack Ollama: {proc.stderr.strip()[:300]}")


def install_mac(
    progress: Progress,
    *,
    client: httpx.Client | None = None,
    extract: Callable[[Path, Path], None] = _extract_app,
    target: Path | None = None,
) -> Path:
    import hashlib

    own = client is None
    client = client or httpx.Client(timeout=httpx.Timeout(30.0, read=120.0))
    target = target or Path.home() / "Applications"
    stage = user_dir("tools") / ".ollama-download"
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir(parents=True)
    try:
        try:
            progress(0, 0, "Reading the checksum...")
            sums = client.get(f"{RELEASE}/{SUMS}", follow_redirects=True)
            sums.raise_for_status()
            expected = parse_checksum(sums.text, MAC_ZIP)
            part = stage / MAC_ZIP
            h = hashlib.sha256()
            with client.stream("GET", f"{RELEASE}/{MAC_ZIP}", follow_redirects=True) as resp:
                resp.raise_for_status()
                total = int(resp.headers.get("content-length") or 0)
                done = 0
                with part.open("wb") as fh:
                    for chunk in resp.iter_bytes(1 << 20):
                        fh.write(chunk)
                        h.update(chunk)
                        done += len(chunk)
                        progress(done, total, "Downloading Ollama")
        except httpx.HTTPError as exc:
            raise OllamaSetupError(
                f"Download failed: {exc}. Check your internet connection and try again."
            ) from exc
        except Exception as exc:  # noqa: BLE001 - e.g. no checksum for the file
            raise OllamaSetupError(f"Could not read Ollama's checksum: {exc}") from exc
        if h.hexdigest() != expected:
            raise OllamaSetupError(
                f"Ollama: checksum mismatch (expected {expected[:12]}..., "
                f"got {h.hexdigest()[:12]}...); nothing was installed. Try again."
            )
        progress(done, done, "Installing...")
        extract(part, target)
    finally:
        shutil.rmtree(stage, ignore_errors=True)
        if own:
            client.close()
    app = target / "Ollama.app"
    if not app.is_dir():
        raise OllamaSetupError("Ollama was unpacked but Ollama.app is not where expected.")
    return app


def install_windows(progress: Progress) -> None:
    winget = shutil.which("winget")
    if winget is None:
        raise OllamaSetupError(
            "winget is not available on this computer. Install Ollama from https://ollama.com/download."
        )
    progress(0, 0, "Installing with winget (this can take a few minutes)...")
    proc = subprocess.run(  # noqa: S603 - winget, fixed package id, list arguments, no shell
        [winget, "install", "--id", WINGET_ID, "-e", "--silent", "--accept-source-agreements",
         "--accept-package-agreements"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=3600,
        stdin=subprocess.DEVNULL, creationflags=_NO_WINDOW, check=False,
    )  # fmt: skip
    if proc.returncode != 0 and not is_present():
        tail = "\n".join((proc.stdout + proc.stderr).strip().splitlines()[-5:])
        raise OllamaSetupError(
            f"winget could not install Ollama (exit code {proc.returncode}):\n{tail}"
        )


def install(progress: Progress) -> None:
    if sys.platform == "darwin":
        install_mac(progress)
    elif sys.platform == "win32":
        install_windows(progress)
    else:
        raise OllamaSetupError("Install Ollama from https://ollama.com/download.")


# ----- starting --------------------------------------------------------------------------------


def start() -> None:
    """Start Ollama's background server (its menu-bar or tray app where there is one)."""
    try:
        app = find_mac_app() if sys.platform == "darwin" else None
        if app is not None:
            subprocess.Popen(["open", "-a", str(app)])  # noqa: S603,S607 - Finder, list args
            return
        if sys.platform == "win32":
            tray = windows_program() / "ollama app.exe"
            if tray.is_file():
                subprocess.Popen(  # noqa: S603
                    [str(tray)], creationflags=_DETACHED | _NO_WINDOW, stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True,
                )  # fmt: skip
                return
        cli = find_cli()
        if cli is None:
            raise OllamaSetupError("Ollama is not installed.")
        subprocess.Popen(  # noqa: S603 - the program we located, list arguments
            [str(cli), "serve"], creationflags=_DETACHED | _NO_WINDOW,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=sys.platform != "win32",
        )  # fmt: skip
    except OSError as exc:
        raise OllamaSetupError(f"Ollama could not be started: {exc}") from exc


def ensure_running(base_url: str, wait_s: float = 60.0) -> bool:
    """Start Ollama if it is not answering and wait until it does."""
    if is_running(base_url):
        return True
    start()
    deadline = time.monotonic() + wait_s
    while time.monotonic() < deadline:
        if is_running(base_url):
            return True
        time.sleep(1.0)
    return False

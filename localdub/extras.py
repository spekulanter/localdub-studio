"""Optional PyTorch packages (speech removal, voice cloning), installed from inside the app.

Why a separate folder: the program lives in `Program Files`, which a normal user cannot write to,
and an elevated installer must not download 3 GB of optional packages the user may never use. So
the app installs them, as the user, into `%LOCALAPPDATA%\\LocalDub Studio\\extras` and adds that
folder to the *end* of `sys.path` (packages already in the main environment always win).

What gets installed is exactly what `uv.lock` pins, minus what the base install already has. The
wheels are downloaded here (visible byte-level progress, resumable, SHA-256 checked against the
lock) and then unpacked with `uv pip install --no-deps --no-index --target`.

This module is imported by `localdub/__init__.py`, so everything at module level must stay cheap.
"""

from __future__ import annotations

import importlib
import json
import logging
import os
import re
import shutil
import site
import subprocess
import sys
import threading
import time
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from localdub.paths import REPO_ROOT, user_dir

log = logging.getLogger(__name__)

EXTRAS_ENV = "LOCALDUB_EXTRAS_DIR"
COMPLETE = ".complete"
MODULES = ("torch", "demucs")
# Used only for the size shown before a download starts (the lock has no size for the PyTorch
# wheel); the real size is read from the server before downloading.
SIZE_ESTIMATES = {"torch": 2_862_033_275}
DEFAULT_ESTIMATE = 5_000_000
CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

Progress = Callable[[int, int, str], None]  # (bytes done, bytes total, message)


class ExtrasError(RuntimeError):
    """The optional packages could not be installed (the message is shown to the user)."""


def extras_dir() -> Path:
    override = os.environ.get(EXTRAS_ENV)
    return Path(override) if override else user_dir("extras")


def activate() -> bool:
    """Make installed optional packages importable. Cheap, idempotent, safe to call often."""
    folder = extras_dir()
    if not (folder / COMPLETE).is_file():
        return False
    path = str(folder)
    if path not in sys.path:
        site.addsitedir(path)  # appends: never shadows the main environment
    importlib.invalidate_caches()
    return True


def packages_available() -> bool:
    """True if torch and demucs can be imported (from the main environment or the extras folder)."""
    import importlib.util

    activate()
    return all(importlib.util.find_spec(m) is not None for m in MODULES)


# ----- the plan: which wheels, from the lock -------------------------------------------------


@dataclass(frozen=True)
class Wheel:
    name: str
    version: str
    url: str
    sha256: str
    size: int | None  # None: the lock does not know (PyTorch index)

    @property
    def filename(self) -> str:
        return unquote(Path(urlparse(self.url).path).name)

    @property
    def estimate(self) -> int:
        return self.size or SIZE_ESTIMATES.get(self.name, DEFAULT_ESTIMATE)


def find_uv() -> Path | None:
    bundled = REPO_ROOT / "tools" / "uv.exe"
    if bundled.is_file():
        return bundled
    found = shutil.which("uv")
    return Path(found) if found else None


def _run(
    cmd: list[str | Path], *, cwd: Path | None = None, env: dict[str, str] | None = None
) -> str:
    proc = subprocess.run(  # noqa: S603 - fixed program, list arguments, no shell
        [str(c) for c in cmd],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=CREATE_NO_WINDOW,
        check=False,
    )
    if proc.returncode != 0:
        tail = "\n".join((proc.stderr or proc.stdout).strip().splitlines()[-8:])
        raise ExtrasError(f"{Path(str(cmd[0])).name} failed (exit code {proc.returncode}):\n{tail}")
    return proc.stdout


_PIN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s;]+)")


def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def parse_pins(requirements: str) -> dict[str, str]:
    """{normalised name: version} from `uv export` output (hash/comment lines are skipped)."""
    pins: dict[str, str] = {}
    for line in requirements.splitlines():
        m = _PIN.match(line)
        if m:
            pins[normalize(m.group(1))] = m.group(2)
    return pins


def extra_only(base: dict[str, str], full: dict[str, str]) -> dict[str, str]:
    """Pins that the optional extra adds (or changes) compared with the base install."""
    return {k: v for k, v in full.items() if base.get(k) != v}


def pick_wheel(package: dict[str, Any], tags: list[Any] | None = None) -> Wheel:
    """The best wheel of a lock entry for this Python/platform; never an sdist."""
    from packaging.tags import sys_tags
    from packaging.utils import InvalidWheelFilename, parse_wheel_filename

    ranking = {t: i for i, t in enumerate(tags if tags is not None else sys_tags())}
    best: tuple[int, dict[str, Any]] | None = None
    for w in package.get("wheels", []):
        try:
            _, _, _, wtags = parse_wheel_filename(unquote(Path(urlparse(w["url"]).path).name))
        except InvalidWheelFilename:
            continue
        score = min((ranking[t] for t in wtags if t in ranking), default=None)
        if score is not None and (best is None or score < best[0]):
            best = (score, w)
    if best is None:
        raise ExtrasError(
            f"No prebuilt wheel of {package['name']} {package['version']} fits this computer "
            "(64-bit Windows with Python 3.12 is required)."
        )
    w = best[1]
    digest = str(w.get("hash", ""))
    if not digest.startswith("sha256:"):
        raise ExtrasError(
            f"The lock file has no SHA-256 for {package['name']}; refusing to install"
        )
    return Wheel(
        name=normalize(package["name"]),
        version=package["version"],
        url=w["url"],
        sha256=digest.removeprefix("sha256:"),
        size=w.get("size"),
    )


def build_plan(root: Path = REPO_ROOT, uv: Path | None = None) -> list[Wheel]:
    uv = uv or find_uv()
    if uv is None:
        raise ExtrasError("uv was not found. Reinstall LocalDub Studio.")
    lock_path = root / "uv.lock"
    if not lock_path.is_file():
        raise ExtrasError(f"{lock_path} is missing; the optional packages cannot be installed.")
    common = ["export", "--frozen", "--no-dev", "--no-emit-project", "--no-header"]
    base = parse_pins(_run([uv, *common], cwd=root))
    full = parse_pins(_run([uv, *common, "--extra", "experimental"], cwd=root))
    wanted = extra_only(base, full)
    if not wanted:
        raise ExtrasError("The lock file lists no optional packages.")
    lock = tomllib.loads(lock_path.read_text(encoding="utf-8"))
    by_key = {(normalize(p["name"]), p["version"]): p for p in lock.get("package", [])}
    wheels = []
    for name, version in sorted(wanted.items()):
        package = by_key.get((name, version))
        if package is None:
            raise ExtrasError(f"{name} {version} is not in the lock file")
        wheels.append(pick_wheel(package))
    return wheels


_plan_cache: dict[tuple[Path, float], list[Wheel]] = {}


def cached_plan(root: Path = REPO_ROOT) -> list[Wheel]:
    key = (root, (root / "uv.lock").stat().st_mtime)
    if key not in _plan_cache:
        _plan_cache.clear()
        _plan_cache[key] = build_plan(root)
    return _plan_cache[key]


def estimated_total_bytes() -> int | None:
    """Download size for the UI, or None if it cannot be determined."""
    try:
        return sum(w.estimate for w in cached_plan())
    except (ExtrasError, OSError):
        return None


# ----- download and install ------------------------------------------------------------------


def _sha256_file(path: Path) -> str:
    import hashlib

    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def resolve_sizes(wheels: list[Wheel], client: Any) -> dict[str, int]:
    """Exact size of every wheel (a HEAD request for those the lock has no size for)."""
    sizes: dict[str, int] = {}
    for w in wheels:
        if w.size:
            sizes[w.filename] = w.size
            continue
        head = client.head(w.url, follow_redirects=True)
        head.raise_for_status()
        length = int(head.headers.get("content-length") or 0)
        sizes[w.filename] = length or w.estimate
    return sizes


def download_wheel(
    w: Wheel, size: int, dest: Path, client: Any, on_bytes: Callable[[int], None]
) -> Path:
    """Download one wheel (resuming a partial file), verify its SHA-256, return its path."""
    final = dest / w.filename
    part = dest / (w.filename + ".part")
    if final.is_file() and _sha256_file(final) == w.sha256:
        on_bytes(final.stat().st_size)
        return final
    final.unlink(missing_ok=True)
    have = part.stat().st_size if part.is_file() else 0
    for _ in range(2):
        headers = {"Range": f"bytes={have}-"} if have else {}
        with client.stream("GET", w.url, headers=headers, follow_redirects=True) as resp:
            if resp.status_code == 416:  # nothing left to fetch, or the partial file is invalid
                part.unlink(missing_ok=True)
                have = 0
                continue
            resp.raise_for_status()
            if have and resp.status_code != 206:  # the server ignored the range: start over
                have = 0
            with part.open("ab" if have else "wb") as fh:
                done = have
                on_bytes(done)
                for chunk in resp.iter_bytes(1 << 20):
                    fh.write(chunk)
                    done += len(chunk)
                    on_bytes(done)
        break
    else:
        raise ExtrasError(f"Could not download {w.filename}")
    digest = _sha256_file(part)
    if digest != w.sha256:
        part.unlink(missing_ok=True)
        raise ExtrasError(
            f"{w.filename}: checksum mismatch (expected {w.sha256[:12]}..., got {digest[:12]}...). "
            "The file was discarded; try again."
        )
    part.replace(final)
    return final


def _dir_size(path: Path) -> int:
    total = 0
    if path.exists():
        for p in path.rglob("*"):
            try:
                if p.is_file():
                    total += p.stat().st_size
            except OSError:
                continue
    return total


# Unpacked packages are about this much larger than the wheels (torch: 2.9 GB -> 4.3 GB).
UNPACK_FACTOR = 1.6


def _gb(n: int) -> str:
    return f"{n / 1e9:.1f} GB" if n >= 1e9 else f"{n / 1e6:.0f} MB"


def _free_bytes(path: Path) -> int:
    probe = path
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    return shutil.disk_usage(probe).free


def install(progress: Progress, *, client: Any | None = None, uv: Path | None = None) -> None:
    """Download and install the optional packages. Blocking; raises ExtrasError on failure."""
    import httpx

    uv = uv or find_uv()
    if uv is None:
        raise ExtrasError("uv was not found. Reinstall LocalDub Studio.")
    folder = extras_dir()
    staging = folder.parent / (folder.name + "-download")
    fresh = folder.parent / (folder.name + "-new")
    staging.mkdir(parents=True, exist_ok=True)

    progress(0, 0, "Preparing...")
    wheels = build_plan(uv=uv)
    own = client is None
    client = client or httpx.Client(timeout=httpx.Timeout(30.0, read=120.0))
    try:
        sizes = resolve_sizes(wheels, client)
        total = sum(sizes.values())
        grand_total = total + int(total * UNPACK_FACTOR)
        need = total * 3
        free = _free_bytes(staging)
        if free < need:
            raise ExtrasError(
                f"Not enough free disk space: about {need / 1e9:.0f} GB are needed on "
                f"{staging.drive or staging}, {free / 1e9:.1f} GB are free."
            )
        done_before = 0
        files: list[Path] = []
        for w in wheels:
            base = done_before

            def on_bytes(n: int, base: int = base, name: str = w.name) -> None:
                progress(
                    base + n, grand_total, f"Downloading {name} ({_gb(base + n)} of {_gb(total)})"
                )

            files.append(download_wheel(w, sizes[w.filename], staging, client, on_bytes))
            done_before += sizes[w.filename]
    except httpx.HTTPError as exc:
        raise ExtrasError(
            f"Download failed: {exc}. Check your internet connection and try again."
        ) from exc
    finally:
        if own:
            client.close()

    unpack = int(total * UNPACK_FACTOR)
    grand = total + unpack
    progress(total, grand, "Unpacking and installing (a few minutes)...")
    shutil.rmtree(fresh, ignore_errors=True)
    cache = staging / "uv-cache"
    stop = threading.Event()

    def watch() -> None:
        # uv gives no progress: follow the growth of its cache and of the target folder instead.
        while not stop.wait(1.0):
            grown = max(_dir_size(cache), _dir_size(fresh))
            progress(
                total + min(grown, int(unpack * 0.99)),
                grand,
                "Unpacking and installing (a few minutes)...",
            )

    watcher = threading.Thread(target=watch, daemon=True)
    watcher.start()
    try:
        _run(
            [uv, "pip", "install", "--python", sys.executable, "--target", fresh, "--no-deps",
             "--no-index", "--no-progress", *files],
            env={**os.environ, "UV_CACHE_DIR": str(cache)},
        )  # fmt: skip
    finally:
        stop.set()
        watcher.join(timeout=3)
    (fresh / COMPLETE).write_text(
        json.dumps(
            {
                "installed": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "wheels": [f"{w.name}=={w.version}" for w in wheels],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    shutil.rmtree(folder, ignore_errors=True)
    fresh.replace(folder)
    shutil.rmtree(staging, ignore_errors=True)
    activate()
    progress(grand, grand, "Done")

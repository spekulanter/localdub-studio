"""Download of model files from documented sources, with integrity checks.

Only data files (ONNX weights) are fetched, never executables, and only when the user has enabled
the feature that needs them. Every source and its licence is listed in docs/LICENSES.md.
"""

from __future__ import annotations

import hashlib
import logging
import tarfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import httpx

log = logging.getLogger(__name__)


class ModelDownloadError(RuntimeError):
    pass


@dataclass(frozen=True)
class RemoteModel:
    name: str
    url: str
    sha256: str  # of the downloaded file (the archive for tarballs)
    dest: str  # relative to models_dir
    member: str | None = None  # file inside a .tar.bz2 to extract to `dest`


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def is_readable(path: Path) -> bool:
    """True if this process can open the file. A file written by an elevated installer can be
    present but unreadable for the normal user (ACL), which looks like 'error 13' later."""
    try:
        with path.open("rb") as fh:
            fh.read(1)
        return True
    except OSError:
        return False


ProgressFn = Callable[[int, int], None]  # (bytes done, bytes total or 0)


def ensure_model(
    model: RemoteModel,
    models_dir: Path,
    *,
    client: httpx.Client | None = None,
    progress: ProgressFn | None = None,
) -> Path:
    """Return the local path of `model`, downloading and verifying it if it is missing.

    Files are written straight into the destination folder (never via tempfile.mkdtemp, whose
    Windows ACL would lock the file to the creating user's elevated token).
    """
    target = models_dir / model.dest
    if target.is_file():
        if is_readable(target):
            return target
        log.warning("%s exists but cannot be read; downloading it again", target)
        target.unlink()
    target.parent.mkdir(parents=True, exist_ok=True)
    log.info("Downloading %s from %s", model.name, model.url)
    own = client is None
    client = client or httpx.Client(follow_redirects=True, timeout=httpx.Timeout(60.0, read=300.0))
    blob = target.with_name(target.name + ".download")
    part = target.with_name(target.name + ".part")
    try:
        try:
            with client.stream("GET", model.url) as resp:
                resp.raise_for_status()
                total = int(resp.headers.get("content-length") or 0)
                done = 0
                with blob.open("wb") as fh:
                    for chunk in resp.iter_bytes(1 << 20):
                        fh.write(chunk)
                        done += len(chunk)
                        if progress:
                            progress(done, total)
        except httpx.HTTPError as exc:
            raise ModelDownloadError(f"Could not download {model.name}: {exc}") from exc
        digest = sha256_of(blob)
        if digest != model.sha256:
            raise ModelDownloadError(
                f"{model.name}: checksum mismatch (expected {model.sha256}, got {digest}); "
                "the file was not installed"
            )
        if model.member is None:
            blob.replace(target)
        else:
            with tarfile.open(blob, "r:bz2") as tar:
                info = tar.getmember(model.member)  # exact name only: no path traversal
                if not info.isfile():
                    raise ModelDownloadError(f"{model.member} is not a regular file")
                src = tar.extractfile(info)
                assert src is not None
                with part.open("wb") as out:
                    while chunk := src.read(1 << 20):
                        out.write(chunk)
            part.replace(target)
    finally:
        blob.unlink(missing_ok=True)
        part.unlink(missing_ok=True)
        if own:
            client.close()
    return target

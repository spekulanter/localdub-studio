"""One handler per kind of source: installed? download, delete, where is it, is there a newer one.

Deleting is the dangerous part, so it is done in exactly two ways: Hugging Face's own cache API for
cached repositories, and `safe_rmtree` for plain folders. Both only ever touch paths computed from
the catalogue (never from the request) and inside the models folder.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from localdub import extras
from localdub.config import Settings
from localdub.core.modelmgr.catalog import Entry
from localdub.core.models import ensure_archive_files, ensure_model, is_readable
from localdub.core.youtube import tools as youtube_tools

log = logging.getLogger(__name__)

Progress = Callable[[int, int, str], None]  # (bytes done, bytes total or 0, message)
OLLAMA_REGISTRY = "https://registry.ollama.ai/v2"
_MANIFEST = "application/vnd.docker.distribution.manifest.v2+json"


class ModelError(RuntimeError):
    """A model operation failed; the message is shown to the user."""


class NotDeletable(ModelError):
    """This entry cannot (or must not) be deleted by LocalDub."""


# ----- helpers -------------------------------------------------------------------------------


def dir_size(path: Path) -> int:
    total = 0
    if path.exists():
        for p in path.rglob("*"):
            try:
                if p.is_file() and not p.is_symlink():
                    total += p.stat().st_size
            except OSError:
                continue
    return total


def is_link(path: Path) -> bool:
    """Symlink or Windows junction: removing through it could delete something elsewhere."""
    try:
        return path.is_symlink() or path.is_junction()
    except OSError:
        return True


def safe_rmtree(path: Path, root: Path) -> bool:
    """Remove `path` (a folder strictly inside `root`). Returns False if it did not exist."""
    root_r = root.resolve()
    if is_link(path):
        raise NotDeletable(f"{path} is a link; remove it yourself if you want it gone.")
    if not path.exists():
        return False
    path_r = path.resolve()
    if path_r == root_r or root_r not in path_r.parents:
        raise NotDeletable(f"{path} is not inside {root}; refusing to delete it.")
    for child in path_r.rglob("*"):
        if is_link(child):
            raise NotDeletable(f"{child} is a link inside the folder; refusing to delete it.")
    shutil.rmtree(path_r)
    return True


def delete_hf_repo(cache_dir: Path, repo_id: str) -> bool:
    """Remove every cached revision of a repository with Hugging Face's own cache API."""
    from huggingface_hub import scan_cache_dir
    from huggingface_hub.errors import CacheNotFound

    try:
        info = scan_cache_dir(cache_dir)
    except CacheNotFound:
        return False
    for repo in info.repos:
        if repo.repo_id == repo_id and repo.repo_type == "model":
            hashes = [r.commit_hash for r in repo.revisions]
            if hashes:
                info.delete_revisions(*hashes).execute()
            return True
    return False


def prune_old_revisions(cache_dir: Path, repo_id: str) -> int:
    """After an update keep only the revision `main` points to; returns how many were removed."""
    from huggingface_hub import scan_cache_dir
    from huggingface_hub.errors import CacheNotFound

    try:
        info = scan_cache_dir(cache_dir)
    except CacheNotFound:
        return 0
    for repo in info.repos:
        if repo.repo_id == repo_id and repo.repo_type == "model":
            old = [r.commit_hash for r in repo.revisions if "main" not in r.refs]
            keep = [r for r in repo.revisions if "main" in r.refs]
            if old and keep:  # never prune when we cannot tell which revision is current
                info.delete_revisions(*old).execute()
                return len(old)
    return 0


def hf_repo_dir(cache_dir: Path, repo_id: str) -> Path:
    return cache_dir / ("models--" + repo_id.replace("/", "--"))


def with_polling(
    watch: Path, total: int, progress: Progress, fn: Callable[[], Any], message: str = ""
) -> None:
    """Report progress from the growth of a folder, for libraries that have no callback."""
    stop = threading.Event()
    start = dir_size(watch)

    def poll() -> None:
        while not stop.wait(0.7):
            progress(min(max(dir_size(watch) - start, 0), int(total * 0.99)), total, message)

    t = threading.Thread(target=poll, daemon=True)
    t.start()
    try:
        fn()
    finally:
        stop.set()
        t.join(timeout=2)


def split_ollama_tag(tag: str) -> tuple[str, str, str]:
    """'translategemma:4b' -> ('library', 'translategemma', '4b')."""
    name, _, version = tag.partition(":")
    namespace, _, short = name.rpartition("/")
    return namespace or "library", short, version or "latest"


def ollama_manifest(tag: str, timeout: float = 20.0) -> tuple[str, int]:
    """(digest, total size of the layers) of a model in Ollama's public registry."""
    ns, name, version = split_ollama_tag(tag)
    try:
        r = httpx.get(
            f"{OLLAMA_REGISTRY}/{ns}/{name}/manifests/{version}",
            headers={"Accept": _MANIFEST},
            timeout=timeout,
            follow_redirects=True,
        )
    except httpx.HTTPError as exc:
        raise ModelError(f"Could not reach the Ollama registry: {exc}") from exc
    if r.status_code == 404:
        raise ModelError(f"'{tag}' does not exist in the Ollama registry.")
    if r.status_code != 200:
        raise ModelError(f"The Ollama registry answered {r.status_code} for '{tag}'.")
    try:
        manifest = r.json()
        size = sum(int(layer["size"]) for layer in manifest["layers"])
    except (ValueError, KeyError, TypeError) as exc:
        raise ModelError(f"The Ollama registry returned an unreadable answer for '{tag}'.") from exc
    return hashlib.sha256(r.content).hexdigest(), size


@dataclass
class Ctx:
    """Per-request context; caches the Ollama model list so one page view asks it only once."""

    settings: Settings
    _ollama: list[dict[str, Any]] | None = None
    _ollama_loaded: bool = False
    extras_cache: dict[str, Any] = field(default_factory=dict)

    @property
    def models_dir(self) -> Path:
        return self.settings.models_dir

    @property
    def hf_cache(self) -> Path:
        return self.settings.models_dir / "huggingface"

    def ollama_tags(self) -> list[dict[str, Any]] | None:
        """Installed Ollama models [{name, digest, size}], or None when Ollama is not running."""
        if not self._ollama_loaded:
            from localdub.core.translation.ollama_provider import OllamaClient

            client = OllamaClient(self.settings.ollama_url, timeout=3.0)
            try:
                self._ollama = client.tags()
            except Exception:  # noqa: BLE001 - "not running" is a normal state
                self._ollama = None
            finally:
                client.close()
            self._ollama_loaded = True
        return self._ollama


def ollama_find(tags: list[dict[str, Any]] | None, wanted: str) -> dict[str, Any] | None:
    """Ollama stores an untagged name as `name:latest`."""
    if not tags:
        return None
    want = wanted.removesuffix(":latest")
    return next((t for t in tags if str(t["name"]).removesuffix(":latest") == want), None)


# ----- handlers ------------------------------------------------------------------------------


class Handler:
    def installed(self, e: Entry, ctx: Ctx) -> bool:
        raise NotImplementedError

    def download(self, e: Entry, ctx: Ctx, progress: Progress) -> None:
        raise NotImplementedError

    def update(self, e: Entry, ctx: Ctx, progress: Progress) -> None:
        """Fetch the newest version. Default: the download is already incremental/idempotent."""
        self.download(e, ctx, progress)

    def delete(self, e: Entry, ctx: Ctx) -> None:
        raise NotDeletable("This cannot be deleted here.")

    def locations(self, e: Entry, ctx: Ctx) -> list[Path]:
        return []

    def disk_bytes(self, e: Entry, ctx: Ctx) -> int | None:
        locs = self.locations(e, ctx)
        return sum(dir_size(p) for p in locs) if locs else None

    def local_revision(self, e: Entry, ctx: Ctx) -> str | None:
        return None

    def remote_revision(self, e: Entry, ctx: Ctx) -> str | None:
        return None

    def note(self, e: Entry, ctx: Ctx) -> str | None:
        """Where the files really are, when that is not a folder we own."""
        return None


class WhisperHandler(Handler):
    PATTERNS = [
        "config.json",
        "preprocessor_config.json",
        "model.bin",
        "tokenizer.json",
        "vocabulary.*",
    ]

    def _cache(self, ctx: Ctx) -> Path:
        return ctx.models_dir / "whisper"

    def _snapshot(self, e: Entry, ctx: Ctx) -> Path | None:
        from huggingface_hub import snapshot_download

        try:
            found: str = snapshot_download(
                e.source["repo"],
                cache_dir=str(self._cache(ctx)),
                allow_patterns=self.PATTERNS,
                local_files_only=True,
            )
        except Exception:  # noqa: BLE001 - not downloaded (or incomplete)
            return None
        return Path(found)

    def installed(self, e: Entry, ctx: Ctx) -> bool:
        snap = self._snapshot(e, ctx)
        return snap is not None and is_readable(snap / "model.bin")

    def download(self, e: Entry, ctx: Ctx, progress: Progress) -> None:
        from huggingface_hub import snapshot_download

        cache = self._cache(ctx)
        repo = e.source["repo"]

        def fetch() -> None:
            snapshot_download(repo, allow_patterns=self.PATTERNS, cache_dir=str(cache))

        with_polling(cache, e.size_bytes, progress, fetch)

    def update(self, e: Entry, ctx: Ctx, progress: Progress) -> None:
        self.download(e, ctx, progress)
        prune_old_revisions(self._cache(ctx), e.source["repo"])

    def delete(self, e: Entry, ctx: Ctx) -> None:
        delete_hf_repo(self._cache(ctx), e.source["repo"])
        leftover = hf_repo_dir(self._cache(ctx), e.source["repo"])
        if leftover.exists():  # the API leaves the empty skeleton behind
            safe_rmtree(leftover, self._cache(ctx))

    def locations(self, e: Entry, ctx: Ctx) -> list[Path]:
        d = hf_repo_dir(self._cache(ctx), e.source["repo"])
        return [d] if d.exists() else []

    def local_revision(self, e: Entry, ctx: Ctx) -> str | None:
        snap = self._snapshot(e, ctx)
        return snap.name if snap else None

    def remote_revision(self, e: Entry, ctx: Ctx) -> str | None:
        from huggingface_hub import HfApi

        try:
            return str(HfApi().model_info(e.source["repo"]).sha)
        except Exception as exc:  # noqa: BLE001
            raise ModelError(f"Could not ask Hugging Face about {e.source['repo']}: {exc}") from exc


class OllamaHandler(Handler):
    def installed(self, e: Entry, ctx: Ctx) -> bool:
        return ollama_find(ctx.ollama_tags(), e.source["tag"]) is not None

    def download(self, e: Entry, ctx: Ctx, progress: Progress) -> None:
        if ctx.ollama_tags() is None:
            raise ModelError(
                "Ollama is not running. Start Ollama (or install it from ollama.com) and retry."
            )
        url = ctx.settings.ollama_url.rstrip("/") + "/api/pull"
        with (
            httpx.Client(timeout=httpx.Timeout(30.0, read=None)) as client,
            client.stream("POST", url, json={"model": e.source["tag"], "stream": True}) as resp,
        ):
            resp.raise_for_status()
            layers: dict[str, tuple[int, int]] = {}  # digest -> (completed, total)
            for line in resp.iter_lines():
                if not line:
                    continue
                msg = json.loads(line)
                if msg.get("error"):
                    raise ModelError(f"Ollama: {msg['error']}")
                if msg.get("digest") and msg.get("total"):
                    layers[str(msg["digest"])] = (int(msg.get("completed") or 0), int(msg["total"]))
                progress(
                    sum(c for c, _ in layers.values()),
                    sum(t for _, t in layers.values()),
                    str(msg.get("status", "")),
                )

    def delete(self, e: Entry, ctx: Ctx) -> None:
        from localdub.core.translation.ollama_provider import OllamaClient

        client = OllamaClient(ctx.settings.ollama_url, timeout=30.0)
        try:
            client.delete(e.source["tag"])
        except Exception as exc:  # noqa: BLE001
            raise ModelError(f"Ollama could not remove the model: {exc}") from exc
        finally:
            client.close()

    def disk_bytes(self, e: Entry, ctx: Ctx) -> int | None:
        found = ollama_find(ctx.ollama_tags(), e.source["tag"])
        return int(found["size"]) if found else None

    def note(self, e: Entry, ctx: Ctx) -> str | None:
        store = os.environ.get("OLLAMA_MODELS") or str(Path.home() / ".ollama" / "models")
        return f"Stored by Ollama in {store} (shared with every program that uses Ollama)."

    def local_revision(self, e: Entry, ctx: Ctx) -> str | None:
        found = ollama_find(ctx.ollama_tags(), e.source["tag"])
        return str(found["digest"]) if found else None

    def remote_revision(self, e: Entry, ctx: Ctx) -> str | None:
        return ollama_manifest(e.source["tag"])[0]


class FolderHandler(Handler):
    """Models that live in one folder under the models folder."""

    def folder(self, e: Entry, ctx: Ctx) -> Path:
        return Path(ctx.models_dir / e.source["dir"])

    def locations(self, e: Entry, ctx: Ctx) -> list[Path]:
        d = self.folder(e, ctx)
        return [d] if d.exists() else []

    def delete(self, e: Entry, ctx: Ctx) -> None:
        safe_rmtree(self.folder(e, ctx), ctx.models_dir)


class SupertonicHandler(FolderHandler):
    def installed(self, e: Entry, ctx: Ctx) -> bool:
        base = self.folder(e, ctx)
        onnx = list((base / "onnx").glob("*.onnx")) if (base / "onnx").is_dir() else []
        return len(onnx) >= 4 and (base / "voice_styles" / "F1.json").is_file()

    def download(self, e: Entry, ctx: Ctx, progress: Progress) -> None:
        from localdub.core.tts.supertonic_provider import SupertonicProvider

        base = self.folder(e, ctx)
        with_polling(
            base, e.size_bytes, progress,
            lambda: SupertonicProvider(model_dir=base, threads=ctx.settings.tts_threads).close(),
        )  # fmt: skip


class ParakeetHandler(FolderHandler):
    def _files(self, e: Entry) -> list[str]:
        return list(e.source["files"])

    def installed(self, e: Entry, ctx: Ctx) -> bool:
        d = self.folder(e, ctx)
        return all((d / f).is_file() and is_readable(d / f) for f in self._files(e))

    def download(self, e: Entry, ctx: Ctx, progress: Progress) -> None:
        members = {e.source["prefix"] + f: f for f in self._files(e)}
        ensure_archive_files(
            e.source["url"], e.source["sha256"], members, self.folder(e, ctx),
            progress=lambda done, total: progress(done, total or e.size_bytes, "Downloading"),
        )  # fmt: skip


class OpenVoiceHandler(FolderHandler):
    def installed(self, e: Entry, ctx: Ctx) -> bool:
        base = self.folder(e, ctx) / "converter"
        return all(is_readable(base / f) for f in ("config.json", "checkpoint.pth"))

    def download(self, e: Entry, ctx: Ctx, progress: Progress) -> None:
        with_polling(
            self.folder(e, ctx), e.size_bytes, progress, lambda: fetch_in_subprocess("cloning")
        )


class DiarizationHandler(Handler):
    def _models(self) -> tuple[Any, Any]:
        from localdub.core.diarize.sherpa_diarizer import EMBEDDING, SEGMENTATION

        return SEGMENTATION, EMBEDDING

    def installed(self, e: Entry, ctx: Ctx) -> bool:
        return all(
            (ctx.models_dir / m.dest).is_file() and is_readable(ctx.models_dir / m.dest)
            for m in self._models()
        )

    def download(self, e: Entry, ctx: Ctx, progress: Progress) -> None:
        sizes = [6_958_444, 39_593_761]
        total = sum(sizes)
        before = 0
        for model, size in zip(self._models(), sizes, strict=True):

            def on_bytes(done: int, _total: int, offset: int = before) -> None:
                progress(offset + done, total, "")

            ensure_model(model, ctx.models_dir, progress=on_bytes)
            before += size

    def locations(self, e: Entry, ctx: Ctx) -> list[Path]:
        d = ctx.models_dir / "diarization"
        return [d] if d.exists() else []

    def delete(self, e: Entry, ctx: Ctx) -> None:
        for m in self._models():
            (ctx.models_dir / m.dest).unlink(missing_ok=True)
        d = ctx.models_dir / "diarization"
        if d.is_dir() and not any(d.iterdir()):
            d.rmdir()


class DemucsHandler(Handler):
    def installed(self, e: Entry, ctx: Ctx) -> bool:
        from huggingface_hub import try_to_load_from_cache

        return all(
            isinstance(try_to_load_from_cache(e.source["repo"], f, cache_dir=ctx.hf_cache), str)
            for f in e.source["files"]
        )

    def download(self, e: Entry, ctx: Ctx, progress: Progress) -> None:
        with_polling(
            ctx.hf_cache, e.size_bytes, progress, lambda: fetch_in_subprocess("separation")
        )

    def delete(self, e: Entry, ctx: Ctx) -> None:
        delete_hf_repo(ctx.hf_cache, e.source["repo"])
        leftover = hf_repo_dir(ctx.hf_cache, e.source["repo"])
        if leftover.exists():
            safe_rmtree(leftover, ctx.hf_cache)

    def locations(self, e: Entry, ctx: Ctx) -> list[Path]:
        d = hf_repo_dir(ctx.hf_cache, e.source["repo"])
        return [d] if d.exists() else []


class YoutubeHandler(Handler):
    def installed(self, e: Entry, ctx: Ctx) -> bool:
        return youtube_tools.is_installed()

    def download(self, e: Entry, ctx: Ctx, progress: Progress) -> None:
        youtube_tools.install(progress)

    def locations(self, e: Entry, ctx: Ctx) -> list[Path]:
        d = youtube_tools.tools_dir()
        return [d] if d.exists() else []

    def delete(self, e: Entry, ctx: Ctx) -> None:
        d = youtube_tools.tools_dir()
        removed = False
        for name in ("yt-dlp.exe", "deno.exe"):
            f = d / name
            if f.is_file() and not is_link(f):
                f.unlink()
                removed = True
        if not removed:
            raise NotDeletable(
                "These tools were not installed by LocalDub, so it will not remove them."
            )


class PackagesHandler(Handler):
    def installed(self, e: Entry, ctx: Ctx) -> bool:
        return extras.packages_available()

    def download(self, e: Entry, ctx: Ctx, progress: Progress) -> None:
        extras.install(progress)

    def locations(self, e: Entry, ctx: Ctx) -> list[Path]:
        d = extras.extras_dir()
        return [d] if d.exists() else []

    def delete(self, e: Entry, ctx: Ctx) -> None:
        folder = extras.extras_dir()
        if (folder / extras.COMPLETE).is_file() is False and not folder.exists():
            raise NotDeletable("The optional packages were not installed by LocalDub.")
        safe_rmtree(folder, folder.parent)
        for leftover in ("-download", "-new", "-old"):
            safe_rmtree(folder.parent / (folder.name + leftover), folder.parent)


def fetch_in_subprocess(model_id: str) -> None:
    """Download a PyTorch-based model in a child process: the app window never imports torch."""
    flags = 0x08000000 if sys.platform == "win32" else 0  # CREATE_NO_WINDOW
    proc = subprocess.run(  # noqa: S603 - our own module, list arguments, no shell
        [sys.executable, "-m", "localdub.core.model_fetch", model_id],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        creationflags=flags, check=False,
    )  # fmt: skip
    if proc.returncode != 0:
        tail = "\n".join((proc.stderr or proc.stdout).strip().splitlines()[-6:])
        raise ModelError(f"The download process failed (exit code {proc.returncode}):\n{tail}")


HANDLERS: dict[str, Handler] = {
    "whisper": WhisperHandler(),
    "ollama": OllamaHandler(),
    "parakeet": ParakeetHandler(),
    "supertonic": SupertonicHandler(),
    "diarization": DiarizationHandler(),
    "demucs": DemucsHandler(),
    "openvoice": OpenVoiceHandler(),
    "youtube": YoutubeHandler(),
    "packages": PackagesHandler(),
}

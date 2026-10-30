"""The AI models the app needs: what they are, whether they are installed, how to download them.

Downloads happen inside the app, under the user's own account, with visible progress (never in an
elevated installer: files written by an elevated process can be unreadable for the normal user).
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from localdub import extras
from localdub.config import Settings
from localdub.core.models import ensure_model, is_readable

log = logging.getLogger(__name__)

# (bytes done, bytes total or 0, message)
Progress = Callable[[int, int, str], None]


@dataclass(frozen=True)
class ModelSpec:
    id: str
    title: str
    description: str
    size_bytes: int  # approximate, used for the progress bar
    required: bool
    group: str  # "core" | "diarization" | "separation" | "cloning"


SPECS: list[ModelSpec] = [
    ModelSpec("whisper", "Speech recognition (faster-whisper large-v3)",
              "Turns the English speech into text with timestamps. Hugging Face.",
              3_090_000_000, True, "core"),
    ModelSpec("supertonic", "Slovak voice (Supertonic 3)",
              "Generates the Slovak speech, 10 voices. Hugging Face.",
              400_000_000, True, "core"),
    ModelSpec("translation", "Translation model (Ollama)",
              "Translates English to Slovak. Downloaded by Ollama from its registry.",
              3_300_000_000, True, "core"),
    ModelSpec("diarization", "Speaker detection",
              "Tells speakers apart (experimental). GitHub, checksum-verified.",
              46_000_000, False, "diarization"),
    ModelSpec("packages", "Optional packages (PyTorch and Demucs)",
              "Program libraries (not an AI model) that speech removal and voice cloning need. "
              "Installed into your user folder; no administrator rights needed.",
              2_900_000_000, False, "packages"),
    ModelSpec("separation", "Speech and music separation (htdemucs)",
              "Removes the original speech but keeps music (experimental, needs the optional "
              "PyTorch packages). Hugging Face.", 80_000_000, False, "separation"),
    ModelSpec("cloning", "Voice cloning (OpenVoice V2)",
              "Makes the Slovak voice sound like the original speaker (experimental, needs the "
              "optional PyTorch packages). Hugging Face.", 131_000_000, False, "cloning"),
]  # fmt: skip
BY_ID = {s.id: s for s in SPECS}


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


def optional_packages_available() -> bool:
    return extras.packages_available()


def _whisper_repo(settings: Settings) -> str:
    from faster_whisper.utils import _MODELS

    return str(_MODELS.get(settings.asr_model, f"Systran/faster-whisper-{settings.asr_model}"))


def ollama_models(settings: Settings, timeout: float = 3.0) -> list[str] | None:
    """Installed Ollama models, or None if Ollama is not reachable."""
    from localdub.core.translation.ollama_provider import OllamaClient

    client = OllamaClient(settings.ollama_url, timeout=timeout)
    try:
        return client.list_models()
    except Exception:  # noqa: BLE001
        return None
    finally:
        client.close()


def has_ollama_model(installed: list[str], wanted: str) -> bool:
    """Ollama stores untagged names as `name:latest`."""
    names = {m.removesuffix(":latest") for m in installed}
    return wanted.removesuffix(":latest") in names


def is_installed(spec: ModelSpec, settings: Settings) -> bool:
    d = settings.models_dir
    if spec.id == "whisper":
        from faster_whisper.utils import download_model

        try:
            path = Path(download_model(settings.asr_model, local_files_only=True,
                                       cache_dir=str(d / "whisper")))  # fmt: skip
        except Exception:  # noqa: BLE001
            return False
        return is_readable(path / "model.bin")
    if spec.id == "packages":
        return extras.packages_available()
    if spec.id == "supertonic":
        base = d / settings.tts_model.replace("-", "")
        onnx = list((base / "onnx").glob("*.onnx")) if (base / "onnx").is_dir() else []
        return len(onnx) >= 4 and (base / "voice_styles" / "F1.json").is_file()
    if spec.id == "translation":
        models = ollama_models(settings)
        return models is not None and has_ollama_model(models, settings.translation_model)
    if spec.id == "diarization":
        from localdub.core.diarize.sherpa_diarizer import EMBEDDING, SEGMENTATION

        return all(
            (d / m.dest).is_file() and is_readable(d / m.dest) for m in (SEGMENTATION, EMBEDDING)
        )
    if spec.id == "separation":
        from huggingface_hub import try_to_load_from_cache

        return all(
            isinstance(try_to_load_from_cache("adefossez/HTDemucs", f), str)
            for f in ("htdemucs.yaml", "955717e8.safetensors")
        )
    if spec.id == "cloning":
        base = d / "openvoice" / "converter"
        return all(is_readable(base / f) for f in ("config.json", "checkpoint.pth"))
    return False


def _poll(
    watch: Path, start_size: int, total: int, progress: Progress, stop: threading.Event
) -> None:
    """Report progress from the growth of a download folder (for libraries without callbacks)."""
    while not stop.wait(0.7):
        done = max(_dir_size(watch) - start_size, 0)
        progress(min(done, int(total * 0.99)), total, "")


def _with_polling(watch: Path, spec: ModelSpec, progress: Progress, fn: Callable[[], Any]) -> None:
    stop = threading.Event()
    start = _dir_size(watch)
    t = threading.Thread(
        target=_poll, args=(watch, start, spec.size_bytes, progress, stop), daemon=True
    )
    t.start()
    try:
        fn()
    finally:
        stop.set()
        t.join(timeout=2)


def download(spec: ModelSpec, settings: Settings, progress: Progress) -> None:
    """Download one model (blocking). Raises on failure."""
    d = settings.models_dir
    d.mkdir(parents=True, exist_ok=True)
    progress(0, spec.size_bytes, "Starting...")
    if spec.id == "whisper":
        from huggingface_hub import snapshot_download

        cache = d / "whisper"
        patterns = [
            "config.json",
            "preprocessor_config.json",
            "model.bin",
            "tokenizer.json",
            "vocabulary.*",
        ]
        _with_polling(cache, spec, progress, lambda: snapshot_download(
            _whisper_repo(settings), allow_patterns=patterns, cache_dir=str(cache)))  # fmt: skip
    elif spec.id == "supertonic":
        from localdub.core.tts.supertonic_provider import SupertonicProvider

        base = d / settings.tts_model.replace("-", "")

        def fetch() -> None:
            SupertonicProvider(model_dir=base, threads=settings.tts_threads).close()

        _with_polling(base, spec, progress, fetch)
    elif spec.id == "translation":
        _pull_ollama(settings, progress)
    elif spec.id == "diarization":
        from localdub.core.diarize.sherpa_diarizer import EMBEDDING, SEGMENTATION

        sizes = [6_958_444, 39_593_761]
        total = sum(sizes)
        done_before = 0
        for model, size in zip((SEGMENTATION, EMBEDDING), sizes, strict=True):

            def on_bytes(done: int, _total: int, offset: int = done_before) -> None:
                progress(offset + done, total, "")

            ensure_model(model, d, progress=on_bytes)
            done_before += size
    elif spec.id == "packages":
        extras.install(progress)
    elif spec.id == "separation":
        hub = Path.home() / ".cache" / "huggingface" / "hub"
        _with_polling(hub, spec, progress, lambda: _fetch_in_subprocess(spec.id))
    elif spec.id == "cloning":
        _with_polling(d / "openvoice", spec, progress, lambda: _fetch_in_subprocess(spec.id))
    else:
        raise ValueError(f"Unknown model {spec.id}")
    if not is_installed(spec, settings):
        raise RuntimeError(f"{spec.title} was downloaded but is not usable; see the log")
    if spec.id != "packages":  # the package installer reports its own final state
        progress(spec.size_bytes, spec.size_bytes, "Done")


def _fetch_in_subprocess(model_id: str) -> None:
    """Download a PyTorch-based model in a child process: the app window never imports torch."""
    import subprocess
    import sys

    flags = 0x08000000 if sys.platform == "win32" else 0  # CREATE_NO_WINDOW
    proc = subprocess.run(  # noqa: S603 - our own module, list arguments, no shell
        [sys.executable, "-m", "localdub.core.model_fetch", model_id],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=flags,
        check=False,
    )
    if proc.returncode != 0:
        tail = "\n".join((proc.stderr or proc.stdout).strip().splitlines()[-6:])
        raise RuntimeError(f"The download process failed (exit code {proc.returncode}):\n{tail}")


def _pull_ollama(settings: Settings, progress: Progress) -> None:
    """`ollama pull` through its HTTP API, with byte-level progress."""
    import json

    if ollama_models(settings) is None:
        raise RuntimeError(
            "Ollama is not running. Start Ollama (or install it from ollama.com), then try again."
        )
    url = settings.ollama_url.rstrip("/") + "/api/pull"
    with (
        httpx.Client(timeout=httpx.Timeout(30.0, read=None)) as client,
        client.stream(
            "POST", url, json={"model": settings.translation_model, "stream": True}
        ) as resp,
    ):
        resp.raise_for_status()
        layers: dict[str, tuple[int, int]] = {}  # digest -> (completed, total)
        for line in resp.iter_lines():
            if not line:
                continue
            msg = json.loads(line)
            if msg.get("error"):
                raise RuntimeError(f"Ollama: {msg['error']}")
            if msg.get("digest") and msg.get("total"):
                layers[str(msg["digest"])] = (int(msg.get("completed") or 0), int(msg["total"]))
            progress(
                sum(c for c, _ in layers.values()),
                sum(t for _, t in layers.values()),
                str(msg.get("status", "")),
            )


class Downloads:
    """Runs model downloads one at a time in a background thread and exposes their progress."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._lock = threading.Lock()
        self._state: dict[str, dict[str, Any]] = {}
        self._queue: list[str] = []
        self._thread: threading.Thread | None = None

    def state(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            return {k: dict(v) for k, v in self._state.items()}

    def busy(self) -> bool:
        with self._lock:
            return any(v["status"] in ("queued", "running") for v in self._state.values())

    def start(self, ids: list[str]) -> None:
        with self._lock:
            for i in ids:
                if self._state.get(i, {}).get("status") in ("queued", "running"):
                    continue
                self._state[i] = {
                    "status": "queued",
                    "done": 0,
                    "total": BY_ID[i].size_bytes,
                    "message": "Waiting",
                    "error": None,
                    "show_bytes": True,
                }
                self._queue.append(i)
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(
                    target=self._run, name="model-downloads", daemon=True
                )
                self._thread.start()

    def _set(self, model_id: str, **fields: Any) -> None:
        with self._lock:
            self._state[model_id].update(fields)

    def _run(self) -> None:
        while True:
            with self._lock:
                if not self._queue:
                    return
                model_id = self._queue.pop(0)
            spec = BY_ID[model_id]
            self._set(
                model_id,
                status="running",
                message="Starting...",
                error=None,
                started=time.time(),
                # The package install reports percent plus a text, not bytes: its total includes an
                # estimate of the unpacking work, so "X GB of Y GB" would be misleading.
                show_bytes=spec.id != "packages",
            )

            def progress(done: int, total: int, message: str, mid: str = model_id) -> None:
                fields: dict[str, Any] = {"done": done, "total": total or BY_ID[mid].size_bytes}
                if message:
                    fields["message"] = message
                self._set(mid, **fields)

            try:
                download(spec, self.settings, progress)
                self._set(model_id, status="done", message="Installed")
            except Exception as exc:  # noqa: BLE001 - shown to the user
                log.exception("Download of %s failed", model_id)
                self._set(
                    model_id, status="error", error=f"{type(exc).__name__}: {exc}", message="Failed"
                )

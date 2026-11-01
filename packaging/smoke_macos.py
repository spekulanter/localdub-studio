"""Checks run by the macOS CI job against the finished app, with the app's own Python.

    <app>/Contents/Resources/python/bin/python3 packaging/smoke_macos.py <check>

where <check> is imports, ffmpeg, youtube, extras or asr.

Each check prints what it found and exits non-zero when something is wrong.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

TINY = ("mlx-community/whisper-tiny.en-mlx", "5f4dafbb28e62a53c1b10426ff7eed36ca733bf7")


def imports() -> None:
    import importlib

    for name in (
        "localdub", "fastapi", "uvicorn", "webview", "sherpa_onnx", "ctranslate2", "faster_whisper",
        "supertonic", "mlx.core", "mlx_whisper", "torch", "AppKit", "WebKit",
    ):  # fmt: skip
        mod = importlib.import_module(name)
        print(f"ok  {name} {getattr(mod, '__version__', '')}")
    from localdub.core.modelmgr.catalog import load_catalog

    cat = load_catalog()
    assert cat.default_of("asr").id == "whisper-large-v3-mlx", cat.default_of("asr")  # type: ignore[union-attr]
    assert cat.default_of("ffmpeg") is not None
    print("catalogue for this Mac:", [e.id for e in cat.entries if e.role in ("asr", "ffmpeg")])
    from localdub.core.modelmgr import hardware

    gpu = hardware.detect_gpu()
    print("gpu:", gpu)
    assert gpu is not None and gpu.unified, "Apple Silicon was not detected"


def ffmpeg() -> None:
    from localdub.core.media import ffmpeg_tools

    with tempfile.TemporaryDirectory() as tmp:
        os.environ[ffmpeg_tools.TOOLS_ENV] = tmp
        ffmpeg_tools.install(lambda d, t, m: None)
        for name, path in ffmpeg_tools.managed_paths().items():
            out = subprocess.run(  # noqa: S603
                [str(path), "-version"], capture_output=True, text=True, check=True
            )
            print(name, "->", out.stdout.splitlines()[0])
        assert ffmpeg_tools.managed_installed()


def youtube() -> None:
    from localdub.core.youtube import tools

    with tempfile.TemporaryDirectory() as tmp:
        os.environ[tools.TOOLS_ENV] = tmp
        tools.install(lambda d, t, m: None)
        for key, info in tools.status().items():
            print(key, info)
            assert info.available, info


def extras() -> None:
    from localdub import extras as ex

    uv = ex.find_uv()
    print("uv:", uv)
    assert uv is not None and uv.is_file()
    plan = ex.build_plan(uv=uv)
    print("optional packages:", ", ".join(f"{w.name} {w.version}" for w in plan))
    assert any(w.name == "demucs" for w in plan)
    assert not any(w.name == "torch" for w in plan), "torch is already part of the app on a Mac"


def asr() -> None:
    """Whisper tiny through the same provider the app uses, on the processor (CI has no GPU)."""
    from huggingface_hub import snapshot_download

    from localdub.core.asr.mlx_whisper_provider import MlxWhisperProvider
    from localdub.core.media import ffmpeg_tools

    with tempfile.TemporaryDirectory() as tmp_name:
        tmp = Path(tmp_name)
        os.environ[ffmpeg_tools.TOOLS_ENV] = str(tmp / "tools")
        ffmpeg_tools.install(lambda d, t, m: None)
        aiff, wav = tmp / "say.aiff", tmp / "say.wav"
        text = "Hello. This is a short test of the local dubbing studio."
        subprocess.run(["say", "-o", str(aiff), text], check=True)  # noqa: S603,S607
        subprocess.run(  # noqa: S603
            [str(ffmpeg_tools.managed_paths()["ffmpeg"]), "-y", "-i", str(aiff), "-ar", "16000",
             "-ac", "1", str(wav)],
            check=True, capture_output=True,
        )  # fmt: skip
        root = tmp / "whisper"
        snapshot_download(TINY[0], revision=TINY[1], cache_dir=str(root))
        provider = MlxWhisperProvider(TINY[0], TINY[1], "tiny.en", root, device="cpu")
        t0 = time.perf_counter()
        res = provider.transcribe(wav, "en")
        spoken = "".join(w.text for w in res.words).lower()
        print(f"{time.perf_counter() - t0:.1f}s on {res.engine}: {spoken}")
        provider.close()
        assert len(res.words) >= 6 and "test" in spoken, spoken
        assert all(w.end >= w.start for w in res.words)


CHECKS = {"imports": imports, "ffmpeg": ffmpeg, "youtube": youtube, "extras": extras, "asr": asr}

if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in CHECKS:
        raise SystemExit(f"usage: smoke_macos.py {'|'.join(CHECKS)}")
    CHECKS[sys.argv[1]]()
    print("OK")

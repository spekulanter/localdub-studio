"""Environment report: tools, GPU, runtimes and local model servers."""

from __future__ import annotations

import platform
import shutil
import sys
from typing import Any

from localdub.config import Settings
from localdub.core.media.ffmpeg import FFmpeg, MediaError, run_tool


def environment_report(settings: Settings) -> dict[str, Any]:
    rep: dict[str, Any] = {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "executable": sys.executable,
    }

    try:
        ff = FFmpeg(settings.ffmpeg_path, settings.ffprobe_path)
        rep["ffmpeg"] = {
            "path": str(ff.ffmpeg),
            "version": ff.version(),
            "rubberband": ff.has_filter("rubberband"),
        }
    except MediaError as exc:
        rep["ffmpeg"] = {"error": str(exc)}

    smi = shutil.which("nvidia-smi")
    if smi:
        q = "name,driver_version,compute_cap,memory.total,memory.used"
        out = run_tool([smi, f"--query-gpu={q}", "--format=csv,noheader"], check=False).stdout
        rep["nvidia_smi"] = out.strip()
    else:
        rep["nvidia_smi"] = "not found"

    try:
        from localdub.core.gpu import register_cuda_dlls

        register_cuda_dlls()
        import ctranslate2

        n = ctranslate2.get_cuda_device_count()
        rep["ctranslate2"] = {
            "version": ctranslate2.__version__,
            "cuda_devices": n,
            "cuda_compute_types": sorted(ctranslate2.get_supported_compute_types("cuda"))
            if n
            else [],
        }
    except Exception as exc:  # noqa: BLE001 - diagnostics must never crash
        rep["ctranslate2"] = {"error": f"{type(exc).__name__}: {exc}"}

    try:
        import onnxruntime

        rep["onnxruntime"] = {
            "version": onnxruntime.__version__,
            "providers": onnxruntime.get_available_providers(),
        }
    except Exception as exc:  # noqa: BLE001
        rep["onnxruntime"] = {"error": str(exc)}

    from localdub.core.translation.ollama_provider import OllamaClient, OllamaError

    client = OllamaClient(settings.ollama_url, timeout=5)
    try:
        rep["ollama"] = {"url": settings.ollama_url, "models": client.list_models()}
    except OllamaError as exc:
        rep["ollama"] = {"url": settings.ollama_url, "error": str(exc)}
    finally:
        client.close()
    return rep

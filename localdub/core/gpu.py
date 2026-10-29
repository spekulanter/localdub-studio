"""GPU helpers: CUDA DLL discovery on Windows and memory release between stages."""

from __future__ import annotations

import gc
import logging
import os
import sys
from pathlib import Path

log = logging.getLogger(__name__)

_registered = False


def register_cuda_dlls() -> list[Path]:
    """Make the cuBLAS/cuDNN DLLs from the nvidia-* wheels loadable by CTranslate2.

    CTranslate2 loads cuDNN lazily via LoadLibrary, so the directories must be on PATH
    as well as registered with os.add_dll_directory.
    """
    global _registered
    if sys.platform != "win32" or _registered:
        return []
    try:
        import nvidia
    except ImportError:
        log.warning("nvidia-* CUDA wheels not installed; relying on system CUDA libraries")
        return []

    dirs: list[Path] = []
    for root in getattr(nvidia, "__path__", []):
        for bin_dir in sorted(Path(root).glob("*/bin")):
            if any(bin_dir.glob("*.dll")):
                dirs.append(bin_dir)
    for d in dirs:
        os.add_dll_directory(str(d))
    os.environ["PATH"] = os.pathsep.join([*map(str, dirs), os.environ.get("PATH", "")])
    _registered = True
    log.debug("Registered CUDA DLL directories: %s", dirs)
    return dirs


def release_memory() -> None:
    """Drop Python references to freed models; CTranslate2 frees VRAM on object deletion."""
    gc.collect()

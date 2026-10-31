"""What this computer has, and whether a model will be comfortable on it."""

from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from localdub.core.modelmgr.catalog import Requirements

CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


@dataclass(frozen=True)
class Gpu:
    name: str
    vram_total_mb: int
    vram_free_mb: int
    driver: str

    @property
    def vram_gb(self) -> float:
        return self.vram_total_mb / 1024


@dataclass(frozen=True)
class Hardware:
    gpu: Gpu | None
    ram_gb: float | None
    cpu_threads: int
    disk_free_bytes: int
    disk_total_bytes: int


_gpu_cache: tuple[float, Gpu | None] | None = None


def _smi() -> str | None:
    found = shutil.which("nvidia-smi")
    if found:
        return found
    fallback = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "nvidia-smi.exe"
    return str(fallback) if fallback.is_file() else None


def parse_smi(output: str) -> Gpu | None:
    """First GPU of `nvidia-smi --query-gpu=name,memory.total,memory.free,driver_version`."""
    for line in output.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 4:
            try:
                return Gpu(parts[0], int(float(parts[1])), int(float(parts[2])), parts[3])
            except ValueError:
                continue
    return None


def detect_gpu(max_age_s: float = 20.0) -> Gpu | None:
    global _gpu_cache
    now = time.monotonic()
    if _gpu_cache is not None and now - _gpu_cache[0] < max_age_s:
        return _gpu_cache[1]
    gpu: Gpu | None = None
    smi = _smi()
    if smi:
        try:
            proc = subprocess.run(  # noqa: S603 - a program we located, list arguments, no shell
                [smi, "--query-gpu=name,memory.total,memory.free,driver_version",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15,
                creationflags=CREATE_NO_WINDOW, stdin=subprocess.DEVNULL, check=False,
            )  # fmt: skip
            gpu = parse_smi(proc.stdout) if proc.returncode == 0 else None
        except (OSError, subprocess.TimeoutExpired):
            gpu = None
    _gpu_cache = (now, gpu)
    return gpu


def detect_ram_gb() -> float | None:
    if sys.platform == "win32":

        class _Mem(ctypes.Structure):
            _fields_ = [  # noqa: RUF012
                ("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]  # fmt: skip

        mem = _Mem()
        mem.dwLength = ctypes.sizeof(_Mem)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(mem)):  # type: ignore[attr-defined,unused-ignore]
            return float(round(mem.ullTotalPhys / 1024**3, 1))
        return None
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal:"):
                return float(round(int(line.split()[1]) / 1024**2, 1))
    except (OSError, ValueError):
        pass
    return None


def detect(models_dir: Path) -> Hardware:
    probe = models_dir
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    usage = shutil.disk_usage(probe)
    return Hardware(
        gpu=detect_gpu(),
        ram_gb=detect_ram_gb(),
        cpu_threads=os.cpu_count() or 1,
        disk_free_bytes=usage.free,
        disk_total_bytes=usage.total,
    )


CPU_TEXT = "Runs on the processor; the graphics card stays free."
NO_GPU_TEXT = "No NVIDIA graphics card was found, so this runs on the processor, much slower."
_SK = {
    CPU_TEXT: "Beží na procesore; grafická karta zostane voľná.",
    NO_GPU_TEXT: "Nenašla sa grafická karta NVIDIA, takže to beží na procesore, oveľa pomalšie.",
}


def fits(req: Requirements, hw: Hardware, lang: str = "en") -> dict[str, Any]:
    """How comfortably the model runs here: level + a sentence for the user."""
    sk = lang == "sk"
    if req.runs_on == "cpu" or req.vram_gb is None:
        text = CPU_TEXT
        return {"level": "cpu", "text": _SK[text] if sk else text}
    if hw.gpu is None:
        text = NO_GPU_TEXT
        return {"level": "no_gpu", "text": _SK[text] if sk else text}
    have, want = hw.gpu.vram_gb, req.vram_gb
    if have >= want:
        text = (
            f"Sedí vašej grafickej karte ({have:.0f} GB; potrebuje asi {want:g} GB)."
            if sk
            else f"Fits your graphics card ({have:.0f} GB; about {want:g} GB wanted)."
        )
        return {"level": "ok", "text": text}
    if have >= want * 0.5:
        text = (
            f"Chce asi {want:g} GB pamäte grafickej karty, vy máte {have:.0f} GB: časť pobeží na "
            "procesore, citeľne pomalšie."
            if sk
            else f"Wants about {want:g} GB of graphics memory, you have {have:.0f} GB: "
            "part of it will run on the processor, noticeably slower."
        )
        return {"level": "partial", "text": text}
    text = (
        f"Chce asi {want:g} GB pamäte grafickej karty, vy máte {have:.0f} GB: bude to veľmi pomalé."
        if sk
        else f"Wants about {want:g} GB of graphics memory, you have {have:.0f} GB: "
        "it would be very slow."
    )
    return {"level": "too_big", "text": text}

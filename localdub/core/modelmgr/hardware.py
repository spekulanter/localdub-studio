"""What this computer has, and whether a model will be comfortable on it."""

from __future__ import annotations

import ctypes
import os
import platform
import re
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
    unified: bool = False  # Apple Silicon: the GPU shares the Mac's memory
    vendor: str = "nvidia"  # nvidia | apple | amd | intel | other

    @property
    def vram_gb(self) -> float:
        return self.vram_total_mb / 1024

    @property
    def cuda(self) -> bool:
        """Speech recognition, separation and voice cloning use only NVIDIA (CUDA) or Apple."""
        return self.vendor in ("nvidia", "apple")


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


def _sysctl(key: str) -> str | None:
    try:
        proc = subprocess.run(  # noqa: S603 - fixed system tool, list arguments, no shell
            ["sysctl", "-n", key],  # noqa: S607
            capture_output=True, text=True, timeout=10, stdin=subprocess.DEVNULL, check=False,
        )  # fmt: skip
    except (OSError, subprocess.TimeoutExpired):
        return None
    return proc.stdout.strip() if proc.returncode == 0 else None


def apple_gpu(chip: str | None, memory_bytes: int | None) -> Gpu | None:
    """The GPU of an Apple Silicon Mac. It has no memory of its own: Metal lets it use about two
    thirds of the Mac's memory on small machines and three quarters on big ones."""
    if not chip or not chip.startswith("Apple") or not memory_bytes:
        return None
    total_mb = memory_bytes // 1024**2
    usable = int(total_mb * (0.67 if memory_bytes <= 36 * 1024**3 else 0.75))
    return Gpu(f"{chip} (GPU)", usable, usable, "Metal", unified=True, vendor="apple")


# Windows keeps one registry key per display adapter under this device class.
DISPLAY_CLASS = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
VENDOR_IDS = {"10de": "nvidia", "1002": "amd", "1022": "amd", "8086": "intel"}


def _as_int(value: Any) -> int | None:
    """A registry number: REG_DWORD/REG_QWORD come as int, some drivers write REG_BINARY."""
    if isinstance(value, int):
        return value
    if isinstance(value, bytes | bytearray) and 0 < len(value) <= 8:
        return int.from_bytes(value, "little")
    return None


def adapter_from_values(values: dict[str, Any]) -> Gpu | None:
    """One display adapter from the values of its registry key (None: not a real graphics card)."""
    name = str(values.get("DriverDesc") or "").strip()
    match = re.search(r"ven_([0-9a-f]{4})", str(values.get("MatchingDeviceId") or ""), re.I)
    # software adapters (Basic Display, remote desktop) have no PCI vendor id
    if not name or match is None:
        return None
    memory = _as_int(values.get("HardwareInformation.qwMemorySize"))
    if not memory:  # the 32-bit value tops out at 4 GB, so it is only the fallback
        memory = _as_int(values.get("HardwareInformation.MemorySize")) or 0
    mb = memory // 1024**2
    vendor = VENDOR_IDS.get(match.group(1).lower(), "other")
    # Free memory cannot be read without the vendor's tools; the total is the best guess.
    return Gpu(name, mb, mb, str(values.get("DriverVersion") or ""), vendor=vendor)


def pick_adapter(adapters: list[Gpu]) -> Gpu | None:
    """The card a model would use: the one with the most graphics memory."""
    return max(adapters, key=lambda g: g.vram_total_mb, default=None)


def windows_adapters() -> list[Gpu]:
    """Every display adapter Windows knows about, from any maker (no vendor tools needed)."""
    if sys.platform != "win32":
        return []
    import winreg

    found: list[Gpu] = []
    try:
        root = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, DISPLAY_CLASS)
    except OSError:
        return []
    with root:
        for i in range(64):
            try:
                sub = winreg.EnumKey(root, i)
            except OSError:
                break
            if not sub.isdigit():  # "Configuration", "Properties"
                continue
            values: dict[str, Any] = {}
            try:
                with winreg.OpenKey(root, sub) as key:
                    for j in range(256):
                        try:
                            name, value, _ = winreg.EnumValue(key, j)
                        except OSError:
                            break
                        values[name] = value
            except OSError:
                continue
            gpu = adapter_from_values(values)
            if gpu is not None:
                found.append(gpu)
    return found


def detect_gpu(max_age_s: float = 20.0) -> Gpu | None:
    global _gpu_cache
    now = time.monotonic()
    if _gpu_cache is not None and now - _gpu_cache[0] < max_age_s:
        return _gpu_cache[1]
    gpu: Gpu | None = None
    if sys.platform == "darwin":
        mem = _sysctl("hw.memsize")
        gpu = apple_gpu(
            _sysctl("machdep.cpu.brand_string") if platform.machine() == "arm64" else None,
            int(mem) if mem and mem.isdigit() else None,
        )
        _gpu_cache = (now, gpu)
        return gpu
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
    if gpu is None:  # no NVIDIA card: an AMD or Intel one still matters (Ollama can use AMD)
        gpu = pick_adapter([g for g in windows_adapters() if g.vendor != "nvidia"])
    _gpu_cache = (now, gpu)
    return gpu


def detect_ram_gb() -> float | None:
    if sys.platform == "darwin":
        mem = _sysctl("hw.memsize")
        return float(round(int(mem) / 1024**3, 1)) if mem and mem.isdigit() else None
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
NO_APPLE_GPU_TEXT = (
    "This Mac has no Apple Silicon chip, so this runs on the processor, much slower."
)
_SK = {
    NO_APPLE_GPU_TEXT: (
        "Tento Mac nemá čip Apple Silicon, takže to beží na procesore, oveľa pomalšie."
    ),
    CPU_TEXT: "Beží na procesore; grafická karta zostane voľná.",
    NO_GPU_TEXT: "Nenašla sa grafická karta NVIDIA, takže to beží na procesore, oveľa pomalšie.",
}


def fits(req: Requirements, hw: Hardware, lang: str = "en", ollama: bool = False) -> dict[str, Any]:
    """How comfortably the model runs here: level + a sentence for the user.

    `ollama`: the model runs in Ollama, which can also use AMD cards; everything else here uses
    only NVIDIA (CUDA) or Apple Silicon.
    """
    sk = lang == "sk"
    if req.runs_on == "cpu" or req.vram_gb is None:
        text = CPU_TEXT
        return {"level": "cpu", "text": _SK[text] if sk else text}
    if hw.gpu is None:
        text = NO_APPLE_GPU_TEXT if sys.platform == "darwin" else NO_GPU_TEXT
        return {"level": "no_gpu", "text": _SK[text] if sk else text}
    amd_ollama = ollama and hw.gpu.vendor == "amd"
    if not hw.gpu.cuda and not amd_ollama:
        name = hw.gpu.name
        text = (
            f"Používa len karty NVIDIA; s kartou {name} to beží na procesore, oveľa pomalšie."
            if sk
            else f"Uses NVIDIA cards only; with {name} it runs on the processor, much slower."
        )
        return {"level": "needs_nvidia", "text": text}
    have, want = hw.gpu.vram_gb, req.vram_gb
    mac = hw.gpu.unified
    caveat = ""
    if amd_ollama:
        caveat = (
            " Ollama ju použije, ak túto kartu AMD podporuje (Radeon RX 6000 a novšie);"
            " inak to beží na procesore."
            if sk
            else " Ollama uses it if it supports this AMD card (Radeon RX 6000 and newer);"
            " otherwise it runs on the processor."
        )
    if have >= want:
        if sk:
            text = (
                f"Sedí vášmu Macu ({have:.0f} GB použiteľných pre GPU; potrebuje asi {want:g} GB)."
                if mac
                else f"Sedí vašej grafickej karte ({have:.0f} GB; potrebuje asi {want:g} GB)."
            )
        elif mac:
            text = f"Fits your Mac ({have:.0f} GB usable by the GPU; about {want:g} GB wanted)."
        else:
            text = f"Fits your graphics card ({have:.0f} GB; about {want:g} GB wanted)."
        return {"level": "ok", "text": text + caveat}
    what_sk = "pamäte Macu pre GPU" if mac else "pamäte grafickej karty"
    what_en = "usable Mac memory" if mac else "graphics memory"
    if have >= want * 0.5:
        text = (
            f"Chce asi {want:g} GB {what_sk}, vy máte {have:.0f} GB: časť pobeží na "
            "procesore, citeľne pomalšie."
            if sk
            else f"Wants about {want:g} GB of {what_en}, you have {have:.0f} GB: "
            "part of it will run on the processor, noticeably slower."
        )
        return {"level": "partial", "text": text + caveat}
    text = (
        f"Chce asi {want:g} GB {what_sk}, vy máte {have:.0f} GB: bude to veľmi pomalé."
        if sk
        else f"Wants about {want:g} GB of {what_en}, you have {have:.0f} GB: "
        "it would be very slow."
    )
    return {"level": "too_big", "text": text}

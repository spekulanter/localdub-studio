"""OS-specific process setup."""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys

log = logging.getLogger(__name__)

_PROCESS_POWER_THROTTLING = 4  # PROCESS_INFORMATION_CLASS.ProcessPowerThrottling
_THROTTLE_EXECUTION_SPEED = 0x1
_THROTTLE_IGNORE_TIMER_RESOLUTION = 0x4


def disable_power_throttling() -> bool:
    """Opt this process out of Windows 11 EcoQoS power throttling.

    Without a foreground window (CLI launched from WSL, background server), Windows may run
    the process at low QoS on efficiency cores. Measured on an i7-13700HX, this made
    Supertonic CPU inference 5-10x slower and erratic.
    """
    if sys.platform != "win32":
        return False
    import ctypes
    from ctypes import wintypes

    class _State(ctypes.Structure):
        _fields_ = [
            ("Version", wintypes.ULONG),
            ("ControlMask", wintypes.ULONG),
            ("StateMask", wintypes.ULONG),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.SetProcessInformation.argtypes = [
        wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
    ]  # fmt: skip
    kernel32.SetProcessInformation.restype = wintypes.BOOL
    state = _State(1, _THROTTLE_EXECUTION_SPEED | _THROTTLE_IGNORE_TIMER_RESOLUTION, 0)
    ok = bool(
        kernel32.SetProcessInformation(
            kernel32.GetCurrentProcess(),
            _PROCESS_POWER_THROTTLING,
            ctypes.byref(state),
            ctypes.sizeof(state),
        )
    )
    if not ok:
        log.warning("Could not disable power throttling (error %d)", ctypes.get_last_error())
    return ok


def pid_alive(pid: int) -> bool:
    """True if a process with this id exists (Windows: never signals the process)."""
    if pid <= 0:
        return False
    if sys.platform != "win32":
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True
    import ctypes
    from ctypes import wintypes

    synchronize, still_active = 0x00100000, 259
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    handle = kernel32.OpenProcess(0x1000 | synchronize, False, pid)  # QUERY_LIMITED_INFORMATION
    if not handle:
        return False
    try:
        code = wintypes.DWORD()
        ok = kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        return bool(ok) and code.value == still_active
    finally:
        kernel32.CloseHandle(handle)


def _children(pid: int) -> list[int]:
    """Every descendant of `pid` (POSIX), from one `ps` listing."""
    try:
        out = subprocess.run(  # noqa: S603
            ["ps", "-A", "-o", "pid=,ppid="],  # noqa: S607
            capture_output=True, text=True, timeout=10, check=False,
        ).stdout  # fmt: skip
    except (OSError, subprocess.TimeoutExpired):
        return []
    parent_of: dict[int, list[int]] = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            parent_of.setdefault(int(parts[1]), []).append(int(parts[0]))
    found: list[int] = []
    todo = [pid]
    while todo:
        for child in parent_of.get(todo.pop(), []):
            if child not in found:
                found.append(child)
                todo.append(child)
    return found


def kill_tree(pid: int) -> None:
    """Terminate a process and all its children (ffmpeg, yt-dlp, ...) without a shell."""
    if sys.platform == "win32":
        subprocess.run(  # noqa: S603
            ["taskkill", "/PID", str(pid), "/T", "/F"],  # noqa: S607
            capture_output=True,
            creationflags=0x08000000,  # CREATE_NO_WINDOW
            check=False,
        )
        return
    # Children first (so none is re-parented and missed), then the process itself.
    for victim in [*reversed(_children(pid)), pid]:
        try:
            os.kill(victim, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass


_activity: object | None = None


def keep_awake(reason: str = "LocalDub Studio is dubbing a video") -> bool:
    """macOS: tell the system this process is doing user-requested work.

    Without it App Nap slows a process that has no visible window down by a large factor and the
    Mac may go to sleep in the middle of a long dub. Other systems: does nothing.
    """
    global _activity
    if sys.platform != "darwin" or _activity is not None:
        return False
    try:
        from Foundation import (  # type: ignore[import-not-found,unused-ignore]
            NSActivityIdleSystemSleepDisabled,
            NSActivityUserInitiated,
            NSProcessInfo,
        )

        _activity = NSProcessInfo.processInfo().beginActivityWithOptions_reason_(
            NSActivityUserInitiated | NSActivityIdleSystemSleepDisabled, reason
        )
    except Exception:  # noqa: BLE001 - an optimisation; never fatal
        log.warning("Could not ask macOS to keep this process awake", exc_info=True)
        return False
    return True

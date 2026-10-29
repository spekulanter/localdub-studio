"""OS-specific process setup."""

from __future__ import annotations

import logging
import os
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

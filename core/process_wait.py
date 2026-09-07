from __future__ import annotations

import os
import sys
import time
from collections.abc import Callable

PROCESS_SYNCHRONIZE = 0x00100000
WAIT_OBJECT_0 = 0
WAIT_TIMEOUT = 0x00000102
ERROR_ACCESS_DENIED = 5


class ProcessWaitError(RuntimeError):
    """Raised when a process cannot be waited on without termination rights."""


def wait_for_process_exit(
    pid: int,
    *,
    timeout: float,
    wait_impl: Callable[[int, float], bool] | None = None,
) -> None:
    if pid <= 0:
        raise ValueError("Parent process ID must be positive")
    impl = wait_impl if wait_impl is not None else _default_wait_for_exit
    try:
        exited = bool(impl(int(pid), float(timeout)))
    except ProcessWaitError:
        raise
    except PermissionError as exc:
        raise ProcessWaitError(str(exc)) from exc
    if not exited:
        raise TimeoutError("Parent process did not exit before update")


def is_process_alive(
    pid: int,
    *,
    probe_impl: Callable[[int], bool] | None = None,
) -> bool:
    if pid <= 0:
        return False
    impl = probe_impl if probe_impl is not None else _default_is_alive
    try:
        return bool(impl(int(pid)))
    except PermissionError:
        return True
    except ProcessWaitError:
        return True
    except OSError:
        return False


def _default_wait_for_exit(pid: int, timeout: float) -> bool:
    if sys.platform == "win32":
        return _windows_wait_for_exit(pid, timeout)
    return _posix_wait_for_exit(pid, timeout)


def _default_is_alive(pid: int) -> bool:
    if sys.platform == "win32":
        return _windows_is_alive(pid)
    return _posix_is_alive(pid)


def _posix_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _posix_wait_for_exit(pid: int, timeout: float) -> bool:
    deadline = time.monotonic() + max(0.0, float(timeout))
    while True:
        if not _posix_is_alive(pid):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.2)


def _windows_open_synchronize(pid: int):
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.OpenProcess(PROCESS_SYNCHRONIZE, False, wintypes.DWORD(pid))
    if handle:
        return kernel32, handle
    error = ctypes.get_last_error()
    if error == ERROR_ACCESS_DENIED:
        raise ProcessWaitError(
            f"Access denied while waiting for process {pid} with SYNCHRONIZE"
        )
    return kernel32, None


def _windows_wait_for_exit(pid: int, timeout: float) -> bool:
    kernel32, handle = _windows_open_synchronize(pid)
    if handle is None:
        return True
    try:
        timeout_ms = max(0, int(float(timeout) * 1000.0))
        result = int(kernel32.WaitForSingleObject(handle, timeout_ms))
        if result == WAIT_OBJECT_0:
            return True
        if result == WAIT_TIMEOUT:
            return False
        raise ProcessWaitError(
            f"WaitForSingleObject failed for pid {pid} with status {result}"
        )
    finally:
        kernel32.CloseHandle(handle)


def _windows_is_alive(pid: int) -> bool:
    kernel32, handle = _windows_open_synchronize(pid)
    if handle is None:
        return False
    try:
        result = int(kernel32.WaitForSingleObject(handle, 0))
        return result == WAIT_TIMEOUT
    finally:
        kernel32.CloseHandle(handle)

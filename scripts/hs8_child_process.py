"""Bounded, exception-safe child process lifecycle for HS8 qualification."""

from __future__ import annotations

import os
import signal
import subprocess
import time
from pathlib import Path
from typing import Mapping, NamedTuple, Sequence


POLL_SECONDS = 0.05
WINDOWS_CREATE_SUSPENDED = 0x00000004


class ChildProcessError(RuntimeError):
    """A bounded child failed before returning a usable receipt."""


class ChildResult(NamedTuple):
    returncode: int
    stdout: bytes
    stderr: bytes


def run_child(
    command: Sequence[str],
    *,
    cwd: Path,
    environment: Mapping[str, str],
    run_root: Path,
    timeout_seconds: float,
    max_stdout_bytes: int,
    max_stderr_bytes: int,
) -> ChildResult:
    stdout_path = run_root / "stdout.json"
    stderr_path = run_root / "stderr.log"
    process: subprocess.Popen[bytes] | None = None
    windows_job: _WindowsJob | None = None
    try:
        with stdout_path.open("xb") as stdout, stderr_path.open("xb") as stderr:
            process = subprocess.Popen(
                list(command),
                cwd=str(cwd),
                env=dict(environment),
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                shell=False,
                start_new_session=os.name != "nt",
                creationflags=(
                    subprocess.CREATE_NEW_PROCESS_GROUP
                    | WINDOWS_CREATE_SUSPENDED
                    if os.name == "nt" else 0
                ),
            )
            if os.name == "nt":
                windows_job = _WindowsJob.assign(process)
                _resume_windows_process(process)
            deadline = time.monotonic() + timeout_seconds
            while process.poll() is None:
                if time.monotonic() >= deadline:
                    raise ChildProcessError("Child exceeded its timeout.")
                if (
                    _size(stdout_path) > max_stdout_bytes
                    or _size(stderr_path) > max_stderr_bytes
                ):
                    raise ChildProcessError("Child exceeded its output limit.")
                time.sleep(POLL_SECONDS)
        return ChildResult(
            returncode=int(process.returncode),
            stdout=_read(stdout_path, max_stdout_bytes, "stdout"),
            stderr=_read(stderr_path, max_stderr_bytes, "stderr"),
        )
    finally:
        if windows_job is not None:
            windows_job.close()
            _wait_for_exit(process)
        elif process is not None:
            terminate_tree(process)
        _truncate(stdout_path, max_stdout_bytes)
        _truncate(stderr_path, max_stderr_bytes)


def terminate_tree(process: subprocess.Popen[bytes]) -> None:
    if os.name == "nt":
        if process.poll() is not None:
            return
        result = subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
            timeout=10.0,
            check=False,
        )
        if result.returncode != 0 and process.poll() is None:
            process.kill()
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        else:
            _wait_for_group_exit(process.pid, 5.0)
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    _wait_for_exit(process)


class _WindowsJob:
    """Kill-on-close job that owns the direct process and every descendant."""

    def __init__(self, handle: int):
        self._handle = handle

    @classmethod
    def assign(cls, process: subprocess.Popen[bytes]) -> _WindowsJob:
        import ctypes
        from ctypes import wintypes

        class _IoCounters(ctypes.Structure):
            _fields_ = [
                ("ReadOperationCount", ctypes.c_ulonglong),
                ("WriteOperationCount", ctypes.c_ulonglong),
                ("OtherOperationCount", ctypes.c_ulonglong),
                ("ReadTransferCount", ctypes.c_ulonglong),
                ("WriteTransferCount", ctypes.c_ulonglong),
                ("OtherTransferCount", ctypes.c_ulonglong),
            ]

        class _BasicLimitInformation(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_longlong),
                ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class _ExtendedLimitInformation(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", _BasicLimitInformation),
                ("IoInfo", _IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.SetInformationJobObject.argtypes = (
            wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
        )
        kernel32.SetInformationJobObject.restype = wintypes.BOOL
        kernel32.AssignProcessToJobObject.argtypes = (
            wintypes.HANDLE, wintypes.HANDLE,
        )
        kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        handle = kernel32.CreateJobObjectW(None, None)
        if not handle:
            raise ChildProcessError("Could not create the child process job.")
        job = cls(int(handle))
        information = _ExtendedLimitInformation()
        information.BasicLimitInformation.LimitFlags = 0x00002000
        if not kernel32.SetInformationJobObject(
            handle, 9, ctypes.byref(information), ctypes.sizeof(information),
        ):
            job.close()
            raise ChildProcessError("Could not configure the child process job.")
        if not kernel32.AssignProcessToJobObject(
            handle, wintypes.HANDLE(int(process._handle)),
        ):
            job.close()
            raise ChildProcessError("Could not contain the child process tree.")
        return job

    def close(self) -> None:
        if not self._handle:
            return
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel32.CloseHandle.restype = wintypes.BOOL
        handle, self._handle = self._handle, 0
        if not kernel32.CloseHandle(wintypes.HANDLE(handle)):
            raise ChildProcessError("Could not close the child process job.")


def _resume_windows_process(process: subprocess.Popen[bytes]) -> None:
    """Resume the sole primary thread after the process enters its job."""

    import ctypes
    from ctypes import wintypes

    class _ThreadEntry(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ThreadID", wintypes.DWORD),
            ("th32OwnerProcessID", wintypes.DWORD),
            ("tpBasePri", wintypes.LONG),
            ("tpDeltaPri", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.Thread32First.argtypes = (
        wintypes.HANDLE, ctypes.POINTER(_ThreadEntry),
    )
    kernel32.Thread32First.restype = wintypes.BOOL
    kernel32.Thread32Next.argtypes = (
        wintypes.HANDLE, ctypes.POINTER(_ThreadEntry),
    )
    kernel32.Thread32Next.restype = wintypes.BOOL
    kernel32.OpenThread.argtypes = (
        wintypes.DWORD, wintypes.BOOL, wintypes.DWORD,
    )
    kernel32.OpenThread.restype = wintypes.HANDLE
    kernel32.ResumeThread.argtypes = (wintypes.HANDLE,)
    kernel32.ResumeThread.restype = wintypes.DWORD
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL
    snapshot = kernel32.CreateToolhelp32Snapshot(0x00000004, 0)
    invalid = ctypes.c_void_p(-1).value
    if not snapshot or int(snapshot) == invalid:
        raise ChildProcessError("Could not inspect the suspended child thread.")
    thread_handle = None
    try:
        entry = _ThreadEntry()
        entry.dwSize = ctypes.sizeof(entry)
        available = bool(kernel32.Thread32First(snapshot, ctypes.byref(entry)))
        while available:
            if entry.th32OwnerProcessID == process.pid:
                thread_handle = kernel32.OpenThread(
                    0x0002, False, entry.th32ThreadID,
                )
                break
            available = bool(kernel32.Thread32Next(snapshot, ctypes.byref(entry)))
        if not thread_handle:
            raise ChildProcessError("Could not open the suspended child thread.")
        previous = kernel32.ResumeThread(thread_handle)
        if previous != 1:
            raise ChildProcessError("Could not resume the contained child process.")
    finally:
        thread_closed = (
            thread_handle is None or bool(kernel32.CloseHandle(thread_handle))
        )
        snapshot_closed = bool(kernel32.CloseHandle(snapshot))
        if not thread_closed or not snapshot_closed:
            raise ChildProcessError("Could not close child containment handles.")


def _wait_for_group_exit(process_group: int, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            os.killpg(process_group, 0)
        except ProcessLookupError:
            return
        time.sleep(POLL_SECONDS)


def _wait_for_exit(process: subprocess.Popen[bytes] | None) -> None:
    if process is None:
        return
    try:
        process.wait(timeout=10.0)
    except subprocess.TimeoutExpired as exc:
        raise ChildProcessError("Child process tree could not be terminated.") from exc


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError as exc:
        raise ChildProcessError("Could not inspect child output.") from exc


def _read(path: Path, maximum: int, label: str) -> bytes:
    if _size(path) > maximum:
        raise ChildProcessError(f"Child {label} exceeds its byte limit.")
    try:
        return path.read_bytes()
    except OSError as exc:
        raise ChildProcessError(f"Could not read child {label}.") from exc


def _truncate(path: Path, maximum: int) -> None:
    try:
        if path.is_file() and path.stat().st_size > maximum:
            with path.open("r+b") as stream:
                stream.truncate(maximum)
    except OSError as exc:
        raise ChildProcessError("Could not bound retained child output.") from exc


__all__ = [
    "ChildProcessError",
    "ChildResult",
    "run_child",
    "terminate_tree",
]

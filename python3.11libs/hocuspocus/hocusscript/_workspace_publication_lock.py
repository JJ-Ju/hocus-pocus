"""Host-owned publication lock storage for descriptor-safe workspaces."""

from __future__ import annotations

import hashlib
import logging
import os
import stat
import sys
import uuid
from pathlib import Path
from typing import Callable, Iterable

from ._workspace_boundary_types import NativeWorkspaceError

_REPARSE_POINT = 0x400
LEGACY_LOCK_NAME = ".hocus-recovery-lock-v1"


def open_publication_lock(platform_name: str, identity: Iterable[int]) -> int:
    """Open a current-user lock keyed only by a workspace's native identity."""

    directory = _lock_directory()
    key = _identity_key(platform_name, identity)
    path = directory / f"{key}.lock"
    _reject_reparse(path)
    flags = os.O_RDWR | os.O_CREAT
    flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as exc:
        raise NativeWorkspaceError(
            "HOCUS828", "Workspace publication lock cannot be opened."
        ) from exc
    try:
        information = os.fstat(descriptor)
        if not stat.S_ISREG(information.st_mode) or information.st_nlink != 1:
            raise NativeWorkspaceError(
                "HOCUS828", "Workspace publication lock is unsafe."
            )
        if os.name == "posix" and information.st_uid != os.getuid():
            raise NativeWorkspaceError(
                "HOCUS828", "Workspace publication lock has another owner."
            )
        if os.name == "nt" and not _windows_owned_by_current_user(path):
            raise NativeWorkspaceError(
                "HOCUS828", "Workspace publication lock has another owner."
            )
        if os.name == "posix":
            os.fchmod(descriptor, 0o600)
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


def release_publication_lock(
    actions: Iterable[Callable[[], object]],
    *,
    committed: bool,
    logger: logging.Logger,
) -> None:
    """Exhaust cleanup while preserving a primary exception or committed result."""

    primary_active = sys.exc_info()[0] is not None
    failure: Exception | None = None
    for action in actions:
        try:
            result = action()
            if result is False:
                raise OSError("publication lock release failed")
        except Exception as exc:
            failure = failure or exc
    if failure is None:
        return
    if committed or primary_active:
        logger.warning("HOCUS828 workspace publication lock release deferred")
        return
    raise NativeWorkspaceError(
        "HOCUS828", "Workspace publication lock release failed."
    ) from failure


def reject_legacy_windows_lock(
    *,
    open_file: Callable[[], tuple[int | None, int]],
    close: Callable[[int], object],
    missing_errors: set[int],
) -> None:
    """Require explicit migration of every legacy project-visible lock."""

    handle, error = open_file()
    if handle is None:
        if error in missing_errors:
            return
        raise NativeWorkspaceError(
            "HOCUS828", "Legacy workspace lock requires explicit host migration."
        )
    try:
        raise NativeWorkspaceError(
            "HOCUS828", "Legacy workspace lock requires explicit host migration."
        )
    finally:
        close(handle)


def _identity_key(platform_name: str, identity: Iterable[int]) -> str:
    fields = ",".join(str(int(field)) for field in identity)
    return hashlib.sha256(f"{platform_name}:{fields}".encode("ascii")).hexdigest()


def _lock_directory() -> Path:
    root = _host_state_root()
    directory = root / "hocuspocus" / "runtime" / "source-publication-locks"
    try:
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        _reject_reparse(directory)
        information = directory.stat()
        if not stat.S_ISDIR(information.st_mode):
            raise OSError("publication lock location is not a directory")
        if os.name == "posix":
            if information.st_uid != os.getuid():
                raise OSError("publication lock location has another owner")
            os.chmod(directory, 0o700)
        elif not _windows_owned_by_current_user(directory):
            raise OSError("publication lock location has another owner")
    except OSError as exc:
        raise NativeWorkspaceError(
            "HOCUS828", "Workspace publication lock directory is unsafe."
        ) from exc
    return directory


def _host_state_root() -> Path:
    if os.name == "nt":
        return _windows_local_app_data()
    import pwd

    account = pwd.getpwuid(os.getuid())
    if not account.pw_dir:
        raise NativeWorkspaceError(
            "HOCUS828", "Workspace publication account state is unavailable."
        )
    return Path(account.pw_dir) / ".local" / "state"


def _windows_local_app_data() -> Path:
    import ctypes

    folder_id = _guid("f1b32785-6fba-4fcf-9d55-7b8e7f157091")
    output = ctypes.c_wchar_p()
    shell = ctypes.windll.shell32
    shell.SHGetKnownFolderPath.argtypes = (
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_wchar_p),
    )
    result = shell.SHGetKnownFolderPath(
        ctypes.byref(folder_id), 0, None, ctypes.byref(output)
    )
    if result:
        raise NativeWorkspaceError(
            "HOCUS828", "Workspace publication account state is unavailable."
        )
    try:
        return Path(output.value)
    finally:
        ctypes.windll.ole32.CoTaskMemFree(ctypes.cast(output, ctypes.c_void_p))


def _guid(value: str):
    import ctypes

    class Guid(ctypes.Structure):
        _fields_ = (
            ("data1", ctypes.c_uint32),
            ("data2", ctypes.c_uint16),
            ("data3", ctypes.c_uint16),
            ("data4", ctypes.c_ubyte * 8),
        )

    return Guid.from_buffer_copy(uuid.UUID(value).bytes_le)


def _windows_owned_by_current_user(path: Path) -> bool:
    import ctypes
    from ctypes import wintypes

    owner = ctypes.c_void_p()
    descriptor = ctypes.c_void_p()
    advapi = ctypes.windll.advapi32
    kernel = ctypes.windll.kernel32
    advapi.GetNamedSecurityInfoW.argtypes = (
        wintypes.LPWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p),
    )
    advapi.EqualSid.argtypes = (ctypes.c_void_p, ctypes.c_void_p)
    advapi.OpenProcessToken.argtypes = (
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.HANDLE),
    )
    advapi.GetTokenInformation.argtypes = (
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    )
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    result = advapi.GetNamedSecurityInfoW(
        str(path), 1, 1, ctypes.byref(owner), None, None, None, ctypes.byref(descriptor)
    )
    if result:
        return False
    token = wintypes.HANDLE()
    try:
        if not advapi.OpenProcessToken(
            kernel.GetCurrentProcess(), 8, ctypes.byref(token)
        ):
            return False
        needed = wintypes.DWORD()
        advapi.GetTokenInformation(token, 1, None, 0, ctypes.byref(needed))
        buffer = ctypes.create_string_buffer(needed.value)
        if not advapi.GetTokenInformation(
            token, 1, buffer, needed, ctypes.byref(needed)
        ):
            return False
        current_sid = ctypes.c_void_p.from_buffer(buffer).value
        return bool(advapi.EqualSid(owner, ctypes.c_void_p(current_sid)))
    finally:
        if token:
            kernel.CloseHandle(token)
        kernel.LocalFree(descriptor)


def _reject_reparse(path: Path) -> None:
    try:
        information = path.lstat()
    except FileNotFoundError:
        return
    attributes = getattr(information, "st_file_attributes", 0)
    if stat.S_ISLNK(information.st_mode) or attributes & _REPARSE_POINT:
        raise NativeWorkspaceError(
            "HOCUS828", "Workspace publication lock location is unsafe."
        )

"""NTFS handle-relative atomic rename used by the workspace boundary."""
from __future__ import annotations
import ctypes
import hashlib
import logging
import msvcrt
import os
import secrets
import sys
import threading
from typing import Callable
from ._workspace_boundary_types import NativeWorkspaceError
from ._workspace_publication_lock import (
    LEGACY_LOCK_NAME,
    open_publication_lock,
    reject_legacy_windows_lock,
    release_publication_lock,
)
from ._workspace_recovery_record import (
    MAX_RECOVERY_ARTIFACTS as _MAX_RECOVERY_ARTIFACTS,
    MAX_RECOVERY_BYTES as _MAX_RECOVERY_BYTES,
    RecoveryRequired,
    artifact_metadata,
    encode_recovery_record,
)
if os.name != "nt":
    raise ImportError("Windows workspace rename primitives are unavailable.")
from ctypes import wintypes
_FILE_RENAME_INFO_EX = 65
_FILE_DISPOSITION_INFORMATION = 13
_REPLACE_IF_EXISTS = 0x00000001
_POSIX_SEMANTICS = 0x00000002
_OBJ_CASE_INSENSITIVE = 0x00000040
_FILE_OPEN = 1
_FILE_CREATE = 2
_FILE_NON_DIRECTORY_FILE = 0x00000040
_FILE_DIRECTORY_FILE = 0x00000001
_FILE_SYNCHRONOUS_IO_NONALERT = 0x00000020
_FILE_ATTRIBUTE_NORMAL = 0x00000080
_FILE_SHARE_ALL = 0x00000007
_LOCKFILE_FAIL_IMMEDIATELY = 0x00000001
_LOCKFILE_EXCLUSIVE_LOCK = 0x00000002
_DELETE = 0x00010000
_SYNCHRONIZE = 0x00100000
_FILE_READ_DATA = 0x00000001
_FILE_WRITE_DATA = 0x00000002
_FILE_READ_ATTRIBUTES = 0x00000080
_WRITE_CHUNK = 64 * 1024
_LOG = logging.getLogger(__name__)
RECOVERY_MARKER = ".hocus-recovery-v1.json"
_MISSING_ERRORS = {2, 3, 0xC0000034, 0xC000003A}
_LOCK_STATES = {
    "clean": b"clean           \n",
    "publishing": b"publishing      \n",
    "orphan": b"orphan          \n",
    "recovery": b"recovery        \n",
}
_RECOVERY_CONTEXT = threading.local()
_PUBLICATION_LOCK = threading.RLock()
def publication_guard(root_handle: int, operation: Callable[[int], bytes]) -> bytes:
    with _PUBLICATION_LOCK:
        return _publication_guard_locked(root_handle, operation)
def _publication_guard_locked(
    root_handle: int,
    operation: Callable[[int], bytes],
) -> bytes:
    """Serialize publication and retain a crash-persistent recovery state."""
    publication_root, error = _open_relative(
        root_handle,
        "",
        _SYNCHRONIZE | _FILE_READ_DATA | _FILE_WRITE_DATA | _FILE_READ_ATTRIBUTES,
        directory=True,
    )
    if publication_root is None or _identity(publication_root) != _identity(root_handle):
        if publication_root is not None:
            _CloseHandle(publication_root)
        raise OSError(error or 5, "workspace publication root cannot be retained")
    lock_descriptor, lock_handle = _open_recovery_lock(publication_root)
    lock = _Overlapped()
    lock.Offset = 0x7FFFFFFF
    if not _LockFileEx(
        lock_handle, _LOCKFILE_EXCLUSIVE_LOCK, 0, 1, 0, ctypes.byref(lock)
    ):
        os.close(lock_descriptor)
        _CloseHandle(publication_root)
        raise OSError(ctypes.get_last_error(), "workspace recovery lock failed")
    _RECOVERY_CONTEXT.current = (publication_root, lock_handle)
    committed = False
    try:
        state = _read_lock_state(lock_handle)
        if state == _LOCK_STATES["recovery"]:
            try:
                assert_recovery_clear(publication_root)
            except RecoveryRequired as exc:
                raise NativeWorkspaceError(
                    "HOCUS828", "Workspace recovery is required."
                ) from exc
            _write_lock_state(lock_handle, "clean")
            state = _LOCK_STATES["clean"]
        if state not in {b"", _LOCK_STATES["clean"]}:
            raise NativeWorkspaceError("HOCUS828", "Workspace recovery is required.")
        reject_legacy_windows_lock(
            open_file=lambda: _open_relative(
                publication_root,
                LEGACY_LOCK_NAME,
                _SYNCHRONIZE | _FILE_READ_ATTRIBUTES,
            ),
            close=_CloseHandle,
            missing_errors=_MISSING_ERRORS,
        )
        assert_recovery_clear(publication_root)
        _write_lock_state(lock_handle, "publishing")
        result = operation(publication_root)
        committed = True
        return result
    finally:
        _finish_publication_lock(lock_handle)
        _RECOVERY_CONTEXT.current = None
        release_publication_lock(
            (
                lambda: _UnlockFileEx(
                    lock_handle, 0, 1, 0, ctypes.byref(lock)
                ),
                lambda: os.close(lock_descriptor),
                lambda: _CloseHandle(publication_root),
            ),
            committed=committed,
            logger=_LOG,
        )
def _finish_publication_lock(lock_handle: int) -> None:
    try:
        if _read_lock_state(lock_handle) == _LOCK_STATES["publishing"]:
            _write_lock_state(lock_handle, "clean")
    except Exception:
        _LOG.warning("HOCUS828 workspace publication lock remains fail-closed")
def _open_recovery_lock(root_handle: int) -> tuple[int, int]:
    identity = _identity(root_handle)
    if identity is None:
        raise OSError(5, "workspace recovery lock identity is unavailable")
    descriptor = open_publication_lock("windows", identity[:2])
    return descriptor, msvcrt.get_osfhandle(descriptor)
def _read_lock_state(lock_handle: int) -> bytes:
    if not _rewind(lock_handle):
        raise OSError(ctypes.get_last_error(), "workspace recovery lock seek failed")
    content, error = _read_all(lock_handle, 32)
    if error:
        raise OSError(error, "workspace recovery lock read failed")
    return content
def _write_lock_state(lock_handle: int, state: str) -> None:
    if not _rewind(lock_handle):
        raise OSError(ctypes.get_last_error(), "workspace recovery lock seek failed")
    error = write_all(lock_handle, _LOCK_STATES[state])
    if error:
        raise OSError(error, "workspace recovery lock write failed")
def _set_recovery_state(root_handle: int, state: str) -> None:
    current = getattr(_RECOVERY_CONTEXT, "current", None)
    if current is not None and current[0] == root_handle:
        _write_lock_state(current[1], state)
        return
    lock_descriptor, lock_handle = _open_recovery_lock(root_handle)
    try:
        _write_lock_state(lock_handle, state)
    finally:
        os.close(lock_descriptor)
def close_publication(closer: Callable[[], object], committed: bool) -> bool:
    """Preserve the transaction result when handle cleanup itself fails."""
    already_failing = sys.exc_info()[0] is not None
    try:
        if closer() is False:
            raise OSError(ctypes.get_last_error(), "workspace handle close failed")
    except Exception:
        if not committed and not already_failing:
            raise
        _LOG.warning("HOCUS828 workspace publication cleanup deferred")
        return True
    return False
def assert_recovery_clear(root_handle: int) -> None:
    """Block publication while durable recovery evidence is unresolved."""
    handle, error = _open_relative(
        root_handle,
        RECOVERY_MARKER,
        _SYNCHRONIZE | _FILE_READ_ATTRIBUTES,
    )
    if handle is not None:
        _CloseHandle(handle)
        raise RecoveryRequired(())
    if error not in _MISSING_ERRORS:
        raise OSError(error, "workspace recovery marker cannot be inspected")
def fail_recovery(
    root_handle: int,
    target: str,
    parent: str,
    recovery: RecoveryRequired,
) -> None:
    write_recovery_marker(root_handle, target, parent, recovery)
    raise NativeWorkspaceError("HOCUS828", "Workspace recovery is required.") from recovery
def recovery_guard(
    root_handle: int,
    target: str,
    parent: str,
    operation: Callable[[], None],
) -> None:
    try:
        operation()
    except RecoveryRequired as exc:
        fail_recovery(root_handle, target, parent, exc)
def write_recovery_marker(
    root_handle: int,
    target: str,
    parent: str,
    recovery: RecoveryRequired,
) -> None:
    """Durably publish the single path-free recovery incident marker."""
    _set_recovery_state(root_handle, "orphan")
    content = encode_recovery_record(target, parent, recovery)
    handle, error = create_relative(root_handle, RECOVERY_MARKER)
    if handle is None:
        raise OSError(error, "workspace recovery marker cannot be created")
    try:
        error = write_all(handle, content)
        if error:
            raise OSError(error, "workspace recovery marker cannot be written")
    finally:
        _CloseHandle(handle)
    if not _FlushFileBuffers(root_handle):
        raise OSError(ctypes.get_last_error(), "workspace recovery namespace is not durable")
    _set_recovery_state(root_handle, "recovery")
class _FileRenameInformationEx(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("RootDirectory", wintypes.HANDLE),
        ("FileNameLength", wintypes.DWORD),
        ("FileName", wintypes.WCHAR * 1),
    ]
class _IoStatusBlock(ctypes.Structure):
    _fields_ = [("Status", ctypes.c_void_p), ("Information", ctypes.c_size_t)]
class _UnicodeString(ctypes.Structure):
    _fields_ = [
        ("Length", wintypes.USHORT),
        ("MaximumLength", wintypes.USHORT),
        ("Buffer", wintypes.LPWSTR),
    ]
class _ObjectAttributes(ctypes.Structure):
    _fields_ = [
        ("Length", wintypes.ULONG),
        ("RootDirectory", wintypes.HANDLE),
        ("ObjectName", ctypes.POINTER(_UnicodeString)),
        ("Attributes", wintypes.ULONG),
        ("SecurityDescriptor", wintypes.LPVOID),
        ("SecurityQualityOfService", wintypes.LPVOID),
    ]
class _FileDispositionInformation(ctypes.Structure):
    _fields_ = [("DeleteFile", wintypes.BYTE)]
class _ByHandleFileInformation(ctypes.Structure):
    _fields_ = [
        ("dwFileAttributes", wintypes.DWORD),
        ("ftCreationTime", wintypes.FILETIME),
        ("ftLastAccessTime", wintypes.FILETIME),
        ("ftLastWriteTime", wintypes.FILETIME),
        ("dwVolumeSerialNumber", wintypes.DWORD),
        ("nFileSizeHigh", wintypes.DWORD),
        ("nFileSizeLow", wintypes.DWORD),
        ("nNumberOfLinks", wintypes.DWORD),
        ("nFileIndexHigh", wintypes.DWORD),
        ("nFileIndexLow", wintypes.DWORD),
    ]
class _Overlapped(ctypes.Structure):
    _fields_ = [
        ("Internal", ctypes.c_void_p),
        ("InternalHigh", ctypes.c_void_p),
        ("Offset", wintypes.DWORD),
        ("OffsetHigh", wintypes.DWORD),
        ("hEvent", wintypes.HANDLE),
    ]


_NTDLL = ctypes.WinDLL("ntdll")
_NtCreateFile = _NTDLL.NtCreateFile
_NtCreateFile.argtypes = [
    ctypes.POINTER(wintypes.HANDLE),
    wintypes.DWORD,
    ctypes.POINTER(_ObjectAttributes),
    ctypes.POINTER(_IoStatusBlock),
    ctypes.c_void_p,
    wintypes.ULONG,
    wintypes.ULONG,
    wintypes.ULONG,
    wintypes.ULONG,
    wintypes.LPVOID,
    wintypes.ULONG,
]
_NtCreateFile.restype = ctypes.c_long
_NtSetInformationFile = _NTDLL.NtSetInformationFile
_NtSetInformationFile.argtypes = [
    wintypes.HANDLE,
    ctypes.POINTER(_IoStatusBlock),
    wintypes.LPVOID,
    wintypes.ULONG,
    ctypes.c_int,
]
_NtSetInformationFile.restype = ctypes.c_long
_KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)
_WriteFile = _KERNEL32.WriteFile
_WriteFile.argtypes = [
    wintypes.HANDLE,
    wintypes.LPCVOID,
    wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD),
    wintypes.LPVOID,
]
_WriteFile.restype = wintypes.BOOL
_FlushFileBuffers = _KERNEL32.FlushFileBuffers
_FlushFileBuffers.argtypes = [wintypes.HANDLE]
_FlushFileBuffers.restype = wintypes.BOOL
_GetFileInformationByHandle = _KERNEL32.GetFileInformationByHandle
_GetFileInformationByHandle.argtypes = [
    wintypes.HANDLE,
    ctypes.POINTER(_ByHandleFileInformation),
]
_GetFileInformationByHandle.restype = wintypes.BOOL
_ReadFile = _KERNEL32.ReadFile
_ReadFile.argtypes = [
    wintypes.HANDLE,
    wintypes.LPVOID,
    wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD),
    wintypes.LPVOID,
]
_ReadFile.restype = wintypes.BOOL
_CloseHandle = _KERNEL32.CloseHandle
_CloseHandle.argtypes = [wintypes.HANDLE]
_CloseHandle.restype = wintypes.BOOL
_LockFileEx = _KERNEL32.LockFileEx
_LockFileEx.argtypes = [
    wintypes.HANDLE,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.DWORD,
    ctypes.POINTER(_Overlapped),
]
_LockFileEx.restype = wintypes.BOOL
_UnlockFileEx = _KERNEL32.UnlockFileEx
_UnlockFileEx.argtypes = [
    wintypes.HANDLE,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.DWORD,
    ctypes.POINTER(_Overlapped),
]
_UnlockFileEx.restype = wintypes.BOOL
_SetFilePointerEx = _KERNEL32.SetFilePointerEx
_SetFilePointerEx.argtypes = [
    wintypes.HANDLE,
    ctypes.c_longlong,
    ctypes.POINTER(ctypes.c_longlong),
    wintypes.DWORD,
]
_SetFilePointerEx.restype = wintypes.BOOL
_GetFinalPathNameByHandleW = _KERNEL32.GetFinalPathNameByHandleW
_GetFinalPathNameByHandleW.argtypes = [
    wintypes.HANDLE,
    wintypes.LPWSTR,
    wintypes.DWORD,
    wintypes.DWORD,
]
_GetFinalPathNameByHandleW.restype = wintypes.DWORD
_ReplaceFileW = _KERNEL32.ReplaceFileW
_ReplaceFileW.argtypes = [
    wintypes.LPCWSTR,
    wintypes.LPCWSTR,
    wintypes.LPCWSTR,
    wintypes.DWORD,
    wintypes.LPVOID,
    wintypes.LPVOID,
]
_ReplaceFileW.restype = wintypes.BOOL
_DeleteFileW = _KERNEL32.DeleteFileW
_DeleteFileW.argtypes = [wintypes.LPCWSTR]
_DeleteFileW.restype = wintypes.BOOL
def create_relative(parent_handle: int, name: str) -> tuple[int | None, int]:
    """Exclusively create one regular file relative to a directory handle."""
    name_buffer = ctypes.create_unicode_buffer(name)
    encoded_length = len(name.encode("utf-16-le"))
    unicode_name = _UnicodeString(
        encoded_length,
        encoded_length + 2,
        ctypes.cast(name_buffer, wintypes.LPWSTR),
    )
    attributes = _ObjectAttributes(
        ctypes.sizeof(_ObjectAttributes),
        parent_handle,
        ctypes.pointer(unicode_name),
        _OBJ_CASE_INSENSITIVE,
        None,
        None,
    )
    output = wintypes.HANDLE()
    status = _IoStatusBlock()
    result = _NtCreateFile(
        ctypes.byref(output),
        _DELETE
        | _SYNCHRONIZE
        | _FILE_READ_DATA
        | _FILE_WRITE_DATA
        | _FILE_READ_ATTRIBUTES,
        ctypes.byref(attributes),
        ctypes.byref(status),
        None,
        _FILE_ATTRIBUTE_NORMAL,
        _FILE_SHARE_ALL,
        _FILE_CREATE,
        _FILE_NON_DIRECTORY_FILE | _FILE_SYNCHRONOUS_IO_NONALERT,
        None,
        0,
    )
    code = int(result) & 0xFFFFFFFF
    return (int(output.value), 0) if code == 0 else (None, code)


def mark_delete(handle: int) -> int:
    """Mark an open temporary file for deletion when its handle closes."""
    information = _FileDispositionInformation(1)
    status = _IoStatusBlock()
    result = _NtSetInformationFile(
        handle,
        ctypes.byref(status),
        ctypes.byref(information),
        ctypes.sizeof(information),
        _FILE_DISPOSITION_INFORMATION,
    )
    return int(result) & 0xFFFFFFFF


def write_all(handle: int, content: bytes) -> int:
    """Write and durably flush raw bytes to a synchronous native handle."""
    offset = 0
    while offset < len(content):
        chunk = content[offset : offset + _WRITE_CHUNK]
        buffer = ctypes.create_string_buffer(chunk)
        written = wintypes.DWORD()
        if not _WriteFile(handle, buffer, len(chunk), ctypes.byref(written), None):
            return ctypes.get_last_error()
        if written.value != len(chunk):
            return 29
        offset += written.value
    if not _FlushFileBuffers(handle):
        return ctypes.get_last_error()
    return 0


def publish_create_transaction(
    parent_handle: int,
    candidate_handle: int,
    target_name: str,
    candidate_identity: tuple[int, int, int, int, int, int],
    candidate_digest: str,
    candidate_content: bytes,
    verify_namespace: Callable[[], None],
) -> None:
    """Publish a create while retaining candidate rollback authority."""
    error = rename_relative(
        candidate_handle,
        parent_handle,
        target_name,
        replace_existing=False,
    )
    if error:
        code = "HOCUS826" if error in {80, 183, 0xC0000035} else "HOCUS828"
        message = (
            "Workspace create target already exists."
            if code == "HOCUS826"
            else "Workspace publication failed."
        )
        raise NativeWorkspaceError(code, message)
    try:
        error = verify_relative(
            parent_handle,
            target_name,
            candidate_identity,
            candidate_digest,
            max(len(candidate_content), 1),
        )
        if error:
            raise NativeWorkspaceError(
                "HOCUS828", "Published workspace bytes failed verification."
            )
        verify_namespace()
        if flush_handle(parent_handle):
            raise NativeWorkspaceError("HOCUS828", "Workspace publication failed.")
    except Exception:
        _rollback_create(
            parent_handle,
            candidate_handle,
            target_name,
            candidate_identity,
            candidate_content,
        )
        raise


def _rollback_create(
    parent_handle: int,
    candidate_handle: int,
    target_name: str,
    candidate_identity: tuple[int, int, int, int, int, int],
    candidate_content: bytes,
) -> None:
    current, error = _relative_identity(parent_handle, target_name)
    if current is None and error in _MISSING_ERRORS:
        return
    if current == candidate_identity:
        error = mark_delete(candidate_handle)
        if error:
            raise RecoveryRequired(
                (
                    {
                        "digest": "sha256:"
                        + hashlib.sha256(candidate_content).hexdigest(),
                        "path": target_name,
                        "role": "candidate",
                        "size": len(candidate_content),
                    },
                )
            )
        if flush_handle(parent_handle):
            raise RecoveryRequired(())
        return
    recovery_name = (
        f".hocus-recovery-v1-{secrets.token_hex(16)}-candidate.bin"
    )
    handle, error = create_relative(parent_handle, recovery_name)
    if handle is None:
        raise RecoveryRequired(())
    try:
        error = write_all(handle, candidate_content)
        if error:
            raise RecoveryRequired(())
    finally:
        _CloseHandle(handle)
    _FlushFileBuffers(parent_handle)
    _LOG.warning("HOCUS828 competing workspace target preserved for recovery")
    raise RecoveryRequired(
        (_recovery_artifact(parent_handle, recovery_name, role="candidate"),)
    )


def replace_cas(
    parent_handle: int,
    temporary_path: str,
    target_name: str,
    expected_digest: str,
    max_bytes: int,
    expected_identity: tuple[int, int, int, int, int, int],
    replacement_identity: tuple[int, int, int, int, int, int],
    replacement_digest: str,
    replacement_size: int,
    recovery_root_handle: int,
    recovery_target: str,
    recovery_parent: str,
) -> tuple[str, int]:
    """Compare retained bytes before atomically replacing the target name."""
    result = _replace_cas_retained(
        parent_handle,
        temporary_path,
        target_name,
        expected_digest,
        max_bytes,
        expected_identity,
        replacement_identity,
        replacement_digest,
        replacement_size,
        recovery_root_handle,
        recovery_target,
        recovery_parent,
    )
    if not _DeleteFileW(temporary_path):
        temporary_name = temporary_path.rsplit("\\", 1)[-1]
        retained, _ = _relative_identity(parent_handle, temporary_name)
        if retained is not None:
            _record_deferred_cleanup(
                recovery_root_handle,
                recovery_target,
                recovery_parent,
                _safe_recovery_artifact(
                    parent_handle, temporary_name, role="candidate"
                ),
            )
            _LOG.warning("HOCUS828 rollback candidate cleanup deferred")
    return result


def _replace_cas_retained(
    parent_handle: int,
    temporary_path: str,
    target_name: str,
    expected_digest: str,
    max_bytes: int,
    expected_identity: tuple[int, int, int, int, int, int],
    replacement_identity: tuple[int, int, int, int, int, int],
    replacement_digest: str,
    replacement_size: int,
    recovery_root_handle: int,
    recovery_target: str,
    recovery_parent: str,
) -> tuple[str, int]:
    target_handle, error = _open_relative(
        parent_handle,
        target_name,
        _SYNCHRONIZE | _FILE_READ_DATA | _FILE_READ_ATTRIBUTES,
    )
    if target_handle is None:
        return "conflict", error
    try:
        before = _identity(target_handle)
        if (
            before != expected_identity
            or before[3] > max_bytes
            or before[4] != 1
        ):
            return "conflict", 0
        content, error = _read_all(target_handle, max_bytes)
        compared = _identity(target_handle)
        if (
            error
            or compared != before
            or "sha256:" + hashlib.sha256(content).hexdigest() != expected_digest
        ):
            return "conflict", error
        lock, error = _lock_target(target_handle)
        if lock is None:
            return ("conflict", error) if error in {32, 33} else ("error", error)
        try:
            if _identity(target_handle) != before or not _rewind(target_handle):
                return "conflict", 0
            content, error = _read_all(target_handle, max_bytes)
            compared = _identity(target_handle)
            if (
                error
                or compared != before
                or "sha256:" + hashlib.sha256(content).hexdigest() != expected_digest
            ):
                return "conflict", error
        finally:
            _unlock_target(target_handle, lock)
    finally:
        _CloseHandle(target_handle)
    return _replace_compared_target(
        parent_handle,
        temporary_path,
        target_name,
        before,
        expected_digest,
        max_bytes,
        replacement_identity,
        replacement_digest,
        replacement_size,
        recovery_root_handle,
        recovery_target,
        recovery_parent,
    )


def _replace_compared_target(
    parent_handle: int,
    temporary_path: str,
    target_name: str,
    expected_identity: tuple[int, int, int, int, int, int],
    expected_digest: str,
    max_bytes: int,
    replacement_identity: tuple[int, int, int, int, int, int],
    replacement_digest: str,
    replacement_size: int,
    recovery_root_handle: int,
    recovery_target: str,
    recovery_parent: str,
) -> tuple[str, int]:
    backup_name = (
        f".hocus-recovery-v1-{secrets.token_hex(16)}-displaced.bin"
    )
    parent_path = _final_path(parent_handle)
    if (
        parent_path is None
        or not target_name
        or "\\" in target_name
        or "/" in target_name
        or not _is_direct_child(parent_path, temporary_path)
    ):
        return "error", 123
    target_path = parent_path + "\\" + target_name
    backup_path = parent_path + "\\" + backup_name
    error = _replace_with_backup(target_path, temporary_path, backup_path)
    if error:
        return "error", error
    backup_handle, error = _open_relative(
        parent_handle,
        backup_name,
        _DELETE | _SYNCHRONIZE | _FILE_READ_DATA | _FILE_READ_ATTRIBUTES,
    )
    if backup_handle is None:
        rollback = _restore_backup(
            parent_handle,
            target_path,
            backup_path,
            target_name,
            replacement_identity,
            recovery_root_handle,
            recovery_target,
            recovery_parent,
        )
        return "error", rollback or error
    retained_backup: int | None = backup_handle
    try:
        displaced, error = _read_all(backup_handle, max_bytes)
        after = _identity(backup_handle)
        if (
            error
            or not _same_displaced_identity(expected_identity, after)
            or "sha256:" + hashlib.sha256(displaced).hexdigest() != expected_digest
        ):
            _CloseHandle(backup_handle)
            retained_backup = None
            rollback = _restore_backup(
                parent_handle,
                target_path,
                backup_path,
                target_name,
                replacement_identity,
                recovery_root_handle,
                recovery_target,
                recovery_parent,
            )
            return ("conflict", error) if rollback == 0 else ("error", rollback)
        error = verify_relative(
            parent_handle,
            target_name,
            replacement_identity,
            replacement_digest,
            replacement_size,
        )
        if error:
            _CloseHandle(backup_handle)
            retained_backup = None
            rollback = _restore_backup(
                parent_handle,
                target_path,
                backup_path,
                target_name,
                replacement_identity,
                recovery_root_handle,
                recovery_target,
                recovery_parent,
            )
            return "error", rollback or error
        if not _FlushFileBuffers(parent_handle):
            error = ctypes.get_last_error()
            _CloseHandle(backup_handle)
            retained_backup = None
            rollback = _restore_backup(
                parent_handle,
                target_path,
                backup_path,
                target_name,
                replacement_identity,
                recovery_root_handle,
                recovery_target,
                recovery_parent,
            )
            return "error", rollback or error
        deletion = mark_delete(backup_handle)
        close_deferred = close_publication(lambda: _CloseHandle(backup_handle), True)
        retained_backup = None
        if deletion or close_deferred:
            artifacts = (
                {
                    "digest": expected_digest,
                    "path": backup_name,
                    "role": "displaced",
                    "size": len(displaced),
                },
            ) if deletion else ()
            _record_deferred_cleanup(
                recovery_root_handle,
                recovery_target,
                recovery_parent,
                artifacts,
            )
            _LOG.warning("HOCUS828 committed workspace backup cleanup deferred")
        elif not _FlushFileBuffers(parent_handle):
            _record_deferred_cleanup(
                recovery_root_handle,
                recovery_target,
                recovery_parent,
                (),
            )
            _LOG.warning("HOCUS828 committed workspace backup cleanup durability deferred")
        return "ok", 0
    finally:
        if retained_backup is not None:
            close_publication(lambda: _CloseHandle(retained_backup), False)


def _replace_with_backup(
    target_path: str,
    replacement_path: str,
    backup_path: str | None,
) -> int:
    if _ReplaceFileW(
        target_path,
        replacement_path,
        backup_path,
        0,
        None,
        None,
    ):
        return 0
    return ctypes.get_last_error()


def _restore_backup(
    parent_handle: int,
    target_path: str,
    backup_path: str,
    target_name: str,
    expected_candidate: tuple[int, int, int, int, int, int],
    recovery_root_handle: int,
    recovery_target: str,
    recovery_parent: str,
) -> int:
    current, error = _relative_identity(parent_handle, target_name)
    if current != expected_candidate:
        _FlushFileBuffers(parent_handle)
        _LOG.warning("HOCUS828 competing workspace target preserved for recovery")
        raise RecoveryRequired(
            _rollback_failure_artifacts(
                parent_handle,
                backup_path.rsplit("\\", 1)[-1],
                target_name,
                expected_candidate,
            )
        )
    recovery_name = (
        f".hocus-recovery-v1-{secrets.token_hex(16)}-candidate.bin"
    )
    recovery_path = target_path.rsplit("\\", 1)[0] + "\\" + recovery_name
    error = _replace_with_backup(target_path, backup_path, recovery_path)
    if error:
        _FlushFileBuffers(parent_handle)
        _LOG.warning("HOCUS828 rollback syscall lost workspace target authority")
        raise RecoveryRequired(
            _rollback_failure_artifacts(
                parent_handle,
                backup_path.rsplit("\\", 1)[-1],
                target_name,
                expected_candidate,
            )
        )
    displaced, inspect_error = _relative_identity(parent_handle, recovery_name)
    if displaced != expected_candidate:
        restored = _replace_with_backup(target_path, recovery_path, backup_path)
        if restored == 0:
            _FlushFileBuffers(parent_handle)
        _LOG.warning("HOCUS828 competing workspace target preserved for recovery")
        if restored:
            _FlushFileBuffers(parent_handle)
            _LOG.warning("HOCUS828 rollback restore syscall lost target authority")
            raise RecoveryRequired(
                _rollback_failure_artifacts(
                    parent_handle,
                    backup_path.rsplit("\\", 1)[-1],
                    target_name,
                    expected_candidate,
                )
            )
        raise RecoveryRequired(
            (_recovery_artifact(parent_handle, backup_path.rsplit("\\", 1)[-1]),)
        )
    if not _DeleteFileW(recovery_path):
        _record_deferred_cleanup(
            recovery_root_handle,
            recovery_target,
            recovery_parent,
            _safe_recovery_artifact(
                parent_handle, recovery_name, role="candidate"
            ),
        )
        _LOG.warning("HOCUS828 rollback candidate cleanup deferred")
    return 0 if _FlushFileBuffers(parent_handle) else ctypes.get_last_error()


def _rollback_failure_artifacts(
    parent_handle: int,
    backup_name: str,
    target_name: str,
    expected_candidate: tuple[int, int, int, int, int, int],
) -> tuple[dict[str, object], ...]:
    artifacts = list(
        _safe_recovery_artifact(parent_handle, backup_name, role="displaced")
    )
    current, _ = _relative_identity(parent_handle, target_name)
    if current == expected_candidate:
        artifacts.extend(
            _safe_recovery_artifact(parent_handle, target_name, role="candidate")
        )
    return tuple(artifacts[:_MAX_RECOVERY_ARTIFACTS])


def _record_deferred_cleanup(
    root_handle: int,
    target: str,
    parent: str,
    artifacts: tuple[dict[str, object], ...],
) -> None:
    try:
        write_recovery_marker(
            root_handle,
            target,
            parent,
            RecoveryRequired(artifacts),
        )
    except Exception:
        _LOG.warning("HOCUS828 workspace recovery marker publication deferred")


def _safe_recovery_artifact(
    parent_handle: int,
    name: str,
    *,
    role: str,
) -> tuple[dict[str, object], ...]:
    try:
        return (_recovery_artifact(parent_handle, name, role=role),)
    except Exception:
        _LOG.warning("HOCUS828 workspace recovery artifact inspection deferred")
        return ()


def _recovery_artifact(
    parent_handle: int,
    name: str,
    *,
    role: str = "displaced",
) -> dict[str, object]:
    handle, error = _open_relative(
        parent_handle,
        name,
        _SYNCHRONIZE | _FILE_READ_DATA | _FILE_READ_ATTRIBUTES,
    )
    if handle is None:
        raise OSError(error, "workspace recovery evidence cannot be inspected")
    try:
        identity = _identity(handle)
        content, error = _read_all(handle, _MAX_RECOVERY_BYTES)
        if error or identity[4] != 1:
            raise OSError(error or 5, "unsafe workspace recovery evidence")
    finally:
        _CloseHandle(handle)
    return artifact_metadata(name, role, content)


def _relative_identity(
    parent_handle: int,
    target_name: str,
) -> tuple[tuple[int, int, int, int, int, int] | None, int]:
    handle, error = _open_relative(
        parent_handle,
        target_name,
        _SYNCHRONIZE | _FILE_READ_ATTRIBUTES,
    )
    if handle is None:
        return None, error
    try:
        return _identity(handle), 0
    finally:
        _CloseHandle(handle)


def _final_path(handle: int) -> str | None:
    size = _GetFinalPathNameByHandleW(handle, None, 0, 0)
    if not size or size > 32768:
        return None
    buffer = ctypes.create_unicode_buffer(size + 1)
    written = _GetFinalPathNameByHandleW(handle, buffer, size + 1, 0)
    return buffer.value.rstrip("\\") if 0 < written <= size else None


def _is_direct_child(parent_path: str, child_path: str) -> bool:
    parent, separator, name = child_path.rpartition("\\")
    return bool(separator and name) and parent.casefold() == parent_path.casefold()


def verify_relative(
    parent_handle: int,
    target_name: str,
    expected_identity: tuple[int, int, int, int, int, int],
    expected_digest: str,
    max_bytes: int,
) -> int:
    handle, error = _open_relative(
        parent_handle,
        target_name,
        _SYNCHRONIZE | _FILE_READ_DATA | _FILE_READ_ATTRIBUTES,
    )
    if handle is None:
        return error
    try:
        before = _identity(handle)
        if (
            before != expected_identity
            or before[3] > max_bytes
            or before[4] != 1
        ):
            return 1006
        content, error = _read_all(handle, max_bytes)
        after = _identity(handle)
        if (
            error
            or after != before
            or "sha256:" + hashlib.sha256(content).hexdigest() != expected_digest
        ):
            return error or 23
        return 0
    finally:
        _CloseHandle(handle)


def _lock_target(handle: int) -> tuple[_Overlapped | None, int]:
    lock = _Overlapped()
    if _LockFileEx(
        handle,
        _LOCKFILE_FAIL_IMMEDIATELY | _LOCKFILE_EXCLUSIVE_LOCK,
        0,
        0xFFFFFFFF,
        0xFFFFFFFF,
        ctypes.byref(lock),
    ):
        return lock, 0
    return None, ctypes.get_last_error()


def _unlock_target(handle: int, lock: _Overlapped) -> None:
    _UnlockFileEx(
        handle,
        0,
        0xFFFFFFFF,
        0xFFFFFFFF,
        ctypes.byref(lock),
    )


def _rewind(handle: int) -> bool:
    return bool(_SetFilePointerEx(handle, 0, None, 0))


def flush_handle(handle: int) -> int:
    """Flush a file or directory handle."""
    return 0 if _FlushFileBuffers(handle) else ctypes.get_last_error()


def _identity(handle: int) -> tuple[int, int, int, int, int, int] | None:
    information = _ByHandleFileInformation()
    if not _GetFileInformationByHandle(handle, ctypes.byref(information)):
        return None
    return (
        information.dwVolumeSerialNumber,
        (information.nFileIndexHigh << 32) | information.nFileIndexLow,
        information.dwFileAttributes,
        (information.nFileSizeHigh << 32) | information.nFileSizeLow,
        information.nNumberOfLinks,
        (information.ftLastWriteTime.dwHighDateTime << 32)
        | information.ftLastWriteTime.dwLowDateTime,
    )


def _same_displaced_identity(
    before: tuple[int, int, int, int, int, int],
    after: tuple[int, int, int, int, int, int] | None,
) -> bool:
    return after is not None and (
        before[0],
        before[1],
        before[2],
        before[3],
        before[5],
    ) == (after[0], after[1], after[2], after[3], after[5])


def _read_all(handle: int, max_bytes: int) -> tuple[bytes, int]:
    output: list[bytes] = []
    remaining = max_bytes + 1
    while remaining:
        size = min(_WRITE_CHUNK, remaining)
        buffer = ctypes.create_string_buffer(size)
        received = wintypes.DWORD()
        if not _ReadFile(handle, buffer, size, ctypes.byref(received), None):
            return b"", ctypes.get_last_error()
        if not received.value:
            break
        output.append(buffer.raw[: received.value])
        remaining -= received.value
    content = b"".join(output)
    return (content, 0) if len(content) <= max_bytes else (b"", 223)


def _open_relative(
    parent_handle: int,
    name: str,
    access: int,
    *,
    directory: bool = False,
) -> tuple[int | None, int]:
    name_buffer = ctypes.create_unicode_buffer(name)
    encoded_length = len(name.encode("utf-16-le"))
    unicode_name = _UnicodeString(
        encoded_length,
        encoded_length + 2,
        ctypes.cast(name_buffer, wintypes.LPWSTR),
    )
    attributes = _ObjectAttributes(
        ctypes.sizeof(_ObjectAttributes),
        parent_handle,
        ctypes.pointer(unicode_name),
        _OBJ_CASE_INSENSITIVE,
        None,
        None,
    )
    output = wintypes.HANDLE()
    status = _IoStatusBlock()
    result = _NtCreateFile(
        ctypes.byref(output),
        access,
        ctypes.byref(attributes),
        ctypes.byref(status),
        None,
        _FILE_ATTRIBUTE_NORMAL,
        _FILE_SHARE_ALL,
        _FILE_OPEN,
        (
            _FILE_DIRECTORY_FILE if directory else _FILE_NON_DIRECTORY_FILE
        ) | _FILE_SYNCHRONOUS_IO_NONALERT,
        None,
        0,
    )
    code = int(result) & 0xFFFFFFFF
    return (int(output.value), 0) if code == 0 else (None, code)


def _delete_relative(parent_handle: int, name: str) -> None:
    handle, _ = _open_relative(
        parent_handle,
        name,
        _DELETE | _SYNCHRONIZE,
    )
    if handle is not None:
        mark_delete(handle)
        _CloseHandle(handle)


def rename_relative(
    source_handle: int,
    parent_handle: int,
    name: str,
    *,
    replace_existing: bool,
) -> int:
    """Rename an open file relative to a retained directory handle."""
    encoded = name.encode("utf-16-le")
    offset = _FileRenameInformationEx.FileName.offset
    buffer = ctypes.create_string_buffer(offset + len(encoded) + 2)
    information = _FileRenameInformationEx.from_buffer(buffer)
    information.Flags = (
        _POSIX_SEMANTICS | _REPLACE_IF_EXISTS if replace_existing else 0
    )
    information.RootDirectory = parent_handle
    information.FileNameLength = len(encoded)
    ctypes.memmove(ctypes.addressof(buffer) + offset, encoded, len(encoded))
    status = _IoStatusBlock()
    result = _NtSetInformationFile(
        source_handle,
        ctypes.byref(status),
        buffer,
        len(buffer),
        _FILE_RENAME_INFO_EX,
    )
    return int(result) & 0xFFFFFFFF


__all__ = [
    "create_relative",
    "flush_handle",
    "mark_delete",
    "rename_relative",
    "replace_cas",
    "verify_relative",
    "write_all",
]

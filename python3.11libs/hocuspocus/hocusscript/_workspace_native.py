"""Private descriptor-aware native filesystem boundary for workspace I/O."""
from __future__ import annotations
import ctypes
import hashlib
import os
import secrets
import stat
import sys
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from ._workspace_boundary_types import (
    NativeRootInfo,
    NativeWorkspaceError,
    NativeWorkspaceMissing,
)
if os.name == "posix" and sys.platform.startswith("linux"):
    from ._workspace_linux import (
        PosixIdentity as _PosixIdentity,
        RecoveryRequired as _LinuxRecoveryRequired,
        canonical_root as _canonical_posix_root,
        close_publication as _linux_close_publication,
        fail_recovery as _linux_fail_recovery,
        inspect_regular as _linux_inspect_regular,
        local_filesystem_name as _linux_filesystem_name,
        open_beneath as _linux_open,
        open_child_directory as _open_posix_child_directory,
        open_root as _posix_open_directory_path,
        publication_guard as _linux_publication_guard,
        publish_transaction as _linux_publish_transaction,
        read_descriptor as _read_posix_fd,
        require_safe_file as _require_safe_posix_file,
        require_safe_object as _require_safe_posix_object,
        strong_root_identity as _linux_strong_root_identity,
        write_temporary as _write_posix_temp,
    )
_ROOT_DIGEST_DOMAIN = b"hocus.workspace.root.v1\0"
_OBJECT_DIGEST_DOMAIN = b"hocus.workspace.object.v1\0"
_READ_CHUNK = 64 * 1024
class _Provider(Protocol):
    root_info: NativeRootInfo
    def close(self) -> None: ...
    def assert_current(self) -> None: ...
    def read(self, parts: tuple[str, ...], max_bytes: int) -> bytes: ...
    def inspect_identity(self, parts: tuple[str, ...]) -> str: ...
    def enumerate_files(
        self,
        directory_parts: tuple[str, ...],
        *,
        max_files: int,
        max_depth: int,
        file_suffix: str,
        excluded_directories: frozenset[str],
    ) -> tuple[str, ...]: ...
    def publish(
        self,
        parts: tuple[str, ...],
        content: bytes,
        *,
        expected_digest: str | None,
        create: bool,
    ) -> bytes: ...
class PinnedWorkspace:
    """Platform-selected pinned root with sanitized, relative-only operations."""
    def __init__(self, root: Path):
        if os.name == "nt":
            self._provider: _Provider = _WindowsProvider(root)
        elif os.name == "posix" and sys.platform.startswith("linux"):
            self._provider = _PosixProvider(root)
        else:
            raise NativeWorkspaceError(
                "HOCUS822", "Workspace I/O is unsupported on this host platform."
            )
    @property
    def root_info(self) -> NativeRootInfo:
        return self._provider.root_info
    def close(self) -> None:
        self._provider.close()
    def assert_current(self) -> None:
        self._provider.assert_current()
    def read(self, parts: tuple[str, ...], max_bytes: int) -> bytes:
        return self._provider.read(parts, max_bytes)
    def inspect_identity(self, parts: tuple[str, ...]) -> str:
        return self._provider.inspect_identity(parts)
    def enumerate_files(
        self,
        directory_parts: tuple[str, ...],
        *,
        max_files: int,
        max_depth: int,
        file_suffix: str = "",
        excluded_directories: frozenset[str] = frozenset(),
    ) -> tuple[str, ...]:
        return self._provider.enumerate_files(
            directory_parts,
            max_files=max_files,
            max_depth=max_depth,
            file_suffix=file_suffix,
            excluded_directories=excluded_directories,
        )
    def publish(
        self,
        parts: tuple[str, ...],
        content: bytes,
        *,
        expected_digest: str | None,
        create: bool,
    ) -> bytes:
        return self._provider.publish(
            parts, content, expected_digest=expected_digest, create=create
        )
    def __enter__(self) -> PinnedWorkspace:
        return self
    def __exit__(self, *_args: object) -> None:
        self.close()
def _digest(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()
def _identity_digest(fields: tuple[int, ...]) -> str:
    encoded = "|".join(str(value) for value in fields).encode("ascii")
    return "sha256:" + hashlib.sha256(_ROOT_DIGEST_DOMAIN + encoded).hexdigest()
def _object_identity_digest(fields: tuple[int, ...]) -> str:
    encoded = "|".join(str(value) for value in fields).encode("ascii")
    return "sha256:" + hashlib.sha256(_OBJECT_DIGEST_DOMAIN + encoded).hexdigest()
def _publication_temp_name() -> str:
    return f".hocus-write-{secrets.token_hex(16)}.tmp"
class _PosixProvider:
    def __init__(self, root: Path):
        self._require_primitives()
        self._root_path = _canonical_posix_root(root)
        self._root_fd = _posix_open_directory_path(self._root_path)
        try:
            probe = _linux_open(
                self._root_fd,
                ".",
                os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC,
            )
            os.close(probe)
        except OSError as exc:
            os.close(self._root_fd)
            raise NativeWorkspaceError(
                "HOCUS822", "Required openat2 resolution semantics are unavailable."
            ) from exc
        root_stat = os.fstat(self._root_fd)
        if not stat.S_ISDIR(root_stat.st_mode):
            os.close(self._root_fd)
            raise NativeWorkspaceError("HOCUS822", "Approved workspace root is not a directory.")
        filesystem = _linux_filesystem_name(self._root_fd)
        if filesystem is None:
            os.close(self._root_fd)
            raise NativeWorkspaceError(
                "HOCUS822", "Workspace root filesystem is unsupported or nonlocal."
            )
        try:
            self._strong_root_identity = _linux_strong_root_identity(self._root_fd)
        except Exception:
            os.close(self._root_fd)
            raise
        self._root_identity = _PosixIdentity.from_stat(root_stat)
        self.root_info = NativeRootInfo(
            _identity_digest(self._strong_root_identity), "linux", filesystem
        )
        self.assert_current()
    @staticmethod
    def _require_primitives() -> None:
        required = (
            hasattr(os, "O_NOFOLLOW"),
            os.stat in os.supports_dir_fd,
            os.unlink in os.supports_dir_fd,
            os.rename in os.supports_dir_fd,
        )
        if not all(required):
            raise NativeWorkspaceError(
                "HOCUS822", "Required descriptor-relative filesystem primitives are unavailable."
            )
    def close(self) -> None:
        if self._root_fd >= 0:
            os.close(self._root_fd)
            self._root_fd = -1
    def assert_current(self) -> None:
        if self._root_fd < 0:
            raise NativeWorkspaceError("HOCUS822", "Workspace root authority is closed.")
        try:
            current_fd = _posix_open_directory_path(self._root_path)
            try:
                current = _PosixIdentity.from_stat(os.fstat(current_fd))
                pinned = _PosixIdentity.from_stat(os.fstat(self._root_fd))
                current_strong = _linux_strong_root_identity(current_fd)
                pinned_strong = _linux_strong_root_identity(self._root_fd)
            finally:
                os.close(current_fd)
        except OSError as exc:
            raise NativeWorkspaceError(
                "HOCUS824", "Workspace root authority is no longer safely reachable."
            ) from exc
        if current.object_key != self._root_identity.object_key:
            raise NativeWorkspaceError("HOCUS824", "Workspace root identity changed.")
        if pinned.object_key != self._root_identity.object_key:
            raise NativeWorkspaceError("HOCUS824", "Pinned workspace root identity changed.")
        if len({self._strong_root_identity, current_strong, pinned_strong}) != 1:
            raise NativeWorkspaceError("HOCUS824", "Workspace root generation changed.")
    def read(self, parts: tuple[str, ...], max_bytes: int) -> bytes:
        self.assert_current()
        with ExitStack() as stack:
            file_fd, identities = self._open_chain(parts, stack, final_directory=False)
            before = _PosixIdentity.from_stat(os.fstat(file_fd))
            _require_safe_posix_file(before, self._root_identity.device)
            content = _read_posix_fd(file_fd, max_bytes, before.size)
            after = _PosixIdentity.from_stat(os.fstat(file_fd))
            if before != after:
                raise NativeWorkspaceError("HOCUS824", "Workspace file changed during read.")
            self._verify_chain(parts, identities)
        self.assert_current()
        return content
    def inspect_identity(self, parts: tuple[str, ...]) -> str:
        self.assert_current()
        with ExitStack() as stack:
            file_fd, identities = self._open_chain(
                parts, stack, final_directory=False
            )
            identity = _PosixIdentity.from_stat(os.fstat(file_fd))
            _require_safe_posix_file(identity, self._root_identity.device)
            self._verify_chain(parts, identities)
        self.assert_current()
        return _object_identity_digest((identity.device, identity.inode))
    def enumerate_files(
        self,
        directory_parts: tuple[str, ...],
        *,
        max_files: int,
        max_depth: int,
        file_suffix: str,
        excluded_directories: frozenset[str],
    ) -> tuple[str, ...]:
        self.assert_current()
        with ExitStack() as stack:
            directory_fd, identities = self._open_chain(
                directory_parts, stack, final_directory=True
            )
            output = self._scan_directory(
                directory_fd,
                prefix=directory_parts,
                max_files=max_files,
                max_depth=max_depth,
                file_suffix=file_suffix,
                excluded_directories=excluded_directories,
            )
            self._verify_chain(directory_parts, identities)
        self.assert_current()
        return tuple(output)
    def publish(
        self,
        parts: tuple[str, ...],
        content: bytes,
        *,
        expected_digest: str | None,
        create: bool,
    ) -> bytes:
        return self._publish_locked(
            parts, content, expected_digest=expected_digest, create=create
        )
    def _publish_locked(
        self,
        parts: tuple[str, ...],
        content: bytes,
        *,
        expected_digest: str | None,
        create: bool,
    ) -> bytes:
        return _linux_publication_guard(
            self._root_fd,
            lambda: self._publish_guarded(
                parts, content, expected_digest=expected_digest, create=create
            ),
        )

    def _publish_guarded(
        self,
        parts: tuple[str, ...],
        content: bytes,
        *,
        expected_digest: str | None,
        create: bool,
    ) -> bytes:
        self.assert_current()
        parent_parts, name = parts[:-1], parts[-1]
        stack, committed = ExitStack(), False
        try:
            parent_fd, identities = self._open_chain(
                parent_parts, stack, final_directory=True
            )
            mode = 0o600
            existing_key: tuple[int, int, int] | None = None
            if not create:
                if expected_digest is None:
                    raise NativeWorkspaceError("HOCUS826", "Workspace file digest conflict.")
                try:
                    mode, existing_key = _linux_inspect_regular(
                        parent_fd, name, self._root_identity.device
                    )
                except OSError as exc:
                    raise NativeWorkspaceError(
                        "HOCUS824", "Workspace target cannot be safely opened."
                    ) from exc
            temp_name = _publication_temp_name()
            _write_posix_temp(parent_fd, temp_name, content, mode)
            try:
                matched = _linux_publish_transaction(
                    parent_fd,
                    temp_name,
                    name,
                    content,
                    create=create,
                    expected_digest=expected_digest,
                    expected_identity=existing_key,
                    max_bytes=max(len(content), 16 * 1024 * 1024),
                    verify_namespace=lambda: (
                        self._verify_chain(parent_parts, identities),
                        self.assert_current(),
                    ),
                    recovery_context=(
                        self._root_fd,
                        "/".join(parts),
                        "/".join(parent_parts),
                    ),
                )
                if not matched:
                    raise NativeWorkspaceError(
                        "HOCUS826", "Workspace file digest conflict."
                    )
                committed = True
            except _LinuxRecoveryRequired as exc:
                _linux_fail_recovery(
                    self._root_fd, "/".join(parts), "/".join(parent_parts), exc
                )
            except FileExistsError as exc:
                raise NativeWorkspaceError(
                    "HOCUS826", "Workspace create target already exists."
                ) from exc
            except OSError as exc:
                raise NativeWorkspaceError("HOCUS828", "Workspace publication failed.") from exc
        finally:
            _linux_close_publication(stack.close, committed)
        return content

    def _open_chain(
        self,
        parts: tuple[str, ...],
        stack: ExitStack,
        *,
        final_directory: bool,
    ) -> tuple[int, tuple[_PosixIdentity, ...]]:
        current_fd = os.dup(self._root_fd)
        stack.callback(os.close, current_fd)
        identities: list[_PosixIdentity] = []
        for index, part in enumerate(parts):
            is_directory = index < len(parts) - 1 or final_directory
            flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW
            if is_directory:
                flags |= os.O_DIRECTORY
            try:
                next_fd = _linux_open(current_fd, part, flags)
            except FileNotFoundError as exc:
                raise NativeWorkspaceMissing() from exc
            except OSError as exc:
                raise NativeWorkspaceError(
                    "HOCUS824", "Workspace path cannot be opened without traversal."
                ) from exc
            stack.callback(os.close, next_fd)
            identity = _PosixIdentity.from_stat(os.fstat(next_fd))
            _require_safe_posix_object(
                identity, self._root_identity.device, directory=is_directory
            )
            identities.append(identity)
            current_fd = next_fd
        return current_fd, tuple(identities)

    def _verify_chain(
        self,
        parts: tuple[str, ...],
        expected: tuple[_PosixIdentity, ...],
    ) -> None:
        if not parts:
            return
        with ExitStack() as stack:
            _, current = self._open_chain(
                parts,
                stack,
                final_directory=stat.S_ISDIR(expected[-1].mode),
            )
        if tuple(item.object_key for item in current) != tuple(
            item.object_key for item in expected
        ):
            raise NativeWorkspaceError("HOCUS824", "Workspace path identity changed.")

    def _scan_directory(
        self,
        directory_fd: int,
        *,
        prefix: tuple[str, ...],
        max_files: int,
        max_depth: int,
        file_suffix: str,
        excluded_directories: frozenset[str],
    ) -> list[str]:
        output: list[str] = []
        pending: list[tuple[int, tuple[str, ...], int]] = [(os.dup(directory_fd), prefix, 0)]
        try:
            while pending:
                current_fd, current_prefix, depth = pending.pop()
                try:
                    children = sorted(os.scandir(current_fd), key=lambda item: item.name.casefold())
                    self._scan_children(
                        children,
                        current_fd,
                        current_prefix,
                        depth,
                        max_depth,
                        max_files,
                        file_suffix,
                        excluded_directories,
                        output,
                        pending,
                    )
                finally:
                    os.close(current_fd)
        finally:
            for fd, _, _ in pending:
                os.close(fd)
        return output

    def _scan_children(
        self,
        children: list[os.DirEntry[str]],
        current_fd: int,
        prefix: tuple[str, ...],
        depth: int,
        max_depth: int,
        max_files: int,
        file_suffix: str,
        excluded_directories: frozenset[str],
        output: list[str],
        pending: list[tuple[int, tuple[str, ...], int]],
    ) -> None:
        for child in children:
            child_parts = (*prefix, child.name)
            try:
                child_stat = child.stat(follow_symlinks=False)
            except OSError as exc:
                raise NativeWorkspaceError(
                    "HOCUS824", "Workspace enumeration encountered an unstable object."
                ) from exc
            identity = _PosixIdentity.from_stat(child_stat)
            if stat.S_ISLNK(identity.mode):
                raise NativeWorkspaceError(
                    "HOCUS824", "Workspace enumeration rejects symbolic links."
                )
            if stat.S_ISDIR(identity.mode):
                if child.name.casefold() in excluded_directories:
                    continue
                if depth >= max_depth:
                    raise NativeWorkspaceError("HOCUS825", "Workspace directory depth exceeds limit.")
                fd = _open_posix_child_directory(
                    current_fd, child.name, self._root_identity.device
                )
                pending.append((fd, child_parts, depth + 1))
                continue
            _require_safe_posix_object(
                identity, self._root_identity.device, directory=False
            )
            if not file_suffix or child.name.casefold().endswith(file_suffix):
                if identity.links != 1:
                    raise NativeWorkspaceError(
                        "HOCUS824", "Workspace files with hard links are rejected."
                    )
                output.append("/".join(child_parts))
                if len(output) > max_files:
                    raise NativeWorkspaceError("HOCUS825", "Workspace file count exceeds limit.")
if os.name == "nt":
    from ctypes import wintypes
    from ._workspace_windows_rename import (
        create_relative as _create_relative,
        close_publication as _windows_close_publication,
        flush_handle as _flush_windows_handle,
        mark_delete as _mark_delete,
        publish_create_transaction as _windows_publish_create,
        publication_guard as _windows_publication_guard,
        recovery_guard as _windows_recovery_guard,
        replace_cas as _replace_windows_cas,
        write_all as _write_all,
    )

    _GENERIC_READ = 0x80000000
    _GENERIC_WRITE = 0x40000000
    _DELETE = 0x00010000
    _FILE_WRITE_ATTRIBUTES = 0x00000100
    _FILE_SHARE_READ = 0x00000001
    _FILE_SHARE_WRITE = 0x00000002
    _FILE_SHARE_DELETE = 0x00000004
    _OPEN_EXISTING = 3
    _FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
    _FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
    _FILE_ATTRIBUTE_DIRECTORY = 0x00000010
    _FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
    _FILE_TYPE_DISK = 0x0001
    _INVALID_HANDLE = ctypes.c_void_p(-1).value

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

    _KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _CreateFileW = _KERNEL32.CreateFileW
    _CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    _CreateFileW.restype = wintypes.HANDLE
    _CloseHandle = _KERNEL32.CloseHandle
    _CloseHandle.argtypes = [wintypes.HANDLE]
    _CloseHandle.restype = wintypes.BOOL
    _GetFileInformationByHandle = _KERNEL32.GetFileInformationByHandle
    _GetFileInformationByHandle.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(_ByHandleFileInformation),
    ]
    _GetFileInformationByHandle.restype = wintypes.BOOL
    _GetFinalPathNameByHandleW = _KERNEL32.GetFinalPathNameByHandleW
    _GetFinalPathNameByHandleW.argtypes = [
        wintypes.HANDLE,
        wintypes.LPWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
    ]
    _GetFinalPathNameByHandleW.restype = wintypes.DWORD
    _GetFileType = _KERNEL32.GetFileType
    _GetFileType.argtypes = [wintypes.HANDLE]
    _GetFileType.restype = wintypes.DWORD
    _ReadFile = _KERNEL32.ReadFile
    _ReadFile.argtypes = [
        wintypes.HANDLE,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPVOID,
    ]
    _ReadFile.restype = wintypes.BOOL
    _GetVolumePathNameW = _KERNEL32.GetVolumePathNameW
    _GetVolumePathNameW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
    _GetVolumePathNameW.restype = wintypes.BOOL
    _GetVolumeInformationW = _KERNEL32.GetVolumeInformationW
    _GetVolumeInformationW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.LPWSTR,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPWSTR,
        wintypes.DWORD,
    ]
    _GetVolumeInformationW.restype = wintypes.BOOL
@dataclass(frozen=True, slots=True)
class _WindowsIdentity:
    volume: int
    index: int
    attributes: int
    size: int
    links: int
    write_time: int
    @property
    def object_key(self) -> tuple[int, int, int]:
        return self.volume, self.index, self.attributes
    @property
    def is_directory(self) -> bool:
        return bool(self.attributes & _FILE_ATTRIBUTE_DIRECTORY)
    @property
    def is_reparse(self) -> bool:
        return bool(self.attributes & _FILE_ATTRIBUTE_REPARSE_POINT)

    @property
    def fields(self) -> tuple[int, int, int, int, int, int]:
        return self.volume, self.index, self.attributes, self.size, self.links, self.write_time


class _WindowsHandle:
    def __init__(self, value: int):
        self.value = value

    def close(self) -> None:
        if self.value != _INVALID_HANDLE:
            _CloseHandle(self.value)
            self.value = _INVALID_HANDLE

    def __enter__(self) -> _WindowsHandle:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


class _WindowsProvider:
    def __init__(self, root: Path):
        if os.name != "nt":
            raise NativeWorkspaceError("HOCUS822", "Windows provider is unavailable.")
        self._root_path = _canonical_windows_root(root)
        filesystem = _windows_filesystem(self._root_path)
        if filesystem.casefold() != "ntfs":
            raise NativeWorkspaceError("HOCUS822", "Workspace root must reside on local NTFS.")
        try:
            _verify_windows_root_chain(self._root_path)
            self._root_handle = _open_windows_handle(self._root_path, directory=True)
        except NativeWorkspaceMissing as exc:
            raise NativeWorkspaceError(
                "HOCUS822", "Approved workspace root is unavailable."
            ) from exc
        self._root_identity = _windows_identity(self._root_handle)
        _require_safe_windows_object(self._root_identity, None, directory=True)
        self._root_final = _windows_final_path(self._root_handle)
        self.root_info = NativeRootInfo(
            _identity_digest(self._root_identity.object_key), "windows", "NTFS"
        )
        self.assert_current()

    def close(self) -> None:
        self._root_handle.close()

    def assert_current(self) -> None:
        if self._root_handle.value == _INVALID_HANDLE:
            raise NativeWorkspaceError("HOCUS822", "Workspace root authority is closed.")
        with _open_windows_handle(self._root_path, directory=True) as current:
            identity = _windows_identity(current)
            final = _windows_final_path(current)
        if identity.object_key != self._root_identity.object_key or final != self._root_final:
            raise NativeWorkspaceError("HOCUS824", "Workspace root identity changed.")
        if _windows_identity(self._root_handle).object_key != self._root_identity.object_key:
            raise NativeWorkspaceError("HOCUS824", "Pinned workspace root identity changed.")

    def read(self, parts: tuple[str, ...], max_bytes: int) -> bytes:
        self.assert_current()
        handles, identities = self._open_chain(parts, final_directory=False)
        try:
            final = handles[-1]
            before = _windows_identity(final)
            _require_safe_windows_object(
                before, self._root_identity.volume, directory=False
            )
            content = _read_windows_handle(final, max_bytes, before.size)
            if _windows_identity(final) != before:
                raise NativeWorkspaceError("HOCUS824", "Workspace file changed during read.")
            self._verify_chain(parts, identities)
        finally:
            for handle in reversed(handles):
                handle.close()
        self.assert_current()
        return content

    def inspect_identity(self, parts: tuple[str, ...]) -> str:
        self.assert_current()
        handles, identities = self._open_chain(parts, final_directory=False)
        try:
            identity = _windows_identity(handles[-1])
            _require_safe_windows_object(
                identity, self._root_identity.volume, directory=False
            )
            self._verify_chain(parts, identities)
        finally:
            for handle in reversed(handles):
                handle.close()
        self.assert_current()
        return _object_identity_digest((identity.volume, identity.index))

    def enumerate_files(
        self,
        directory_parts: tuple[str, ...],
        *,
        max_files: int,
        max_depth: int,
        file_suffix: str,
        excluded_directories: frozenset[str],
    ) -> tuple[str, ...]:
        self.assert_current()
        handles, identities = self._open_chain(directory_parts, final_directory=True)
        try:
            output = self._scan_windows(
                self._root_path.joinpath(*directory_parts),
                prefix=directory_parts,
                max_files=max_files,
                max_depth=max_depth,
                file_suffix=file_suffix,
                excluded_directories=excluded_directories,
            )
            self._verify_chain(directory_parts, identities)
        finally:
            for handle in reversed(handles):
                handle.close()
        self.assert_current()
        return tuple(output)

    def publish(
        self,
        parts: tuple[str, ...],
        content: bytes,
        *,
        expected_digest: str | None,
        create: bool,
    ) -> bytes:
        return self._publish_locked(
            parts, content, expected_digest=expected_digest, create=create
        )

    def _publish_locked(
        self,
        parts: tuple[str, ...],
        content: bytes,
        *,
        expected_digest: str | None,
        create: bool,
    ) -> bytes:
        return _windows_publication_guard(
            self._root_handle.value,
            lambda recovery_root: self._publish_guarded(
                parts,
                content,
                expected_digest=expected_digest,
                create=create,
                recovery_root=recovery_root,
            ),
        )

    def _publish_guarded(
        self,
        parts: tuple[str, ...],
        content: bytes,
        *,
        expected_digest: str | None,
        create: bool,
        recovery_root: int,
    ) -> bytes:
        self.assert_current()
        parent_parts = parts[:-1]
        handles, identities = self._open_chain(parent_parts, final_directory=True)
        temp_handle: _WindowsHandle | None = None
        publication_parent: _WindowsHandle | None = None
        namespace_guards: list[_WindowsHandle] = []
        renamed = False
        try:
            expected_parent = identities[-1] if identities else self._root_identity
            publication_parent = _open_windows_handle(
                self._root_path.joinpath(*parent_parts), directory=True, access=_GENERIC_READ | _GENERIC_WRITE
            )
            if _windows_identity(publication_parent).object_key != expected_parent.object_key:
                raise NativeWorkspaceError("HOCUS824", "Workspace parent identity changed.")
            parent_handle = publication_parent
            namespace_guards = self._open_namespace_guards(parent_parts, identities)
            temp_handle = _create_windows_temp(parent_handle, content)
            replacement_identity = _windows_identity(temp_handle)
            replacement_digest = _digest(content)
            self._verify_chain(parent_parts, identities)
            operation = (
                (lambda: _windows_publish_create(
                    parent_handle.value, temp_handle.value, parts[-1],
                    replacement_identity.fields, replacement_digest, content,
                    lambda: self._verify_chain(parent_parts, identities),
                ))
                if create
                else (lambda: self._replace_target(
                    parts, parent_handle, temp_handle, expected_digest,
                    replacement_identity, replacement_digest, max(len(content), 1),
                    recovery_root,
                ))
            )
            _windows_recovery_guard(
                recovery_root, "/".join(parts),
                "/".join(parent_parts), operation,
            )
            renamed = True
        finally:
            if temp_handle is not None:
                rollback_create = temp_handle.value != _INVALID_HANDLE and not renamed
                if rollback_create:
                    _mark_delete(temp_handle.value)
                _windows_close_publication(temp_handle.close, renamed)
                if rollback_create and publication_parent is not None:
                    _flush_windows_handle(publication_parent.value)
            for guard in reversed(namespace_guards):
                _windows_close_publication(guard.close, renamed)
            if publication_parent is not None:
                _windows_close_publication(publication_parent.close, renamed)
            for handle in reversed(handles):
                _windows_close_publication(handle.close, renamed)
        return content

    def _replace_target(
        self,
        parts: tuple[str, ...],
        parent: _WindowsHandle,
        temporary: _WindowsHandle,
        expected_digest: str | None,
        replacement_identity: _WindowsIdentity,
        replacement_digest: str,
        replacement_size: int,
        recovery_root: int,
    ) -> None:
        if expected_digest is None:
            raise NativeWorkspaceError("HOCUS826", "Workspace file digest conflict.")
        handles, identities = self._open_chain(parts, final_directory=False)
        target: _WindowsHandle | None = None
        try:
            target = _open_windows_handle(
                self._root_path.joinpath(*parts),
                directory=False,
                access=(
                    _GENERIC_READ
                    | _GENERIC_WRITE
                    | _DELETE
                    | _FILE_WRITE_ATTRIBUTES
                ),
            )
            if _windows_identity(target) != identities[-1]:
                raise NativeWorkspaceError("HOCUS826", "Workspace file digest conflict.")
            expected_identity = _windows_identity(target)
            self._verify_chain(parts, identities)
            for handle in reversed(handles):
                handle.close()
            handles.clear()
            target.close()
            temporary_path = _windows_final_path(temporary)
            temporary.close()
            status, _native_error = _replace_windows_cas(
                parent.value,
                temporary_path,
                parts[-1],
                expected_digest,
                16 * 1024 * 1024,
                expected_identity.fields,
                replacement_identity.fields,
                replacement_digest,
                replacement_size,
                recovery_root,
                "/".join(parts),
                "/".join(parts[:-1]),
            )
            if status != "ok":
                code = "HOCUS826" if status == "conflict" else "HOCUS828"
                message = (
                    "Workspace file digest conflict."
                    if status == "conflict"
                    else "Workspace publication failed."
                )
                raise NativeWorkspaceError(code, message)
        finally:
            if target is not None:
                target.close()
            for handle in reversed(handles):
                handle.close()

    def _open_namespace_guards(self, parent_parts: tuple[str, ...], expected: tuple[_WindowsIdentity, ...]) -> list[_WindowsHandle]:
        drive, tail = os.path.splitdrive(str(self._root_path))
        current = Path(drive + "\\")
        paths = [current]
        for part in (item for item in tail.split("\\") if item):
            current /= part
            paths.append(current)
        root_index = len(paths) - 1
        for part in parent_parts:
            current /= part
            paths.append(current)
        guards: list[_WindowsHandle] = []
        try:
            for index, path in enumerate(paths):
                guard = _open_windows_handle(path, directory=True, share_mode=_FILE_SHARE_READ | _FILE_SHARE_WRITE)
                guards.append(guard)
                identity = _windows_identity(guard)
                _require_safe_windows_object(identity, self._root_identity.volume, directory=True)
                if index == root_index:
                    root_changed = (
                        identity.object_key != self._root_identity.object_key
                        or _windows_final_path(guard) != self._root_final
                    )
                    if root_changed:
                        raise NativeWorkspaceError("HOCUS824", "Workspace root identity changed.")
                elif index > root_index:
                    relative_index = index - root_index - 1
                    if identity.object_key != expected[relative_index].object_key:
                        raise NativeWorkspaceError("HOCUS824", "Workspace parent identity changed.")
                    _require_windows_contained(_windows_final_path(guard), self._root_final)
        except Exception:
            for guard in reversed(guards):
                guard.close()
            raise
        return guards

    def _open_chain(
        self,
        parts: tuple[str, ...],
        *,
        final_directory: bool,
    ) -> tuple[list[_WindowsHandle], tuple[_WindowsIdentity, ...]]:
        handles: list[_WindowsHandle] = []
        identities: list[_WindowsIdentity] = []
        try:
            for index in range(len(parts)):
                is_directory = index < len(parts) - 1 or final_directory
                handle = _open_windows_handle(
                    self._root_path.joinpath(*parts[: index + 1]), directory=is_directory
                )
                identity = _windows_identity(handle)
                _require_safe_windows_object(
                    identity, self._root_identity.volume, directory=is_directory
                )
                _require_windows_contained(_windows_final_path(handle), self._root_final)
                handles.append(handle)
                identities.append(identity)
        except Exception:
            for handle in reversed(handles):
                handle.close()
            raise
        return handles, tuple(identities)

    def _verify_chain(
        self,
        parts: tuple[str, ...],
        expected: tuple[_WindowsIdentity, ...],
    ) -> None:
        if not parts:
            return
        handles, current = self._open_chain(
            parts, final_directory=expected[-1].is_directory
        )
        for handle in reversed(handles):
            handle.close()
        if tuple(item.object_key for item in current) != tuple(
            item.object_key for item in expected
        ):
            raise NativeWorkspaceError("HOCUS824", "Workspace path identity changed.")

    def _scan_windows(
        self,
        directory: Path,
        *,
        prefix: tuple[str, ...],
        max_files: int,
        max_depth: int,
        file_suffix: str,
        excluded_directories: frozenset[str],
    ) -> list[str]:
        output: list[str] = []
        pending: list[tuple[Path, tuple[str, ...], int]] = [(directory, prefix, 0)]
        while pending:
            native, portable_prefix, depth = pending.pop()
            try:
                children = sorted(os.scandir(native), key=lambda item: item.name.casefold())
            except OSError as exc:
                raise NativeWorkspaceError(
                    "HOCUS824", "Workspace directory cannot be safely enumerated."
                ) from exc
            for child in children:
                child_prefix = (*portable_prefix, child.name)
                with _open_windows_handle(
                    Path(child.path), directory=child.is_dir(follow_symlinks=False)
                ) as handle:
                    identity = _windows_identity(handle)
                    _require_safe_windows_object_type(
                        identity, self._root_identity.volume, require_single_link=False
                    )
                    _require_windows_contained(_windows_final_path(handle), self._root_final)
                if identity.is_directory:
                    if child.name.casefold() in excluded_directories:
                        continue
                    if depth >= max_depth:
                        raise NativeWorkspaceError(
                            "HOCUS825", "Workspace directory depth exceeds limit."
                        )
                    pending.append((Path(child.path), child_prefix, depth + 1))
                else:
                    if not file_suffix or child.name.casefold().endswith(file_suffix):
                        if identity.links != 1:
                            raise NativeWorkspaceError(
                                "HOCUS824", "Workspace files with hard links are rejected."
                            )
                        output.append("/".join(child_prefix))
                        if len(output) > max_files:
                            raise NativeWorkspaceError(
                                "HOCUS825", "Workspace file count exceeds limit."
                            )
        return output


def _canonical_windows_root(root: Path) -> Path:
    authored = str(root)
    drive, tail = os.path.splitdrive(authored)
    if (
        not root.is_absolute()
        or len(drive) != 2
        or drive[0] != drive[0].upper()
        or authored.startswith(("\\\\", "\\\\?\\", "\\\\.\\"))
        or "/" in authored
        or os.path.normpath(authored) != authored
        or not tail.startswith("\\")
    ):
        raise NativeWorkspaceError("HOCUS822", "Approved Windows workspace root is not canonical.")
    return root


def _open_windows_handle(
    path: Path,
    *,
    directory: bool,
    access: int | None = None,
    share_mode: int | None = None,
) -> _WindowsHandle:
    flags = _FILE_FLAG_OPEN_REPARSE_POINT
    if directory:
        flags |= _FILE_FLAG_BACKUP_SEMANTICS
    value = _CreateFileW(
        str(path),
        _GENERIC_READ if access is None else access,
        (
            _FILE_SHARE_READ | _FILE_SHARE_WRITE | _FILE_SHARE_DELETE
            if share_mode is None
            else share_mode
        ),
        None,
        _OPEN_EXISTING,
        flags,
        None,
    )
    if value == _INVALID_HANDLE:
        if ctypes.get_last_error() in {2, 3}:
            raise NativeWorkspaceMissing()
        raise NativeWorkspaceError("HOCUS824", "Workspace object cannot be safely opened.")
    return _WindowsHandle(value)


def _windows_identity(handle: _WindowsHandle) -> _WindowsIdentity:
    information = _ByHandleFileInformation()
    if not _GetFileInformationByHandle(handle.value, ctypes.byref(information)):
        raise NativeWorkspaceError("HOCUS824", "Workspace object identity cannot be inspected.")
    index = (information.nFileIndexHigh << 32) | information.nFileIndexLow
    size = (information.nFileSizeHigh << 32) | information.nFileSizeLow
    write_time = (
        information.ftLastWriteTime.dwHighDateTime << 32
    ) | information.ftLastWriteTime.dwLowDateTime
    return _WindowsIdentity(
        information.dwVolumeSerialNumber,
        index,
        information.dwFileAttributes,
        size,
        information.nNumberOfLinks,
        write_time,
    )


def _windows_final_path(handle: _WindowsHandle) -> str:
    size = _GetFinalPathNameByHandleW(handle.value, None, 0, 0)
    if not size or size > 32768:
        raise NativeWorkspaceError("HOCUS824", "Workspace object path cannot be verified.")
    buffer = ctypes.create_unicode_buffer(size + 1)
    written = _GetFinalPathNameByHandleW(handle.value, buffer, size + 1, 0)
    if not written or written > size:
        raise NativeWorkspaceError("HOCUS824", "Workspace object path cannot be verified.")
    return buffer.value.casefold().rstrip("\\")


def _windows_filesystem(root: Path) -> str:
    volume_path = ctypes.create_unicode_buffer(32768)
    if not _GetVolumePathNameW(str(root), volume_path, len(volume_path)):
        raise NativeWorkspaceError("HOCUS822", "Workspace volume cannot be inspected.")
    filesystem = ctypes.create_unicode_buffer(64)
    if not _GetVolumeInformationW(
        volume_path.value,
        None,
        0,
        None,
        None,
        None,
        filesystem,
        len(filesystem),
    ):
        raise NativeWorkspaceError("HOCUS822", "Workspace filesystem cannot be inspected.")
    return filesystem.value


def _verify_windows_root_chain(root: Path) -> None:
    drive, tail = os.path.splitdrive(str(root))
    current = Path(drive + "\\")
    for part in (item for item in tail.split("\\") if item):
        current /= part
        with _open_windows_handle(current, directory=True) as handle:
            identity = _windows_identity(handle)
            if identity.is_reparse or not identity.is_directory:
                raise NativeWorkspaceError(
                    "HOCUS822", "Approved workspace root contains a reparse component."
                )


def _require_safe_windows_object(
    identity: _WindowsIdentity,
    root_volume: int | None,
    *,
    directory: bool,
) -> None:
    if root_volume is not None and identity.volume != root_volume:
        raise NativeWorkspaceError("HOCUS824", "Workspace path crosses a volume boundary.")
    if identity.is_reparse or identity.is_directory != directory:
        raise NativeWorkspaceError("HOCUS824", "Workspace path contains an unsafe object type.")
    if not directory and identity.links != 1:
        raise NativeWorkspaceError("HOCUS824", "Workspace files with hard links are rejected.")


def _require_safe_windows_object_type(
    identity: _WindowsIdentity,
    root_volume: int,
    *,
    require_single_link: bool = True,
) -> None:
    if identity.is_directory:
        _require_safe_windows_object(identity, root_volume, directory=True)
        return
    if require_single_link:
        _require_safe_windows_object(identity, root_volume, directory=False)
        return
    if identity.volume != root_volume or identity.is_reparse or identity.is_directory:
        raise NativeWorkspaceError("HOCUS824", "Workspace path contains an unsafe object type.")


def _require_windows_contained(final_path: str, root_final: str) -> None:
    if final_path != root_final and not final_path.startswith(root_final + "\\"):
        raise NativeWorkspaceError("HOCUS824", "Workspace object escapes the pinned root.")


def _read_windows_handle(
    handle: _WindowsHandle,
    max_bytes: int,
    expected_size: int,
) -> bytes:
    if expected_size > max_bytes:
        raise NativeWorkspaceError("HOCUS825", "Workspace file exceeds the read limit.")
    if _GetFileType(handle.value) != _FILE_TYPE_DISK:
        raise NativeWorkspaceError("HOCUS824", "Workspace object is not a disk file.")
    chunks: list[bytes] = []
    remaining = max_bytes + 1
    while remaining:
        size = min(_READ_CHUNK, remaining)
        buffer = ctypes.create_string_buffer(size)
        received = wintypes.DWORD()
        if not _ReadFile(handle.value, buffer, size, ctypes.byref(received), None):
            raise NativeWorkspaceError("HOCUS825", "Workspace file read failed.")
        if not received.value:
            break
        chunks.append(buffer.raw[: received.value])
        remaining -= received.value
    content = b"".join(chunks)
    if len(content) > max_bytes:
        raise NativeWorkspaceError("HOCUS825", "Workspace file exceeds the read limit.")
    return content


def _create_windows_temp(
    parent: _WindowsHandle,
    content: bytes,
) -> _WindowsHandle:
    for _ in range(4):
        name = _publication_temp_name()
        value, status = _create_relative(parent.value, name)
        if value is None and status == 0xC0000035:
            continue
        if value is None:
            raise NativeWorkspaceError("HOCUS828", "Workspace temporary publication failed.")
        handle = _WindowsHandle(value)
        if _write_all(handle.value, content) == 0:
            return handle
        _mark_delete(handle.value)
        handle.close()
        raise NativeWorkspaceError("HOCUS828", "Workspace temporary publication failed.")
    raise NativeWorkspaceError("HOCUS828", "Workspace temporary publication failed.")


__all__ = [
    "NativeRootInfo",
    "NativeWorkspaceError",
    "NativeWorkspaceMissing",
    "PinnedWorkspace",
]

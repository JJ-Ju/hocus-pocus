"""Handle-relative Windows cleanup for governed HS8 installations.

This module is intentionally self-contained so a build transaction can
authenticate its source bytes, execute them in a private module, and invoke the
two cleanup phases without trusting code from the installation being removed.
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import re
import unicodedata
from ctypes import wintypes
from pathlib import Path
from typing import Any, Mapping, NamedTuple


SCHEMA = "hocuspocus://schemas/install-manifest/v1"
MANIFEST_RELATIVE_PATH = "package/install-manifest-v1.json"
GOVERNED_ROOTS = (
    "config",
    "docs/schemas",
    "python_panels",
    "python3.11libs",
    "scripts",
    "toolbar",
    "package",
)
MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_MANIFEST_BYTES = 16 * 1024 * 1024
MAX_FILES = 20_000
MAX_ENTRIES = MAX_FILES * 4
_IDENTITY_PATTERN = re.compile(r"win-fileid-v1:[0-9a-f]{8}:[0-9a-f]{16}")
_DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")
_TOKEN_LINE = re.compile(rb'(?m)^token\s*=\s*"[^"]*"\s*$')


class WindowsManifestCleanupError(RuntimeError):
    """The native cleanup boundary could not prove a safe transition."""


class _Identity(NamedTuple):
    volume: int
    file_id: int
    attributes: int
    size: int
    links: int

    @property
    def durable(self) -> str:
        return f"win-fileid-v1:{self.volume:08x}:{self.file_id:016x}"


class _Entry(NamedTuple):
    name: str
    directory: bool
    attributes: int


class _Scan(NamedTuple):
    files: dict[str, tuple[_Identity, dict[str, Any]]]
    directories: dict[str, _Identity]


_IS_WINDOWS = os.name == "nt"
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
_FILE_ATTRIBUTE_DIRECTORY = 0x00000010
_FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
_FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
_FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
_OPEN_EXISTING = 3
_FILE_OPEN = 1
_FILE_DIRECTORY_FILE = 0x00000001
_FILE_NON_DIRECTORY_FILE = 0x00000040
_FILE_SYNCHRONOUS_IO_NONALERT = 0x00000020
_FILE_OPEN_REPARSE_POINT = 0x00200000
_FILE_ATTRIBUTE_NORMAL = 0x00000080
_FILE_SHARE_READ = 0x00000001
_OBJ_CASE_INSENSITIVE = 0x00000040
_DELETE = 0x00010000
_SYNCHRONIZE = 0x00100000
_FILE_LIST_DIRECTORY = 0x00000001
_FILE_READ_DATA = 0x00000001
_FILE_READ_ATTRIBUTES = 0x00000080
_FILE_DISPOSITION_INFORMATION = 13
_FILE_ID_BOTH_DIRECTORY_INFO = 10
_FILE_ID_BOTH_DIRECTORY_INFORMATION = 37
_ERROR_NO_MORE_FILES = 18
_STATUS_NO_MORE_FILES = 0x80000006
_MISSING_ERRORS = {2, 3, 18, 0xC0000034, 0xC000003A}
_BUFFER_BYTES = 64 * 1024


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


class _FileIdBothDirectoryInfo(ctypes.Structure):
    _fields_ = [
        ("NextEntryOffset", wintypes.DWORD),
        ("FileIndex", wintypes.DWORD),
        ("CreationTime", ctypes.c_longlong),
        ("LastAccessTime", ctypes.c_longlong),
        ("LastWriteTime", ctypes.c_longlong),
        ("ChangeTime", ctypes.c_longlong),
        ("EndOfFile", ctypes.c_longlong),
        ("AllocationSize", ctypes.c_longlong),
        ("FileAttributes", wintypes.DWORD),
        ("FileNameLength", wintypes.DWORD),
        ("EaSize", wintypes.DWORD),
        ("ShortNameLength", ctypes.c_ubyte),
        ("ShortName", wintypes.WCHAR * 12),
        ("FileId", ctypes.c_longlong),
        ("FileName", wintypes.WCHAR * 1),
    ]


if _IS_WINDOWS:
    _KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _NTDLL = ctypes.WinDLL("ntdll")
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
    _GetFileInformationByHandleEx = _KERNEL32.GetFileInformationByHandleEx
    _GetFileInformationByHandleEx.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    ]
    _GetFileInformationByHandleEx.restype = wintypes.BOOL
    _ReadFile = _KERNEL32.ReadFile
    _ReadFile.argtypes = [
        wintypes.HANDLE,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPVOID,
    ]
    _ReadFile.restype = wintypes.BOOL
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
    _NtQueryDirectoryFile = _NTDLL.NtQueryDirectoryFile
    _NtQueryDirectoryFile.argtypes = [
        wintypes.HANDLE,
        wintypes.HANDLE,
        wintypes.LPVOID,
        wintypes.LPVOID,
        ctypes.POINTER(_IoStatusBlock),
        wintypes.LPVOID,
        wintypes.ULONG,
        ctypes.c_int,
        wintypes.BOOLEAN,
        wintypes.LPVOID,
        wintypes.BOOLEAN,
    ]
    _NtQueryDirectoryFile.restype = ctypes.c_long


def governed_cleanup(
    root: str | Path,
    expected_digest: str,
    output_root_identity: str,
) -> dict[str, Any]:
    """Validate and remove the unchanged governed subset, retaining authority."""
    _require_windows()
    if (
        _DIGEST_PATTERN.fullmatch(expected_digest) is None
        or not isinstance(output_root_identity, str)
        or _IDENTITY_PATTERN.fullmatch(output_root_identity) is None
    ):
        raise WindowsManifestCleanupError("Cleanup transaction authority is invalid.")
    parent, root_handle, root_name = _pin_existing_root(
        root,
        output_root_identity,
    )
    package_handle: int | None = None
    try:
        root_identity = _require_identity(root_handle, directory=True)
        manifest = _read_manifest(root_handle)
        if manifest["manifestDigest"] != expected_digest:
            raise WindowsManifestCleanupError(
                "Cleanup manifest differs from transaction authority."
            )
        expected = {row["relativePath"]: row for row in manifest["files"]}
        scan = _scan_tree(root_handle, expected)
        package_identity = scan.directories.get("package")
        if package_identity is None:
            raise WindowsManifestCleanupError("Cleanup package directory is missing.")
        removed_files = _delete_files(root_handle, scan)
        removed_directories = _delete_directories(root_handle, scan)
        package_handle = _open_chain(root_handle, "package", scan.directories)
        _require_manifest_only(root_handle, package_handle)
        return {
            "kind": "hocus_native_manifest_cleanup_authority",
            "schemaVersion": 1,
            "phase": "governed",
            "manifestDigest": expected_digest,
            "outputRootIdentity": output_root_identity,
            "rootIdentity": root_identity.durable,
            "packageIdentity": package_identity.durable,
            "removedFiles": removed_files,
            "removedDirectories": removed_directories,
            "complete": False,
        }
    finally:
        _close(package_handle)
        _close(root_handle)
        _close(parent)
        del root_name


def terminal_cleanup(
    root: str | Path,
    authority: Mapping[str, object],
) -> dict[str, Any]:
    """Finish an authorized cleanup from any valid terminal suffix state."""
    _require_windows()
    checked = _validate_authority(authority)
    parent, root_handle, root_name = _pin_optional_root(
        root,
        checked["outputRootIdentity"],
    )
    if root_handle is None:
        _close(parent)
        return _terminal_receipt(checked, already_absent=True)
    try:
        root_identity = _require_identity(root_handle, directory=True)
        if root_identity.durable != checked["rootIdentity"]:
            raise WindowsManifestCleanupError("Cleanup root identity changed.")
        _terminal_existing_root(root_handle, checked)
        _mark_delete(root_handle)
        _close(root_handle)
        root_handle = None
        _require_relative_absent(parent, root_name)
        return _terminal_receipt(checked, already_absent=False)
    finally:
        _close(root_handle)
        _close(parent)


def _terminal_existing_root(
    root_handle: int,
    authority: dict[str, Any],
) -> None:
    entries = _list_entries(root_handle)
    if not entries:
        return
    if len(entries) != 1 or entries[0].name != "package" or not entries[0].directory:
        raise WindowsManifestCleanupError("Cleanup root has an invalid terminal suffix.")
    package = _open_relative_checked(root_handle, "package", directory=True)
    try:
        package_identity = _require_identity(package, directory=True)
        if package_identity.durable != authority["packageIdentity"]:
            raise WindowsManifestCleanupError("Cleanup package identity changed.")
        package_entries = _list_entries(package)
        if package_entries:
            _delete_terminal_manifest(package, package_entries, authority)
        if _list_entries(package):
            raise WindowsManifestCleanupError(
                "Cleanup package retained unexpected terminal entries."
            )
    finally:
        _close(package)
    _delete_open_child(root_handle, "package", package_identity, directory=True)


def _delete_terminal_manifest(
    package_handle: int,
    entries: list[_Entry],
    authority: dict[str, Any],
) -> None:
    expected_name = "install-manifest-v1.json"
    if len(entries) != 1 or entries[0].name != expected_name or entries[0].directory:
        raise WindowsManifestCleanupError(
            "Cleanup package retained unexpected terminal entries."
        )
    manifest_handle = _open_relative_checked(
        package_handle,
        expected_name,
        directory=False,
    )
    try:
        _require_identity(manifest_handle, directory=False)
        content = _read_all(manifest_handle, MAX_MANIFEST_BYTES)
        manifest = _decode_manifest(content)
        if manifest["manifestDigest"] != authority["manifestDigest"]:
            raise WindowsManifestCleanupError("Cleanup manifest authority changed.")
        _mark_delete(manifest_handle)
    finally:
        _close(manifest_handle)


def _scan_tree(
    root_handle: int,
    expected: dict[str, dict[str, Any]],
) -> _Scan:
    files: dict[str, tuple[_Identity, dict[str, Any]]] = {}
    directories: dict[str, _Identity] = {"": _require_identity(root_handle, True)}
    pending = [("", root_handle, False)]
    seen = 0
    try:
        while pending:
            prefix, directory, owned = pending.pop()
            for entry in _list_entries(directory):
                seen += 1
                if seen > MAX_ENTRIES:
                    raise WindowsManifestCleanupError(
                        "Cleanup tree contains too many entries."
                    )
                relative = f"{prefix}/{entry.name}" if prefix else entry.name
                child = _open_relative_checked(
                    directory,
                    entry.name,
                    directory=entry.directory,
                )
                identity = _require_identity(child, entry.directory)
                if entry.directory:
                    directories[relative] = identity
                    pending.append((relative, child, True))
                else:
                    row = expected.get(relative)
                    _validate_scanned_file(child, relative, row)
                    files[relative] = (identity, row)
                    _close(child)
            if owned:
                _close(directory)
    except Exception:
        for _, handle, owned in pending:
            if owned:
                _close(handle)
        raise
    allowed = {*expected, MANIFEST_RELATIVE_PATH}
    if not set(files).issubset(allowed):
        raise WindowsManifestCleanupError("Cleanup tree contains an undeclared file.")
    allowed_dirs = _allowed_directories(allowed)
    if not (set(directories) - {""}).issubset(allowed_dirs):
        raise WindowsManifestCleanupError(
            "Cleanup tree contains an undeclared directory."
        )
    return _Scan(files, directories)


def _validate_scanned_file(
    handle: int,
    relative: str,
    row: dict[str, Any] | None,
) -> None:
    if relative == MANIFEST_RELATIVE_PATH:
        return
    if row is None:
        raise WindowsManifestCleanupError("Cleanup tree contains an undeclared file.")
    content = _read_all(handle, MAX_FILE_BYTES)
    if relative == "config/default.toml":
        content = _canonical_config(content)
    actual = {
        "relativePath": relative,
        "role": "generated_config"
        if relative == "config/default.toml"
        else "immutable",
        "byteLength": len(content),
        "contentDigest": "sha256:" + hashlib.sha256(content).hexdigest(),
    }
    if actual != row:
        raise WindowsManifestCleanupError(
            "Cleanup tree contains a changed governed file."
        )


def _delete_files(root_handle: int, scan: _Scan) -> int:
    removed = 0
    for relative in sorted(scan.files, key=lambda item: item.casefold()):
        if relative == MANIFEST_RELATIVE_PATH:
            continue
        expected_identity, row = scan.files[relative]
        parent_relative, name = _split_parent(relative)
        parent = _open_chain(root_handle, parent_relative, scan.directories)
        child: int | None = None
        try:
            child = _open_relative_checked(parent, name, directory=False)
            if not _same_identity(
                _require_identity(child, False),
                expected_identity,
                directory=False,
            ):
                raise WindowsManifestCleanupError(
                    "Governed file identity changed during cleanup."
                )
            _validate_scanned_file(child, relative, row)
            _mark_delete(child)
            removed += 1
        finally:
            _close(child)
            if parent != root_handle:
                _close(parent)
    return removed


def _delete_directories(root_handle: int, scan: _Scan) -> int:
    removed = 0
    candidates = (
        relative
        for relative in scan.directories
        if relative not in {"", "package"}
    )
    for relative in sorted(
        candidates,
        key=lambda item: (-item.count("/"), item.casefold()),
    ):
        parent_relative, name = _split_parent(relative)
        parent = _open_chain(root_handle, parent_relative, scan.directories)
        try:
            expected = scan.directories[relative]
            _delete_open_child(parent, name, expected, directory=True)
            removed += 1
        finally:
            if parent != root_handle:
                _close(parent)
    return removed


def _delete_open_child(
    parent: int,
    name: str,
    expected: _Identity,
    *,
    directory: bool,
) -> None:
    child = _open_relative_checked(parent, name, directory=directory)
    try:
        if not _same_identity(
            _require_identity(child, directory),
            expected,
            directory=directory,
        ):
            raise WindowsManifestCleanupError("Cleanup component identity changed.")
        if directory and _list_entries(child):
            raise WindowsManifestCleanupError(
                "Cleanup directory is not empty at deletion."
            )
        _mark_delete(child)
    finally:
        _close(child)


def _open_chain(
    root_handle: int,
    relative: str,
    identities: dict[str, _Identity],
) -> int:
    if not relative:
        return root_handle
    current = root_handle
    prefix = ""
    try:
        for name in relative.split("/"):
            next_handle = _open_relative_checked(current, name, directory=True)
            prefix = f"{prefix}/{name}" if prefix else name
            if not _same_identity(
                _require_identity(next_handle, True),
                identities.get(prefix),
                directory=True,
            ):
                _close(next_handle)
                raise WindowsManifestCleanupError(
                    "Cleanup directory identity changed."
                )
            if current != root_handle:
                _close(current)
            current = next_handle
        return current
    except Exception:
        if current != root_handle:
            _close(current)
        raise


def _pin_existing_root(
    root: str | Path,
    output_root_identity: str,
) -> tuple[int, int, str]:
    parent, child, name = _pin_optional_root(root, output_root_identity)
    if child is None:
        _close(parent)
        raise WindowsManifestCleanupError("Cleanup root is missing.")
    return parent, child, name


def _pin_optional_root(
    root: str | Path,
    output_root_identity: str,
) -> tuple[int, int | None, str]:
    path = _validate_root_path(root)
    parent = _open_ambient_directory(path.parent)
    try:
        if _require_identity(parent, directory=True).durable != output_root_identity:
            raise WindowsManifestCleanupError("Cleanup output root identity changed.")
        child, error = _open_relative(
            parent,
            path.name,
            _DELETE | _SYNCHRONIZE | _FILE_LIST_DIRECTORY | _FILE_READ_ATTRIBUTES,
            directory=True,
        )
        if child is None and error in _MISSING_ERRORS:
            return parent, None, path.name
        if child is None:
            raise WindowsManifestCleanupError("Cleanup root cannot be pinned.")
        _require_identity(child, directory=True)
        return parent, child, path.name
    except Exception:
        _close(parent)
        raise


def _open_ambient_directory(path: Path) -> int:
    handle = _CreateFileW(
        str(path),
        _SYNCHRONIZE | _FILE_LIST_DIRECTORY | _FILE_READ_ATTRIBUTES,
        _FILE_SHARE_READ,
        None,
        _OPEN_EXISTING,
        _FILE_FLAG_BACKUP_SEMANTICS | _FILE_FLAG_OPEN_REPARSE_POINT,
        None,
    )
    if int(handle) == _INVALID_HANDLE_VALUE:
        raise WindowsManifestCleanupError("Cleanup parent cannot be pinned.")
    try:
        _require_identity(int(handle), directory=True)
    except Exception:
        _close(int(handle))
        raise
    return int(handle)


def _open_relative_checked(parent: int, name: str, *, directory: bool) -> int:
    _validate_component(name)
    access = _DELETE | _SYNCHRONIZE | _FILE_READ_ATTRIBUTES
    access |= _FILE_LIST_DIRECTORY if directory else _FILE_READ_DATA
    handle, _ = _open_relative(parent, name, access, directory=directory)
    if handle is None:
        raise WindowsManifestCleanupError("Cleanup component cannot be opened.")
    try:
        _require_identity(handle, directory)
    except Exception:
        _close(handle)
        raise
    return handle


def _open_relative(
    parent: int,
    name: str,
    access: int,
    *,
    directory: bool,
) -> tuple[int | None, int]:
    buffer = ctypes.create_unicode_buffer(name)
    encoded_length = len(name.encode("utf-16-le"))
    unicode_name = _UnicodeString(
        encoded_length,
        encoded_length + 2,
        ctypes.cast(buffer, wintypes.LPWSTR),
    )
    attributes = _ObjectAttributes(
        ctypes.sizeof(_ObjectAttributes),
        parent,
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
        _FILE_SHARE_READ,
        _FILE_OPEN,
        (
            _FILE_DIRECTORY_FILE if directory else _FILE_NON_DIRECTORY_FILE
        )
        | _FILE_SYNCHRONOUS_IO_NONALERT
        | _FILE_OPEN_REPARSE_POINT,
        None,
        0,
    )
    code = int(result) & 0xFFFFFFFF
    return (int(output.value), 0) if code == 0 else (None, code)


def _require_relative_absent(parent: int, name: str) -> None:
    handle, error = _open_relative(
        parent,
        name,
        _SYNCHRONIZE | _FILE_READ_ATTRIBUTES,
        directory=True,
    )
    if handle is not None:
        _close(handle)
        raise WindowsManifestCleanupError("Cleanup root deletion was not terminal.")
    if error not in _MISSING_ERRORS:
        raise WindowsManifestCleanupError("Cleanup root absence cannot be proven.")


def _list_entries(directory: int) -> list[_Entry]:
    return _enumerate_entries(directory)


def _enumerate_entries(directory: int) -> list[_Entry]:
    entries: list[_Entry] = []
    restart = True
    while True:
        buffer = ctypes.create_string_buffer(_BUFFER_BYTES)
        status = _IoStatusBlock()
        result = _NtQueryDirectoryFile(
            directory,
            None,
            None,
            None,
            ctypes.byref(status),
            buffer,
            len(buffer),
            _FILE_ID_BOTH_DIRECTORY_INFORMATION,
            False,
            None,
            restart,
        )
        code = int(result) & 0xFFFFFFFF
        if code == _STATUS_NO_MORE_FILES:
            break
        if code:
            raise WindowsManifestCleanupError("Cleanup directory cannot be enumerated.")
        restart = False
        offset = 0
        while True:
            info = _FileIdBothDirectoryInfo.from_buffer(buffer, offset)
            name_offset = (
                ctypes.addressof(buffer)
                + offset
                + _FileIdBothDirectoryInfo.FileName.offset
            )
            name = ctypes.wstring_at(name_offset, info.FileNameLength // 2)
            if name not in {".", ".."}:
                _validate_component(name)
                if info.FileAttributes & _FILE_ATTRIBUTE_REPARSE_POINT:
                    raise WindowsManifestCleanupError(
                        "Cleanup tree contains a reparse component."
                    )
                entries.append(
                    _Entry(
                        name,
                        bool(info.FileAttributes & _FILE_ATTRIBUTE_DIRECTORY),
                        info.FileAttributes,
                    )
                )
            if not info.NextEntryOffset:
                break
            offset += info.NextEntryOffset
    return entries


def _read_manifest(root_handle: int) -> dict[str, Any]:
    package = _open_relative_checked(root_handle, "package", directory=True)
    manifest: int | None = None
    try:
        manifest = _open_relative_checked(
            package,
            "install-manifest-v1.json",
            directory=False,
        )
        return _decode_manifest(_read_all(manifest, MAX_MANIFEST_BYTES))
    finally:
        _close(manifest)
        _close(package)


def _decode_manifest(content: bytes) -> dict[str, Any]:
    try:
        value = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WindowsManifestCleanupError(
            "Cleanup manifest is invalid."
        ) from exc
    _validate_manifest(value)
    return value


def _validate_manifest(value: Any) -> None:
    fields = {
        "$schema",
        "kind",
        "schemaVersion",
        "governedRoots",
        "files",
        "manifestDigest",
    }
    if not isinstance(value, dict) or set(value) != fields:
        raise WindowsManifestCleanupError("Cleanup manifest envelope is invalid.")
    if (
        value["$schema"] != SCHEMA
        or value["kind"] != "hocus_install_manifest"
        or value["schemaVersion"] != 1
        or value["governedRoots"] != list(GOVERNED_ROOTS)
        or not isinstance(value["files"], list)
        or len(value["files"]) > MAX_FILES
        or _DIGEST_PATTERN.fullmatch(value["manifestDigest"]) is None
    ):
        raise WindowsManifestCleanupError("Cleanup manifest identity is invalid.")
    unsigned = {key: item for key, item in value.items() if key != "manifestDigest"}
    if value["manifestDigest"] != _digest_json(unsigned):
        raise WindowsManifestCleanupError("Cleanup manifest digest is invalid.")
    seen: set[str] = set()
    for row in value["files"]:
        _validate_manifest_row(row, seen)


def _validate_manifest_row(row: Any, seen: set[str]) -> None:
    fields = {"relativePath", "role", "byteLength", "contentDigest"}
    if not isinstance(row, dict) or set(row) != fields:
        raise WindowsManifestCleanupError("Cleanup manifest row is invalid.")
    relative = row["relativePath"]
    if (
        not isinstance(relative, str)
        or relative in seen
        or relative == MANIFEST_RELATIVE_PATH
        or not _valid_relative(relative)
        or row["role"] not in {"immutable", "generated_config"}
        or (relative == "config/default.toml")
        != (row["role"] == "generated_config")
        or isinstance(row["byteLength"], bool)
        or not isinstance(row["byteLength"], int)
        or not 0 <= row["byteLength"] <= MAX_FILE_BYTES
        or not isinstance(row["contentDigest"], str)
        or _DIGEST_PATTERN.fullmatch(row["contentDigest"]) is None
    ):
        raise WindowsManifestCleanupError("Cleanup manifest row is invalid.")
    seen.add(relative)


def _valid_relative(relative: str) -> bool:
    parts = relative.split("/")
    return (
        relative == unicodedata.normalize("NFC", relative)
        and "\\" not in relative
        and bool(parts)
        and all(part not in {"", ".", ".."} for part in parts)
        and any(relative.startswith(root + "/") for root in GOVERNED_ROOTS)
    )


def _validate_authority(value: Mapping[str, object]) -> dict[str, Any]:
    compact_fields = {
        "manifestDigest",
        "outputRootIdentity",
        "rootIdentity",
        "packageIdentity",
    }
    receipt_fields = {
        "kind",
        "schemaVersion",
        "phase",
        "removedFiles",
        "removedDirectories",
        "complete",
    } | compact_fields
    actual_fields = set(value) if isinstance(value, Mapping) else set()
    if (
        not isinstance(value, Mapping)
        or actual_fields not in (compact_fields, receipt_fields)
    ):
        raise WindowsManifestCleanupError("Cleanup authority is invalid.")
    if (
        not isinstance(value["manifestDigest"], str)
        or _DIGEST_PATTERN.fullmatch(value["manifestDigest"]) is None
        or not isinstance(value["outputRootIdentity"], str)
        or _IDENTITY_PATTERN.fullmatch(value["outputRootIdentity"]) is None
        or not isinstance(value["rootIdentity"], str)
        or _IDENTITY_PATTERN.fullmatch(value["rootIdentity"]) is None
        or not isinstance(value["packageIdentity"], str)
        or _IDENTITY_PATTERN.fullmatch(value["packageIdentity"]) is None
    ):
        raise WindowsManifestCleanupError("Cleanup authority is invalid.")
    if actual_fields == receipt_fields:
        _validate_receipt_authority(value)
    return {field: value[field] for field in compact_fields}


def _validate_receipt_authority(value: Mapping[str, object]) -> None:
    if (
        value["kind"] != "hocus_native_manifest_cleanup_authority"
        or value["schemaVersion"] != 1
        or value["phase"] != "governed"
        or value["complete"] is not False
        or not _valid_count(value["removedFiles"])
        or not _valid_count(value["removedDirectories"])
    ):
        raise WindowsManifestCleanupError("Cleanup authority is invalid.")


def _terminal_receipt(
    authority: dict[str, Any],
    *,
    already_absent: bool,
) -> dict[str, Any]:
    return {
        "kind": "hocus_native_manifest_cleanup_receipt",
        "schemaVersion": 1,
        "phase": "terminal",
        "manifestDigest": authority["manifestDigest"],
        "outputRootIdentity": authority["outputRootIdentity"],
        "rootIdentity": authority["rootIdentity"],
        "packageIdentity": authority["packageIdentity"],
        "alreadyAbsent": already_absent,
        "complete": True,
    }


def _require_manifest_only(root: int, package: int) -> None:
    root_entries = _list_entries(root)
    package_entries = _list_entries(package)
    if (
        len(root_entries) != 1
        or root_entries[0].name != "package"
        or not root_entries[0].directory
        or len(package_entries) != 1
        or package_entries[0].name != "install-manifest-v1.json"
        or package_entries[0].directory
    ):
        raise WindowsManifestCleanupError(
            "Cleanup tree retained unexpected governed entries."
        )


def _require_identity(handle: int, directory: bool) -> _Identity:
    information = _ByHandleFileInformation()
    if not _GetFileInformationByHandle(handle, ctypes.byref(information)):
        raise WindowsManifestCleanupError("Cleanup identity is unavailable.")
    attributes = information.dwFileAttributes
    actual_directory = bool(attributes & _FILE_ATTRIBUTE_DIRECTORY)
    if actual_directory != directory or attributes & _FILE_ATTRIBUTE_REPARSE_POINT:
        raise WindowsManifestCleanupError("Cleanup component type is unsafe.")
    if not directory and information.nNumberOfLinks != 1:
        raise WindowsManifestCleanupError("Cleanup file has an unsafe link count.")
    return _Identity(
        information.dwVolumeSerialNumber,
        (information.nFileIndexHigh << 32) | information.nFileIndexLow,
        attributes,
        (information.nFileSizeHigh << 32) | information.nFileSizeLow,
        information.nNumberOfLinks,
    )


def _same_identity(
    actual: _Identity,
    expected: _Identity | None,
    *,
    directory: bool,
) -> bool:
    if expected is None or actual.durable != expected.durable:
        return False
    return directory or actual == expected


def _read_all(handle: int, limit: int) -> bytes:
    output: list[bytes] = []
    remaining = limit + 1
    while remaining:
        size = min(_BUFFER_BYTES, remaining)
        buffer = ctypes.create_string_buffer(size)
        received = wintypes.DWORD()
        if not _ReadFile(handle, buffer, size, ctypes.byref(received), None):
            raise WindowsManifestCleanupError("Cleanup file cannot be read.")
        if not received.value:
            break
        output.append(buffer.raw[: received.value])
        remaining -= received.value
    content = b"".join(output)
    if len(content) > limit:
        raise WindowsManifestCleanupError("Cleanup file exceeds its size bound.")
    return content


def _mark_delete(handle: int) -> None:
    information = _FileDispositionInformation(1)
    status = _IoStatusBlock()
    result = _NtSetInformationFile(
        handle,
        ctypes.byref(status),
        ctypes.byref(information),
        ctypes.sizeof(information),
        _FILE_DISPOSITION_INFORMATION,
    )
    if int(result) & 0xFFFFFFFF:
        raise WindowsManifestCleanupError("Cleanup handle deletion failed.")


def _canonical_config(content: bytes) -> bytes:
    if _TOKEN_LINE.search(content) is None:
        raise WindowsManifestCleanupError(
            "Cleanup generated configuration is invalid."
        )
    return _TOKEN_LINE.sub(b'token = "<redacted>"', content)


def _allowed_directories(files: set[str]) -> set[str]:
    output: set[str] = set()
    for governed in GOVERNED_ROOTS:
        parts = governed.split("/")
        for index in range(1, len(parts) + 1):
            output.add("/".join(parts[:index]))
    for relative in files:
        parts = relative.split("/")[:-1]
        for index in range(1, len(parts) + 1):
            output.add("/".join(parts[:index]))
    return output


def _split_parent(relative: str) -> tuple[str, str]:
    parent, _, name = relative.rpartition("/")
    return parent, name


def _digest_json(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _valid_count(value: object) -> bool:
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and 0 <= value <= MAX_ENTRIES
    )


def _validate_root_path(root: str | Path) -> Path:
    value = os.fspath(root)
    if not isinstance(value, str) or "\x00" in value:
        raise WindowsManifestCleanupError("Cleanup root path is invalid.")
    path = Path(value)
    if (
        not path.is_absolute()
        or path.parent == path
        or path.name in {"", ".", ".."}
        or path.name != unicodedata.normalize("NFC", path.name)
    ):
        raise WindowsManifestCleanupError("Cleanup root path is invalid.")
    return path


def _validate_component(name: str) -> None:
    if (
        not name
        or name in {".", ".."}
        or name != unicodedata.normalize("NFC", name)
        or any(character in name for character in ("/", "\\", "\x00"))
    ):
        raise WindowsManifestCleanupError("Cleanup component name is invalid.")


def _require_windows() -> None:
    if not _IS_WINDOWS:
        raise WindowsManifestCleanupError(
            "Native manifest cleanup requires Windows."
        )


def _close(handle: int | None) -> None:
    if handle is not None and _IS_WINDOWS:
        _CloseHandle(handle)


__all__ = [
    "WindowsManifestCleanupError",
    "governed_cleanup",
    "terminal_cleanup",
]

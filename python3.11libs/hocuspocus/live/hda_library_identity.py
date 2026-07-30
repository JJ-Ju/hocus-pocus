"""Bounded byte identity for regular-file and directory-format HDA libraries."""

from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any


MAX_HDA_FILES = 4096
MAX_HDA_DIRECTORIES = 4096
MAX_HDA_ENTRIES = MAX_HDA_FILES + MAX_HDA_DIRECTORIES
MAX_HDA_FILE_BYTES = 128 * 1024 * 1024
MAX_HDA_TOTAL_BYTES = 256 * 1024 * 1024
_READ_BYTES = 1024 * 1024
_WINDOWS_REPARSE_POINT = 0x400
_DIRECTORY_DIGEST_DOMAIN = b"HocusPocus-HDA-Directory-v1\0"


class HdaLibraryIdentityError(RuntimeError):
    """An HDA library has no bounded, stable, contained byte identity."""


@dataclass(frozen=True)
class _Snapshot:
    mode: int
    size: int
    mtime_ns: int
    ctime_ns: int
    device: int
    file_id: int


@dataclass(frozen=True)
class _FileRecord:
    path: Path
    relative: str
    snapshot: _Snapshot


def hda_library_content_digest(value: str | os.PathLike[str]) -> str:
    """Hash one stable HDA file or directory without following filesystem links."""

    lexical = _absolute_lexical_path(value)
    _reject_reparse_components(lexical)
    root_stat = _lstat(lexical)
    _reject_link_or_reparse(lexical, root_stat)
    try:
        root = lexical.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise HdaLibraryIdentityError(
            "HDA library root cannot be resolved."
        ) from exc
    _require_same_path(root, lexical, "HDA library root")
    directory_format = stat.S_ISDIR(root_stat.st_mode)
    if stat.S_ISREG(root_stat.st_mode):
        records = [_file_record(root, root.name, root_stat)]
        directories: dict[Path, _Snapshot] = {}
    elif directory_format:
        records, directories = _directory_records(root, root_stat)
    else:
        raise HdaLibraryIdentityError(
            "HDA library root is neither a regular file nor a directory."
        )
    digest = hashlib.sha256()
    if directory_format:
        digest.update(_DIRECTORY_DIGEST_DOMAIN)
        digest.update(len(records).to_bytes(8, byteorder="big"))
    for record in records:
        _hash_file_record(digest, record, root, directory_format)
    for path, before in directories.items():
        after = _lstat(path)
        _reject_link_or_reparse(path, after)
        if not stat.S_ISDIR(after.st_mode) or _snapshot(after) != before:
            raise HdaLibraryIdentityError(
                "HDA library directory changed while being hashed."
            )
        _require_contained(path, root)
    return "sha256:" + digest.hexdigest()


def _absolute_lexical_path(value: str | os.PathLike[str]) -> Path:
    try:
        return Path(os.path.abspath(Path(value).expanduser()))
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise HdaLibraryIdentityError("HDA library path is invalid.") from exc


def _reject_reparse_components(path: Path) -> None:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        value = _lstat(current)
        _reject_link_or_reparse(current, value)


def _directory_records(
    root: Path,
    root_stat: os.stat_result,
) -> tuple[list[_FileRecord], dict[Path, _Snapshot]]:
    files: list[_FileRecord] = []
    directories = {root: _snapshot(root_stat)}
    pending = [root]
    entries = 0
    total_bytes = 0
    while pending:
        directory = pending.pop()
        try:
            stream = os.scandir(directory)
        except OSError as exc:
            raise HdaLibraryIdentityError(
                "HDA library directory cannot be enumerated."
            ) from exc
        try:
            for entry in stream:
                entries += 1
                if entries > MAX_HDA_ENTRIES:
                    raise HdaLibraryIdentityError(
                        "HDA library entry count exceeds its limit."
                    )
                path = Path(entry.path)
                value = _lstat(path)
                _reject_link_or_reparse(path, value)
                _require_contained(path, root)
                if stat.S_ISDIR(value.st_mode):
                    if len(directories) >= MAX_HDA_DIRECTORIES:
                        raise HdaLibraryIdentityError(
                            "HDA library directory count exceeds its limit."
                        )
                    directories[path] = _snapshot(value)
                    pending.append(path)
                elif stat.S_ISREG(value.st_mode):
                    if len(files) >= MAX_HDA_FILES:
                        raise HdaLibraryIdentityError(
                            "HDA library file count exceeds its limit."
                        )
                    record = _file_record(
                        path,
                        path.relative_to(root).as_posix(),
                        value,
                    )
                    total_bytes += record.snapshot.size
                    if total_bytes > MAX_HDA_TOTAL_BYTES:
                        raise HdaLibraryIdentityError(
                            "HDA library aggregate bytes exceed their limit."
                        )
                    files.append(record)
                else:
                    raise HdaLibraryIdentityError(
                        "HDA library contains a special filesystem entry."
                    )
        finally:
            stream.close()
    files.sort(key=lambda item: item.relative)
    return files, directories


def _file_record(
    path: Path,
    relative: str,
    value: os.stat_result,
) -> _FileRecord:
    snapshot = _snapshot(value)
    if snapshot.size < 0 or snapshot.size > MAX_HDA_FILE_BYTES:
        raise HdaLibraryIdentityError(
            "HDA library file exceeds its byte limit."
        )
    return _FileRecord(path=path, relative=relative, snapshot=snapshot)


def _hash_file_record(
    digest: Any,
    record: _FileRecord,
    root: Path,
    directory_format: bool,
) -> None:
    current = _lstat(record.path)
    _reject_link_or_reparse(record.path, current)
    if not stat.S_ISREG(current.st_mode) or _snapshot(current) != record.snapshot:
        raise HdaLibraryIdentityError(
            "HDA library file changed before it was hashed."
        )
    _require_contained(record.path, root)
    relative = record.relative.encode("utf-8", errors="surrogatepass")
    if directory_format:
        digest.update(b"F")
        digest.update(len(relative).to_bytes(8, byteorder="big"))
        digest.update(relative)
        digest.update(record.snapshot.size.to_bytes(8, byteorder="big"))
    else:
        digest.update(relative)
        digest.update(b"\0")
    _hash_open_file(digest, record)
    if not directory_format:
        digest.update(b"\0")
    after = _lstat(record.path)
    _reject_link_or_reparse(record.path, after)
    if not stat.S_ISREG(after.st_mode) or _snapshot(after) != record.snapshot:
        raise HdaLibraryIdentityError(
            "HDA library file changed while it was hashed."
        )
    _require_contained(record.path, root)


def _hash_open_file(digest: Any, record: _FileRecord) -> None:
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(record.path, flags)
    except OSError as exc:
        raise HdaLibraryIdentityError(
            "HDA library file cannot be opened without following links."
        ) from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or _snapshot(before) != record.snapshot:
            raise HdaLibraryIdentityError(
                "HDA library file identity changed while being opened."
            )
        change_time = _descriptor_change_time(descriptor)
        count, first_digest, change_time = _read_open_pass(
            descriptor,
            digest,
            record,
            change_time,
        )
        middle = os.fstat(descriptor)
        if (
            _snapshot(middle) != record.snapshot
            or _descriptor_change_time(descriptor) != change_time
        ):
            raise HdaLibraryIdentityError(
                "HDA library file changed while being read."
            )
        os.lseek(descriptor, 0, os.SEEK_SET)
        second_count, second_digest, change_time = _read_open_pass(
            descriptor,
            None,
            record,
            change_time,
        )
        after = os.fstat(descriptor)
        after_change_time = _descriptor_change_time(descriptor)
    except OSError as exc:
        raise HdaLibraryIdentityError(
            "HDA library file cannot be read."
        ) from exc
    finally:
        os.close(descriptor)
    if (
        count != record.snapshot.size
        or second_count != count
        or first_digest != second_digest
        or _snapshot(after) != record.snapshot
        or after_change_time != change_time
    ):
        raise HdaLibraryIdentityError(
            "HDA library file changed while being read."
        )


def _read_open_pass(
    descriptor: int,
    digest: Any | None,
    record: _FileRecord,
    expected_change_time: int,
) -> tuple[int, bytes, int]:
    verifier = hashlib.sha256()
    count = 0
    while True:
        before = _descriptor_change_time(descriptor)
        if before != expected_change_time:
            raise HdaLibraryIdentityError(
                "HDA library file changed while being read."
            )
        chunk = os.read(descriptor, _READ_BYTES)
        after = _descriptor_change_time(descriptor)
        if after != before:
            raise HdaLibraryIdentityError(
                "HDA library file changed while being read."
            )
        expected_change_time = after
        if not chunk:
            return count, verifier.digest(), expected_change_time
        count += len(chunk)
        if count > record.snapshot.size or count > MAX_HDA_FILE_BYTES:
            raise HdaLibraryIdentityError(
                "HDA library file changed size while being hashed."
            )
        verifier.update(chunk)
        if digest is not None:
            digest.update(chunk)


def _descriptor_change_time(descriptor: int) -> int:
    if os.name != "nt":
        return os.fstat(descriptor).st_ctime_ns
    return _windows_descriptor_change_time(descriptor)


def _windows_descriptor_change_time(descriptor: int) -> int:
    import ctypes
    import msvcrt

    class _FileBasicInfo(ctypes.Structure):
        _fields_ = [
            ("CreationTime", ctypes.c_longlong),
            ("LastAccessTime", ctypes.c_longlong),
            ("LastWriteTime", ctypes.c_longlong),
            ("ChangeTime", ctypes.c_longlong),
            ("FileAttributes", ctypes.c_ulong),
        ]

    info = _FileBasicInfo()
    handle = ctypes.c_void_p(msvcrt.get_osfhandle(descriptor))
    read_info = ctypes.windll.kernel32.GetFileInformationByHandleEx
    if not read_info(
        handle,
        0,
        ctypes.byref(info),
        ctypes.sizeof(info),
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    return int(info.ChangeTime)


def _lstat(path: Path) -> os.stat_result:
    try:
        return path.stat(follow_symlinks=False)
    except OSError as exc:
        raise HdaLibraryIdentityError(
            "HDA library filesystem identity is unavailable."
        ) from exc


def _snapshot(value: os.stat_result) -> _Snapshot:
    return _Snapshot(
        mode=stat.S_IFMT(value.st_mode),
        size=value.st_size,
        mtime_ns=value.st_mtime_ns,
        ctime_ns=value.st_ctime_ns,
        device=value.st_dev,
        file_id=value.st_ino,
    )


def _reject_link_or_reparse(path: Path, value: os.stat_result) -> None:
    attributes = getattr(value, "st_file_attributes", 0)
    if stat.S_ISLNK(value.st_mode) or attributes & _WINDOWS_REPARSE_POINT:
        raise HdaLibraryIdentityError(
            f"HDA library traverses a link or reparse point: {path.name}"
        )


def _require_same_path(resolved: Path, lexical: Path, label: str) -> None:
    try:
        if not os.path.samefile(resolved, lexical):
            raise HdaLibraryIdentityError(f"{label} changed during resolution.")
    except OSError as exc:
        raise HdaLibraryIdentityError(
            f"{label} identity cannot be verified."
        ) from exc


def _require_contained(path: Path, root: Path) -> None:
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise HdaLibraryIdentityError(
            "HDA library entry cannot be resolved."
        ) from exc
    if resolved != root and root not in resolved.parents:
        raise HdaLibraryIdentityError(
            "HDA library entry resolves outside its directory root."
        )


__all__ = [
    "HdaLibraryIdentityError",
    "hda_library_content_digest",
]

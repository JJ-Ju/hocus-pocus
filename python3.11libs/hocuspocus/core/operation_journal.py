"""Cross-process durable filesystem slots for terminal operation receipts."""

from __future__ import annotations

import contextlib
import ctypes
import json
import os
from pathlib import Path
import stat
import struct
import threading
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Callable, Iterator


_HEADER = struct.Struct("!8sQ32s")
_MAGIC = b"HOCOPJ1\0"
_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()


@dataclass(frozen=True)
class JournalIdentity:
    name: str
    device: int
    inode: int


def _process_lock(path: Path) -> threading.RLock:
    key = str(path.resolve()).casefold()
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, threading.RLock())


class JournalPlatform:
    def __init__(
        self,
        directory: Path,
        slot_bytes: int,
        *,
        directory_flusher: Callable[[Path], None] | None = None,
    ) -> None:
        self.directory = directory
        self.slot_bytes = slot_bytes
        self._directory_flusher = directory_flusher or flush_directory_namespace
        self._thread_lock = _process_lock(directory / ".namespace.lock")

    @contextlib.contextmanager
    def namespace_lock(self) -> Iterator[None]:
        self.directory.mkdir(parents=True, exist_ok=True)
        lock_path = self.directory / ".namespace.lock"
        with self._thread_lock, lock_path.open("a+b") as handle:
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
                os.fsync(handle.fileno())
            _lock_file(handle.fileno())
            try:
                yield
            finally:
                _unlock_file(handle.fileno())

    def materialize(self, name: str) -> JournalIdentity:
        path = self.directory / name
        flags = os.O_CREAT | os.O_EXCL | os.O_RDWR
        flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags, 0o600)
        try:
            with os.fdopen(descriptor, "r+b", buffering=0) as handle:
                remaining = self.slot_bytes
                block = b"\0" * (1024 * 1024)
                while remaining:
                    written = handle.write(block[:min(remaining, len(block))])
                    if not written:
                        raise OSError("terminal journal allocation was incomplete")
                    remaining -= written
                os.fsync(handle.fileno())
                device, inode = self._verified_identity(handle.fileno())
            return JournalIdentity(name, device, inode)
        except Exception:
            path.unlink(missing_ok=True)
            raise

    def publish(
        self,
        identity: JournalIdentity,
        payload: dict[str, Any],
    ) -> None:
        encoded = json.dumps(
            payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
        if len(encoded) + _HEADER.size > self.slot_bytes:
            raise OSError("terminal journal payload exceeds reserved capacity")
        header = _HEADER.pack(_MAGIC, len(encoded), sha256(encoded).digest())
        flags = os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(self.directory / identity.name, flags)
        with os.fdopen(descriptor, "r+b", buffering=0) as handle:
            if self._verified_identity(handle.fileno()) != (
                identity.device,
                identity.inode,
            ):
                raise OSError("terminal journal identity changed")
            handle.seek(0)
            handle.write(header)
            handle.write(encoded)
            os.fsync(handle.fileno())

    def read(
        self,
        path: Path,
        expected: JournalIdentity | None = None,
    ) -> dict[str, Any] | None:
        try:
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(path, flags)
            with os.fdopen(descriptor, "rb", buffering=0) as handle:
                device, inode = self._verified_identity(handle.fileno())
                if expected is not None and (device, inode) != (
                    expected.device,
                    expected.inode,
                ):
                    return None
                header = handle.read(_HEADER.size)
                magic, length, digest = _HEADER.unpack(header)
                if magic != _MAGIC or length + _HEADER.size > self.slot_bytes:
                    return None
                encoded = handle.read(length)
            if sha256(encoded).digest() != digest:
                return None
            payload = json.loads(encoded)
            if (
                not isinstance(payload, dict)
                or payload.get("fileDevice") != device
                or payload.get("fileInode") != inode
            ):
                return None
            return payload
        except (OSError, ValueError, json.JSONDecodeError, struct.error):
            return None

    def remove(self, name: str) -> None:
        (self.directory / name).unlink(missing_ok=True)
        self.flush_namespace()

    def flush_namespace(self) -> None:
        self._directory_flusher(self.directory)
        self._directory_flusher(self.directory.parent)

    def scan(self, limit: int) -> tuple[list[Path], bool]:
        if not self.directory.is_dir():
            return [], False
        paths: list[Path] = []
        removed = False
        count = 0
        with os.scandir(self.directory) as entries:
            for entry in entries:
                if entry.name == ".namespace.lock":
                    continue
                count += 1
                if count > limit:
                    return paths, True
                path = Path(entry.path)
                if (
                    entry.name.endswith(".slot")
                    and entry.is_file(follow_symlinks=False)
                ):
                    paths.append(path)
                elif entry.is_file(follow_symlinks=False) or entry.is_symlink():
                    entry_path = self.directory / entry.name
                    entry_path.unlink(missing_ok=True)
                    removed = True
                else:
                    return paths, True
        if removed:
            self.flush_namespace()
        return paths, False

    def _verified_identity(self, descriptor: int) -> tuple[int, int]:
        status = os.fstat(descriptor)
        if (
            not stat.S_ISREG(status.st_mode)
            or status.st_nlink != 1
            or status.st_size != self.slot_bytes
        ):
            raise OSError("terminal journal identity is unsafe")
        return int(status.st_dev), int(status.st_ino)


def flush_directory_namespace(directory: Path) -> None:
    if os.name == "nt":
        _flush_windows_directory(directory)
        return
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _flush_windows_directory(directory: Path) -> None:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.restype = ctypes.c_void_p
    handle = create_file(
        str(directory),
        0x80000000 | 0x40000000,
        0x00000001 | 0x00000002 | 0x00000004,
        None,
        3,
        0x02000000,
        None,
    )
    invalid = ctypes.c_void_p(-1).value
    if handle in {None, invalid}:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        if not kernel32.FlushFileBuffers(ctypes.c_void_p(handle)):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        kernel32.CloseHandle(ctypes.c_void_p(handle))


def _lock_file(descriptor: int) -> None:
    if os.name == "nt":
        import msvcrt

        os.lseek(descriptor, 0, os.SEEK_SET)
        msvcrt.locking(descriptor, msvcrt.LK_LOCK, 1)
        return
    import fcntl

    fcntl.flock(descriptor, fcntl.LOCK_EX)


def _unlock_file(descriptor: int) -> None:
    if os.name == "nt":
        import msvcrt

        os.lseek(descriptor, 0, os.SEEK_SET)
        msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
        return
    import fcntl

    fcntl.flock(descriptor, fcntl.LOCK_UN)


__all__ = [
    "JournalIdentity", "JournalPlatform", "flush_directory_namespace",
]

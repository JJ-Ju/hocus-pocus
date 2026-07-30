"""Linux local-filesystem classification for descriptor-safe workspaces."""

from __future__ import annotations

import ctypes
import errno
import fcntl
import hashlib
import logging
import os
import platform
import stat
import sys
import threading
from array import array
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Callable

from ._workspace_boundary_types import NativeWorkspaceError
from ._workspace_publication_lock import (
    LEGACY_LOCK_NAME,
    open_publication_lock,
    release_publication_lock,
)
from ._workspace_recovery_record import (
    MAX_RECOVERY_BYTES as _MAX_RECOVERY_BYTES,
    RecoveryRequired,
    artifact_metadata,
    encode_recovery_record,
)

if os.name != "posix" or not sys.platform.startswith("linux"):
    raise ImportError("Linux workspace primitives are unavailable.")

_FILESYSTEMS = {
    0xEF53: "ext",
    0x58465342: "xfs",
    0x9123683E: "btrfs",
    0x01021994: "tmpfs",
    0x2FC12FC1: "zfs",
    0x794C7630: "overlayfs",
    0xF2F52010: "f2fs",
    0xCA451A4E: "bcachefs",
    0x5346544E: "ntfs3",
}
_RESOLVE_NO_XDEV = 0x01
_RESOLVE_NO_MAGICLINKS = 0x02
_RESOLVE_NO_SYMLINKS = 0x04
_RESOLVE_BENEATH = 0x08
_RENAME_NOREPLACE = 0x01
_RENAME_EXCHANGE = 0x02
_FS_IOC_GETVERSION = 0x80087601
_LOG = logging.getLogger(__name__)
RECOVERY_MARKER = ".hocus-recovery-v1.json"
_PUBLICATION_LOCK = threading.RLock()


def publication_guard(
    root_descriptor: int,
    operation: Callable[[], bytes],
) -> bytes:
    with _PUBLICATION_LOCK:
        return _publication_guard_locked(root_descriptor, operation)


def _publication_guard_locked(
    root_descriptor: int,
    operation: Callable[[], bytes],
) -> bytes:
    """Serialize publication and retain a crash-persistent recovery state."""

    lock_descriptor = open_publication_lock(
        "linux",
        strong_root_identity(root_descriptor),
    )
    committed = False
    try:
        information = os.fstat(lock_descriptor)
        if not stat.S_ISREG(information.st_mode) or information.st_nlink != 1:
            raise NativeWorkspaceError("HOCUS828", "Workspace recovery lock is unsafe.")
        fcntl.flock(lock_descriptor, fcntl.LOCK_EX)
        _assert_lock_clean(root_descriptor, lock_descriptor)
        _remove_legacy_project_lock(root_descriptor)
        assert_recovery_clear(root_descriptor)
        _write_lock_state(lock_descriptor, b"publishing\n")
        result = operation()
        committed = True
        return result
    finally:
        try:
            if os.pread(lock_descriptor, 32, 0) == b"publishing\n":
                _write_lock_state(lock_descriptor, b"clean\n")
        except Exception:
            _LOG.warning("HOCUS828 workspace publication lock remains fail-closed")
        release_publication_lock(
            (
                lambda: fcntl.flock(lock_descriptor, fcntl.LOCK_UN),
                lambda: os.close(lock_descriptor),
            ),
            committed=committed,
            logger=_LOG,
        )


def _remove_legacy_project_lock(root_descriptor: int) -> None:
    try:
        descriptor = open_beneath(
            root_descriptor,
            LEGACY_LOCK_NAME,
            os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW,
        )
    except FileNotFoundError:
        return
    except OSError as exc:
        raise NativeWorkspaceError(
            "HOCUS828", "Legacy workspace lock requires explicit host migration."
        ) from exc
    try:
        raise NativeWorkspaceError(
            "HOCUS828", "Legacy workspace lock requires explicit host migration."
        )
    finally:
        close_publication(lambda: os.close(descriptor), False)


def strong_root_identity(root_descriptor: int) -> tuple[int, int, int]:
    """Return a reuse-resistant native identity or reject the filesystem."""

    information = os.fstat(root_descriptor)
    generation = array("I", (0,))
    try:
        fcntl.ioctl(root_descriptor, _FS_IOC_GETVERSION, generation, True)
    except OSError as exc:
        raise NativeWorkspaceError(
            "HOCUS822", "Workspace filesystem lacks strong root identity."
        ) from exc
    if generation[0] == 0:
        raise NativeWorkspaceError(
            "HOCUS822", "Workspace filesystem returned an invalid root identity."
        )
    return information.st_dev, information.st_ino, generation[0]


def _assert_lock_clean(root_descriptor: int, lock_descriptor: int) -> None:
    state = os.pread(lock_descriptor, 32, 0)
    if state == b"recovery\n":
        try:
            assert_recovery_clear(root_descriptor)
        except RecoveryRequired as exc:
            raise NativeWorkspaceError(
                "HOCUS828", "Workspace recovery is required."
            ) from exc
        _write_lock_state(lock_descriptor, b"clean\n")
        state = b"clean\n"
    if state not in {b"", b"clean\n"}:
        raise NativeWorkspaceError("HOCUS828", "Workspace recovery is required.")
    if not state:
        _write_lock_state(lock_descriptor, b"clean\n")


def _write_lock_state(lock_descriptor: int, state: bytes) -> None:
    os.ftruncate(lock_descriptor, 0)
    os.pwrite(lock_descriptor, state, 0)
    os.fsync(lock_descriptor)


def _set_recovery_state(root_descriptor: int, state: bytes) -> None:
    descriptor = open_publication_lock(
        "linux",
        strong_root_identity(root_descriptor),
    )
    try:
        _write_lock_state(descriptor, state)
    finally:
        close_publication(lambda: os.close(descriptor), False)


def close_publication(closer: Callable[[], None], committed: bool) -> None:
    """Preserve the transaction result when cleanup itself fails."""

    already_failing = sys.exc_info()[0] is not None
    try:
        closer()
    except Exception:
        if not committed and not already_failing:
            raise
        _LOG.warning("HOCUS828 workspace publication cleanup deferred")


def assert_recovery_clear(root_descriptor: int) -> None:
    """Block publication while durable recovery evidence is unresolved."""

    try:
        descriptor = open_beneath(
            root_descriptor,
            RECOVERY_MARKER,
            os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW,
        )
    except FileNotFoundError:
        return
    close_publication(lambda: os.close(descriptor), False)
    raise RecoveryRequired(())


def require_recovery_clear(root_descriptor: int) -> None:
    try:
        assert_recovery_clear(root_descriptor)
    except RecoveryRequired as exc:
        raise NativeWorkspaceError(
            "HOCUS828", "Workspace recovery is required."
        ) from exc


def fail_recovery(
    root_descriptor: int,
    target: str,
    parent: str,
    recovery: RecoveryRequired,
) -> None:
    write_recovery_marker(root_descriptor, target, parent, recovery)
    raise NativeWorkspaceError("HOCUS828", "Workspace recovery is required.") from recovery


def write_recovery_marker(
    root_descriptor: int,
    target: str,
    parent: str,
    recovery: RecoveryRequired,
) -> None:
    """Durably publish the single path-free recovery incident marker."""

    _set_recovery_state(root_descriptor, b"orphan\n")
    body = encode_recovery_record(target, parent, recovery)
    temporary = f".hocus-recovery-marker-{os.urandom(16).hex()}.tmp"
    write_temporary(root_descriptor, temporary, body, 0o600)
    try:
        publish_create(root_descriptor, temporary, RECOVERY_MARKER)
        os.fsync(root_descriptor)
        _set_recovery_state(root_descriptor, b"recovery\n")
    except FileExistsError:
        unlink_if_present(root_descriptor, temporary)
        _set_recovery_state(root_descriptor, b"recovery\n")
    except Exception:
        unlink_if_present(root_descriptor, temporary)
        raise


_OPENAT2_SYSCALLS = {
    "aarch64": 437,
    "arm64": 437,
    "i386": 437,
    "i686": 437,
    "x86_64": 437,
}


class _Fsid(ctypes.Structure):
    _fields_ = [("values", ctypes.c_int * 2)]


class _StatFs(ctypes.Structure):
    _fields_ = [
        ("f_type", ctypes.c_long),
        ("f_bsize", ctypes.c_long),
        ("f_blocks", ctypes.c_ulong),
        ("f_bfree", ctypes.c_ulong),
        ("f_bavail", ctypes.c_ulong),
        ("f_files", ctypes.c_ulong),
        ("f_ffree", ctypes.c_ulong),
        ("f_fsid", _Fsid),
        ("f_namelen", ctypes.c_long),
        ("f_frsize", ctypes.c_long),
        ("f_flags", ctypes.c_long),
        ("f_spare", ctypes.c_long * 4),
    ]


class _OpenHow(ctypes.Structure):
    _fields_ = [
        ("flags", ctypes.c_uint64),
        ("mode", ctypes.c_uint64),
        ("resolve", ctypes.c_uint64),
    ]


@dataclass(frozen=True, slots=True)
class PosixIdentity:
    device: int
    inode: int
    mode: int
    size: int
    modified_ns: int
    links: int

    @classmethod
    def from_stat(cls, value: os.stat_result) -> PosixIdentity:
        return cls(
            value.st_dev,
            value.st_ino,
            value.st_mode,
            value.st_size,
            value.st_mtime_ns,
            value.st_nlink,
        )

    @property
    def object_key(self) -> tuple[int, int, int]:
        return self.device, self.inode, self.mode


_LIBC = ctypes.CDLL(None, use_errno=True)
_fstatfs = _LIBC.fstatfs
_fstatfs.argtypes = [ctypes.c_int, ctypes.POINTER(_StatFs)]
_fstatfs.restype = ctypes.c_int
_syscall = _LIBC.syscall
_syscall.restype = ctypes.c_long
_renameat2 = getattr(_LIBC, "renameat2", None)
if _renameat2 is not None:
    _renameat2.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    _renameat2.restype = ctypes.c_int


def local_filesystem_name(descriptor: int) -> str | None:
    """Return an allowlisted local Linux filesystem name."""

    information = _StatFs()
    ctypes.set_errno(0)
    if _fstatfs(descriptor, ctypes.byref(information)) != 0:
        return None
    return _FILESYSTEMS.get(information.f_type & 0xFFFFFFFF)


def open_beneath(
    directory_descriptor: int,
    name: str,
    flags: int,
    mode: int = 0,
) -> int:
    """Open one path beneath a pinned directory with strict resolution."""

    syscall_number = _OPENAT2_SYSCALLS.get(platform.machine().casefold())
    if syscall_number is None:
        raise OSError(errno.ENOSYS, "openat2 architecture unsupported")
    how = _OpenHow(
        flags,
        mode,
        _RESOLVE_BENEATH
        | _RESOLVE_NO_SYMLINKS
        | _RESOLVE_NO_MAGICLINKS
        | _RESOLVE_NO_XDEV,
    )
    encoded = os.fsencode(name)
    ctypes.set_errno(0)
    result = _syscall(
        syscall_number,
        directory_descriptor,
        ctypes.c_char_p(encoded),
        ctypes.byref(how),
        ctypes.sizeof(how),
    )
    if result < 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))
    os.set_inheritable(result, False)
    return int(result)


def exchange_relative(
    directory_descriptor: int,
    first: str,
    second: str,
) -> None:
    """Atomically exchange two names under one retained directory."""

    if _renameat2 is None:
        raise OSError(errno.ENOSYS, "renameat2 unavailable")
    ctypes.set_errno(0)
    result = _renameat2(
        directory_descriptor,
        os.fsencode(first),
        directory_descriptor,
        os.fsencode(second),
        _RENAME_EXCHANGE,
    )
    if result != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))


def exchange_cas(
    directory_descriptor: int,
    temporary_name: str,
    target_name: str,
    expected_digest: str,
    expected_identity: tuple[int, int, int],
    max_bytes: int,
) -> bool:
    """Exchange new bytes with a target and verify the displaced file."""

    if not _matches_expected_target(
        directory_descriptor,
        target_name,
        expected_digest,
        expected_identity,
        max_bytes,
    ):
        return False
    exchanged = False
    displaced_descriptor = -1
    try:
        exchange_relative(directory_descriptor, temporary_name, target_name)
        exchanged = True
        displaced_descriptor = open_beneath(
            directory_descriptor,
            temporary_name,
            os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW,
        )
        before = os.fstat(displaced_descriptor)
        if (
            (before.st_dev, before.st_ino, before.st_mode) != expected_identity
            or not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_size > max_bytes
        ):
            _restore_exchange(directory_descriptor, temporary_name, target_name)
            return False
        content = _read_bounded(displaced_descriptor, max_bytes)
        after = os.fstat(displaced_descriptor)
        if _stable_stat_key(before) != _stable_stat_key(after) or (
            "sha256:" + hashlib.sha256(content).hexdigest()
        ) != expected_digest:
            _restore_exchange(directory_descriptor, temporary_name, target_name)
            return False
        exchanged = False
        return True
    except OSError:
        if exchanged:
            _restore_exchange(directory_descriptor, temporary_name, target_name)
        raise
    finally:
        if displaced_descriptor >= 0:
            os.close(displaced_descriptor)


def _matches_expected_target(
    directory_descriptor: int,
    target_name: str,
    expected_digest: str,
    expected_identity: tuple[int, int, int],
    max_bytes: int,
) -> bool:
    descriptor = open_beneath(
        directory_descriptor,
        target_name,
        os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW,
    )
    try:
        before = os.fstat(descriptor)
        if (
            (before.st_dev, before.st_ino, before.st_mode) != expected_identity
            or not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_size > max_bytes
        ):
            return False
        content = _read_bounded(descriptor, max_bytes)
        after = os.fstat(descriptor)
        return _stable_stat_key(before) == _stable_stat_key(after) and (
            "sha256:" + hashlib.sha256(content).hexdigest()
        ) == expected_digest
    finally:
        os.close(descriptor)


def _restore_exchange(
    directory_descriptor: int,
    temporary_name: str,
    target_name: str,
) -> None:
    exchange_relative(directory_descriptor, temporary_name, target_name)
    os.fsync(directory_descriptor)


def _stable_stat_key(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _read_bounded(descriptor: int, max_bytes: int) -> bytes:
    os.lseek(descriptor, 0, os.SEEK_SET)
    output: list[bytes] = []
    remaining = max_bytes + 1
    while remaining:
        chunk = os.read(descriptor, min(64 * 1024, remaining))
        if not chunk:
            break
        output.append(chunk)
        remaining -= len(chunk)
    content = b"".join(output)
    if len(content) > max_bytes:
        raise OSError(errno.EFBIG, "displaced file exceeds bound")
    return content


def inspect_regular(
    directory_descriptor: int,
    name: str,
    root_device: int,
) -> tuple[int, tuple[int, int, int]]:
    """Inspect one regular single-link target through openat2."""

    descriptor = open_beneath(
        directory_descriptor,
        name,
        os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW,
    )
    try:
        information = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    if (
        information.st_dev != root_device
        or not stat.S_ISREG(information.st_mode)
        or information.st_nlink != 1
    ):
        raise OSError(errno.EPERM, "unsafe publication target")
    return stat.S_IMODE(information.st_mode), (
        information.st_dev,
        information.st_ino,
        information.st_mode,
    )


def publish_create(
    directory_descriptor: int,
    temporary_name: str,
    target_name: str,
) -> None:
    """Publish one new name without replacement."""

    if _renameat2 is None:
        raise OSError(errno.ENOSYS, "renameat2 unavailable")
    ctypes.set_errno(0)
    result = _renameat2(
        directory_descriptor,
        os.fsencode(temporary_name),
        directory_descriptor,
        os.fsencode(target_name),
        _RENAME_NOREPLACE,
    )
    if result != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))


def publish_transaction(
    directory_descriptor: int,
    temporary_name: str,
    target_name: str,
    content: bytes,
    *,
    create: bool,
    expected_digest: str | None,
    expected_identity: tuple[int, int, int] | None,
    max_bytes: int,
    verify_namespace: Callable[[], None],
    recovery_context: tuple[int, str, str],
) -> bool:
    """Publish, verify durably, then discard rollback authority."""

    candidate_descriptor = open_beneath(
        directory_descriptor,
        temporary_name,
        os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW,
    )
    candidate = _identity_from_descriptor(candidate_descriptor)
    committed = False
    try:
        committed = _publish_transaction_retained(
            directory_descriptor,
            temporary_name,
            target_name,
            content,
            create=create,
            expected_digest=expected_digest,
            expected_identity=expected_identity,
            max_bytes=max_bytes,
            verify_namespace=verify_namespace,
            candidate_descriptor=candidate_descriptor,
            candidate=candidate,
            recovery_context=recovery_context,
        )
        return committed
    finally:
        close_publication(lambda: os.close(candidate_descriptor), committed)


def _publish_transaction_retained(
    directory_descriptor: int,
    temporary_name: str,
    target_name: str,
    content: bytes,
    *,
    create: bool,
    expected_digest: str | None,
    expected_identity: tuple[int, int, int] | None,
    max_bytes: int,
    verify_namespace: Callable[[], None],
    candidate_descriptor: int,
    candidate: tuple[int, int, int],
    recovery_context: tuple[int, str, str],
) -> bool:
    staged = False
    try:
        if create:
            publish_create(directory_descriptor, temporary_name, target_name)
        else:
            assert expected_digest is not None and expected_identity is not None
            if not exchange_cas(
                directory_descriptor,
                temporary_name,
                target_name,
                expected_digest,
                expected_identity,
                max_bytes,
            ):
                _cleanup_candidate(
                    directory_descriptor, temporary_name, recovery_context
                )
                return False
        staged = True
        _verify_published(
            directory_descriptor,
            target_name,
            candidate,
            content,
            max_bytes,
        )
        verify_namespace()
        os.fsync(directory_descriptor)
    except Exception:
        if staged:
            _rollback_publication(
                directory_descriptor,
                temporary_name,
                target_name,
                create=create,
                candidate_descriptor=candidate_descriptor,
                candidate=candidate,
                candidate_content=content,
            )
        _cleanup_candidate(
            directory_descriptor, temporary_name, recovery_context
        )
        raise
    if not create:
        _cleanup_committed_backup(
            directory_descriptor,
            temporary_name,
            recovery_context,
        )
    return True


def _named_identity(
    directory_descriptor: int,
    name: str,
) -> tuple[int, int, int]:
    descriptor = open_beneath(
        directory_descriptor,
        name,
        os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW,
    )
    try:
        information = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    return information.st_dev, information.st_ino, information.st_mode


def _identity_from_descriptor(descriptor: int) -> tuple[int, int, int]:
    information = os.fstat(descriptor)
    return information.st_dev, information.st_ino, information.st_mode


def _verify_published(
    directory_descriptor: int,
    target_name: str,
    expected_identity: tuple[int, int, int],
    content: bytes,
    max_bytes: int,
) -> None:
    descriptor = open_beneath(
        directory_descriptor,
        target_name,
        os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW,
    )
    try:
        before = os.fstat(descriptor)
        invalid = (
            (before.st_dev, before.st_ino, before.st_mode) != expected_identity
            or not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
        )
        if invalid:
            raise OSError(errno.EPERM, "published target identity changed")
        actual = _read_bounded(descriptor, max_bytes)
        os.fsync(descriptor)
        after = os.fstat(descriptor)
        if _stable_stat_key(before) != _stable_stat_key(after) or actual != content:
            raise OSError(errno.EIO, "published target verification failed")
    finally:
        os.close(descriptor)


def _rollback_publication(
    directory_descriptor: int,
    temporary_name: str,
    target_name: str,
    *,
    create: bool,
    candidate_descriptor: int,
    candidate: tuple[int, int, int],
    candidate_content: bytes,
) -> None:
    try:
        current = _named_identity(directory_descriptor, target_name)
    except FileNotFoundError:
        current = None
    if current != candidate:
        _preserve_competing_rollback(
            directory_descriptor,
            temporary_name,
            candidate_descriptor,
            candidate_content,
            create=create,
        )
    if create:
        try:
            publish_create(directory_descriptor, target_name, temporary_name)
        except OSError:
            _preserve_competing_rollback(
                directory_descriptor,
                temporary_name,
                candidate_descriptor,
                candidate_content,
                create=True,
            )
        if _named_identity(directory_descriptor, temporary_name) != candidate:
            publish_create(directory_descriptor, temporary_name, target_name)
            _preserve_competing_rollback(
                directory_descriptor,
                temporary_name,
                candidate_descriptor,
                candidate_content,
                create=True,
            )
    else:
        try:
            exchange_relative(directory_descriptor, temporary_name, target_name)
        except OSError:
            _preserve_competing_rollback(
                directory_descriptor,
                temporary_name,
                candidate_descriptor,
                candidate_content,
                create=False,
            )
        if _named_identity(directory_descriptor, temporary_name) != candidate:
            exchange_relative(directory_descriptor, temporary_name, target_name)
            _preserve_competing_rollback(
                directory_descriptor,
                temporary_name,
                candidate_descriptor,
                candidate_content,
                create=False,
            )
    os.fsync(directory_descriptor)


def _preserve_competing_rollback(
    directory_descriptor: int,
    temporary_name: str,
    candidate_descriptor: int,
    candidate_content: bytes,
    *,
    create: bool,
) -> None:
    artifacts: list[dict[str, object]] = []
    if not create:
        recovery_name = (
            f".hocus-recovery-v1-{os.urandom(16).hex()}-displaced.bin"
        )
        try:
            publish_create(directory_descriptor, temporary_name, recovery_name)
            artifacts.append(
                _recovery_artifact(
                    directory_descriptor, recovery_name, "displaced"
                )
            )
        except Exception:
            pass
    candidate_name = (
        f".hocus-recovery-v1-{os.urandom(16).hex()}-candidate.bin"
    )
    try:
        mode = stat.S_IMODE(os.fstat(candidate_descriptor).st_mode)
        write_temporary(
            directory_descriptor,
            candidate_name,
            candidate_content,
            mode,
        )
        artifacts.append(
            _recovery_artifact(
                directory_descriptor, candidate_name, "candidate"
            )
        )
    except Exception:
        pass
    try:
        os.fsync(directory_descriptor)
    except OSError:
        _LOG.warning("HOCUS828 recovery artifact namespace flush deferred")
    _LOG.warning("HOCUS828 competing workspace target preserved for recovery")
    raise RecoveryRequired(tuple(artifacts))


def _recovery_artifact(
    directory_descriptor: int,
    name: str,
    role: str,
) -> dict[str, object]:
    descriptor = open_beneath(
        directory_descriptor,
        name,
        os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW,
    )
    try:
        information = os.fstat(descriptor)
        content = _read_bounded(descriptor, _MAX_RECOVERY_BYTES)
        if not stat.S_ISREG(information.st_mode) or information.st_nlink != 1:
            raise OSError(errno.EPERM, "unsafe recovery evidence")
    finally:
        close_publication(lambda: os.close(descriptor), False)
    return artifact_metadata(name, role, content)


def _cleanup_committed_backup(
    directory_descriptor: int,
    temporary_name: str,
    recovery_context: tuple[int, str, str],
) -> None:
    recovery_root_descriptor, recovery_target, recovery_parent = recovery_context
    try:
        os.unlink(temporary_name, dir_fd=directory_descriptor)
    except OSError:
        recovery_name = (
            f".hocus-recovery-v1-{os.urandom(16).hex()}-displaced.bin"
        )
        try:
            publish_create(directory_descriptor, temporary_name, recovery_name)
        except OSError:
            recovery_name = temporary_name
        _record_deferred_cleanup(
            recovery_root_descriptor,
            recovery_target,
            recovery_parent,
            _safe_recovery_artifact(
                directory_descriptor, recovery_name, "displaced"
            ),
        )
        _LOG.warning("HOCUS828 committed workspace backup cleanup deferred")
        return
    try:
        os.fsync(directory_descriptor)
    except OSError:
        _record_deferred_cleanup(
            recovery_root_descriptor,
            recovery_target,
            recovery_parent,
            (),
        )
        _LOG.warning("HOCUS828 committed workspace cleanup durability deferred")


def _cleanup_candidate(
    directory_descriptor: int,
    temporary_name: str,
    recovery_context: tuple[int, str, str],
) -> None:
    root_descriptor, target, parent = recovery_context
    try:
        os.unlink(temporary_name, dir_fd=directory_descriptor)
    except FileNotFoundError:
        return
    except OSError:
        recovery_name = (
            f".hocus-recovery-v1-{os.urandom(16).hex()}-candidate.bin"
        )
        try:
            publish_create(directory_descriptor, temporary_name, recovery_name)
        except OSError:
            recovery_name = temporary_name
        _record_deferred_cleanup(
            root_descriptor,
            target,
            parent,
            _safe_recovery_artifact(
                directory_descriptor, recovery_name, "candidate"
            ),
        )
        _LOG.warning("HOCUS828 rollback candidate cleanup deferred")
        return
    try:
        os.fsync(directory_descriptor)
    except OSError:
        _record_deferred_cleanup(root_descriptor, target, parent, ())
        _LOG.warning("HOCUS828 rollback candidate cleanup durability deferred")


def _record_deferred_cleanup(
    root_descriptor: int,
    target: str,
    parent: str,
    artifacts: tuple[dict[str, object], ...],
) -> None:
    try:
        write_recovery_marker(
            root_descriptor,
            target,
            parent,
            RecoveryRequired(artifacts),
        )
    except Exception:
        _LOG.warning("HOCUS828 workspace recovery marker publication deferred")


def _safe_recovery_artifact(
    directory_descriptor: int,
    name: str,
    role: str,
) -> tuple[dict[str, object], ...]:
    try:
        return (_recovery_artifact(directory_descriptor, name, role),)
    except Exception:
        _LOG.warning("HOCUS828 workspace recovery artifact inspection deferred")
        return ()


def canonical_root(root: Path) -> Path:
    authored = str(root)
    if not root.is_absolute() or authored != os.path.abspath(authored):
        raise NativeWorkspaceError("HOCUS822", "Approved workspace root is not canonical.")
    try:
        resolved = root.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise NativeWorkspaceError("HOCUS822", "Approved workspace root is unavailable.") from exc
    if str(resolved) != authored:
        raise NativeWorkspaceError("HOCUS822", "Approved workspace root contains a link or alias.")
    current = Path(root.anchor)
    for part in root.parts[1:]:
        current /= part
        try:
            if stat.S_ISLNK(os.lstat(current).st_mode):
                raise NativeWorkspaceError(
                    "HOCUS822", "Approved workspace root contains a symbolic link."
                )
        except OSError as exc:
            raise NativeWorkspaceError("HOCUS822", "Approved workspace root is unavailable.") from exc
    return root


def open_root(path: Path) -> int:
    try:
        return os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError as exc:
        raise NativeWorkspaceError("HOCUS822", "Approved workspace root cannot be pinned.") from exc


def require_safe_object(
    identity: PosixIdentity,
    root_device: int,
    *,
    directory: bool,
) -> None:
    if identity.device != root_device:
        raise NativeWorkspaceError("HOCUS824", "Workspace path crosses a filesystem boundary.")
    expected = stat.S_ISDIR(identity.mode) if directory else stat.S_ISREG(identity.mode)
    if not expected:
        raise NativeWorkspaceError("HOCUS824", "Workspace path contains an unsafe object type.")


def require_safe_file(identity: PosixIdentity, root_device: int) -> None:
    require_safe_object(identity, root_device, directory=False)
    if identity.links != 1:
        raise NativeWorkspaceError("HOCUS824", "Workspace files with hard links are rejected.")


def read_descriptor(descriptor: int, max_bytes: int, expected_size: int) -> bytes:
    if expected_size > max_bytes:
        raise NativeWorkspaceError("HOCUS825", "Workspace file exceeds the read limit.")
    os.lseek(descriptor, 0, os.SEEK_SET)
    chunks: list[bytes] = []
    remaining = max_bytes + 1
    while remaining:
        chunk = os.read(descriptor, min(64 * 1024, remaining))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    content = b"".join(chunks)
    if len(content) > max_bytes:
        raise NativeWorkspaceError("HOCUS825", "Workspace file exceeds the read limit.")
    return content


def write_temporary(
    parent_descriptor: int,
    name: str,
    content: bytes,
    mode: int,
) -> None:
    try:
        descriptor = open_beneath(
            parent_descriptor,
            name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC,
            mode,
        )
        try:
            with os.fdopen(descriptor, "wb", closefd=False) as stream:
                _write_stream(stream, content)
                stream.flush()
                os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError as exc:
        unlink_if_present(parent_descriptor, name)
        raise NativeWorkspaceError(
            "HOCUS828", "Workspace temporary publication failed."
        ) from exc


def unlink_if_present(parent_descriptor: int, name: str) -> None:
    try:
        os.unlink(name, dir_fd=parent_descriptor)
    except FileNotFoundError:
        pass


def open_child_directory(parent_descriptor: int, name: str, root_device: int) -> int:
    try:
        descriptor = open_beneath(
            parent_descriptor,
            name,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
        )
    except OSError as exc:
        raise NativeWorkspaceError(
            "HOCUS824", "Workspace directory cannot be safely opened."
        ) from exc
    try:
        require_safe_object(
            PosixIdentity.from_stat(os.fstat(descriptor)),
            root_device,
            directory=True,
        )
    except Exception:
        os.close(descriptor)
        raise
    return descriptor


def _write_stream(stream: BinaryIO, content: bytes) -> None:
    view = memoryview(content)
    while view:
        written = stream.write(view)
        if written is None or written <= 0:
            raise OSError("short workspace write")
        view = view[written:]


__all__ = [
    "PosixIdentity",
    "canonical_root",
    "exchange_cas",
    "exchange_relative",
    "inspect_regular",
    "local_filesystem_name",
    "open_beneath",
    "open_child_directory",
    "open_root",
    "publish_create",
    "publish_transaction",
    "read_descriptor",
    "require_safe_file",
    "require_safe_object",
    "unlink_if_present",
    "write_temporary",
]

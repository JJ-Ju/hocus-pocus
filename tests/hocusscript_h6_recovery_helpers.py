"""Private fault scenarios for H6 publication recovery."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from pathlib import Path
from unittest import mock

from hocuspocus.hocusscript.workspace_io import WorkspaceIO, WorkspaceIOError

_LOCK_PROBE = """
import ctypes, os, sys
from hocuspocus.hocusscript import _workspace_publication_lock as host
descriptor = host.open_publication_lock(sys.argv[1], map(int, sys.argv[2].split(",")))
blocked = False
if os.name == "nt":
    import msvcrt
    from hocuspocus.hocusscript import _workspace_windows_rename as native
    lock = native._Overlapped()
    lock.Offset = 0x7FFFFFFF
    blocked = not native._LockFileEx(
        msvcrt.get_osfhandle(descriptor),
        native._LOCKFILE_FAIL_IMMEDIATELY | native._LOCKFILE_EXCLUSIVE_LOCK,
        0, 1, 0, ctypes.byref(lock),
    )
else:
    import fcntl
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        blocked = True
print("blocked" if blocked else "unlocked")
"""


def _digest(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


def _assert_code(
    case: unittest.TestCase,
    code: str,
    callback,
) -> None:
    with case.assertRaises(WorkspaceIOError) as caught:
        callback()
    case.assertEqual(caught.exception.code, code)


def _open_workspace(root: Path) -> WorkspaceIO:
    return WorkspaceIO.open_project(
        root,
        source_directories=("src",),
        module_directories=("modules",),
        lock_path="pins/hocus.lock.json",
        catalog_path="catalog/catalog.json",
        writable=True,
    )


def exercise_strong_identity_admission(
    case: unittest.TestCase,
    root: Path,
) -> None:
    with (
        mock.patch(
            "hocuspocus.hocusscript._workspace_linux.fcntl.ioctl",
            side_effect=OSError("injected missing inode generation"),
        ),
        case.subTest(strong_root_identity_required=True),
    ):
        _assert_code(case, "HOCUS822", lambda: _open_workspace(root))
    shared_memory = Path("/dev/shm")
    if not shared_memory.is_dir():
        return
    import tempfile

    with tempfile.TemporaryDirectory(
        prefix="hocus-h6-tmpfs-", dir=shared_memory
    ) as directory:
        tmpfs_root = Path(directory) / "project"
        tmpfs_root.mkdir()
        with case.subTest(tmpfs_identity_rejected=True):
            _assert_code(case, "HOCUS822", lambda: _open_workspace(tmpfs_root))


def exercise_postcommit_close(
    case: unittest.TestCase,
    root: Path,
    workspace: WorkspaceIO,
    source: str,
) -> None:
    target = root / "src/main.hocus"
    expected = workspace.read("src/main.hocus").file.raw_digest
    published = source.replace("Main", "CommittedClose")
    committed = False
    if os.name == "nt":
        from hocuspocus.hocusscript import _workspace_windows_rename as platform_io

        native_close = platform_io._CloseHandle
        native_delete = platform_io.mark_delete

        def observe_commit(handle):
            nonlocal committed
            result = native_delete(handle)
            committed = True
            return result

        def close_after_commit(handle):
            result = native_close(handle)
            if committed:
                raise OSError("injected post-commit close failure")
            return result

        patchers = (
            mock.patch.object(platform_io, "mark_delete", side_effect=observe_commit),
            mock.patch.object(platform_io, "_CloseHandle", side_effect=close_after_commit),
        )
    else:
        from hocuspocus.hocusscript import _workspace_linux as platform_io

        native_close = platform_io.os.close
        native_cleanup = platform_io._cleanup_committed_backup
        injected = False

        def observe_commit(*args):
            nonlocal committed
            native_cleanup(*args)
            committed = True

        def close_after_commit(descriptor):
            nonlocal injected
            result = native_close(descriptor)
            if committed and not injected:
                injected = True
                raise OSError("injected post-commit close failure")
            return result

        patchers = (
            mock.patch.object(
                platform_io, "_cleanup_committed_backup", side_effect=observe_commit
            ),
            mock.patch.object(platform_io.os, "close", side_effect=close_after_commit),
        )
    with patchers[0], patchers[1], case.subTest(postcommit_close_nonthrowing=True):
        result = workspace.publish(
            "src/main.hocus",
            published,
            expected_digest=expected,
        )
    case.assertTrue(committed)
    case.assertEqual(result.file.raw_digest, _digest(published.encode()))
    case.assertEqual(target.read_text(encoding="utf-8"), published)


def exercise_publication_lock_boundary(
    case: unittest.TestCase,
    root: Path,
    workspace: WorkspaceIO,
    source: str,
) -> None:
    legacy = root / ".hocus-recovery-lock-v1"
    legacy.write_bytes(b"clean           \n" if os.name == "nt" else b"clean\n")
    expected = workspace.read("src/main.hocus").file.raw_digest
    published = source.replace("Main", "HostStateLock")
    with case.subTest(legacy_lock_requires_explicit_migration=True):
        _assert_code(
            case,
            "HOCUS828",
            lambda: workspace.publish(
                "src/main.hocus",
                published,
                expected_digest=expected,
            ),
        )
        case.assertTrue(legacy.exists())
        case.assertEqual(
            (root / "src/main.hocus").read_text(encoding="utf-8"),
            source,
        )
    legacy.unlink()

    from hocuspocus.hocusscript import _workspace_publication_lock as host_lock

    hostile_environment = {
        "HOME": str(root / "fake-home"),
        "HOUDINI_USER_PREF_DIR": str(root / "fake-houdini"),
        "LOCALAPPDATA": str(root / "fake-local"),
        "XDG_STATE_HOME": str(root / "fake-xdg"),
    }
    identity = (root.stat().st_dev, root.stat().st_ino, 0x483645)
    with mock.patch.dict(os.environ, hostile_environment):
        first_base = host_lock._host_state_root()
        first_descriptor = host_lock.open_publication_lock("environment-test", identity)
        first_stat = os.fstat(first_descriptor)
        first_lock_identity = first_stat.st_dev, first_stat.st_ino
    with mock.patch.dict(
        os.environ,
        {name: str(root / f"other-{name}") for name in hostile_environment},
    ):
        second_base = host_lock._host_state_root()
        second_descriptor = host_lock.open_publication_lock("environment-test", identity)
        second_stat = os.fstat(second_descriptor)
        second_lock_identity = second_stat.st_dev, second_stat.st_ino
    try:
        case.assertEqual(first_base, second_base)
        case.assertEqual(first_lock_identity, second_lock_identity)
        _assert_host_lock_contention(
            case,
            first_descriptor,
            identity,
            {name: str(root / f"probe-{name}") for name in hostile_environment},
        )
    finally:
        os.close(second_descriptor)
        os.close(first_descriptor)
    case.assertFalse(any(path.name.startswith("fake-") for path in root.iterdir()))

    unlock_failed = False
    closes_after_failure = 0
    if os.name == "nt":
        from hocuspocus.hocusscript import _workspace_windows_rename as platform_io

        native_unlock = platform_io._UnlockFileEx
        native_close = platform_io.os.close

        def fail_guard_unlock(*args):
            nonlocal unlock_failed
            if args[2:4] == (1, 0):
                unlock_failed = True
                return False
            return native_unlock(*args)
    else:
        from hocuspocus.hocusscript import _workspace_linux as platform_io

        native_flock = platform_io.fcntl.flock
        native_close = platform_io.os.close

        def fail_guard_unlock(descriptor, operation):
            nonlocal unlock_failed
            if operation == platform_io.fcntl.LOCK_UN:
                unlock_failed = True
                raise OSError("injected publication unlock failure")
            return native_flock(descriptor, operation)

    def observe_close(descriptor):
        nonlocal closes_after_failure
        if unlock_failed:
            closes_after_failure += 1
        return native_close(descriptor)

    unlock_name = "_UnlockFileEx" if os.name == "nt" else "fcntl.flock"
    unlock_patcher = (
        mock.patch.object(platform_io, "_UnlockFileEx", side_effect=fail_guard_unlock)
        if os.name == "nt"
        else mock.patch.object(platform_io.fcntl, "flock", side_effect=fail_guard_unlock)
    )
    with (
        unlock_patcher,
        mock.patch.object(platform_io.os, "close", side_effect=observe_close),
        case.assertLogs(platform_io.__name__, level="WARNING") as logs,
        case.subTest(host_lock_release_nonmasking=unlock_name),
    ):
        result = workspace.publish(
            "src/main.hocus",
            published,
            expected_digest=expected,
        )
    case.assertEqual(result.file.raw_digest, _digest(published.encode()))
    case.assertGreaterEqual(closes_after_failure, 1)
    case.assertFalse(legacy.exists())
    case.assertNotIn(legacy.name, {path.name for path in root.rglob("*")})
    case.assertNotIn(str(root), "\n".join(logs.output))

    unlock_failed = False
    closes_after_failure = 0
    unlock_patcher = (
        mock.patch.object(platform_io, "_UnlockFileEx", side_effect=fail_guard_unlock)
        if os.name == "nt"
        else mock.patch.object(platform_io.fcntl, "flock", side_effect=fail_guard_unlock)
    )
    with (
        unlock_patcher,
        mock.patch.object(platform_io.os, "close", side_effect=observe_close),
        case.assertLogs(platform_io.__name__, level="WARNING"),
        case.subTest(primary_error_preserved=True),
    ):
        _assert_code(case, "HOCUS826", lambda: workspace.create("src/main.hocus", source))
    case.assertGreaterEqual(closes_after_failure, 1)


def _assert_host_lock_contention(
    case: unittest.TestCase,
    first_descriptor: int,
    identity: tuple[int, ...],
    child_environment: dict[str, str],
) -> None:
    def probe() -> None:
        environment = {**os.environ, **child_environment}
        python_path = str(Path.cwd() / "python3.11libs")
        environment["PYTHONPATH"] = os.pathsep.join(
            filter(None, (python_path, environment.get("PYTHONPATH")))
        )
        completed = subprocess.run(
            (
                sys.executable,
                "-c",
                _LOCK_PROBE,
                "environment-test",
                ",".join(map(str, identity)),
            ),
            capture_output=True,
            check=False,
            env=environment,
            text=True,
            timeout=10,
        )
        case.assertEqual(completed.returncode, 0, completed.stderr)
        case.assertEqual(completed.stdout.strip(), "blocked")

    if os.name == "nt":
        import ctypes
        import msvcrt

        from hocuspocus.hocusscript import _workspace_windows_rename as platform_io

        first_lock = platform_io._Overlapped()
        first_lock.Offset = 0x7FFFFFFF
        case.assertTrue(
            platform_io._LockFileEx(
                msvcrt.get_osfhandle(first_descriptor),
                platform_io._LOCKFILE_EXCLUSIVE_LOCK,
                0,
                1,
                0,
                ctypes.byref(first_lock),
            )
        )
        try:
            probe()
        finally:
            platform_io._UnlockFileEx(
                msvcrt.get_osfhandle(first_descriptor),
                0,
                1,
                0,
                ctypes.byref(first_lock),
            )
        return
    import fcntl

    fcntl.flock(first_descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        probe()
    finally:
        fcntl.flock(first_descriptor, fcntl.LOCK_UN)


def exercise_candidate_cleanup(
    case: unittest.TestCase,
    root: Path,
    workspace: WorkspaceIO,
    source: str,
) -> None:
    target = root / "src/main.hocus"
    original = target.read_bytes()
    expected = workspace.read("src/main.hocus").file.raw_digest
    candidate = source.replace("Main", "RollbackCandidate")
    flushes: list[int] = []
    marker_roots: list[int] = []
    if os.name == "nt":
        from hocuspocus.hocusscript import _workspace_windows_rename as platform_io

        native_delete = platform_io._DeleteFileW
        native_flush = platform_io._FlushFileBuffers
        native_marker = platform_io.write_recovery_marker

        def defer_candidate(path):
            if "-candidate.bin" in str(path):
                return False
            return native_delete(path)

        patchers = (
            mock.patch.object(platform_io, "verify_relative", return_value=23),
            mock.patch.object(
                platform_io, "_DeleteFileW", side_effect=defer_candidate
            ),
        )

        def observe_flush(handle):
            flushes.append(handle)
            return native_flush(handle)

        def observe_marker(root_handle, *args):
            marker_roots.append(root_handle)
            return native_marker(root_handle, *args)

        observations = (
            mock.patch.object(
                platform_io, "_FlushFileBuffers", side_effect=observe_flush
            ),
            mock.patch.object(
                platform_io, "write_recovery_marker", side_effect=observe_marker
            ),
        )
    else:
        from hocuspocus.hocusscript import _workspace_linux as platform_io

        native_unlink = platform_io.os.unlink

        def defer_candidate(path, *args, **kwargs):
            if str(path).startswith(".hocus-write-"):
                raise OSError("injected rollback candidate cleanup failure")
            return native_unlink(path, *args, **kwargs)

        patchers = (
            mock.patch.object(
                platform_io,
                "_verify_published",
                side_effect=OSError("injected rollback"),
            ),
            mock.patch.object(
                platform_io.os, "unlink", side_effect=defer_candidate
            ),
        )
        observations = (nullcontext(), nullcontext())
    with (
        patchers[0],
        patchers[1],
        observations[0],
        observations[1],
        case.assertLogs(platform_io.__name__, level="WARNING") as logs,
        case.subTest(rollback_candidate_cleanup_deferred=True),
    ):
        _assert_code(
            case,
            "HOCUS828",
            lambda: workspace.publish(
                "src/main.hocus",
                candidate,
                expected_digest=expected,
            ),
        )
    marker = root / ".hocus-recovery-v1.json"
    record_text = marker.read_text(encoding="utf-8")
    record = json.loads(record_text)
    artifacts = tuple(root / item["path"] for item in record["artifacts"])
    case.assertEqual(target.read_bytes(), original)
    case.assertIn(candidate.encode(), {path.read_bytes() for path in artifacts})
    case.assertEqual({item["role"] for item in record["artifacts"]}, {"candidate"})
    case.assertLessEqual(len(artifacts), 2)
    case.assertNotIn(str(root), record_text)
    case.assertNotIn(str(root), "\n".join(logs.output))
    if os.name == "nt":
        case.assertTrue(marker_roots)
        case.assertIn(marker_roots[0], flushes)
        case.assertTrue(any(handle != marker_roots[0] for handle in flushes))
    _assert_code(
        case,
        "HOCUS828",
        lambda: workspace.publish(
            "src/main.hocus",
            candidate,
            expected_digest=expected,
        ),
    )
    for artifact in artifacts:
        artifact.unlink()
    marker.unlink()


def exercise_marker_failure(
    case: unittest.TestCase,
    root: Path,
    workspace: WorkspaceIO,
    source: str,
) -> None:
    expected = workspace.read("src/main.hocus").file.raw_digest
    candidate = source.replace("Main", "MarkerFailure")
    if os.name == "nt":
        from hocuspocus.hocusscript import _workspace_windows_rename as platform_io

        native_create = platform_io.create_relative
        native_delete = platform_io._DeleteFileW

        def fail_marker(parent, name):
            if name == platform_io.RECOVERY_MARKER:
                return None, 5
            return native_create(parent, name)

        def defer_candidate(path):
            return False if "-candidate.bin" in str(path) else native_delete(path)

        patchers = (
            mock.patch.object(platform_io, "verify_relative", return_value=23),
            mock.patch.object(platform_io, "create_relative", side_effect=fail_marker),
            mock.patch.object(platform_io, "_DeleteFileW", side_effect=defer_candidate),
        )
    else:
        from hocuspocus.hocusscript import _workspace_linux as platform_io

        native_publish = platform_io.publish_create
        native_unlink = platform_io.os.unlink

        def fail_marker(parent, temporary, target):
            if target == platform_io.RECOVERY_MARKER:
                raise OSError("injected marker publication failure")
            return native_publish(parent, temporary, target)

        def defer_candidate(path, *args, **kwargs):
            if str(path).startswith(".hocus-write-"):
                raise OSError("injected candidate cleanup failure")
            return native_unlink(path, *args, **kwargs)

        patchers = (
            mock.patch.object(
                platform_io,
                "_verify_published",
                side_effect=OSError("injected rollback"),
            ),
            mock.patch.object(platform_io, "publish_create", side_effect=fail_marker),
            mock.patch.object(platform_io.os, "unlink", side_effect=defer_candidate),
        )
    with patchers[0], patchers[1], patchers[2], case.subTest(marker_failure=True):
        _assert_code(
            case,
            "HOCUS828",
            lambda: workspace.publish(
                "src/main.hocus", candidate, expected_digest=expected
            ),
        )
    case.assertFalse((root / ".hocus-recovery-v1.json").exists())
    artifacts = tuple(root.rglob(".hocus-recovery-v1-*.bin"))
    case.assertGreaterEqual(len(artifacts), 1)
    case.assertLessEqual(len(artifacts), 2)
    reopened = _open_workspace(root)
    try:
        _assert_code(
            case,
            "HOCUS828",
            lambda: reopened.publish(
                "src/main.hocus", candidate, expected_digest=expected
            ),
        )
    finally:
        reopened.close()


def exercise_recovery_contention(
    case: unittest.TestCase,
    root: Path,
    workspace: WorkspaceIO,
    source: str,
) -> None:
    second = _open_workspace(root)
    expected = workspace.read("src/main.hocus").file.raw_digest
    barrier = threading.Barrier(2)
    if os.name == "nt":
        from hocuspocus.hocusscript import _workspace_windows_rename as platform_io

        patcher = mock.patch.object(platform_io, "mark_delete", return_value=5)
    else:
        from hocuspocus.hocusscript import _workspace_linux as platform_io

        native_unlink = platform_io.os.unlink

        def defer_backup(path, *args, **kwargs):
            if str(path).startswith(".hocus-write-"):
                raise OSError("injected contender cleanup failure")
            return native_unlink(path, *args, **kwargs)

        patcher = mock.patch.object(
            platform_io.os, "unlink", side_effect=defer_backup
        )

    def publish(current: WorkspaceIO, graph: str) -> str:
        barrier.wait(timeout=10)
        try:
            current.publish(
                "src/main.hocus",
                source.replace("Main", graph),
                expected_digest=expected,
            )
        except WorkspaceIOError as exc:
            return exc.code
        return "ok"

    try:
        with patcher, ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = tuple(
                future.result(timeout=20)
                for future in (
                    pool.submit(publish, workspace, "ContenderA"),
                    pool.submit(publish, second, "ContenderB"),
                )
            )
        case.assertCountEqual(outcomes, ("ok", "HOCUS828"))
        case.assertTrue((root / ".hocus-recovery-v1.json").exists())
        artifacts = tuple(root.rglob(".hocus-recovery-v1-*.bin"))
        case.assertLessEqual(len(artifacts), 2)
        case.assertLessEqual(
            sum(path.stat().st_size for path in artifacts),
            24 * 1024 * 1024,
        )
    finally:
        second.close()


def exercise_competing_recovery(
    case: unittest.TestCase,
    root: Path,
    workspace: WorkspaceIO,
    source: str,
) -> None:
    target = root / "src/main.hocus"
    original = target.read_bytes()
    expected = workspace.read("src/main.hocus").file.raw_digest
    published = source.replace("Main", "RejectedRollback")
    competitor = source.replace("Main", "CompetingWriter").encode()
    if os.name == "nt":
        from hocuspocus.hocusscript import _workspace_windows_rename as platform_io

        native_replace = platform_io._ReplaceFileW
        calls = 0

        def race_rollback(*args):
            nonlocal calls
            calls += 1
            if calls == 2:
                raced = root / "src/competing.tmp"
                raced.write_bytes(competitor)
                os.replace(raced, target)
                return False
            return native_replace(*args)

        patchers = (
            mock.patch.object(platform_io, "verify_relative", return_value=23),
            mock.patch.object(
                platform_io, "_ReplaceFileW", side_effect=race_rollback
            ),
        )
    else:
        from hocuspocus.hocusscript import _workspace_linux as platform_io

        native_exchange = platform_io.exchange_relative
        calls = 0

        def race_rollback(*args):
            nonlocal calls
            calls += 1
            if calls == 2:
                raced = root / "src/competing.tmp"
                raced.write_bytes(competitor)
                os.replace(raced, target)
                raise OSError("injected rollback syscall failure")
            return native_exchange(*args)

        patchers = (
            mock.patch.object(
                platform_io,
                "_verify_published",
                side_effect=OSError("injected competing target"),
            ),
            mock.patch.object(
                platform_io, "exchange_relative", side_effect=race_rollback
            ),
        )
    with (
        patchers[0],
        patchers[1],
        case.assertLogs(platform_io.__name__, level="WARNING") as logs,
        case.subTest(competing_target_preserved=True),
    ):
        _assert_code(
            case,
            "HOCUS828",
            lambda: workspace.publish(
                "src/main.hocus",
                published,
                expected_digest=expected,
            ),
        )
    case.assertEqual(target.read_bytes(), competitor)
    marker = root / ".hocus-recovery-v1.json"
    record_text = marker.read_text(encoding="utf-8")
    record = json.loads(record_text)
    artifacts = tuple(root / item["path"] for item in record["artifacts"])
    case.assertIn(original, {artifact.read_bytes() for artifact in artifacts})
    case.assertEqual((record["target"], record["state"]), ("src/main.hocus", "unresolved"))
    case.assertLessEqual(len(artifacts), 2)
    case.assertLessEqual(sum(item.stat().st_size for item in artifacts), 24 * 1024 * 1024)
    case.assertNotIn(str(root), record_text)
    case.assertNotIn(str(root), "\n".join(logs.output))
    before = tuple(sorted(root.rglob(".hocus-recovery-v1-*")))
    _assert_code(
        case,
        "HOCUS828",
        lambda: workspace.create("src/blocked.hocus", source),
    )
    reopened = WorkspaceIO.open_project(
        root,
        source_directories=("src",),
        module_directories=("modules",),
        lock_path="pins/hocus.lock.json",
        catalog_path="catalog/catalog.json",
        writable=True,
    )
    try:
        _assert_code(
            case,
            "HOCUS828",
            lambda: reopened.publish(
                "src/main.hocus",
                published,
                expected_digest=_digest(competitor),
            ),
        )
    finally:
        reopened.close()
    case.assertEqual(before, tuple(sorted(root.rglob(".hocus-recovery-v1-*"))))
    for artifact in artifacts:
        artifact.unlink()
    marker.unlink()
    result = workspace.publish(
        "src/main.hocus",
        published,
        expected_digest=_digest(competitor),
    )
    case.assertEqual(result.file.raw_digest, _digest(published.encode()))
    _exercise_deleted_rollback_target(case, root, workspace, source)
    if os.name != "nt":
        _exercise_create_race(case, root, workspace, source)


def _exercise_deleted_rollback_target(
    case: unittest.TestCase,
    root: Path,
    workspace: WorkspaceIO,
    source: str,
) -> None:
    target = root / "src/main.hocus"
    baseline = target.read_bytes()
    expected = workspace.read("src/main.hocus").file.raw_digest
    candidate = source.replace("Main", "DeletedRollbackTarget")
    if os.name == "nt":
        from hocuspocus.hocusscript import _workspace_windows_rename as platform_io

        native_replace = platform_io._ReplaceFileW
        calls = 0

        def delete_then_fail(*args):
            nonlocal calls
            calls += 1
            if calls == 2:
                Path(args[0]).unlink(missing_ok=True)
                return False
            return native_replace(*args)

        patchers = (
            mock.patch.object(platform_io, "verify_relative", return_value=23),
            mock.patch.object(
                platform_io, "_ReplaceFileW", side_effect=delete_then_fail
            ),
        )
    else:
        from hocuspocus.hocusscript import _workspace_linux as platform_io

        native_exchange = platform_io.exchange_relative
        calls = 0

        def delete_then_fail(*args):
            nonlocal calls
            calls += 1
            if calls == 2:
                target.unlink(missing_ok=True)
                raise OSError("injected deleted rollback target")
            return native_exchange(*args)

        patchers = (
            mock.patch.object(
                platform_io,
                "_verify_published",
                side_effect=OSError("injected rollback"),
            ),
            mock.patch.object(
                platform_io, "exchange_relative", side_effect=delete_then_fail
            ),
        )
    with patchers[0], patchers[1], case.subTest(rollback_target_deleted=True):
        _assert_code(
            case,
            "HOCUS828",
            lambda: workspace.publish(
                "src/main.hocus", candidate, expected_digest=expected
            ),
        )
    marker = root / ".hocus-recovery-v1.json"
    record = json.loads(marker.read_text(encoding="utf-8"))
    artifacts = tuple(root / item["path"] for item in record["artifacts"])
    case.assertFalse(target.exists())
    case.assertIn(baseline, {path.read_bytes() for path in artifacts})
    case.assertLessEqual(len(artifacts), 2)
    for artifact in artifacts:
        artifact.unlink()
    marker.unlink()
    target.write_bytes(baseline)


def _exercise_create_race(
    case: unittest.TestCase,
    root: Path,
    workspace: WorkspaceIO,
    source: str,
) -> None:
    target = root / "src/create-race.hocus"
    candidate = source.replace("Main", "CreateCandidate")
    competitor = source.replace("Main", "CreateCompetitor").encode()

    def install_competitor() -> None:
        raced = root / "src/create-competing.tmp"
        raced.write_bytes(competitor)
        os.replace(raced, target)

    from hocuspocus.hocusscript import _workspace_linux as platform_io

    def fail_after_race(*_args, **_kwargs):
        install_competitor()
        raise OSError("injected create competitor")

    patcher = mock.patch.object(
        platform_io,
        "_verify_published",
        side_effect=fail_after_race,
    )
    with patcher, case.subTest(competing_create_preserved=True):
        _assert_code(
            case,
            "HOCUS828",
            lambda: workspace.create("src/create-race.hocus", candidate),
        )
    marker = root / ".hocus-recovery-v1.json"
    record = json.loads(marker.read_text(encoding="utf-8"))
    artifacts = tuple(root / item["path"] for item in record["artifacts"])
    case.assertEqual(target.read_bytes(), competitor)
    case.assertIn(candidate.encode(), {artifact.read_bytes() for artifact in artifacts})
    case.assertEqual({item["role"] for item in record["artifacts"]}, {"candidate"})
    _assert_code(
        case,
        "HOCUS828",
        lambda: workspace.create("src/create-race-2.hocus", candidate),
    )
    for artifact in artifacts:
        artifact.unlink()
    marker.unlink()

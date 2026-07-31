"""Private H6 descriptor-I/O acceptance helpers.

The public catalogue keeps one workflow per product promise.  Platform and
fault permutations live here so they do not become individual test methods.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
import threading
import unittest
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from hocuspocus.hocusscript import workspace_snapshot
from hocuspocus.hocusscript.project_manifest_guard import validate_manifest_patch
from hocuspocus.hocusscript.project_service_support import SourceServiceError
from hocuspocus.hocusscript.project_services import SourceWorkspaceService
from hocuspocus.hocusscript.workspace_io import (
    MAX_WORKSPACE_FILE_BYTES,
    MAX_WORKSPACE_FILES,
    WorkspaceFilePolicy,
    WorkspaceIO,
    WorkspaceIOError,
)
from hocuspocus.hocusscript.workspace_snapshot import MAX_SNAPSHOT_BYTES
from tests.hocusscript_h6_snapshot_helpers import exercise_snapshot_construction_unwind

_MANIFEST = """schema_version = 4
[project]
uid = "h6-io-project"
name = "H6 IO"
source_directories = ["src"]
module_directories = ["modules"]
[language]
version = "0.3"
[lock]
policy = "required"
path = "pins/hocus.lock.json"
[catalog]
path = "catalog/catalog.json"
"""
_SOURCE = 'hocus 0.3;\ngraph Main { target "/obj"; category Sop; }\n'
_EXTERNAL_MANIFEST = """schema_version = 2
entry_modules = ["modules/main.hocus"]
[library]
uid = "h6-library"
version = "1.0.0"
[language]
version = "0.3"
"""


def _digest(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


def _write_project(root: Path) -> None:
    for relative in ("src", "modules", "pins", "catalog"):
        (root / relative).mkdir(parents=True, exist_ok=True)
    (root / "hocus.project.toml").write_bytes(_MANIFEST.encode())
    (root / "src/main.hocus").write_bytes(_SOURCE.encode())
    (root / "modules/shared.hocus").write_bytes(
        b'hocus 0.3;\ngraph Shared { target "/obj"; category Sop; }\n'
    )
    (root / "pins/hocus.lock.json").write_bytes(b"{}\n")
    (root / "catalog/catalog.json").write_bytes(b"{}\n")


@contextmanager
def _project_workspace(*, writable: bool = False):
    with tempfile.TemporaryDirectory(prefix="hocus-h6-io-") as directory:
        root = Path(directory) / "project"
        _write_project(root)
        workspace = WorkspaceIO.open_project(
            root,
            source_directories=("src",),
            module_directories=("modules",),
            lock_path="pins/hocus.lock.json",
            catalog_path="catalog/catalog.json",
            writable=writable,
        )
        try:
            yield root, workspace
        finally:
            workspace.close()


def _assert_code(
    case: unittest.TestCase,
    code: str,
    callback,
) -> WorkspaceIOError:
    with case.assertRaises(WorkspaceIOError) as caught:
        callback()
    case.assertEqual(caught.exception.code, code)
    return caught.exception


def _exercise_admission_aliases(case: unittest.TestCase, workspace: WorkspaceIO) -> None:
    hostile = (
        "../src/main.hocus",
        "/src/main.hocus",
        r"src\main.hocus",
        "src/./main.hocus",
        unicodedata.normalize("NFD", "src/caf\u00e9.hocus"),
    )
    for path in hostile:
        with case.subTest(hostile_path=path):
            _assert_code(case, "HOCUS823", lambda path=path: workspace.read(path))
    with case.subTest(case_alias=True):
        _assert_code(
            case,
            "HOCUS823",
            lambda: WorkspaceFilePolicy.create(
                ("src", "SRC"),
                (),
                "pins/hocus.lock.json",
                None,
            ),
        )
    with case.subTest(unicode_alias=True):
        composed = "caf\u00e9"
        decomposed = unicodedata.normalize("NFD", composed)
        _assert_code(
            case,
            "HOCUS823",
            lambda: WorkspaceFilePolicy.create(
                (composed, decomposed),
                (),
                "pins/hocus.lock.json",
                None,
            ),
        )


def _exercise_link_denials(
    case: unittest.TestCase,
    root: Path,
    workspace: WorkspaceIO,
) -> None:
    hardlink = root / "src/hardlink.hocus"
    try:
        os.link(root / "src/main.hocus", hardlink)
    except OSError:
        with case.subTest(hardlink_supported=False):
            pass
    else:
        try:
            with case.subTest(hardlink=True):
                _assert_code(case, "HOCUS824", lambda: workspace.read("src/hardlink.hocus"))
        finally:
            hardlink.unlink(missing_ok=True)

    candidates = (
        (root / "src/file-link.hocus", root / "src/main.hocus", False),
        (root / "src/directory-link", root / "modules", True),
    )
    for link, target, directory in candidates:
        try:
            link.symlink_to(target, target_is_directory=directory)
        except (OSError, NotImplementedError):
            with case.subTest(symlink_supported=False, directory=directory):
                pass
            continue
        try:
            relative = (
                "src/directory-link/shared.hocus"
                if directory
                else "src/file-link.hocus"
            )
            with case.subTest(symlink=True, directory=directory):
                _assert_code(case, "HOCUS824", lambda: workspace.read(relative))
        finally:
            link.unlink(missing_ok=True)


def _exercise_root_swap(
    case: unittest.TestCase,
    root: Path,
    workspace: WorkspaceIO,
) -> None:
    displaced = root.with_name("project-displaced")
    replacement_open = False
    try:
        root.rename(displaced)
    except PermissionError:
        with case.subTest(root_swap_blocked=True):
            case.assertEqual(workspace.read("src/main.hocus").content, _SOURCE)
        return
    try:
        _write_project(root)
        replacement_open = True
        with case.subTest(root_swap=True):
            _assert_code(case, "HOCUS824", lambda: workspace.read("src/main.hocus"))
    finally:
        if replacement_open:
            shutil.rmtree(root)
        displaced.rename(root)


def _exercise_component_swap(
    case: unittest.TestCase,
    root: Path,
    workspace: WorkspaceIO,
) -> None:
    provider = workspace._native._provider
    original_verify = type(provider)._verify_chain
    source = root / "src"
    displaced = root / "src-displaced"
    swapped = False
    blocked = False

    def swap_then_verify(instance, parts, identities):
        nonlocal blocked, swapped
        if not swapped and parts and parts[0] == "src":
            try:
                source.rename(displaced)
            except PermissionError:
                blocked = True
            else:
                source.mkdir()
                (source / "main.hocus").write_bytes(_SOURCE.encode())
                swapped = True
        return original_verify(instance, parts, identities)

    try:
        with mock.patch.object(type(provider), "_verify_chain", swap_then_verify):
            with case.subTest(component_swap=True):
                if os.name == "nt":
                    case.assertEqual(workspace.read("src/main.hocus").content, _SOURCE)
                    case.assertTrue(blocked)
                else:
                    _assert_code(
                        case,
                        "HOCUS824",
                        lambda: workspace.read("src/main.hocus"),
                    )
    finally:
        if swapped:
            shutil.rmtree(source)
            displaced.rename(source)


def _exercise_unsupported_filesystem(
    case: unittest.TestCase,
    root: Path,
) -> None:
    if os.name == "nt":
        patcher = mock.patch(
            "hocuspocus.hocusscript._workspace_native._windows_filesystem",
            return_value="ReFS",
        )
    else:
        patcher = mock.patch(
            "hocuspocus.hocusscript._workspace_native._linux_filesystem_name",
            return_value=None,
        )
    with patcher, case.subTest(unsupported_filesystem=True):
        _assert_code(
            case,
            "HOCUS822",
            lambda: WorkspaceIO.open_project(
                root,
                source_directories=("src",),
                module_directories=("modules",),
                lock_path="pins/hocus.lock.json",
            ),
        )
    if os.name != "nt":
        from tests.hocusscript_h6_recovery_helpers import (
            exercise_strong_identity_admission,
        )

        exercise_strong_identity_admission(case, root)


def _exercise_external_internal_manifest(case: unittest.TestCase) -> None:
    with tempfile.TemporaryDirectory(prefix="hocus-h6-external-") as directory:
        root = Path(directory)
        (root / "modules").mkdir()
        (root / "hocus.module.toml").write_bytes(_EXTERNAL_MANIFEST.encode())
        (root / "modules/main.hocus").write_bytes(_SOURCE.encode())
        with WorkspaceIO.open_external(root) as scope:
            with case.subTest(external_manifest_not_public=True):
                names = {item.relative_path for item in scope.enumerate_files()}
                case.assertNotIn("hocus.module.toml", names)
                case.assertEqual(names, {"modules/main.hocus"})
                _assert_code(
                    case,
                    "HOCUS823",
                    lambda: scope.read("hocus.module.toml"),
                )
        with _project_workspace() as (_, project):
            with project.native_snapshot(
                include_external_roots={"studio": root}
            ) as snapshot:
                with case.subTest(external_manifest_snapshot_internal=True):
                    copied = snapshot.external_roots["studio"] / "hocus.module.toml"
                    case.assertEqual(copied.read_text(encoding="utf-8"), _EXTERNAL_MANIFEST)
                (root / "modules/late.hocus").write_bytes(
                    _SOURCE.replace("Main", "LateExternal").encode()
                )
                with case.subTest(external_added_path_rejected=True):
                    _assert_code(case, "HOCUS824", snapshot.recheck)


def _exercise_snapshot_cleanup_aggregation(case: unittest.TestCase) -> None:
    from hocuspocus.hocusscript._workspace_native import PinnedWorkspace

    with tempfile.TemporaryDirectory(prefix="hocus-h6-cleanup-") as directory:
        external = Path(directory) / "external"
        (external / "modules").mkdir(parents=True)
        (external / "hocus.module.toml").write_bytes(_EXTERNAL_MANIFEST.encode())
        (external / "modules/main.hocus").write_bytes(_SOURCE.encode())
        with _project_workspace() as (_, workspace):
            snapshot = workspace.native_snapshot(
                include_external_roots={"studio": external}
            )
            attempts = {
                "native": 0,
                "scope": 0,
                "permissions": 0,
                "tree": 0,
            }
            close_native = PinnedWorkspace.close
            close_scope = WorkspaceIO._close_strict
            prepare_tree = workspace_snapshot._require_tree_cleanup
            cleanup_tree = tempfile.TemporaryDirectory.cleanup

            def failing_native(native):
                attempts["native"] += 1
                close_native(native)
                raise RuntimeError("private-native-cleanup")

            def failing_scope(scope):
                attempts["scope"] += 1
                close_scope(scope)
                raise RuntimeError("private-root-cleanup")

            def failing_permissions(root):
                attempts["permissions"] += 1
                prepare_tree(root)
                raise OSError("private-permission-cleanup")

            def failing_tree(owner):
                attempts["tree"] += 1
                cleanup_tree(owner)
                raise OSError("private-tree-cleanup")

            with (
                mock.patch.object(PinnedWorkspace, "close", failing_native),
                mock.patch.object(
                    WorkspaceIO, "_close_strict", failing_scope
                ),
                mock.patch.object(
                    workspace_snapshot,
                    "_require_tree_cleanup",
                    failing_permissions,
                ),
                mock.patch.object(
                    tempfile.TemporaryDirectory,
                    "cleanup",
                    failing_tree,
                ),
                case.assertRaises(WorkspaceIOError) as failed,
            ):
                snapshot.close()
            with case.subTest(snapshot_cleanup_attempts_all_resources=True):
                case.assertGreaterEqual(attempts["native"], 2)
                case.assertEqual(attempts["scope"], 1)
                case.assertEqual(attempts["permissions"], 1)
                case.assertEqual(attempts["tree"], 1)
                case.assertGreaterEqual(failed.exception.details["failureCount"], 5)
                case.assertNotIn("private-", str(failed.exception.details))
                before = dict(attempts)
                snapshot.close()
                case.assertEqual(attempts, before)


def _exercise_generated_read_limits(
    case: unittest.TestCase,
    root: Path,
    workspace: WorkspaceIO,
) -> None:
    oversized_authored = b"x" * (MAX_WORKSPACE_FILE_BYTES + 1)
    catalog = b" " * (MAX_WORKSPACE_FILE_BYTES + 1) + b"\n"
    lock = b" " * (MAX_WORKSPACE_FILE_BYTES + 1) + b"\n"
    (root / "src/oversized.hocus").write_bytes(oversized_authored)
    (root / "catalog/catalog.json").write_bytes(catalog)
    (root / "pins/hocus.lock.json").write_bytes(lock)

    with case.subTest(authored_limit_remains_narrow=True):
        _assert_code(case, "HOCUS825", lambda: workspace.read("src/oversized.hocus"))
    (root / "src/oversized.hocus").unlink()
    with case.subTest(generated_limits_are_kind_specific=True):
        case.assertEqual(
            workspace.read_generated("catalog/catalog.json").file.raw_digest,
            _digest(catalog),
        )
        case.assertEqual(
            workspace.read_generated("pins/hocus.lock.json").file.raw_digest,
            _digest(lock),
        )
        with workspace.native_snapshot(
            include_external_roots={}
        ) as identity_snapshot:
            replacement = root / "src/same-bytes.tmp"
            replacement.write_bytes((root / "src/main.hocus").read_bytes())
            os.replace(replacement, root / "src/main.hocus")
            with case.subTest(snapshot_same_bytes_new_identity_rejected=True):
                _assert_code(case, "HOCUS824", identity_snapshot.recheck)
        with workspace.native_snapshot(include_external_roots={}) as snapshot:
            case.assertEqual(
                snapshot.read_generated("catalog/catalog.json"),
                catalog,
            )
            case.assertEqual(
                snapshot.read_generated("pins/hocus.lock.json"),
                lock,
            )
            snapshot.recheck()
            read_identity = workspace_snapshot._read_with_identity
            inserted = False

            def insert_during_recheck(scope, path, maximum):
                nonlocal inserted
                receipt = read_identity(scope, path, maximum)
                if scope is workspace and not inserted:
                    inserted = True
                    (root / "src/late-winner.hocus").write_bytes(
                        _SOURCE.replace("Main", "LateWinner").encode()
                    )
                return receipt

            with (
                mock.patch.object(
                    workspace_snapshot,
                    "_read_with_identity",
                    insert_during_recheck,
                ),
                case.subTest(snapshot_phase_boundary_addition_rejected=True),
            ):
                _assert_code(case, "HOCUS824", snapshot.recheck)
            case.assertTrue(inserted)


def _exercise_snapshot_incremental_budgets(case: unittest.TestCase) -> None:
    with _project_workspace() as (_, workspace):
        paths = {f"src/item-{index:04d}.hocus" for index in range(40)}
        chunk = b"x" * MAX_WORKSPACE_FILE_BYTES
        reads = 0

        def bounded_read(_scope, _path, maximum):
            nonlocal reads
            reads += 1
            case.assertLessEqual(maximum, MAX_SNAPSHOT_BYTES)
            return chunk, f"native-{reads}"

        with (
            mock.patch.object(
                WorkspaceIO, "_enumerated_authored_paths", return_value=paths
            ),
            mock.patch.object(
                workspace_snapshot, "_read_with_identity", bounded_read
            ),
            case.subTest(snapshot_byte_budget_rejects_before_extra_read=True),
        ):
            _assert_code(
                case,
                "HOCUS825",
                lambda: workspace.native_snapshot(include_external_roots={}),
            )
        case.assertEqual(reads, MAX_SNAPSHOT_BYTES // MAX_WORKSPACE_FILE_BYTES)

        too_many = {
            f"src/item-{index:04d}.hocus" for index in range(MAX_WORKSPACE_FILES)
        }
        with (
            mock.patch.object(
                WorkspaceIO, "_enumerated_authored_paths", return_value=too_many
            ),
            mock.patch.object(workspace_snapshot, "_read_with_identity") as unread,
            case.subTest(snapshot_file_budget_rejects_before_reads=True),
        ):
            _assert_code(
                case,
                "HOCUS825",
                lambda: workspace.native_snapshot(include_external_roots={}),
            )
            unread.assert_not_called()


def exercise_descriptor_safe_reads(case: unittest.TestCase) -> None:
    """Exercise the complete descriptor-safe enumeration/read workflow."""

    with _project_workspace() as (root, workspace):
        with case.subTest(happy_path=True):
            files = workspace.enumerate_files()
            case.assertEqual(
                {item.relative_path for item in files},
                {
                    "hocus.project.toml",
                    "modules/shared.hocus",
                    "src/main.hocus",
                },
            )
            receipt = workspace.read("src/main.hocus")
            case.assertEqual(receipt.content, _SOURCE)
            case.assertEqual(
                [match.relative_path for match in workspace.search("graph Main")],
                ["src/main.hocus"],
            )
            identity = workspace._native.inspect_identity(("src", "main.hocus"))
            case.assertRegex(identity, r"^sha256:[0-9a-f]{64}$")
            case.assertEqual(
                identity,
                workspace._native.inspect_identity(("src", "main.hocus")),
            )
        _exercise_admission_aliases(case, workspace)
        _exercise_link_denials(case, root, workspace)
        _exercise_component_swap(case, root, workspace)
        _exercise_unsupported_filesystem(case, root)
        _exercise_root_swap(case, root, workspace)
        _exercise_generated_read_limits(case, root, workspace)
    _exercise_external_internal_manifest(case)
    _exercise_snapshot_cleanup_aggregation(case)
    exercise_snapshot_construction_unwind(
        case, _project_workspace, _SOURCE, _EXTERNAL_MANIFEST
    )
    _exercise_snapshot_incremental_budgets(case)


def _patch_for(path: str, old: str, new: str) -> str:
    return (
        f"--- a/{path}\n"
        f"+++ b/{path}\n"
        "@@ -1,2 +1,2 @@\n"
        " hocus 0.3;\n"
        f'-graph {old} {{ target "/obj"; category Sop; }}\n'
        f'+graph {new} {{ target "/obj"; category Sop; }}\n'
    )


def _exercise_create_patch_and_generated_denial(
    case: unittest.TestCase,
    workspace: WorkspaceIO,
) -> None:
    with case.subTest(create=True):
        created = workspace.create("src/created.hocus", _SOURCE.replace("Main", "Created"))
        case.assertTrue(created.created)
        _assert_code(
            case,
            "HOCUS826",
            lambda: workspace.create("src/created.hocus", _SOURCE),
        )
    with case.subTest(unified_patch=True):
        current = workspace.read("src/main.hocus")
        patched = workspace.apply_patch(
            "src/main.hocus",
            _patch_for("src/main.hocus", "Main", "Patched"),
            expected_digest=current.file.raw_digest,
        )
        case.assertIn("graph Patched", workspace.read("src/main.hocus").content)
        case.assertEqual(patched.previous_raw_digest, current.file.raw_digest)
    for operation in (
        lambda: workspace.read("pins/hocus.lock.json"),
        lambda: workspace.create("pins/hocus.lock.json", "{}\n"),
        lambda: workspace.publish(
            "catalog/catalog.json",
            "{}\n",
            expected_digest=_digest(b"{}\n"),
        ),
    ):
        with case.subTest(generated_file_denial=True):
            _assert_code(case, "HOCUS823", operation)


def _exercise_stale_digest_rollback(
    case: unittest.TestCase,
    root: Path,
    workspace: WorkspaceIO,
) -> None:
    target = root / "src/main.hocus"
    admitted = workspace.read("src/main.hocus").file.raw_digest
    concurrent = _SOURCE.replace("Main", "ExternalWriter").encode()
    replacement = root / "src/external.tmp"
    replacement.write_bytes(concurrent)
    os.replace(replacement, target)
    rejected = _SOURCE.replace("Main", "Rejected")

    if os.name == "nt":
        from hocuspocus.hocusscript import _workspace_native as native_io
        from hocuspocus.hocusscript import _workspace_windows_rename as platform_io

        with native_io._open_windows_handle(target, directory=False) as retained:
            retained_native = native_io._windows_identity(retained)
            retained_identity = (retained_native.volume, retained_native.index)
        compare_started = threading.Event()
        observation_complete = threading.Event()
        observations: list[tuple[bytes, tuple[int, int]]] = []
        native_read = platform_io._read_all

        def observed_native_read(handle: int, max_bytes: int):
            compare_started.set()
            if not observation_complete.wait(timeout=10):
                raise AssertionError("concurrent observer did not complete")
            return native_read(handle, max_bytes)

        def observe_target() -> None:
            if not compare_started.wait(timeout=10):
                return
            with native_io._open_windows_handle(target, directory=False) as observed:
                identity = native_io._windows_identity(observed)
                content = native_io._read_windows_handle(
                    observed,
                    MAX_WORKSPACE_FILE_BYTES,
                    identity.size,
                )
            observations.append((content, (identity.volume, identity.index)))
            observation_complete.set()

        with (
            mock.patch.object(platform_io, "_read_all", observed_native_read),
            ThreadPoolExecutor(max_workers=1) as pool,
        ):
            observer = pool.submit(observe_target)
            with case.subTest(stale_digest_never_publishes=True):
                _assert_code(
                    case,
                    "HOCUS826",
                    lambda: workspace.publish(
                        "src/main.hocus",
                        rejected,
                        expected_digest=admitted,
                    ),
                )
            observer.result(timeout=10)
        case.assertEqual(observations, [(concurrent, retained_identity)])
    else:
        from hocuspocus.hocusscript import _workspace_linux as platform_io

        retained_identity = (target.stat().st_dev, target.stat().st_ino)
        compare_started = threading.Event()
        observation_complete = threading.Event()
        observations = []
        native_read = platform_io._read_bounded

        def observed_native_read(descriptor: int, max_bytes: int):
            compare_started.set()
            if not observation_complete.wait(timeout=10):
                raise AssertionError("concurrent observer did not complete")
            return native_read(descriptor, max_bytes)

        def observe_target() -> None:
            if not compare_started.wait(timeout=10):
                return
            stat_result = target.stat()
            observations.append(
                (
                    target.read_bytes(),
                    (stat_result.st_dev, stat_result.st_ino),
                )
            )
            observation_complete.set()

        with (
            mock.patch.object(platform_io, "_read_bounded", observed_native_read),
            ThreadPoolExecutor(max_workers=1) as pool,
        ):
            observer = pool.submit(observe_target)
            with case.subTest(stale_digest_never_publishes=True):
                _assert_code(
                    case,
                    "HOCUS826",
                    lambda: workspace.publish(
                        "src/main.hocus",
                        rejected,
                        expected_digest=admitted,
                    ),
                )
            observer.result(timeout=10)
        case.assertEqual(observations, [(concurrent, retained_identity)])
    with case.subTest(stale_displaced_digest=True):
        case.assertEqual(target.read_bytes(), concurrent)
        if os.name == "nt":
            with native_io._open_windows_handle(target, directory=False) as final_handle:
                final_native = native_io._windows_identity(final_handle)
                final_identity = (final_native.volume, final_native.index)
        else:
            final_identity = (target.stat().st_dev, target.stat().st_ino)
        case.assertEqual(final_identity, retained_identity)
        case.assertFalse(tuple(target.parent.glob(".hocus-*.tmp")))
    _exercise_windows_pre_guard_swap(case, root, workspace)
    _exercise_windows_commit_race(case, root, workspace)


def _exercise_windows_pre_guard_swap(
    case: unittest.TestCase,
    root: Path,
    workspace: WorkspaceIO,
) -> None:
    if os.name != "nt":
        return
    provider = workspace._native._provider
    original_guard = type(provider)._open_namespace_guards
    source = root / "src"
    displaced = root / "src-pre-guard"
    swapped = False

    def swap_then_guard(instance, parent_parts, expected):
        nonlocal swapped
        source.rename(displaced)
        source.mkdir()
        (source / "main.hocus").write_bytes(_SOURCE.encode())
        swapped = True
        return original_guard(instance, parent_parts, expected)

    expected = workspace.read("src/main.hocus").file.raw_digest
    try:
        with (
            mock.patch.object(
                type(provider),
                "_open_namespace_guards",
                swap_then_guard,
            ),
            case.subTest(pre_guard_parent_swap_rejected=True),
        ):
            _assert_code(
                case,
                "HOCUS824",
                lambda: workspace.publish(
                    "src/main.hocus",
                    _SOURCE.replace("Main", "RejectedPreGuard"),
                    expected_digest=expected,
                ),
            )
    finally:
        if swapped:
            shutil.rmtree(source)
            displaced.rename(source)


def _exercise_windows_commit_race(
    case: unittest.TestCase,
    root: Path,
    workspace: WorkspaceIO,
) -> None:
    if os.name != "nt":
        return
    from hocuspocus.hocusscript import _workspace_native as native_io
    from hocuspocus.hocusscript import _workspace_windows_rename as platform_io

    target = root / "src/main.hocus"
    expected = workspace.read("src/main.hocus").file.raw_digest
    raced_content = _SOURCE.replace("Main", "CommitRace").encode()
    native_replace = platform_io._ReplaceFileW
    replace_calls = 0
    raced_identity: tuple[int, int] | None = None
    parent_swap_blocked = False

    def inject_race(*args):
        nonlocal parent_swap_blocked, raced_identity, replace_calls
        replace_calls += 1
        if replace_calls == 1:
            parent = root / "src"
            displaced_parent = root / "src-displaced"
            try:
                parent.rename(displaced_parent)
            except PermissionError:
                parent_swap_blocked = True
            else:
                displaced_parent.rename(parent)
            raced_file = root / "src/raced.tmp"
            raced_file.write_bytes(raced_content)
            os.replace(raced_file, target)
            with native_io._open_windows_handle(target, directory=False) as handle:
                identity = native_io._windows_identity(handle)
                raced_identity = (identity.volume, identity.index)
        return native_replace(*args)

    with (
        mock.patch.object(platform_io, "_ReplaceFileW", side_effect=inject_race),
        case.subTest(actual_displaced_object_restored=True),
    ):
        _assert_code(
            case,
            "HOCUS826",
            lambda: workspace.publish(
                "src/main.hocus",
                _SOURCE.replace("Main", "RejectedCommit"),
                expected_digest=expected,
            ),
        )
    with native_io._open_windows_handle(target, directory=False) as final_handle:
        final = native_io._windows_identity(final_handle)
        final_identity = (final.volume, final.index)
    case.assertEqual(replace_calls, 2)
    case.assertTrue(parent_swap_blocked)
    case.assertEqual(target.read_bytes(), raced_content)
    case.assertEqual(final_identity, raced_identity)
    case.assertFalse(tuple(target.parent.glob(".hocus-*.tmp")))


def _exercise_concurrent_writers(
    case: unittest.TestCase,
    root: Path,
) -> None:
    first = WorkspaceIO.open_project(
        root,
        source_directories=("src",),
        module_directories=("modules",),
        lock_path="pins/hocus.lock.json",
        catalog_path="catalog/catalog.json",
        writable=True,
    )
    second = WorkspaceIO.open_project(
        root,
        source_directories=("src",),
        module_directories=("modules",),
        lock_path="pins/hocus.lock.json",
        catalog_path="catalog/catalog.json",
        writable=True,
    )
    expected = first.read("src/main.hocus").file.raw_digest
    barrier = threading.Barrier(2)

    def publish(workspace: WorkspaceIO, graph: str) -> str:
        barrier.wait(timeout=10)
        try:
            workspace.publish(
                "src/main.hocus",
                _SOURCE.replace("Main", graph),
                expected_digest=expected,
            )
        except WorkspaceIOError as exc:
            return exc.code
        return "ok"

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = tuple(
                future.result(timeout=20)
                for future in (
                    pool.submit(publish, first, "WriterA"),
                    pool.submit(publish, second, "WriterB"),
                )
            )
        with case.subTest(concurrent_writers=True):
            case.assertCountEqual(outcomes, ("ok", "HOCUS826"))
            final = (root / "src/main.hocus").read_text(encoding="utf-8")
            case.assertTrue("graph WriterA" in final or "graph WriterB" in final)
    finally:
        first.close()
        second.close()


def _exercise_fault_rollback(
    case: unittest.TestCase,
    root: Path,
    workspace: WorkspaceIO,
) -> None:
    target = root / "src/main.hocus"
    original = target.read_bytes()
    expected = _digest(original)
    calls = 0
    if os.name == "nt":
        from hocuspocus.hocusscript import _workspace_windows_rename as platform_io

        durable = platform_io._FlushFileBuffers

        def injected_flush(handle):
            nonlocal calls
            calls += 1
            return False if calls == 3 else durable(handle)

        patcher = mock.patch.object(
            platform_io,
            "_FlushFileBuffers",
            side_effect=injected_flush,
        )
    else:
        from hocuspocus.hocusscript import _workspace_linux as platform_io

        durable = platform_io.os.fsync

        def injected_flush(handle):
            nonlocal calls
            calls += 1
            if calls == 3:
                raise OSError("injected directory flush failure")
            return durable(handle)

        patcher = mock.patch.object(
            platform_io.os,
            "fsync",
            side_effect=injected_flush,
        )
    with patcher, case.subTest(atomic_fault_rollback=True):
        _assert_code(
            case,
            "HOCUS828",
            lambda: workspace.publish(
                "src/main.hocus",
                _SOURCE.replace("Main", "NeverPublished"),
                expected_digest=expected,
            ),
        )
    case.assertEqual(target.read_bytes(), original)
    case.assertFalse(tuple(target.parent.glob(".hocus-*.tmp")))


def _exercise_postcommit_cleanup_deferred(
    case: unittest.TestCase,
    root: Path,
    workspace: WorkspaceIO,
) -> None:
    import json

    target = root / "src/main.hocus"
    original = target.read_bytes()
    expected = workspace.read("src/main.hocus").file.raw_digest
    published = _SOURCE.replace("Main", "CommittedCleanup")
    if os.name == "nt":
        from hocuspocus.hocusscript import _workspace_windows_rename as platform_io

        patcher = mock.patch.object(platform_io, "mark_delete", return_value=5)
        logger_name = platform_io.__name__
    else:
        from hocuspocus.hocusscript import _workspace_linux as platform_io

        native_unlink = platform_io.os.unlink

        def defer_backup_unlink(path, *args, **kwargs):
            if str(path).startswith(".hocus-write-"):
                raise OSError("injected committed backup cleanup failure")
            return native_unlink(path, *args, **kwargs)

        patcher = mock.patch.object(
            platform_io.os,
            "unlink",
            side_effect=defer_backup_unlink,
        )
        logger_name = platform_io.__name__
    with (
        patcher,
        case.assertLogs(logger_name, level="WARNING") as logs,
        case.subTest(postcommit_cleanup_deferred=True),
    ):
        result = workspace.publish(
            "src/main.hocus",
            published,
            expected_digest=expected,
        )
        _assert_code(
            case,
            "HOCUS828",
            lambda: workspace.publish(
                "src/main.hocus",
                _SOURCE.replace("Main", "BlockedCleanup"),
                expected_digest=result.file.raw_digest,
            ),
        )
    case.assertEqual(result.file.raw_digest, _digest(published.encode()))
    case.assertEqual(target.read_text(encoding="utf-8"), published)
    marker = root / ".hocus-recovery-v1.json"
    record_text = marker.read_text(encoding="utf-8")
    record = json.loads(record_text)
    artifacts = tuple(root / item["path"] for item in record["artifacts"])
    case.assertLessEqual(len(artifacts), 2)
    case.assertLessEqual(sum(path.stat().st_size for path in artifacts), 24 * 1024 * 1024)
    case.assertIn(original, {path.read_bytes() for path in artifacts})
    case.assertNotIn(str(root), record_text)
    case.assertNotIn(str(root), "\n".join(logs.output))
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
                _SOURCE,
                expected_digest=result.file.raw_digest,
            ),
        )
    finally:
        reopened.close()
    for artifact in artifacts:
        artifact.unlink()
    marker.unlink()


def _exercise_create_final_verification_rollback(
    case: unittest.TestCase,
    root: Path,
    workspace: WorkspaceIO,
) -> None:
    target = root / "src/unverified.hocus"
    if os.name == "nt":
        from hocuspocus.hocusscript import _workspace_windows_rename as platform_io

        patcher = mock.patch.object(
            platform_io,
            "verify_relative",
            return_value=23,
        )
    else:
        from hocuspocus.hocusscript import _workspace_linux as platform_io

        patcher = mock.patch.object(
            platform_io,
            "_verify_published",
            side_effect=OSError("injected final verification failure"),
        )
    with patcher, case.subTest(create_final_verification_rollback=True):
        _assert_code(
            case,
            "HOCUS828",
            lambda: workspace.create(
                "src/unverified.hocus",
                _SOURCE.replace("Main", "Unverified"),
            ),
        )
    case.assertFalse(target.exists())
    case.assertFalse(tuple(target.parent.glob(".hocus-*.tmp")))


def _exercise_manifest_reapproval(
    case: unittest.TestCase,
    workspace: WorkspaceIO,
) -> None:
    from hocuspocus.hocusscript.project import ProjectContext
    from hocuspocus.hocusscript.project_manifest_guard import _projection_digest

    current = workspace.read("hocus.project.toml")
    with workspace.native_snapshot(include_external_roots={}) as snapshot:
        context = ProjectContext.load(snapshot.root, validate_lock=False)
        approved = SimpleNamespace(projection_digest=_projection_digest(context))
    patch = (
        "--- a/hocus.project.toml\n"
        "+++ b/hocus.project.toml\n"
        "@@ -5,4 +5,4 @@\n"
        ' source_directories = ["src"]\n'
        '-module_directories = ["modules"]\n'
        '+module_directories = []\n'
        " [language]\n"
        ' version = "0.3"\n'
    )
    with case.subTest(manifest_reapproval=True):
        with case.assertRaises(SourceServiceError) as caught:
            validate_manifest_patch(
                workspace,
                approved,
                "hocus.project.toml",
                patch,
                current.file.raw_digest,
            )
        case.assertEqual(caught.exception.code, "HOCUS824")


class _ServiceAuthority:
    def __init__(self, record: SimpleNamespace):
        self.record = record
        self.invalidations: list[tuple[str, str]] = []

    def authorize(self, *_args, **_kwargs):
        return self.record

    @contextmanager
    def write_lease(self, *_args, **_kwargs):
        yield self.record

    def invalidate(self, project_id: str, reason: str) -> None:
        self.invalidations.append((project_id, reason))


class _ServiceWorkspaceFactory:
    @classmethod
    def open_project(cls, record, *, writable: bool = False):
        return WorkspaceIO.open_project(
            record.approved_root,
            source_directories=("src",),
            module_directories=("modules",),
            lock_path="pins/hocus.lock.json",
            catalog_path="catalog/catalog.json",
            writable=writable,
        )


def _exercise_cache_invalidation(case: unittest.TestCase, root: Path) -> None:
    projection = SimpleNamespace(
        source_directories=("src",),
        module_directories=("modules",),
        lock_path="pins/hocus.lock.json",
        catalog_path="catalog/catalog.json",
        external_aliases=(),
    )
    record = SimpleNamespace(
        project_id="h6-io-project",
        approved_root=root,
        projection_digest="sha256:" + "1" * 64,
        projection=projection,
        grants=("source_read", "source_write"),
        external_roots=(),
        external_root_identities=(),
    )
    authority = _ServiceAuthority(record)
    service = SourceWorkspaceService(authority, _ServiceWorkspaceFactory)
    result = service.apply_patch(
        SimpleNamespace(principal_id="tester", session_id="session"),
        {
            "projectId": record.project_id,
            "mode": "create",
            "path": "src/cache-visible.hocus",
            "content": _SOURCE.replace("Main", "CacheVisible"),
        },
    )
    with case.subTest(cache_invalidation=True):
        case.assertEqual(result["path"], "src/cache-visible.hocus")
        case.assertEqual(
            authority.invalidations,
            [(record.project_id, "source_write")],
        )


def exercise_guarded_publication(case: unittest.TestCase) -> None:
    """Exercise guarded source publication and observable invalidation."""

    from tests.hocusscript_h6_recovery_helpers import (
        exercise_candidate_cleanup,
        exercise_competing_recovery,
        exercise_marker_failure,
        exercise_postcommit_close,
        exercise_publication_lock_boundary,
        exercise_recovery_contention,
    )

    with _project_workspace(writable=True) as (root, workspace):
        _exercise_create_patch_and_generated_denial(case, workspace)
    with _project_workspace(writable=True) as (root, workspace):
        _exercise_stale_digest_rollback(case, root, workspace)
    with tempfile.TemporaryDirectory(prefix="hocus-h6-race-") as directory:
        root = Path(directory) / "project"
        _write_project(root)
        _exercise_concurrent_writers(case, root)
    with _project_workspace(writable=True) as (root, workspace):
        _exercise_fault_rollback(case, root, workspace)
    with _project_workspace(writable=True) as (root, workspace):
        _exercise_postcommit_cleanup_deferred(case, root, workspace)
    with _project_workspace(writable=True) as (root, workspace):
        exercise_postcommit_close(case, root, workspace, _SOURCE)
    with _project_workspace(writable=True) as (root, workspace):
        exercise_publication_lock_boundary(case, root, workspace, _SOURCE)
    with _project_workspace(writable=True) as (root, workspace):
        exercise_candidate_cleanup(case, root, workspace, _SOURCE)
    with _project_workspace(writable=True) as (root, workspace):
        exercise_marker_failure(case, root, workspace, _SOURCE)
    with _project_workspace(writable=True) as (root, workspace):
        exercise_recovery_contention(case, root, workspace, _SOURCE)
    with _project_workspace(writable=True) as (root, workspace):
        _exercise_create_final_verification_rollback(case, root, workspace)
    with _project_workspace(writable=True) as (root, workspace):
        exercise_competing_recovery(case, root, workspace, _SOURCE)
    with _project_workspace(writable=True) as (_, workspace):
        _exercise_manifest_reapproval(case, workspace)
    with tempfile.TemporaryDirectory(prefix="hocus-h6-cache-") as directory:
        root = Path(directory) / "project"
        _write_project(root)
        _exercise_cache_invalidation(case, root)

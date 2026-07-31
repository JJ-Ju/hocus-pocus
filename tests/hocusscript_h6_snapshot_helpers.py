"""Private construction-unwind coverage for H6 workspace snapshots."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from hocuspocus.hocusscript import workspace_snapshot
from hocuspocus.hocusscript._workspace_native import PinnedWorkspace
from hocuspocus.hocusscript.workspace_io import WorkspaceIO, WorkspaceIOError


def exercise_snapshot_construction_unwind(
    case: unittest.TestCase,
    project_workspace,
    source: str,
    external_manifest: str,
) -> None:
    """Prove primary failures survive an attempt-all construction unwind."""

    with tempfile.TemporaryDirectory(prefix="hocus-h6-unwind-") as directory:
        base = Path(directory)
        aliases: dict[str, Path] = {}
        for name in ("one", "two"):
            root = base / name
            (root / "modules").mkdir(parents=True)
            (root / "hocus.module.toml").write_text(
                external_manifest, encoding="utf-8"
            )
            (root / "modules/main.hocus").write_text(source, encoding="utf-8")
            aliases[name] = root

        with project_workspace() as (_, workspace):
            attempts = {"native": 0, "scope": 0, "permissions": 0, "tree": 0}
            close_native = PinnedWorkspace.close
            close_scope = WorkspaceIO._close_strict
            prepare_tree = workspace_snapshot._require_tree_cleanup
            cleanup_tree = tempfile.TemporaryDirectory.cleanup
            materialize = workspace_snapshot._materialize_files
            materializations = 0

            def fail_third_materialization(*args, **kwargs):
                nonlocal materializations
                materializations += 1
                if materializations == 3:
                    raise WorkspaceIOError(
                        "HOCUS826",
                        "Primary snapshot publication rejected.",
                        {"marker": "primary"},
                    )
                return materialize(*args, **kwargs)

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
                mock.patch.object(
                    workspace_snapshot,
                    "_materialize_files",
                    fail_third_materialization,
                ),
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
                case.assertLogs(workspace_snapshot.__name__, level="WARNING") as logs,
                case.assertRaises(WorkspaceIOError) as failed,
            ):
                workspace.native_snapshot(include_external_roots=aliases)

            with case.subTest(snapshot_construction_unwind_preserves_primary=True):
                case.assertEqual(failed.exception.code, "HOCUS826")
                case.assertEqual(failed.exception.details, {"marker": "primary"})
                case.assertEqual(attempts["native"], 3)
                case.assertEqual(attempts["scope"], 2)
                case.assertEqual(attempts["permissions"], 1)
                case.assertEqual(attempts["tree"], 1)
                diagnostics = "\n".join(logs.output)
                case.assertIn("count=5", diagnostics)
                case.assertNotIn("private-", diagnostics)
                case.assertNotIn(directory, diagnostics)


__all__ = ["exercise_snapshot_construction_unwind"]

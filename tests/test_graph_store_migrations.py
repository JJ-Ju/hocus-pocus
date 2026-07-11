from __future__ import annotations

import logging
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python3.11libs"))

from hocuspocus.live.graph_store import (
    GraphStoreSchemaError,
    LiveGraphStore,
    _CURRENT_SCHEMA_VERSION,
    _MIGRATION_1_SQL,
    _MIGRATION_2_SQL,
)


class GraphStoreMigrationTests(unittest.TestCase):
    def _store(self, path: Path) -> LiveGraphStore:
        return LiveGraphStore(logging.getLogger("test"), db_path=path)

    def test_new_database_runs_ordered_migrations(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "graph.sqlite3"
            store = self._store(path)

            with closing(sqlite3.connect(path)) as connection:
                versions = connection.execute(
                    "SELECT version, name FROM graph_store_migrations ORDER BY version"
                ).fetchall()
                user_version = connection.execute("PRAGMA user_version").fetchone()[0]

            self.assertEqual(
                versions,
                [(1, "initial_graph_store"), (2, "apply_operation_audit")],
            )
            self.assertEqual(user_version, _CURRENT_SCHEMA_VERSION)
            self.assertEqual(store.stats()["schemaVersion"], _CURRENT_SCHEMA_VERSION)
            self.assertEqual(store.stats()["migrationCount"], 2)

    def test_version_one_fixture_upgrades_without_losing_documents(self) -> None:
        fixture = ROOT / "tests" / "fixtures" / "graph_store" / "v1.sql"
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "graph.sqlite3"
            with closing(sqlite3.connect(path)) as connection:
                connection.executescript(fixture.read_text(encoding="utf-8"))
                connection.commit()

            store = self._store(path)

            self.assertEqual(
                store.get_document_by_id("fixture:/geo"),
                {"documentId": "fixture:/geo", "kind": "network"},
            )
            store.record_apply_result(
                apply_commit_id="fixture-apply",
                document_id="fixture:/geo",
                root_path="/obj/geo",
                baseline_document_revision=1,
                applied_document_revision=2,
                mode="merge",
                verified=True,
                summary={"created": 1},
                operations=[{"type": "create_node"}],
                diagnostics=[],
                error=None,
            )
            with closing(sqlite3.connect(path)) as connection:
                versions = connection.execute(
                    "SELECT version FROM graph_store_migrations ORDER BY version"
                ).fetchall()
                audit_table = connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='apply_operation_audit'"
                ).fetchone()
            self.assertEqual(versions, [(1,), (2,)])
            self.assertIsNotNone(audit_table)
            self.assertEqual(store.stats()["applyAuditRowCount"], 1)

    def test_exact_unversioned_bootstrap_is_adopted(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "graph.sqlite3"
            with closing(sqlite3.connect(path)) as connection:
                connection.executescript(_MIGRATION_1_SQL)
                connection.executescript(_MIGRATION_2_SQL)
                connection.execute(
                    """
                    INSERT INTO documents (
                        document_id, kind, root_path, latest_revision, live_revision,
                        content_hash, payload_json, source, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "legacy:/geo",
                        "network",
                        "/obj/geo",
                        1,
                        1,
                        "legacy-hash",
                        '{"documentId":"legacy:/geo"}',
                        "legacy",
                        1.0,
                        1.0,
                    ),
                )
                connection.commit()

            store = self._store(path)

            self.assertEqual(store.get_document_by_id("legacy:/geo")["documentId"], "legacy:/geo")
            self.assertEqual(store.stats()["migrationCount"], 2)

    def test_tampered_migration_ledger_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "graph.sqlite3"
            self._store(path)
            with closing(sqlite3.connect(path)) as connection:
                connection.execute(
                    "UPDATE graph_store_migrations SET checksum = 'tampered' WHERE version = 1"
                )
                connection.commit()

            with self.assertRaisesRegex(GraphStoreSchemaError, "does not match this build"):
                self._store(path)

    def test_future_schema_version_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "graph.sqlite3"
            self._store(path)
            with closing(sqlite3.connect(path)) as connection:
                connection.execute("PRAGMA user_version=999")

            with self.assertRaisesRegex(GraphStoreSchemaError, "newer than supported"):
                self._store(path)

    def test_unknown_partial_legacy_schema_is_not_guessed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "graph.sqlite3"
            with closing(sqlite3.connect(path)) as connection:
                connection.execute("CREATE TABLE documents (document_id TEXT PRIMARY KEY)")
                connection.commit()

            with self.assertRaisesRegex(GraphStoreSchemaError, "Cannot safely adopt"):
                self._store(path)

    def test_versioned_database_with_tampered_columns_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "graph.sqlite3"
            self._store(path)
            with closing(sqlite3.connect(path)) as connection:
                connection.execute("DROP TABLE apply_operation_audit")
                connection.execute("CREATE TABLE apply_operation_audit (audit_id INTEGER PRIMARY KEY)")
                connection.commit()

            with self.assertRaisesRegex(GraphStoreSchemaError, "column or index signature"):
                self._store(path)

    def test_versioned_database_with_tampered_index_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "graph.sqlite3"
            self._store(path)
            with closing(sqlite3.connect(path)) as connection:
                connection.execute("DROP INDEX idx_nodes_path")
                connection.execute("CREATE INDEX idx_nodes_path ON nodes(name)")
                connection.commit()

            with self.assertRaisesRegex(GraphStoreSchemaError, "column or index signature"):
                self._store(path)

    def test_malformed_unversioned_legacy_schema_is_not_adopted(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "graph.sqlite3"
            with closing(sqlite3.connect(path)) as connection:
                connection.executescript(_MIGRATION_1_SQL)
                connection.executescript(_MIGRATION_2_SQL)
                connection.execute("DROP INDEX idx_documents_root_path")
                connection.execute("CREATE INDEX idx_documents_root_path ON documents(kind)")
                connection.commit()

            with self.assertRaisesRegex(GraphStoreSchemaError, "column or index signature"):
                self._store(path)


if __name__ == "__main__":
    unittest.main()

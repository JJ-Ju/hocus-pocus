from __future__ import annotations

import logging
import hashlib
import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python3.11libs"))

from hocuspocus.live.graph_store import (
    GraphStorePlanError,
    GraphStoreSchemaError,
    LiveGraphStore,
    _CURRENT_SCHEMA_VERSION,
    _MIGRATION_1_SQL,
    _MIGRATION_2_SQL,
    _MIGRATION_3_SQL,
)


class GraphStoreMigrationTests(unittest.TestCase):
    def _store(self, path: Path) -> LiveGraphStore:
        return LiveGraphStore(logging.getLogger("test"), db_path=path)

    @staticmethod
    def _plan(*, source: str = "sha256:source", plan_id: str = "plan-1") -> dict:
        plan = {
            "kind": "hocus_apply_plan",
            "planVersion": "1.0",
            "planId": plan_id,
            "sessionId": "session-1",
            "createdAt": 100.0,
            "expiresAt": 200.0,
            "sourceDigest": source,
            "catalogFingerprint": "sha256:catalog",
            "catalogContentDigest": "sha256:catalog-content",
            "ownership": "studio.terrain",
            "rootPath": "/obj/geo1",
            "baseline": {
                "documentId": "network:/obj/geo1",
                "documentRevision": 4,
                "liveRevision": 9,
            },
            "requiredCapabilities": ["edit_scene"],
            "executionPlan": {
                "operations": [{"operationId": "op:000000", "action": "create_node", "label": "créer"}],
            },
        }
        encoded = json.dumps(plan, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        plan["planHash"] = f"sha256:{hashlib.sha256(encoded.encode('utf-8')).hexdigest()}"
        return plan

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
                [
                    (1, "initial_graph_store"),
                    (2, "apply_operation_audit"),
                    (3, "immutable_plan_lifecycle"),
                ],
            )
            self.assertEqual(user_version, _CURRENT_SCHEMA_VERSION)
            self.assertEqual(store.stats()["schemaVersion"], _CURRENT_SCHEMA_VERSION)
            self.assertEqual(store.stats()["migrationCount"], 3)

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
            self.assertEqual(versions, [(1,), (2,), (3,)])
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
            self.assertEqual(store.stats()["migrationCount"], 3)

    def test_exact_unversioned_v3_bootstrap_is_adopted(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "graph.sqlite3"
            with closing(sqlite3.connect(path)) as connection:
                connection.executescript(_MIGRATION_1_SQL)
                connection.executescript(_MIGRATION_2_SQL)
                connection.executescript(_MIGRATION_3_SQL)
                connection.commit()

            store = self._store(path)

            self.assertEqual(store.stats()["migrationCount"], 3)
            self.assertEqual(store.stats()["schemaVersion"], 3)

    def test_immutable_plan_round_trip_rejects_replacement_and_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = self._store(Path(temp_dir) / "graph.sqlite3")
            payload = self._plan()
            stored = store.store_immutable_plan(
                plan_id="plan-1",
                session_id="session-1",
                root_path="/obj/geo1",
                expires_at=200.0,
                created_at=100.0,
                payload=payload,
            )
            payload["executionPlan"]["operations"][0]["action"] = "tampered-after-store"

            self.assertEqual(stored["payload"]["executionPlan"]["operations"][0]["action"], "create_node")
            self.assertEqual(store.load_immutable_plan("plan-1"), stored)
            self.assertEqual(store.stats()["immutablePlanCount"], 1)
            with self.assertRaisesRegex(GraphStorePlanError, "already exists"):
                store.store_immutable_plan(
                    plan_id="plan-1",
                    session_id="session-1",
                    root_path="/obj/geo1",
                    expires_at=200.0,
                    created_at=100.0,
                    payload=self._plan(source="sha256:other"),
                )
            tampered = self._plan(plan_id="plan-2")
            tampered["executionPlan"]["operations"].append({"action": "delete_node"})
            with self.assertRaisesRegex(GraphStorePlanError, "hash does not match"):
                store.store_immutable_plan(
                    plan_id="plan-2",
                    session_id="session-1",
                    root_path="/obj/geo1",
                    expires_at=200.0,
                    created_at=100.0,
                    payload=tampered,
                )
            with closing(sqlite3.connect(store.stats()["dbPath"])) as connection:
                connection.execute(
                    "UPDATE immutable_apply_plans SET payload_json = ? WHERE plan_id = 'plan-1'",
                    ('{"planHash":"sha256:tampered"}',),
                )
                connection.commit()
            with self.assertRaisesRegex(GraphStorePlanError, "content-hash"):
                store.load_immutable_plan("plan-1")

    def test_plan_commit_lifecycle_is_atomic_idempotent_and_recoverable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "graph.sqlite3"
            store = self._store(path)
            payload = self._plan()
            store.store_immutable_plan(
                plan_id="plan-1", session_id="session-1", root_path="/obj/geo1",
                expires_at=200.0, created_at=100.0, payload=payload,
            )
            pending = store.begin_plan_commit(
                plan_commit_id="commit-1",
                plan_id="plan-1",
                plan_hash=payload["planHash"],
                session_id="session-1",
                idempotency_key="request-1",
                pre_apply_snapshot={"documentRevision": 4},
                inverse_plan={"operations": []},
                now=150.0,
            )
            replay = store.begin_plan_commit(
                plan_commit_id="ignored-on-replay",
                plan_id="plan-1",
                plan_hash=payload["planHash"],
                session_id="session-1",
                idempotency_key="request-1",
                pre_apply_snapshot={"different": True},
                inverse_plan=None,
                now=151.0,
            )
            self.assertEqual(pending, replay)
            with self.assertRaisesRegex(GraphStorePlanError, "session"):
                store.begin_plan_commit(
                    plan_commit_id="ignored-on-replay",
                    plan_id="plan-1",
                    plan_hash=payload["planHash"],
                    session_id="wrong-session",
                    idempotency_key="request-1",
                    pre_apply_snapshot={},
                    inverse_plan=None,
                    now=151.0,
                )
            self.assertEqual(store.stats()["pendingPlanCommitCount"], 1)
            self.assertEqual(store.recoverable_plan_commits(), [pending])
            with self.assertRaisesRegex(GraphStorePlanError, "already been claimed"):
                store.begin_plan_commit(
                    plan_commit_id="commit-2", plan_id="plan-1", plan_hash=payload["planHash"],
                    session_id="session-1", idempotency_key="request-2",
                    pre_apply_snapshot={}, inverse_plan=None, now=152.0,
                )

            committed = store.finish_plan_commit(
                plan_commit_id="commit-1",
                state="committed",
                result={"verified": True},
                error=None,
                now=160.0,
            )
            replayed_finish = store.finish_plan_commit(
                plan_commit_id="commit-1",
                state="committed",
                result={"verified": True},
                error=None,
                now=170.0,
            )
            self.assertEqual(committed, replayed_finish)
            self.assertEqual(store.load_plan_commit(idempotency_key="request-1"), committed)
            self.assertEqual(store.recoverable_plan_commits(), [])
            with self.assertRaisesRegex(GraphStorePlanError, "already terminal"):
                store.finish_plan_commit(
                    plan_commit_id="commit-1", state="aborted", result=None,
                    error={"code": "late"}, now=180.0,
                )
            with closing(sqlite3.connect(path)) as connection:
                events = connection.execute(
                    "SELECT from_state, to_state FROM plan_commit_events ORDER BY event_id"
                ).fetchall()
            self.assertEqual(events, [(None, "pending"), ("pending", "committed")])

    def test_plan_commit_claim_rejects_expiry_session_and_hash_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = self._store(Path(temp_dir) / "graph.sqlite3")
            payload = self._plan()
            store.store_immutable_plan(
                plan_id="plan-1", session_id="session-1", root_path="/obj/geo1",
                expires_at=200.0, created_at=100.0, payload=payload,
            )
            cases = (
                ({"plan_hash": "sha256:wrong", "session_id": "session-1", "now": 150.0}, "hash"),
                ({"plan_hash": payload["planHash"], "session_id": "session-2", "now": 150.0}, "session"),
                ({"plan_hash": payload["planHash"], "session_id": "session-1", "now": 200.0}, "expired"),
            )
            for index, (overrides, message) in enumerate(cases):
                with self.subTest(message=message), self.assertRaisesRegex(GraphStorePlanError, message):
                    store.begin_plan_commit(
                        plan_commit_id=f"commit-{index}", plan_id="plan-1",
                        idempotency_key=f"request-{index}", pre_apply_snapshot={}, inverse_plan=None,
                        **overrides,
                    )

    def test_partial_commit_requires_explicit_recovery_classification(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = self._store(Path(temp_dir) / "graph.sqlite3")
            payload = self._plan()
            store.store_immutable_plan(payload=payload)
            store.begin_plan_commit(
                plan_commit_id="commit-recovery",
                plan_id=payload["planId"],
                plan_hash=payload["planHash"],
                session_id=payload["sessionId"],
                idempotency_key="request-recovery",
                pre_apply_snapshot={"documentRevision": 4},
                inverse_plan={"operations": []},
                now=150.0,
            )
            store.finish_plan_commit(
                plan_commit_id="commit-recovery",
                state="partial_or_unknown",
                result={"verified": False},
                error={"message": "rollback unknown"},
                now=160.0,
            )
            recovered = store.resolve_plan_commit_recovery(
                plan_commit_id="commit-recovery",
                state="aborted",
                result={"classification": "baseline", "verified": True},
                now=170.0,
            )
            self.assertEqual(recovered["state"], "aborted")
            self.assertEqual(store.recoverable_plan_commits(), [])
            with self.assertRaisesRegex(GraphStorePlanError, "Only partial_or_unknown"):
                store.resolve_plan_commit_recovery(
                    plan_commit_id="commit-recovery",
                    state="committed",
                    result={"classification": "target"},
                    now=180.0,
                )

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

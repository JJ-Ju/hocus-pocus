"""Embedded SQLite-backed document graph store."""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import math
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from hocuspocus.core import paths as core_paths


class GraphStoreSchemaError(RuntimeError):
    """Raised when a graph-store database cannot be migrated safely."""


class GraphStorePlanError(RuntimeError):
    """Raised when immutable-plan or apply-commit state is inconsistent."""


class _ClosingConnection(sqlite3.Connection):
    """SQLite connection whose context manager also releases the file handle."""

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> bool:
        try:
            return bool(super().__exit__(exc_type, exc_value, traceback))
        finally:
            self.close()


_MIGRATION_1_SQL = """
CREATE TABLE IF NOT EXISTS documents (
    document_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    root_path TEXT,
    latest_revision INTEGER NOT NULL,
    live_revision INTEGER,
    content_hash TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    source TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_documents_root_path ON documents(root_path);
CREATE TABLE IF NOT EXISTS document_versions (
    version_id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id TEXT NOT NULL,
    document_revision INTEGER NOT NULL,
    live_revision INTEGER,
    content_hash TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    source TEXT NOT NULL,
    created_at REAL NOT NULL,
    UNIQUE(document_id, document_revision)
);
CREATE INDEX IF NOT EXISTS idx_document_versions_document
    ON document_versions(document_id, document_revision);
CREATE TABLE IF NOT EXISTS nodes (
    document_id TEXT NOT NULL,
    document_revision INTEGER NOT NULL,
    root_path TEXT,
    node_uid TEXT NOT NULL,
    path TEXT NOT NULL,
    name TEXT,
    type_name TEXT,
    category TEXT,
    parent_path TEXT,
    is_network INTEGER NOT NULL DEFAULT 0,
    flags_json TEXT NOT NULL,
    material_path TEXT,
    metadata_json TEXT NOT NULL,
    PRIMARY KEY(document_id, node_uid)
);
CREATE INDEX IF NOT EXISTS idx_nodes_path ON nodes(path);
CREATE INDEX IF NOT EXISTS idx_nodes_type ON nodes(type_name);
CREATE INDEX IF NOT EXISTS idx_nodes_category ON nodes(category);
CREATE INDEX IF NOT EXISTS idx_nodes_root_path ON nodes(root_path);
CREATE TABLE IF NOT EXISTS edges (
    document_id TEXT NOT NULL,
    document_revision INTEGER NOT NULL,
    edge_uid TEXT NOT NULL,
    kind TEXT NOT NULL,
    from_node_uid TEXT,
    to_node_uid TEXT,
    from_json TEXT NOT NULL,
    to_json TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    PRIMARY KEY(document_id, edge_uid)
);
CREATE TABLE IF NOT EXISTS parameter_bindings (
    document_id TEXT NOT NULL,
    document_revision INTEGER NOT NULL,
    binding_uid TEXT NOT NULL,
    node_uid TEXT NOT NULL,
    parm_name TEXT NOT NULL,
    value_mode TEXT NOT NULL,
    value_json TEXT,
    expression TEXT,
    expression_language TEXT,
    channel_reference TEXT,
    code_blob_uid TEXT,
    metadata_json TEXT NOT NULL,
    PRIMARY KEY(document_id, binding_uid)
);
CREATE INDEX IF NOT EXISTS idx_parameter_bindings_node
    ON parameter_bindings(node_uid, parm_name);
CREATE TABLE IF NOT EXISTS code_blobs (
    document_id TEXT NOT NULL,
    document_revision INTEGER NOT NULL,
    code_blob_uid TEXT NOT NULL,
    language TEXT NOT NULL,
    target_json TEXT NOT NULL,
    body TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    PRIMARY KEY(document_id, code_blob_uid)
);
CREATE TABLE IF NOT EXISTS checkouts (
    checkout_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL,
    document_kind TEXT NOT NULL,
    root_path TEXT,
    baseline_document_json TEXT NOT NULL,
    working_document_json TEXT NOT NULL,
    diagnostics_json TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_checkouts_document ON checkouts(document_id);
CREATE TABLE IF NOT EXISTS apply_commits (
    apply_commit_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL,
    root_path TEXT,
    baseline_document_revision INTEGER,
    applied_document_revision INTEGER,
    mode TEXT NOT NULL,
    verified INTEGER NOT NULL DEFAULT 0,
    summary_json TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS live_sync_state (
    scope_key TEXT PRIMARY KEY,
    dirty INTEGER NOT NULL DEFAULT 1,
    last_event TEXT,
    last_marked_revision INTEGER,
    last_synced_live_revision INTEGER,
    updated_at REAL NOT NULL
);
"""

_MIGRATION_2_SQL = """
CREATE TABLE apply_operation_audit (
    audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
    apply_commit_id TEXT NOT NULL,
    phase TEXT NOT NULL,
    operation_index INTEGER,
    operation_type TEXT,
    status TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE INDEX idx_apply_operation_audit_commit
    ON apply_operation_audit(apply_commit_id, operation_index);
"""

_MIGRATION_3_SQL = """
CREATE TABLE immutable_apply_plans (
    plan_id TEXT PRIMARY KEY,
    plan_hash TEXT NOT NULL,
    source_digest TEXT NOT NULL,
    session_id TEXT NOT NULL,
    catalog_fingerprint TEXT NOT NULL,
    catalog_content_digest TEXT,
    ownership TEXT,
    document_id TEXT NOT NULL,
    root_path TEXT NOT NULL,
    baseline_document_revision INTEGER NOT NULL CHECK(baseline_document_revision >= 0),
    baseline_live_revision INTEGER NOT NULL CHECK(baseline_live_revision >= 0),
    required_capabilities_json TEXT NOT NULL,
    execution_plan_json TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    expires_at REAL NOT NULL,
    created_at REAL NOT NULL
);
CREATE INDEX idx_immutable_apply_plans_expiry
    ON immutable_apply_plans(expires_at);
CREATE INDEX idx_immutable_apply_plans_target
    ON immutable_apply_plans(root_path, baseline_live_revision);
CREATE TABLE plan_apply_commits (
    plan_commit_id TEXT PRIMARY KEY,
    plan_id TEXT NOT NULL UNIQUE,
    idempotency_key TEXT NOT NULL UNIQUE,
    state TEXT NOT NULL CHECK(state IN ('pending', 'committed', 'aborted', 'partial_or_unknown')),
    pre_apply_snapshot_json TEXT NOT NULL,
    inverse_plan_json TEXT,
    result_json TEXT,
    error_json TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    FOREIGN KEY(plan_id) REFERENCES immutable_apply_plans(plan_id)
);
CREATE INDEX idx_plan_apply_commits_state
    ON plan_apply_commits(state, updated_at);
CREATE TABLE plan_commit_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_commit_id TEXT NOT NULL,
    from_state TEXT,
    to_state TEXT NOT NULL,
    details_json TEXT NOT NULL,
    created_at REAL NOT NULL,
    FOREIGN KEY(plan_commit_id) REFERENCES plan_apply_commits(plan_commit_id)
);
CREATE INDEX idx_plan_commit_events_commit
    ON plan_commit_events(plan_commit_id, event_id);
"""

_MIGRATIONS = (
    (1, "initial_graph_store", _MIGRATION_1_SQL),
    (2, "apply_operation_audit", _MIGRATION_2_SQL),
    (3, "immutable_plan_lifecycle", _MIGRATION_3_SQL),
)
_CURRENT_SCHEMA_VERSION = _MIGRATIONS[-1][0]
_VERSIONED_TABLE = "graph_store_migrations"
_V1_TABLES = frozenset(
    {
        "documents",
        "document_versions",
        "nodes",
        "edges",
        "parameter_bindings",
        "code_blobs",
        "checkouts",
        "apply_commits",
        "live_sync_state",
    }
)
_V2_TABLES = _V1_TABLES | {"apply_operation_audit"}
_V3_TABLES = _V2_TABLES | {
    "immutable_apply_plans",
    "plan_apply_commits",
    "plan_commit_events",
}


class LiveGraphStore:
    _GLOBAL_SCOPE_KEY = "scene:/"

    def __init__(self, logger: logging.Logger, db_path: Path | None = None):
        self._logger = logger.getChild("live.graph_store")
        self._db_path = db_path or (core_paths.runtime_dir() / "document_graph.sqlite3")
        self._lock = threading.Lock()
        self._cache_lock = threading.Lock()
        self._document_cache: dict[str, dict[str, Any]] = {}
        self._cache_hits = 0
        self._cache_misses = 0
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            str(self._db_path),
            timeout=30.0,
            factory=_ClosingConnection,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    @staticmethod
    def _migration_checksum(sql: str) -> str:
        return hashlib.sha256(sql.encode("utf-8")).hexdigest()

    @staticmethod
    def _execute_migration_sql(connection: sqlite3.Connection, sql: str) -> None:
        statement = ""
        for line in sql.splitlines(keepends=True):
            statement += line
            if sqlite3.complete_statement(statement):
                connection.execute(statement.strip())
                statement = ""
        if statement.strip():
            raise GraphStoreSchemaError("Graph-store migration contains incomplete SQL.")

    @staticmethod
    def _table_names(connection: sqlite3.Connection) -> set[str]:
        rows = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
        return {
            str(row["name"])
            for row in rows
            if str(row["name"]) != "sqlite_sequence"
        }

    @staticmethod
    def _quoted_identifier(value: str) -> str:
        return '"' + value.replace('"', '""') + '"'

    @classmethod
    def _table_signature(
        cls,
        connection: sqlite3.Connection,
        table: str,
    ) -> tuple[tuple[Any, ...], ...]:
        quoted = cls._quoted_identifier(table)
        rows = connection.execute(f"PRAGMA table_info({quoted})").fetchall()
        return tuple(
            (
                str(row["name"]),
                str(row["type"]).upper(),
                int(row["notnull"]),
                row["dflt_value"],
                int(row["pk"]),
            )
            for row in rows
        )

    @classmethod
    def _index_signature(
        cls,
        connection: sqlite3.Connection,
        table: str,
    ) -> tuple[tuple[Any, ...], ...]:
        quoted = cls._quoted_identifier(table)
        indexes = []
        for row in connection.execute(f"PRAGMA index_list({quoted})").fetchall():
            name = str(row["name"])
            index_name = cls._quoted_identifier(name)
            columns = tuple(
                str(item["name"])
                for item in connection.execute(f"PRAGMA index_info({index_name})").fetchall()
            )
            origin = str(row["origin"])
            stable_name = name if origin == "c" else None
            indexes.append(
                (
                    stable_name,
                    int(row["unique"]),
                    origin,
                    int(row["partial"]),
                    columns,
                )
            )
        return tuple(sorted(indexes, key=repr))

    @classmethod
    def _schema_signatures(
        cls,
        connection: sqlite3.Connection,
    ) -> dict[str, tuple[tuple[tuple[Any, ...], ...], tuple[tuple[Any, ...], ...]]]:
        return {
            table: (
                cls._table_signature(connection, table),
                cls._index_signature(connection, table),
            )
            for table in sorted(cls._table_names(connection))
        }

    def _expected_schema_signatures(
        self,
        version: int,
    ) -> dict[str, tuple[tuple[tuple[Any, ...], ...], tuple[tuple[Any, ...], ...]]]:
        reference = sqlite3.connect(":memory:")
        reference.row_factory = sqlite3.Row
        try:
            reference.execute(
                """
                CREATE TABLE graph_store_migrations (
                    version INTEGER PRIMARY KEY CHECK(version > 0),
                    name TEXT NOT NULL,
                    checksum TEXT NOT NULL,
                    applied_at REAL NOT NULL
                )
                """
            )
            for _, _, sql in _MIGRATIONS[:version]:
                self._execute_migration_sql(reference, sql)
            return self._schema_signatures(reference)
        finally:
            reference.close()

    def _record_migration(
        self,
        connection: sqlite3.Connection,
        version: int,
        name: str,
        sql: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO graph_store_migrations (
                version, name, checksum, applied_at
            ) VALUES (?, ?, ?, ?)
            """,
            (version, name, self._migration_checksum(sql), time.time()),
        )

    def _adopt_legacy_schema(
        self,
        connection: sqlite3.Connection,
        tables_before_ledger: set[str],
    ) -> int:
        if tables_before_ledger == _V1_TABLES:
            self._record_migration(connection, *_MIGRATIONS[0])
            return 1
        if tables_before_ledger == _V2_TABLES:
            for migration in _MIGRATIONS[:2]:
                self._record_migration(connection, *migration)
            return 2
        if tables_before_ledger == _V3_TABLES:
            for migration in _MIGRATIONS:
                self._record_migration(connection, *migration)
            return 3
        unexpected = sorted(tables_before_ledger - _V3_TABLES)
        missing = sorted(_V1_TABLES - tables_before_ledger)
        details: list[str] = []
        if missing:
            details.append(f"missing tables: {', '.join(missing)}")
        if unexpected:
            details.append(f"unexpected tables: {', '.join(unexpected)}")
        detail = "; ".join(details) or "schema does not match a supported legacy version"
        raise GraphStoreSchemaError(
            "Cannot safely adopt unversioned graph-store database: " + detail
        )

    def _validate_migration_ledger(
        self,
        rows: list[sqlite3.Row],
    ) -> int:
        if len(rows) > len(_MIGRATIONS):
            raise GraphStoreSchemaError(
                f"Graph-store schema is newer than supported version {_CURRENT_SCHEMA_VERSION}."
            )
        for index, row in enumerate(rows):
            expected_version, expected_name, expected_sql = _MIGRATIONS[index]
            version = int(row["version"])
            name = str(row["name"])
            checksum = str(row["checksum"])
            expected_checksum = self._migration_checksum(expected_sql)
            if version != expected_version:
                raise GraphStoreSchemaError(
                    "Graph-store migration ledger is not contiguous: "
                    f"expected version {expected_version}, found {version}."
                )
            if name != expected_name or checksum != expected_checksum:
                raise GraphStoreSchemaError(
                    f"Graph-store migration {version} does not match this build."
                )
        return len(rows)

    def _validate_schema_shape(
        self,
        connection: sqlite3.Connection,
        version: int,
    ) -> None:
        expected = {_VERSIONED_TABLE}
        if version >= 1:
            expected.update(_V1_TABLES)
        if version >= 2:
            expected.add("apply_operation_audit")
        if version >= 3:
            expected.update({"immutable_apply_plans", "plan_apply_commits", "plan_commit_events"})
        actual = self._table_names(connection)
        if actual != expected:
            missing = sorted(expected - actual)
            unexpected = sorted(actual - expected)
            details: list[str] = []
            if missing:
                details.append(f"missing tables: {', '.join(missing)}")
            if unexpected:
                details.append(f"unexpected tables: {', '.join(unexpected)}")
            raise GraphStoreSchemaError(
                f"Graph-store schema version {version} has an invalid shape: "
                + "; ".join(details)
            )
        expected_signatures = self._expected_schema_signatures(version)
        actual_signatures = self._schema_signatures(connection)
        for table in sorted(expected):
            if actual_signatures[table] != expected_signatures[table]:
                raise GraphStoreSchemaError(
                    f"Graph-store schema version {version} has an invalid "
                    f"column or index signature for table {table}."
                )

    def _ensure_schema(self) -> None:
        with self._connect() as connection:
            tables_before_ledger = self._table_names(connection)
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS graph_store_migrations (
                        version INTEGER PRIMARY KEY CHECK(version > 0),
                        name TEXT NOT NULL,
                        checksum TEXT NOT NULL,
                        applied_at REAL NOT NULL
                    )
                    """
                )
                rows = connection.execute(
                    """
                    SELECT version, name, checksum, applied_at
                    FROM graph_store_migrations
                    ORDER BY version
                    """
                ).fetchall()
                if rows:
                    current_version = self._validate_migration_ledger(rows)
                elif tables_before_ledger:
                    current_version = self._adopt_legacy_schema(
                        connection, tables_before_ledger
                    )
                else:
                    current_version = 0

                self._validate_schema_shape(connection, current_version)

                user_version = int(
                    connection.execute("PRAGMA user_version").fetchone()[0]
                )
                if user_version > _CURRENT_SCHEMA_VERSION:
                    raise GraphStoreSchemaError(
                        f"Graph-store schema version {user_version} is newer than "
                        f"supported version {_CURRENT_SCHEMA_VERSION}."
                    )
                if user_version not in (0, current_version):
                    raise GraphStoreSchemaError(
                        "Graph-store user_version disagrees with its migration ledger: "
                        f"{user_version} != {current_version}."
                    )

                for version, name, sql in _MIGRATIONS[current_version:]:
                    self._execute_migration_sql(connection, sql)
                    self._record_migration(connection, version, name, sql)
                    current_version = version

                self._validate_schema_shape(connection, current_version)
                connection.execute(f"PRAGMA user_version={current_version}")
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    @staticmethod
    def _stable_json(payload: Any) -> str:
        return json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))

    def _document_for_hash(self, document: dict[str, Any]) -> dict[str, Any]:
        payload = copy.deepcopy(document)
        payload["documentRevision"] = 0
        payload["baselineLiveRevision"] = 0
        payload["lastSyncedLiveRevision"] = 0
        metadata = payload.get("metadata")
        if isinstance(metadata, dict):
            metadata.pop("graphRevision", None)
            metadata.pop("store", None)
        return payload

    def _content_hash(self, document: dict[str, Any]) -> str:
        digest = hashlib.sha256()
        digest.update(self._stable_json(self._document_for_hash(document)).encode("utf-8"))
        return digest.hexdigest()

    def _cache_get(self, document_id: str) -> dict[str, Any] | None:
        with self._cache_lock:
            cached = self._document_cache.get(document_id)
            if cached is None:
                self._cache_misses += 1
                return None
            self._cache_hits += 1
            return copy.deepcopy(cached)

    def _cache_set(self, document_id: str, payload: dict[str, Any]) -> None:
        with self._cache_lock:
            self._document_cache[document_id] = copy.deepcopy(payload)

    def _cache_delete(self, document_id: str) -> None:
        with self._cache_lock:
            self._document_cache.pop(document_id, None)

    def stats(self) -> dict[str, Any]:
        with self._connect() as connection:
            schema_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            migration_count = connection.execute(
                "SELECT COUNT(*) AS count FROM graph_store_migrations"
            ).fetchone()["count"]
            documents = connection.execute("SELECT COUNT(*) AS count FROM documents").fetchone()["count"]
            versions = connection.execute("SELECT COUNT(*) AS count FROM document_versions").fetchone()["count"]
            nodes = connection.execute("SELECT COUNT(*) AS count FROM nodes").fetchone()["count"]
            scopes = connection.execute("SELECT COUNT(*) AS count FROM live_sync_state WHERE dirty = 1").fetchone()["count"]
            apply_commits = connection.execute("SELECT COUNT(*) AS count FROM apply_commits").fetchone()["count"]
            apply_audit_rows = connection.execute("SELECT COUNT(*) AS count FROM apply_operation_audit").fetchone()["count"]
            immutable_plans = connection.execute("SELECT COUNT(*) AS count FROM immutable_apply_plans").fetchone()["count"]
            pending_plan_commits = connection.execute(
                "SELECT COUNT(*) AS count FROM plan_apply_commits WHERE state = 'pending'"
            ).fetchone()["count"]
        with self._cache_lock:
            cache_size = len(self._document_cache)
            hits = self._cache_hits
            misses = self._cache_misses
        return {
            "dbPath": str(self._db_path),
            "schemaVersion": schema_version,
            "migrationCount": int(migration_count),
            "documentCount": int(documents),
            "versionCount": int(versions),
            "nodeIndexCount": int(nodes),
            "dirtyScopeCount": int(scopes),
            "applyCommitCount": int(apply_commits),
            "applyAuditRowCount": int(apply_audit_rows),
            "immutablePlanCount": int(immutable_plans),
            "pendingPlanCommitCount": int(pending_plan_commits),
            "cacheSize": cache_size,
            "cacheHits": hits,
            "cacheMisses": misses,
        }

    def _latest_row_by_document_id(self, connection: sqlite3.Connection, document_id: str) -> sqlite3.Row | None:
        return connection.execute(
            "SELECT * FROM documents WHERE document_id = ?",
            (document_id,),
        ).fetchone()

    def _latest_row_by_root_path(self, connection: sqlite3.Connection, root_path: str) -> sqlite3.Row | None:
        return connection.execute(
            "SELECT * FROM documents WHERE root_path = ?",
            (root_path,),
        ).fetchone()

    def get_document_by_id(self, document_id: str) -> dict[str, Any] | None:
        cached = self._cache_get(document_id)
        if cached is not None:
            return cached
        with self._connect() as connection:
            row = self._latest_row_by_document_id(connection, document_id)
            if row is None:
                return None
            payload = json.loads(row["payload_json"])
        self._cache_set(document_id, payload)
        return payload

    def get_document_by_root_path(self, root_path: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = self._latest_row_by_root_path(connection, root_path)
            if row is None:
                return None
            document_id = str(row["document_id"])
        return self.get_document_by_id(document_id)

    def upsert_document_from_live(
        self,
        document: dict[str, Any],
        *,
        live_revision: int,
        source: str,
    ) -> dict[str, Any]:
        payload = copy.deepcopy(document)
        document_id = str(payload.get("documentId", "")).strip()
        if not document_id:
            raise ValueError("document must include documentId")
        kind = str(payload.get("kind", "")).strip()
        root_path = payload.get("rootPath")
        content_hash = self._content_hash(payload)
        now = time.time()

        with self._lock, self._connect() as connection:
            latest = self._latest_row_by_document_id(connection, document_id)
            latest_revision = int(latest["latest_revision"]) if latest is not None else 0
            previous_live_revision = int(latest["live_revision"]) if latest is not None and latest["live_revision"] is not None else 0
            changed = latest is None or str(latest["content_hash"]) != content_hash
            document_revision = latest_revision + 1 if changed else max(latest_revision, 1)

            payload["documentRevision"] = document_revision
            payload["baselineLiveRevision"] = previous_live_revision if previous_live_revision > 0 else live_revision
            payload["lastSyncedLiveRevision"] = live_revision
            metadata = payload.setdefault("metadata", {})
            if isinstance(metadata, dict):
                metadata["store"] = {
                    "source": source,
                    "liveRevision": live_revision,
                    "contentHash": content_hash,
                }

            payload_json = self._stable_json(payload)
            if changed:
                connection.execute(
                    """
                    INSERT OR REPLACE INTO documents (
                        document_id, kind, root_path, latest_revision, live_revision,
                        content_hash, payload_json, source, created_at, updated_at
                    ) VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?,
                        COALESCE((SELECT created_at FROM documents WHERE document_id = ?), ?),
                        ?
                    )
                    """,
                    (
                        document_id,
                        kind,
                        root_path,
                        document_revision,
                        live_revision,
                        content_hash,
                        payload_json,
                        source,
                        document_id,
                        now,
                        now,
                    ),
                )
                connection.execute(
                    """
                    INSERT OR REPLACE INTO document_versions (
                        document_id, document_revision, live_revision,
                        content_hash, payload_json, source, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        document_id,
                        document_revision,
                        live_revision,
                        content_hash,
                        payload_json,
                        source,
                        now,
                    ),
                )
                self._replace_document_indexes(connection, payload)
            else:
                connection.execute(
                    """
                    UPDATE documents
                    SET kind = ?, root_path = ?, live_revision = ?, payload_json = ?,
                        source = ?, updated_at = ?
                    WHERE document_id = ?
                    """,
                    (
                        kind,
                        root_path,
                        live_revision,
                        payload_json,
                        source,
                        now,
                        document_id,
                    ),
                )
            self.mark_scope_clean(root_path or self._GLOBAL_SCOPE_KEY, live_revision, connection=connection)

        self._cache_set(document_id, payload)
        return payload

    def _replace_document_indexes(self, connection: sqlite3.Connection, document: dict[str, Any]) -> None:
        document_id = str(document["documentId"])
        document_revision = int(document.get("documentRevision") or 0)
        root_path = document.get("rootPath")
        connection.execute("DELETE FROM nodes WHERE document_id = ?", (document_id,))
        connection.execute("DELETE FROM edges WHERE document_id = ?", (document_id,))
        connection.execute("DELETE FROM parameter_bindings WHERE document_id = ?", (document_id,))
        connection.execute("DELETE FROM code_blobs WHERE document_id = ?", (document_id,))

        for node in document.get("nodes", []):
            if not isinstance(node, dict):
                continue
            metadata = node.get("metadata") if isinstance(node.get("metadata"), dict) else {}
            connection.execute(
                """
                INSERT INTO nodes (
                    document_id, document_revision, root_path, node_uid, path, name,
                    type_name, category, parent_path, is_network, flags_json,
                    material_path, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    document_id,
                    document_revision,
                    root_path,
                    node.get("uid"),
                    node.get("path"),
                    node.get("name"),
                    node.get("typeName"),
                    node.get("category"),
                    node.get("parentPath"),
                    1 if bool(node.get("isNetwork", False)) else 0,
                    self._stable_json(node.get("flags", {})),
                    metadata.get("materialPath"),
                    self._stable_json(metadata),
                ),
            )

        for edge in document.get("edges", []):
            if not isinstance(edge, dict):
                continue
            connection.execute(
                """
                INSERT INTO edges (
                    document_id, document_revision, edge_uid, kind,
                    from_node_uid, to_node_uid, from_json, to_json, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    document_id,
                    document_revision,
                    edge.get("uid"),
                    edge.get("kind"),
                    (edge.get("from") or {}).get("nodeUid"),
                    (edge.get("to") or {}).get("nodeUid"),
                    self._stable_json(edge.get("from", {})),
                    self._stable_json(edge.get("to", {})),
                    self._stable_json(edge.get("metadata", {})),
                ),
            )

        for binding in document.get("parameterBindings", []):
            if not isinstance(binding, dict):
                continue
            connection.execute(
                """
                INSERT INTO parameter_bindings (
                    document_id, document_revision, binding_uid, node_uid, parm_name,
                    value_mode, value_json, expression, expression_language,
                    channel_reference, code_blob_uid, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    document_id,
                    document_revision,
                    binding.get("uid"),
                    binding.get("nodeUid"),
                    binding.get("parmName"),
                    binding.get("valueMode"),
                    None if "value" not in binding else self._stable_json(binding.get("value")),
                    binding.get("expression"),
                    binding.get("expressionLanguage"),
                    binding.get("channelReference"),
                    binding.get("codeBlobUid"),
                    self._stable_json(binding.get("metadata", {})),
                ),
            )

        for blob in document.get("codeBlobs", []):
            if not isinstance(blob, dict):
                continue
            connection.execute(
                """
                INSERT INTO code_blobs (
                    document_id, document_revision, code_blob_uid, language,
                    target_json, body, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    document_id,
                    document_revision,
                    blob.get("uid"),
                    blob.get("language"),
                    self._stable_json(blob.get("target", {})),
                    blob.get("body", ""),
                    self._stable_json(blob.get("metadata", {})),
                ),
            )

    def query_nodes(self, arguments: dict[str, Any]) -> dict[str, Any]:
        limit = int(arguments.get("limit", 200))
        root_path = str(arguments.get("root_path", "")).strip() or None
        path_prefix = str(arguments.get("path_prefix", "")).strip() or None
        node_type_name = str(arguments.get("node_type_name", "")).strip() or None
        category = str(arguments.get("category", "")).strip() or None
        name_contains = str(arguments.get("name_contains", "")).strip().lower() or None
        material_path = str(arguments.get("material_path", "")).strip() or None
        flag_name = str(arguments.get("flag_name", "")).strip() or None
        flag_value = arguments.get("flag_value")

        with self._connect() as connection:
            if root_path:
                rows = connection.execute(
                    """
                    SELECT n.*, d.root_path AS document_root_path, d.latest_revision, d.live_revision AS document_live_revision
                    FROM nodes AS n
                    JOIN documents AS d ON d.document_id = n.document_id
                    WHERE d.root_path = ?
                    """,
                    (root_path,),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT n.*, d.root_path AS document_root_path, d.latest_revision, d.live_revision AS document_live_revision
                    FROM nodes AS n
                    JOIN documents AS d ON d.document_id = n.document_id
                    """
                ).fetchall()

        best_by_path: dict[str, dict[str, Any]] = {}
        for row in rows:
            path = str(row["path"])
            if root_path and not (path == root_path or path.startswith(f"{root_path}/")):
                continue
            if path_prefix and not path.startswith(path_prefix):
                continue
            if node_type_name and str(row["type_name"] or "") != node_type_name:
                continue
            if category and str(row["category"] or "") != category:
                continue
            if name_contains and name_contains not in str(row["name"] or "").lower():
                continue
            if material_path and str(row["material_path"] or "") != material_path:
                continue
            flags = json.loads(str(row["flags_json"] or "{}"))
            if flag_name:
                if flag_name not in flags:
                    continue
                if flag_value is not None and bool(flags.get(flag_name)) != bool(flag_value):
                    continue
            candidate = {
                "uid": row["node_uid"],
                "path": path,
                "name": row["name"],
                "typeName": row["type_name"],
                "category": row["category"],
                "parentPath": row["parent_path"],
                "isNetwork": bool(row["is_network"]),
                "flags": flags,
                "metadata": json.loads(str(row["metadata_json"] or "{}")),
                "rootPath": row["document_root_path"],
                "liveRevision": int(row["document_live_revision"] or 0),
            }
            current = best_by_path.get(path)
            if current is None:
                best_by_path[path] = candidate
                continue
            if int(candidate["liveRevision"]) > int(current.get("liveRevision", 0)):
                best_by_path[path] = candidate
                continue
            if int(candidate["liveRevision"]) == int(current.get("liveRevision", 0)) and len(str(candidate["rootPath"] or "")) > len(str(current["rootPath"] or "")):
                best_by_path[path] = candidate

        matches = sorted(best_by_path.values(), key=lambda item: item["path"])[:limit]
        return {
            "count": len(matches),
            "matches": matches,
        }

    def save_checkout_record(self, record: dict[str, Any]) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO checkouts (
                    checkout_id, document_id, document_kind, root_path,
                    baseline_document_json, working_document_json, diagnostics_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record["checkout_id"],
                    record["document_id"],
                    record["document_kind"],
                    record.get("root_path"),
                    self._stable_json(record["baseline_document"]),
                    self._stable_json(record["working_document"]),
                    self._stable_json(record.get("diagnostics", [])),
                    float(record["created_at"]),
                    float(record["updated_at"]),
                ),
            )

    def load_checkout_record(self, checkout_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM checkouts WHERE checkout_id = ?",
                (checkout_id,),
            ).fetchone()
            if row is None:
                return None
            return {
                "checkout_id": row["checkout_id"],
                "document_id": row["document_id"],
                "document_kind": row["document_kind"],
                "root_path": row["root_path"],
                "baseline_document": json.loads(row["baseline_document_json"]),
                "working_document": json.loads(row["working_document_json"]),
                "diagnostics": json.loads(row["diagnostics_json"]),
                "created_at": float(row["created_at"]),
                "updated_at": float(row["updated_at"]),
            }

    def delete_checkout_record(self, checkout_id: str) -> None:
        with self._lock, self._connect() as connection:
            connection.execute("DELETE FROM checkouts WHERE checkout_id = ?", (checkout_id,))

    @staticmethod
    def _plan_digest(payload: dict[str, Any]) -> str:
        unsigned = copy.deepcopy(payload)
        unsigned.pop("planHash", None)
        encoded = json.dumps(
            unsigned,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        return f"sha256:{hashlib.sha256(encoded.encode('utf-8')).hexdigest()}"

    @staticmethod
    def _strict_plan_json(payload: Any, label: str) -> str:
        try:
            return json.dumps(
                payload,
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
        except (TypeError, ValueError) as exc:
            raise GraphStorePlanError(f"{label} must be finite canonical JSON.") from exc

    @staticmethod
    def _required_plan_string(payload: dict[str, Any], key: str) -> str:
        value = payload.get(key)
        if not isinstance(value, str) or not value.strip():
            raise GraphStorePlanError(f"Immutable plan requires non-empty {key}.")
        if value != value.strip():
            raise GraphStorePlanError(f"Immutable plan {key} must not contain surrounding whitespace.")
        return value

    @classmethod
    def _decode_plan_row(cls, row: sqlite3.Row) -> dict[str, Any]:
        try:
            required_capabilities = json.loads(row["required_capabilities_json"])
            execution_plan = json.loads(row["execution_plan_json"])
            payload = json.loads(row["payload_json"])
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise GraphStorePlanError("Stored immutable plan contains invalid JSON.") from exc
        plan_hash = str(row["plan_hash"])
        try:
            computed_hash = cls._plan_digest(payload) if isinstance(payload, dict) else None
        except (TypeError, ValueError) as exc:
            raise GraphStorePlanError("Stored immutable plan is not canonical JSON.") from exc
        if not isinstance(payload, dict) or payload.get("planHash") != plan_hash or computed_hash != plan_hash:
            raise GraphStorePlanError("Stored immutable plan failed its content-hash check.")
        baseline = payload.get("baseline") if isinstance(payload.get("baseline"), dict) else {}
        payload_execution_plan = payload.get("executionPlan") if isinstance(payload.get("executionPlan"), dict) else {}
        mirrors = (
            (payload.get("planId"), str(row["plan_id"]), "plan ID"),
            (payload.get("sessionId"), str(row["session_id"]), "session ID"),
            (payload.get("rootPath"), str(row["root_path"]), "root path"),
            (payload.get("expiresAt"), float(row["expires_at"]), "expiry"),
            (payload.get("createdAt"), float(row["created_at"]), "creation time"),
            (payload.get("sourceDigest"), str(row["source_digest"]), "source digest"),
            (payload.get("catalogFingerprint"), str(row["catalog_fingerprint"]), "catalog fingerprint"),
            (payload.get("catalogContentDigest"), row["catalog_content_digest"], "catalog content digest"),
            (payload.get("ownership"), row["ownership"], "ownership"),
            (baseline.get("documentId"), str(row["document_id"]), "document ID"),
            (baseline.get("documentRevision"), int(row["baseline_document_revision"]), "document revision"),
            (baseline.get("liveRevision"), int(row["baseline_live_revision"]), "live revision"),
            (payload.get("requiredCapabilities"), required_capabilities, "capabilities"),
            (payload_execution_plan, execution_plan, "execution plan"),
        )
        mismatch = next((label for actual, stored, label in mirrors if actual != stored), None)
        if mismatch is not None:
            raise GraphStorePlanError(f"Stored immutable plan has inconsistent {mismatch} metadata.")
        return {
            "plan_id": str(row["plan_id"]),
            "plan_hash": plan_hash,
            "source_digest": str(row["source_digest"]),
            "session_id": str(row["session_id"]),
            "catalog_fingerprint": str(row["catalog_fingerprint"]),
            "catalog_content_digest": row["catalog_content_digest"],
            "ownership": row["ownership"],
            "document_id": str(row["document_id"]),
            "root_path": str(row["root_path"]),
            "baseline_document_revision": int(row["baseline_document_revision"]),
            "baseline_live_revision": int(row["baseline_live_revision"]),
            "required_capabilities": required_capabilities,
            "execution_plan": execution_plan,
            "payload": payload,
            "expires_at": float(row["expires_at"]),
            "created_at": float(row["created_at"]),
        }

    @staticmethod
    def _decode_plan_commit_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "plan_commit_id": str(row["plan_commit_id"]),
            "plan_id": str(row["plan_id"]),
            "idempotency_key": str(row["idempotency_key"]),
            "state": str(row["state"]),
            "pre_apply_snapshot": json.loads(row["pre_apply_snapshot_json"]),
            "inverse_plan": json.loads(row["inverse_plan_json"]) if row["inverse_plan_json"] is not None else None,
            "result": json.loads(row["result_json"]) if row["result_json"] is not None else None,
            "error": json.loads(row["error_json"]) if row["error_json"] is not None else None,
            "created_at": float(row["created_at"]),
            "updated_at": float(row["updated_at"]),
        }

    def store_immutable_plan(
        self,
        *,
        payload: dict[str, Any],
        plan_id: str | None = None,
        session_id: str | None = None,
        root_path: str | None = None,
        expires_at: float | None = None,
        created_at: float | None = None,
    ) -> dict[str, Any]:
        """Persist one content-verified plan; an existing ID is never replaced."""
        if not isinstance(payload, dict):
            raise GraphStorePlanError("Immutable plan payload must be an object.")
        plan_payload = copy.deepcopy(payload)
        declared_plan_id = self._required_plan_string(plan_payload, "planId")
        declared_session_id = self._required_plan_string(plan_payload, "sessionId")
        declared_root_path = self._required_plan_string(plan_payload, "rootPath")
        if not declared_root_path.startswith("/"):
            raise GraphStorePlanError("Immutable plan rootPath must be absolute.")
        if plan_id is not None and str(plan_id).strip() != declared_plan_id:
            raise GraphStorePlanError("plan_id does not match immutable plan planId.")
        if session_id is not None and str(session_id).strip() != declared_session_id:
            raise GraphStorePlanError("session_id does not match immutable plan sessionId.")
        if root_path is not None and str(root_path).strip() != declared_root_path:
            raise GraphStorePlanError("root_path does not match immutable plan rootPath.")
        plan_id = declared_plan_id
        session_id = declared_session_id
        root_path = declared_root_path
        plan_hash = self._required_plan_string(plan_payload, "planHash")
        try:
            computed_hash = self._plan_digest(plan_payload)
        except (TypeError, ValueError) as exc:
            raise GraphStorePlanError("Immutable plan payload is not canonical JSON.") from exc
        if plan_hash != computed_hash:
            raise GraphStorePlanError("Immutable plan hash does not match its payload.")
        source_digest = self._required_plan_string(plan_payload, "sourceDigest")
        catalog_fingerprint = self._required_plan_string(plan_payload, "catalogFingerprint")
        baseline = plan_payload.get("baseline")
        if not isinstance(baseline, dict):
            raise GraphStorePlanError("Immutable plan requires a baseline object.")
        document_id = self._required_plan_string(baseline, "documentId")
        catalog_content_digest = plan_payload.get("catalogContentDigest")
        if catalog_content_digest is not None and (not isinstance(catalog_content_digest, str) or not catalog_content_digest.strip()):
            raise GraphStorePlanError("catalogContentDigest must be null or a non-empty string.")
        if isinstance(catalog_content_digest, str) and catalog_content_digest != catalog_content_digest.strip():
            raise GraphStorePlanError("catalogContentDigest must not contain surrounding whitespace.")
        ownership = plan_payload.get("ownership")
        if ownership is not None and (not isinstance(ownership, str) or not ownership.strip()):
            raise GraphStorePlanError("ownership must be null or a non-empty string.")
        if isinstance(ownership, str) and ownership != ownership.strip():
            raise GraphStorePlanError("ownership must not contain surrounding whitespace.")
        baseline_document_revision = baseline.get("documentRevision")
        baseline_live_revision = baseline.get("liveRevision")
        if type(baseline_document_revision) is not int or baseline_document_revision < 0:
            raise GraphStorePlanError("baselineDocumentRevision must be a non-negative integer.")
        if type(baseline_live_revision) is not int or baseline_live_revision < 0:
            raise GraphStorePlanError("baselineLiveRevision must be a non-negative integer.")
        required_capabilities = plan_payload.get("requiredCapabilities")
        execution_plan = plan_payload.get("executionPlan")
        if not isinstance(execution_plan, dict):
            raise GraphStorePlanError("Immutable plan requires an executionPlan object.")
        if not isinstance(required_capabilities, list) or any(
            not isinstance(item, str) or not item or item != item.strip()
            for item in required_capabilities
        ):
            raise GraphStorePlanError("requiredCapabilities must be an array of non-empty strings.")
        if len(set(required_capabilities)) != len(required_capabilities):
            raise GraphStorePlanError("requiredCapabilities must not contain duplicates.")
        declared_created = plan_payload.get("createdAt")
        declared_expiry = plan_payload.get("expiresAt")
        if not isinstance(declared_created, (int, float)) or isinstance(declared_created, bool):
            raise GraphStorePlanError("Immutable plan createdAt must be a number.")
        if not isinstance(declared_expiry, (int, float)) or isinstance(declared_expiry, bool):
            raise GraphStorePlanError("Immutable plan expiresAt must be a number.")
        created = float(declared_created)
        expiry = float(declared_expiry)
        if created_at is not None and float(created_at) != created:
            raise GraphStorePlanError("created_at does not match immutable plan createdAt.")
        if expires_at is not None and float(expires_at) != expiry:
            raise GraphStorePlanError("expires_at does not match immutable plan expiresAt.")
        if not math.isfinite(created) or not math.isfinite(expiry) or expiry <= created:
            raise GraphStorePlanError("expires_at must be finite and later than created_at.")

        with self._lock, self._connect() as connection:
            try:
                connection.execute(
                    """
                    INSERT INTO immutable_apply_plans (
                        plan_id, plan_hash, source_digest, session_id,
                        catalog_fingerprint, catalog_content_digest, ownership,
                        document_id, root_path, baseline_document_revision,
                        baseline_live_revision, required_capabilities_json,
                        execution_plan_json, payload_json, expires_at, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        plan_id, plan_hash, source_digest, session_id,
                        catalog_fingerprint, catalog_content_digest, ownership,
                        document_id, root_path, baseline_document_revision,
                        baseline_live_revision, self._strict_plan_json(required_capabilities, "requiredCapabilities"),
                        self._strict_plan_json(execution_plan, "executionPlan"), self._strict_plan_json(plan_payload, "plan payload"),
                        expiry, created,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise GraphStorePlanError(f"Immutable plan ID already exists: {plan_id}") from exc
        stored = self.load_immutable_plan(plan_id)
        assert stored is not None
        return stored

    def load_immutable_plan(self, plan_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM immutable_apply_plans WHERE plan_id = ?",
                (str(plan_id).strip(),),
            ).fetchone()
        return None if row is None else self._decode_plan_row(row)

    def load_plan_commit(
        self,
        *,
        plan_commit_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any] | None:
        normalized_commit_id = str(plan_commit_id or "").strip()
        normalized_idempotency_key = str(idempotency_key or "").strip()
        if bool(normalized_commit_id) == bool(normalized_idempotency_key):
            raise GraphStorePlanError("Provide exactly one of plan_commit_id or idempotency_key.")
        field = "plan_commit_id" if normalized_commit_id else "idempotency_key"
        value = normalized_commit_id or normalized_idempotency_key
        with self._connect() as connection:
            row = connection.execute(
                f"SELECT * FROM plan_apply_commits WHERE {field} = ?",
                (value,),
            ).fetchone()
        return None if row is None else self._decode_plan_commit_row(row)

    def begin_plan_commit(
        self,
        *,
        plan_commit_id: str,
        plan_id: str,
        plan_hash: str,
        session_id: str,
        idempotency_key: str,
        pre_apply_snapshot: dict[str, Any],
        inverse_plan: dict[str, Any] | None,
        now: float | None = None,
    ) -> dict[str, Any]:
        """Atomically claim a live, session-bound plan for one idempotent apply."""
        plan_commit_id = str(plan_commit_id).strip()
        plan_id = str(plan_id).strip()
        plan_hash = str(plan_hash).strip()
        session_id = str(session_id).strip()
        idempotency_key = str(idempotency_key).strip()
        identifiers = [plan_commit_id, plan_id, plan_hash, session_id, idempotency_key]
        if any(not isinstance(item, str) or not item.strip() for item in identifiers):
            raise GraphStorePlanError("Plan commit identifiers must be non-empty strings.")
        if not isinstance(pre_apply_snapshot, dict) or (inverse_plan is not None and not isinstance(inverse_plan, dict)):
            raise GraphStorePlanError("pre_apply_snapshot and inverse_plan must be objects.")
        timestamp = time.time() if now is None else float(now)
        if not math.isfinite(timestamp):
            raise GraphStorePlanError("Plan commit timestamp must be finite.")
        snapshot_json = self._strict_plan_json(pre_apply_snapshot, "pre_apply_snapshot")
        inverse_json = self._strict_plan_json(inverse_plan, "inverse_plan") if inverse_plan is not None else None
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            plan = connection.execute(
                "SELECT * FROM immutable_apply_plans WHERE plan_id = ?",
                (plan_id,),
            ).fetchone()
            if plan is None:
                raise GraphStorePlanError(f"Unknown immutable plan: {plan_id}")
            if str(plan["plan_hash"]) != plan_hash:
                raise GraphStorePlanError("Plan hash does not match the stored immutable plan.")
            if str(plan["session_id"]) != session_id:
                raise GraphStorePlanError("Plan session does not match the current session.")
            existing = connection.execute(
                "SELECT * FROM plan_apply_commits WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
            if existing is not None:
                if str(existing["plan_id"]) != plan_id:
                    raise GraphStorePlanError("Idempotency key is already bound to another plan.")
                return self._decode_plan_commit_row(existing)
            if timestamp < float(plan["created_at"]):
                raise GraphStorePlanError("Plan commit timestamp predates the immutable plan.")
            if float(plan["expires_at"]) <= timestamp:
                raise GraphStorePlanError("Immutable plan has expired.")
            previous = connection.execute(
                "SELECT plan_commit_id FROM plan_apply_commits WHERE plan_id = ?",
                (plan_id,),
            ).fetchone()
            if previous is not None:
                raise GraphStorePlanError("Immutable plan has already been claimed for apply.")
            try:
                connection.execute(
                    """
                    INSERT INTO plan_apply_commits (
                        plan_commit_id, plan_id, idempotency_key, state,
                        pre_apply_snapshot_json, inverse_plan_json,
                        result_json, error_json, created_at, updated_at
                    ) VALUES (?, ?, ?, 'pending', ?, ?, NULL, NULL, ?, ?)
                    """,
                    (
                        plan_commit_id, plan_id, idempotency_key,
                        snapshot_json,
                        inverse_json,
                        timestamp, timestamp,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO plan_commit_events (
                        plan_commit_id, from_state, to_state, details_json, created_at
                    ) VALUES (?, NULL, 'pending', ?, ?)
                    """,
                    (plan_commit_id, self._stable_json({"idempotencyKey": idempotency_key}), timestamp),
                )
            except sqlite3.IntegrityError as exc:
                raise GraphStorePlanError("Plan commit identity conflicts with an existing record.") from exc
            row = connection.execute(
                "SELECT * FROM plan_apply_commits WHERE plan_commit_id = ?",
                (plan_commit_id,),
            ).fetchone()
            assert row is not None
            return self._decode_plan_commit_row(row)

    def finish_plan_commit(
        self,
        *,
        plan_commit_id: str,
        state: str,
        result: dict[str, Any] | None,
        error: dict[str, Any] | None,
        now: float | None = None,
    ) -> dict[str, Any]:
        """Move a pending commit exactly once to a durable terminal state."""
        plan_commit_id = str(plan_commit_id).strip()
        if not plan_commit_id:
            raise GraphStorePlanError("plan_commit_id is required.")
        if state not in {"committed", "aborted", "partial_or_unknown"}:
            raise GraphStorePlanError("Plan commit terminal state is invalid.")
        if result is not None and not isinstance(result, dict):
            raise GraphStorePlanError("Plan commit result must be null or an object.")
        if error is not None and not isinstance(error, dict):
            raise GraphStorePlanError("Plan commit error must be null or an object.")
        timestamp = time.time() if now is None else float(now)
        if not math.isfinite(timestamp):
            raise GraphStorePlanError("Plan commit timestamp must be finite.")
        result_json = self._strict_plan_json(result, "result") if result is not None else None
        error_json = self._strict_plan_json(error, "error") if error is not None else None
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM plan_apply_commits WHERE plan_commit_id = ?",
                (plan_commit_id,),
            ).fetchone()
            if row is None:
                raise GraphStorePlanError(f"Unknown plan commit: {plan_commit_id}")
            current_state = str(row["state"])
            if current_state != "pending":
                if current_state == state and row["result_json"] == result_json and row["error_json"] == error_json:
                    return self._decode_plan_commit_row(row)
                raise GraphStorePlanError(f"Plan commit is already terminal: {current_state}")
            if timestamp < float(row["updated_at"]):
                raise GraphStorePlanError("Plan commit timestamp predates its current lifecycle state.")
            connection.execute(
                """
                UPDATE plan_apply_commits
                SET state = ?, result_json = ?, error_json = ?, updated_at = ?
                WHERE plan_commit_id = ? AND state = 'pending'
                """,
                (state, result_json, error_json, timestamp, plan_commit_id),
            )
            connection.execute(
                """
                INSERT INTO plan_commit_events (
                    plan_commit_id, from_state, to_state, details_json, created_at
                ) VALUES (?, 'pending', ?, ?, ?)
                """,
                (
                    plan_commit_id, state,
                    self._stable_json({"hasResult": result is not None, "hasError": error is not None}),
                    timestamp,
                ),
            )
            updated = connection.execute(
                "SELECT * FROM plan_apply_commits WHERE plan_commit_id = ?",
                (plan_commit_id,),
            ).fetchone()
            assert updated is not None
            return self._decode_plan_commit_row(updated)

    def recoverable_plan_commits(self) -> list[dict[str, Any]]:
        """Return commits requiring crash recovery or explicit quarantine handling."""
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM plan_apply_commits
                WHERE state IN ('pending', 'partial_or_unknown')
                ORDER BY created_at, plan_commit_id
                """
            ).fetchall()
        return [self._decode_plan_commit_row(row) for row in rows]

    def resolve_plan_commit_recovery(
        self,
        *,
        plan_commit_id: str,
        state: str,
        result: dict[str, Any],
        now: float | None = None,
    ) -> dict[str, Any]:
        """Resolve a previously quarantined commit after live-state classification."""
        plan_commit_id = str(plan_commit_id).strip()
        if state not in {"committed", "aborted"}:
            raise GraphStorePlanError("Recovered plan commit state must be committed or aborted.")
        if not isinstance(result, dict):
            raise GraphStorePlanError("Recovered plan commit result must be an object.")
        timestamp = time.time() if now is None else float(now)
        if not math.isfinite(timestamp):
            raise GraphStorePlanError("Recovery timestamp must be finite.")
        result_json = self._strict_plan_json(result, "recovery result")
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM plan_apply_commits WHERE plan_commit_id = ?", (plan_commit_id,)
            ).fetchone()
            if row is None:
                raise GraphStorePlanError(f"Unknown plan commit: {plan_commit_id}")
            current_state = str(row["state"])
            if current_state != "partial_or_unknown":
                raise GraphStorePlanError(
                    f"Only partial_or_unknown commits require explicit recovery; found {current_state}."
                )
            connection.execute(
                "UPDATE plan_apply_commits SET state = ?, result_json = ?, error_json = NULL, updated_at = ? WHERE plan_commit_id = ? AND state = 'partial_or_unknown'",
                (state, result_json, timestamp, plan_commit_id),
            )
            connection.execute(
                "INSERT INTO plan_commit_events (plan_commit_id, from_state, to_state, details_json, created_at) VALUES (?, 'partial_or_unknown', ?, ?, ?)",
                (plan_commit_id, state, self._stable_json({"recovered": True}), timestamp),
            )
            updated = connection.execute(
                "SELECT * FROM plan_apply_commits WHERE plan_commit_id = ?", (plan_commit_id,)
            ).fetchone()
            assert updated is not None
            return self._decode_plan_commit_row(updated)

    def record_apply_commit(
        self,
        *,
        apply_commit_id: str,
        document_id: str,
        root_path: str | None,
        baseline_document_revision: int | None,
        applied_document_revision: int | None,
        mode: str,
        verified: bool,
        summary: dict[str, Any],
    ) -> None:
        self.record_apply_result(
            apply_commit_id=apply_commit_id,
            document_id=document_id,
            root_path=root_path,
            baseline_document_revision=baseline_document_revision,
            applied_document_revision=applied_document_revision,
            mode=mode,
            verified=verified,
            summary=summary,
            operations=[],
            diagnostics=[],
            error=None,
        )

    def record_apply_result(
        self,
        *,
        apply_commit_id: str,
        document_id: str,
        root_path: str | None,
        baseline_document_revision: int | None,
        applied_document_revision: int | None,
        mode: str,
        verified: bool,
        summary: dict[str, Any],
        operations: list[dict[str, Any]],
        diagnostics: list[dict[str, Any]],
        error: dict[str, Any] | None,
    ) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO apply_commits (
                    apply_commit_id, document_id, root_path,
                    baseline_document_revision, applied_document_revision,
                    mode, verified, summary_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    apply_commit_id,
                    document_id,
                    root_path,
                    baseline_document_revision,
                    applied_document_revision,
                    mode,
                    1 if verified else 0,
                    self._stable_json(summary),
                    time.time(),
                ),
            )
            connection.execute("DELETE FROM apply_operation_audit WHERE apply_commit_id = ?", (apply_commit_id,))
            created_at = time.time()
            for index, operation in enumerate(operations):
                connection.execute(
                    """
                    INSERT INTO apply_operation_audit (
                        apply_commit_id, phase, operation_index, operation_type,
                        status, payload_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        apply_commit_id,
                        "apply",
                        index,
                        str(operation.get("type", "")),
                        "executed",
                        self._stable_json(operation),
                        created_at,
                    ),
                )
            for index, diagnostic in enumerate(diagnostics):
                connection.execute(
                    """
                    INSERT INTO apply_operation_audit (
                        apply_commit_id, phase, operation_index, operation_type,
                        status, payload_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        apply_commit_id,
                        "diagnostic",
                        index,
                        str(diagnostic.get("code", "")),
                        str(diagnostic.get("severity", "info")),
                        self._stable_json(diagnostic),
                        created_at,
                    ),
                )
            if error is not None:
                connection.execute(
                    """
                    INSERT INTO apply_operation_audit (
                        apply_commit_id, phase, operation_index, operation_type,
                        status, payload_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        apply_commit_id,
                        "error",
                        None,
                        str(error.get("type", "error")),
                        "failed",
                        self._stable_json(error),
                        created_at,
                    ),
                )

    def mark_scope_dirty(
        self,
        scope_path: str | None,
        *,
        event_name: str,
        revision: int,
        connection: sqlite3.Connection | None = None,
    ) -> None:
        scope_key = str(scope_path).strip() if scope_path else self._GLOBAL_SCOPE_KEY
        owns_connection = connection is None
        connection = connection or self._connect()
        try:
            connection.execute(
                """
                INSERT OR REPLACE INTO live_sync_state (
                    scope_key, dirty, last_event, last_marked_revision,
                    last_synced_live_revision, updated_at
                ) VALUES (
                    ?,
                    1,
                    ?,
                    ?,
                    COALESCE((SELECT last_synced_live_revision FROM live_sync_state WHERE scope_key = ?), 0),
                    ?
                )
                """,
                (
                    scope_key,
                    event_name,
                    revision,
                    scope_key,
                    time.time(),
                ),
            )
            if owns_connection:
                connection.commit()
        finally:
            if owns_connection:
                connection.close()

    def mark_scope_clean(
        self,
        scope_path: str,
        live_revision: int,
        *,
        connection: sqlite3.Connection | None = None,
    ) -> None:
        scope_key = str(scope_path).strip() if scope_path else self._GLOBAL_SCOPE_KEY
        owns_connection = connection is None
        connection = connection or self._connect()
        try:
            connection.execute(
                """
                INSERT OR REPLACE INTO live_sync_state (
                    scope_key, dirty, last_event, last_marked_revision,
                    last_synced_live_revision, updated_at
                ) VALUES (
                    ?,
                    0,
                    COALESCE((SELECT last_event FROM live_sync_state WHERE scope_key = ?), 'sync'),
                    COALESCE((SELECT last_marked_revision FROM live_sync_state WHERE scope_key = ?), ?),
                    ?,
                    ?
                )
                """,
                (
                    scope_key,
                    scope_key,
                    scope_key,
                    live_revision,
                    live_revision,
                    time.time(),
                ),
            )
            if owns_connection:
                connection.commit()
        finally:
            if owns_connection:
                connection.close()

    def sync_needed(self, scope_path: str, *, live_revision: int) -> bool:
        document = self.get_document_by_id(self._GLOBAL_SCOPE_KEY) if scope_path == self._GLOBAL_SCOPE_KEY else self.get_document_by_root_path(scope_path)
        if document is None:
            return True
        last_synced_live_revision = int(document.get("lastSyncedLiveRevision") or 0)
        if last_synced_live_revision >= live_revision:
            return False
        with self._connect() as connection:
            scene_row = connection.execute(
                "SELECT * FROM live_sync_state WHERE scope_key = ?",
                (self._GLOBAL_SCOPE_KEY,),
            ).fetchone()
            scope_row = connection.execute(
                "SELECT * FROM live_sync_state WHERE scope_key = ?",
                (scope_path,),
            ).fetchone()
        for row in (scene_row, scope_row):
            if row is None:
                continue
            if int(row["dirty"]) and int(row["last_marked_revision"] or 0) > last_synced_live_revision:
                return True
        return False

    def last_scope_event(self, scope_path: str | None) -> str | None:
        scope_key = str(scope_path).strip() if scope_path else self._GLOBAL_SCOPE_KEY
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT scope_key, last_event, last_marked_revision
                FROM live_sync_state
                WHERE scope_key IN (?, ?)
                ORDER BY last_marked_revision DESC
                """,
                (self._GLOBAL_SCOPE_KEY, scope_key),
            ).fetchall()
        for row in rows:
            event_name = str(row["last_event"] or "").strip()
            if event_name:
                return event_name
        return None

    def on_monitor_event(self, event: dict[str, Any]) -> None:
        self.mark_scope_dirty(
            event.get("scopePath"),
            event_name=str(event.get("event", "event")),
            revision=int(event.get("revision", 0)),
        )

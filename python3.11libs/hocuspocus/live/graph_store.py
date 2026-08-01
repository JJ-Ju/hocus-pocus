"""Embedded SQLite-backed document graph store."""
from __future__ import annotations

import copy
import hashlib
import json
import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from hocuspocus.core import paths as core_paths
from .graph_store_documents import GraphStoreDocumentMixin
from .graph_store_live_revisions import live_revision_fields
from .graph_store_plans import (
    GraphStorePlanError as _GraphStorePlanError,
    GraphStorePlanMixin,
)
from .graph_store_sqlite import (
    GraphStoreSchemaError,
    open_storage_connection,
)

GraphStorePlanError = _GraphStorePlanError


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


class LiveGraphStore(GraphStoreDocumentMixin, GraphStorePlanMixin):
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
        self.prune_durable_plan_history()

    def _connect(self) -> sqlite3.Connection:
        connection = open_storage_connection(
            str(self._db_path),
            timeout=30.0,
            pragmas=("PRAGMA journal_mode=WAL", "PRAGMA foreign_keys=ON"),
        )
        connection.row_factory = sqlite3.Row
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
        with open_storage_connection(":memory:") as reference:
            reference.row_factory = sqlite3.Row
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

    def upsert_document_from_live(
        self,
        document: dict[str, Any],
        *,
        live_revision: int,
        source: str,
        force_new_revision: bool = False,
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
            latest_revision = (
                int(latest["latest_revision"])
                if latest is not None
                else self._historical_document_revision(
                    connection, document_id
                )
            )
            previous_live_revision = int(latest["live_revision"]) if latest is not None and latest["live_revision"] is not None else 0
            changed = (
                force_new_revision
                or latest is None
                or str(latest["content_hash"]) != content_hash
            )
            document_revision = latest_revision + 1 if changed else max(latest_revision, 1)

            payload["documentRevision"] = document_revision
            latest_json = str(latest["payload_json"]) if latest is not None else None
            revision_fields = live_revision_fields(latest_json, changed=changed, previous=previous_live_revision, current=live_revision)
            payload.update(revision_fields)
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

    @staticmethod
    def _query_node_candidate(row: Any, filters: dict[str, Any]) -> dict[str, Any] | None:
        path = str(row["path"])
        flags = json.loads(str(row["flags_json"] or "{}"))
        rejected = (
            (filters["root"] and not (path == filters["root"] or path.startswith(f"{filters['root']}/")))
            or (filters["prefix"] and not path.startswith(filters["prefix"]))
            or (filters["type"] and str(row["type_name"] or "") != filters["type"])
            or (filters["category"] and str(row["category"] or "") != filters["category"])
            or (filters["name"] and filters["name"] not in str(row["name"] or "").lower())
            or (filters["material"] and str(row["material_path"] or "") != filters["material"])
            or (filters["flag"] and filters["flag"] not in flags)
            or (
                filters["flag"]
                and filters["flag_value"] is not None
                and bool(flags.get(filters["flag"])) != bool(filters["flag_value"])
            )
        )
        if rejected:
            return None
        return {
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

    @staticmethod
    def _prefer_node_candidate(candidate: dict[str, Any], current: dict[str, Any] | None) -> bool:
        if current is None:
            return True
        candidate_revision = int(candidate["liveRevision"])
        current_revision = int(current.get("liveRevision", 0))
        return candidate_revision > current_revision or (
            candidate_revision == current_revision
            and len(str(candidate["rootPath"] or "")) > len(str(current["rootPath"] or ""))
        )

    def query_nodes(self, arguments: dict[str, Any]) -> dict[str, Any]:
        root_path = str(arguments.get("root_path", "")).strip() or None
        filters = {
            "root": root_path,
            "prefix": str(arguments.get("path_prefix", "")).strip() or None,
            "type": str(arguments.get("node_type_name", "")).strip() or None,
            "category": str(arguments.get("category", "")).strip() or None,
            "name": str(arguments.get("name_contains", "")).strip().lower() or None,
            "material": str(arguments.get("material_path", "")).strip() or None,
            "flag": str(arguments.get("flag_name", "")).strip() or None,
            "flag_value": arguments.get("flag_value"),
        }
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
            candidate = self._query_node_candidate(row, filters)
            if candidate is not None and self._prefer_node_candidate(
                candidate, best_by_path.get(candidate["path"])
            ):
                best_by_path[candidate["path"]] = candidate

        matches = sorted(best_by_path.values(), key=lambda item: item["path"])[
            : int(arguments.get("limit", 200))
        ]
        return {"count": len(matches), "matches": matches}

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

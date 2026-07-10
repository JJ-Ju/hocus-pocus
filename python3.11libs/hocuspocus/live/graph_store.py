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
        connection = sqlite3.connect(str(self._db_path), timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _ensure_schema(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
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

                CREATE INDEX IF NOT EXISTS idx_documents_root_path
                    ON documents(root_path);

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

                CREATE INDEX IF NOT EXISTS idx_nodes_path
                    ON nodes(path);
                CREATE INDEX IF NOT EXISTS idx_nodes_type
                    ON nodes(type_name);
                CREATE INDEX IF NOT EXISTS idx_nodes_category
                    ON nodes(category);
                CREATE INDEX IF NOT EXISTS idx_nodes_root_path
                    ON nodes(root_path);

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

                CREATE INDEX IF NOT EXISTS idx_checkouts_document
                    ON checkouts(document_id);

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

                CREATE TABLE IF NOT EXISTS apply_operation_audit (
                    audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    apply_commit_id TEXT NOT NULL,
                    phase TEXT NOT NULL,
                    operation_index INTEGER,
                    operation_type TEXT,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at REAL NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_apply_operation_audit_commit
                    ON apply_operation_audit(apply_commit_id, operation_index);

                CREATE TABLE IF NOT EXISTS live_sync_state (
                    scope_key TEXT PRIMARY KEY,
                    dirty INTEGER NOT NULL DEFAULT 1,
                    last_event TEXT,
                    last_marked_revision INTEGER,
                    last_synced_live_revision INTEGER,
                    updated_at REAL NOT NULL
                );
                """
            )

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
            documents = connection.execute("SELECT COUNT(*) AS count FROM documents").fetchone()["count"]
            versions = connection.execute("SELECT COUNT(*) AS count FROM document_versions").fetchone()["count"]
            nodes = connection.execute("SELECT COUNT(*) AS count FROM nodes").fetchone()["count"]
            scopes = connection.execute("SELECT COUNT(*) AS count FROM live_sync_state WHERE dirty = 1").fetchone()["count"]
            apply_commits = connection.execute("SELECT COUNT(*) AS count FROM apply_commits").fetchone()["count"]
            apply_audit_rows = connection.execute("SELECT COUNT(*) AS count FROM apply_operation_audit").fetchone()["count"]
        with self._cache_lock:
            cache_size = len(self._document_cache)
            hits = self._cache_hits
            misses = self._cache_misses
        return {
            "dbPath": str(self._db_path),
            "documentCount": int(documents),
            "versionCount": int(versions),
            "nodeIndexCount": int(nodes),
            "dirtyScopeCount": int(scopes),
            "applyCommitCount": int(apply_commits),
            "applyAuditRowCount": int(apply_audit_rows),
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

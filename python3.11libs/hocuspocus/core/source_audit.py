"""Bounded path-free SQLite audit store for source workspace operations."""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from contextlib import closing
from pathlib import Path
from typing import Any

from .paths import workspace_audit_path

_ALLOWED_DETAILS = frozenset(
    {
        "action",
        "argumentDigest",
        "digest",
        "errorCode",
        "externalAlias",
        "grantGeneration",
        "grants",
        "relativePath",
        "resultCount",
        "resultingDigest",
    }
)
_MAX_PROJECT_BUCKETS = 65


class WorkspaceAuditLogger:
    def __init__(
        self,
        logger: logging.Logger,
        *,
        path: Path | None = None,
        events_per_project: int = 10_000,
    ):
        if not 1 <= events_per_project <= 100_000:
            raise ValueError("workspace audit retention is outside supported bounds")
        self._logger = logger.getChild("workspace_audit")
        self._path = path or workspace_audit_path()
        self._limit = events_per_project
        self._total_limit = events_per_project * _MAX_PROJECT_BUCKETS
        self._lock = threading.Lock()
        self._closed = False
        self._initialize()

    def record(
        self,
        *,
        event: str,
        project_id: str | None,
        principal_id: str,
        session_id: str | None,
        success: bool,
        details: dict[str, Any] | None = None,
    ) -> None:
        safe_details = {
            key: _safe_detail(key, value)
            for key, value in (details or {}).items()
            if key in _ALLOWED_DETAILS
        }
        row = (
            time.time(),
            _bounded_token(event, 80),
            _bounded_token(project_id, 80) if project_id else None,
            _bounded_token(principal_id, 128),
            _bounded_token(session_id, 128) if session_id else None,
            int(bool(success)),
            json.dumps(safe_details, ensure_ascii=True, sort_keys=True),
        )
        try:
            with self._lock:
                if self._closed:
                    return
                with closing(self._connect()) as connection:
                    connection.execute("BEGIN IMMEDIATE")
                    cursor = connection.execute(
                        """
                        INSERT INTO workspace_audit_events (
                            occurred_at, event, project_id, principal_id,
                            session_id, success, details_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        row,
                    )
                    self._prune(connection, project_id, int(cursor.lastrowid))
                    connection.commit()
        except sqlite3.Error:
            self._logger.exception("workspace audit write failed")

    def recent(
        self,
        *,
        project_id: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        bounded = max(1, min(int(limit), 1000))
        query = """
            SELECT occurred_at, event, project_id, principal_id,
                   session_id, success, details_json
            FROM workspace_audit_events
        """
        parameters: tuple[Any, ...]
        if project_id is None:
            query += " ORDER BY event_id DESC LIMIT ?"
            parameters = (bounded,)
        else:
            query += " WHERE project_id = ? ORDER BY event_id DESC LIMIT ?"
            parameters = (project_id, bounded)
        try:
            with self._lock:
                if self._closed:
                    return []
                with closing(self._connect()) as connection:
                    rows = connection.execute(query, parameters).fetchall()
        except sqlite3.Error:
            self._logger.exception("workspace audit read failed")
            return []
        return [_audit_payload(row) for row in reversed(rows)]

    @property
    def closed(self) -> bool:
        with self._lock:
            return self._closed

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True

    def _initialize(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, closing(self._connect()) as connection:
            connection.executescript(
                """
                PRAGMA journal_mode = DELETE;
                PRAGMA synchronous = FULL;
                PRAGMA auto_vacuum = INCREMENTAL;
                CREATE TABLE IF NOT EXISTS workspace_audit_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    occurred_at REAL NOT NULL,
                    event TEXT NOT NULL,
                    project_id TEXT,
                    principal_id TEXT NOT NULL,
                    session_id TEXT,
                    success INTEGER NOT NULL CHECK (success IN (0, 1)),
                    details_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS workspace_audit_project_event
                    ON workspace_audit_events(project_id, event_id DESC);
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self._path,
            timeout=5.0,
            isolation_level=None,
        )
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def _prune(
        self,
        connection: sqlite3.Connection,
        project_id: str | None,
        inserted_id: int,
    ) -> None:
        if project_id is None:
            connection.execute(
                """
                DELETE FROM workspace_audit_events
                WHERE project_id IS NULL
                  AND event_id <= ?
                  AND event_id NOT IN (
                      SELECT event_id FROM workspace_audit_events
                      WHERE project_id IS NULL
                      ORDER BY event_id DESC LIMIT ?
                  )
                """,
                (inserted_id, self._limit),
            )
        else:
            connection.execute(
                """
                DELETE FROM workspace_audit_events
                WHERE project_id = ?
                  AND event_id <= ?
                  AND event_id NOT IN (
                      SELECT event_id FROM workspace_audit_events
                      WHERE project_id = ?
                      ORDER BY event_id DESC LIMIT ?
                  )
                """,
                (project_id, inserted_id, project_id, self._limit),
            )
        connection.execute(
            """
            DELETE FROM workspace_audit_events
            WHERE event_id NOT IN (
                SELECT event_id FROM workspace_audit_events
                ORDER BY event_id DESC LIMIT ?
            )
            """,
            (self._total_limit,),
        )
        connection.execute("PRAGMA incremental_vacuum(64)")


def _audit_payload(row: tuple[Any, ...]) -> dict[str, Any]:
    try:
        details = json.loads(row[6])
    except (TypeError, json.JSONDecodeError):
        details = {}
    return {
        "timestamp": row[0],
        "event": row[1],
        "projectId": row[2],
        "principalId": row[3],
        "sessionId": row[4],
        "success": bool(row[5]),
        "details": details if isinstance(details, dict) else {},
    }


def _safe_detail(key: str, value: Any) -> Any:
    if key == "relativePath":
        text = str(value).replace("\\", "/")
        if text.startswith("/") or ":" in text or ".." in text.split("/"):
            return "<invalid-relative-path>"
        return text[:512]
    if key in {"action", "errorCode", "externalAlias"}:
        return _bounded_token(value, 128)
    if key in {"digest", "argumentDigest", "resultingDigest"}:
        text = str(value)
        return text[:80] if text.startswith("sha256:") else "<invalid-digest>"
    if key == "resultCount" or key == "grantGeneration":
        return int(value) if isinstance(value, int) else 0
    if key == "grants" and isinstance(value, (list, tuple)):
        return [_bounded_token(item, 64) for item in value[:16]]
    return None


def _bounded_token(value: Any, maximum: int) -> str:
    text = str(value)
    if any(character in text for character in ("/", "\\", "\r", "\n")):
        return "<invalid-token>"
    return text[:maximum]


__all__ = ["WorkspaceAuditLogger"]

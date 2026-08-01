"""Document lookup and exact admission rollback for the live graph store."""

from __future__ import annotations

import json
import sqlite3
from typing import Any


class GraphStoreDocumentMixin:
    def _latest_row_by_document_id(
        self, connection: sqlite3.Connection, document_id: str
    ) -> sqlite3.Row | None:
        return connection.execute(
            "SELECT * FROM documents WHERE document_id = ?",
            (document_id,),
        ).fetchone()

    def _latest_row_by_root_path(
        self, connection: sqlite3.Connection, root_path: str
    ) -> sqlite3.Row | None:
        return connection.execute(
            "SELECT * FROM documents WHERE root_path = ?",
            (root_path,),
        ).fetchone()

    @staticmethod
    def _historical_document_revision(
        connection: sqlite3.Connection, document_id: str
    ) -> int:
        row = connection.execute(
            """
            SELECT MAX(document_revision) AS latest_revision
            FROM document_versions
            WHERE document_id = ?
            """,
            (document_id,),
        ).fetchone()
        return int(row["latest_revision"] or 0)

    def get_document_by_id(
        self, document_id: str
    ) -> dict[str, Any] | None:
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

    def get_document_by_root_path(
        self, root_path: str
    ) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = self._latest_row_by_root_path(connection, root_path)
            if row is None:
                return None
            document_id = str(row["document_id"])
        return self.get_document_by_id(document_id)

    def discard_document_admission(
        self, admitted_document: dict[str, Any]
    ) -> bool:
        """Remove only the exact current row represented by an admission receipt."""
        document_id = str(admitted_document.get("documentId", "")).strip()
        root_path = str(admitted_document.get("rootPath", "")).strip()
        document_revision = admitted_document.get("documentRevision")
        metadata = admitted_document.get("metadata")
        store = metadata.get("store") if isinstance(metadata, dict) else None
        content_hash = (
            str(store.get("contentHash", "")).strip()
            if isinstance(store, dict)
            else ""
        )
        if (
            not document_id
            or not root_path
            or type(document_revision) is not int
            or not content_hash
        ):
            raise ValueError("admitted document has an invalid rollback identity")

        deleted = False
        with self._lock, self._connect() as connection:
            row = self._latest_row_by_document_id(connection, document_id)
            if (
                row is None
                or str(row["root_path"]) != root_path
                or int(row["latest_revision"]) != document_revision
                or str(row["content_hash"]) != content_hash
                or str(row["payload_json"])
                != self._stable_json(admitted_document)
            ):
                return False
            for table in (
                "nodes",
                "edges",
                "parameter_bindings",
                "code_blobs",
            ):
                connection.execute(
                    f"DELETE FROM {table} WHERE document_id = ?",
                    (document_id,),
                )
            connection.execute(
                "DELETE FROM documents WHERE document_id = ?",
                (document_id,),
            )
            connection.execute(
                "DELETE FROM live_sync_state WHERE scope_key = ?",
                (root_path,),
            )
            deleted = True
        if deleted:
            self._cache_delete(document_id)
        return deleted


__all__ = ["GraphStoreDocumentMixin"]

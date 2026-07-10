"""In-memory document checkout and diagnostics state for MCP document workflows."""

from __future__ import annotations

import copy
import logging
import threading
import time
from dataclasses import dataclass
from typing import Any
from uuid import uuid4


@dataclass(slots=True)
class DocumentCheckoutRecord:
    checkout_id: str
    document_id: str
    document_kind: str
    root_path: str | None
    baseline_document: dict[str, Any]
    working_document: dict[str, Any]
    diagnostics: list[dict[str, Any]]
    created_at: float
    updated_at: float


class LiveDocumentService:
    def __init__(self, logger: logging.Logger, store: Any | None = None):
        self._logger = logger.getChild("live.documents")
        self._store = store
        self._lock = threading.Lock()
        self._checkouts: dict[str, DocumentCheckoutRecord] = {}

    def _persist_record(self, record: DocumentCheckoutRecord) -> None:
        if self._store is None:
            return
        self._store.save_checkout_record(
            {
                "checkout_id": record.checkout_id,
                "document_id": record.document_id,
                "document_kind": record.document_kind,
                "root_path": record.root_path,
                "baseline_document": record.baseline_document,
                "working_document": record.working_document,
                "diagnostics": record.diagnostics,
                "created_at": record.created_at,
                "updated_at": record.updated_at,
            }
        )

    def _record_for_checkout(self, checkout_id: str) -> DocumentCheckoutRecord | None:
        record = self._checkouts.get(checkout_id)
        if record is not None or self._store is None:
            return record
        payload = self._store.load_checkout_record(checkout_id)
        if payload is None:
            return None
        hydrated = DocumentCheckoutRecord(
            checkout_id=payload["checkout_id"],
            document_id=payload["document_id"],
            document_kind=payload["document_kind"],
            root_path=payload["root_path"],
            baseline_document=payload["baseline_document"],
            working_document=payload["working_document"],
            diagnostics=payload["diagnostics"],
            created_at=float(payload["created_at"]),
            updated_at=float(payload["updated_at"]),
        )
        self._checkouts[checkout_id] = hydrated
        return hydrated

    def create_checkout(
        self,
        *,
        document_id: str,
        document_kind: str,
        root_path: str | None,
        document: dict[str, Any],
    ) -> dict[str, Any]:
        checkout_id = str(uuid4())
        now = time.time()
        record = DocumentCheckoutRecord(
            checkout_id=checkout_id,
            document_id=document_id,
            document_kind=document_kind,
            root_path=root_path,
            baseline_document=copy.deepcopy(document),
            working_document=copy.deepcopy(document),
            diagnostics=[],
            created_at=now,
            updated_at=now,
        )
        with self._lock:
            self._checkouts[checkout_id] = record
        self._persist_record(record)
        return self.snapshot(checkout_id) or {}

    def snapshot(self, checkout_id: str) -> dict[str, Any] | None:
        with self._lock:
            record = self._record_for_checkout(checkout_id)
            if record is None:
                return None
            return {
                "checkoutId": record.checkout_id,
                "documentId": record.document_id,
                "documentKind": record.document_kind,
                "rootPath": record.root_path,
                "createdAt": record.created_at,
                "updatedAt": record.updated_at,
                "documentRevision": record.working_document.get("documentRevision"),
                "baselineDocumentRevision": record.baseline_document.get("documentRevision"),
                "diagnosticCount": len(record.diagnostics),
                "resourceUri": f"houdini://documents/checkouts/{record.checkout_id}",
                "diagnosticsUri": f"houdini://documents/diagnostics/{record.checkout_id}",
            }

    def working_document(self, checkout_id: str) -> dict[str, Any] | None:
        with self._lock:
            record = self._record_for_checkout(checkout_id)
            if record is None:
                return None
            document = copy.deepcopy(record.working_document)
            metadata = document.setdefault("metadata", {})
            if isinstance(metadata, dict):
                metadata.setdefault("checkoutId", record.checkout_id)
                metadata.setdefault("documentId", record.document_id)
                metadata.setdefault("baselineDocumentRevision", record.baseline_document.get("documentRevision"))
            return document

    def baseline_document(self, checkout_id: str) -> dict[str, Any] | None:
        with self._lock:
            record = self._record_for_checkout(checkout_id)
            if record is None:
                return None
            return copy.deepcopy(record.baseline_document)

    def diagnostics_payload(self, checkout_id: str) -> dict[str, Any] | None:
        with self._lock:
            record = self._record_for_checkout(checkout_id)
            if record is None:
                return None
            return {
                "checkoutId": record.checkout_id,
                "documentId": record.document_id,
                "rootPath": record.root_path,
                "documentRevision": record.working_document.get("documentRevision"),
                "diagnostics": copy.deepcopy(record.diagnostics),
                "count": len(record.diagnostics),
            }

    def update_working_document(
        self,
        checkout_id: str,
        document: dict[str, Any],
    ) -> dict[str, Any] | None:
        with self._lock:
            record = self._record_for_checkout(checkout_id)
            if record is None:
                return None
            record.working_document = copy.deepcopy(document)
            record.updated_at = time.time()
            self._persist_record(record)
        return self.snapshot(checkout_id)

    def replace_with_applied_document(
        self,
        checkout_id: str,
        document: dict[str, Any],
    ) -> dict[str, Any] | None:
        with self._lock:
            record = self._record_for_checkout(checkout_id)
            if record is None:
                return None
            applied = copy.deepcopy(document)
            record.baseline_document = applied
            record.working_document = copy.deepcopy(applied)
            record.diagnostics = []
            record.updated_at = time.time()
            self._persist_record(record)
        return self.snapshot(checkout_id)

    def set_diagnostics(
        self,
        checkout_id: str,
        diagnostics: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        with self._lock:
            record = self._record_for_checkout(checkout_id)
            if record is None:
                return None
            record.diagnostics = copy.deepcopy(diagnostics)
            record.updated_at = time.time()
            self._persist_record(record)
        return self.snapshot(checkout_id)

    def discard(self, checkout_id: str) -> bool:
        with self._lock:
            removed = self._checkouts.pop(checkout_id, None)
            if removed is None:
                removed = self._record_for_checkout(checkout_id)
                self._checkouts.pop(checkout_id, None)
            if self._store is not None:
                self._store.delete_checkout_record(checkout_id)
        if removed is not None:
            self._logger.info("discarded document checkout %s", checkout_id)
            return True
        return False

"""In-memory document checkout and diagnostics state for MCP document workflows."""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator
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


@dataclass(slots=True)
class PreviewArtifactRecord:
    preview_id: str
    payload: dict[str, Any]
    created_at: float
    last_accessed_at: float
    byte_length: int


@dataclass(slots=True)
class ApplyPlanRecord:
    plan_id: str
    plan_hash: str
    payload: dict[str, Any]
    created_at: float
    expires_at: float
    last_accessed_at: float
    byte_length: int


@dataclass(slots=True)
class IdempotencyRecord:
    idempotency_key: str
    plan_id: str
    plan_hash: str
    reservation_id: str
    state: str
    result: dict[str, Any] | None
    created_at: float
    updated_at: float
    expires_at: float


@dataclass(slots=True)
class ScopeWriteLeaseRecord:
    scope: str
    lease_id: str
    holder_id: str | None
    acquired_at: float


class PreviewArtifactError(ValueError):
    pass


class ApplyPlanError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class LiveDocumentService:
    _MAX_PREVIEW_ARTIFACTS = 64
    _PREVIEW_TTL_SECONDS = 60 * 60
    _MAX_PREVIEW_ARTIFACT_BYTES = 32 * 1024 * 1024
    _MAX_PREVIEW_TOTAL_BYTES = 128 * 1024 * 1024
    _MAX_APPLY_PLANS = 64
    _APPLY_PLAN_TTL_SECONDS = 30 * 60
    _MAX_APPLY_PLAN_BYTES = 16 * 1024 * 1024
    _MAX_APPLY_PLAN_TOTAL_BYTES = 64 * 1024 * 1024
    _MAX_IDEMPOTENCY_RECORDS = 256
    _IDEMPOTENCY_TTL_SECONDS = 24 * 60 * 60

    def __init__(self, logger: logging.Logger, store: Any | None = None):
        self._logger = logger.getChild("live.documents")
        self._store = store
        self._lock = threading.Lock()
        self._checkouts: dict[str, DocumentCheckoutRecord] = {}
        self._previews: dict[str, PreviewArtifactRecord] = {}
        self._apply_plans: dict[str, ApplyPlanRecord] = {}
        self._idempotency: dict[str, IdempotencyRecord] = {}
        self._scope_write_leases: dict[str, ScopeWriteLeaseRecord] = {}

    @staticmethod
    def _preview_encoding(payload: dict[str, Any]) -> tuple[str, int]:
        canonical = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        encoded = canonical.encode("utf-8")
        return hashlib.sha256(encoded).hexdigest(), len(encoded)

    def _prune_previews_locked(self, now: float, *, incoming_bytes: int = 0) -> None:
        expired = [
            preview_id
            for preview_id, record in self._previews.items()
            if now - record.last_accessed_at > self._PREVIEW_TTL_SECONDS
        ]
        for preview_id in expired:
            self._previews.pop(preview_id, None)
        def over_budget() -> bool:
            count_limit = self._MAX_PREVIEW_ARTIFACTS - (1 if incoming_bytes else 0)
            return (
                len(self._previews) > count_limit
                or sum(item.byte_length for item in self._previews.values()) + incoming_bytes
                > self._MAX_PREVIEW_TOTAL_BYTES
            )

        while self._previews and over_budget():
            oldest = min(self._previews.values(), key=lambda item: (item.last_accessed_at, item.preview_id))
            self._previews.pop(oldest.preview_id, None)

    def store_preview_artifact(self, payload: dict[str, Any]) -> dict[str, Any]:
        preview_id, byte_length = self._preview_encoding(payload)
        if byte_length > self._MAX_PREVIEW_ARTIFACT_BYTES:
            raise PreviewArtifactError(
                f"Preview artifact is {byte_length} bytes; the per-artifact limit is "
                f"{self._MAX_PREVIEW_ARTIFACT_BYTES} bytes."
            )
        detached = copy.deepcopy(payload)
        now = time.time()
        with self._lock:
            record = self._previews.get(preview_id)
            if record is None:
                self._prune_previews_locked(now, incoming_bytes=byte_length)
                if byte_length > self._MAX_PREVIEW_TOTAL_BYTES:
                    raise PreviewArtifactError(
                        f"Preview artifact exceeds the {self._MAX_PREVIEW_TOTAL_BYTES}-byte aggregate limit."
                    )
                record = PreviewArtifactRecord(preview_id, detached, now, now, byte_length)
                self._previews[preview_id] = record
            else:
                record.last_accessed_at = now
        return {
            "previewId": preview_id,
            "resourceUri": f"houdini://documents/previews/{preview_id}",
            "contentDigest": f"sha256:{preview_id}",
            "byteLength": byte_length,
        }

    def preview_artifact(self, preview_id: str) -> dict[str, Any] | None:
        now = time.time()
        with self._lock:
            self._prune_previews_locked(now)
            record = self._previews.get(preview_id)
            if record is None:
                return None
            record.last_accessed_at = now
            return copy.deepcopy(record.payload)

    def preview_artifact_stats(self) -> dict[str, int]:
        with self._lock:
            self._prune_previews_locked(time.time())
            return {
                "count": len(self._previews),
                "totalBytes": sum(item.byte_length for item in self._previews.values()),
                "maxArtifactBytes": self._MAX_PREVIEW_ARTIFACT_BYTES,
                "maxTotalBytes": self._MAX_PREVIEW_TOTAL_BYTES,
            }

    @staticmethod
    def _canonical_encoding(payload: dict[str, Any]) -> tuple[str, int]:
        try:
            canonical = json.dumps(
                payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True, allow_nan=False
            )
        except (TypeError, ValueError) as exc:
            raise ApplyPlanError("HOCUS730", f"Apply plan is not canonical JSON: {exc}") from exc
        encoded = canonical.encode("utf-8")
        return f"sha256:{hashlib.sha256(encoded).hexdigest()}", len(encoded)

    @classmethod
    def _verified_plan_encoding(cls, plan: dict[str, Any]) -> tuple[str, int]:
        if not isinstance(plan, dict):
            raise ApplyPlanError("HOCUS730", "Apply plan must be an object.")
        declared_hash = plan.get("planHash")
        if not isinstance(declared_hash, str) or not declared_hash.startswith("sha256:"):
            raise ApplyPlanError("HOCUS730", "Apply plan requires a sha256 planHash.")
        hashable = copy.deepcopy(plan)
        hashable.pop("planHash", None)
        computed_hash, _ = cls._canonical_encoding(hashable)
        if declared_hash != computed_hash:
            raise ApplyPlanError(
                "HOCUS731", f"Apply plan hash mismatch: declared {declared_hash}, computed {computed_hash}."
            )
        _, byte_length = cls._canonical_encoding(plan)
        return computed_hash, byte_length

    def _prune_apply_plans_locked(self, now: float, *, incoming_bytes: int = 0) -> None:
        for plan_id, record in list(self._apply_plans.items()):
            if now >= record.expires_at:
                self._apply_plans.pop(plan_id, None)

        def over_budget() -> bool:
            count_limit = self._MAX_APPLY_PLANS - (1 if incoming_bytes else 0)
            return (
                len(self._apply_plans) > count_limit
                or sum(item.byte_length for item in self._apply_plans.values()) + incoming_bytes
                > self._MAX_APPLY_PLAN_TOTAL_BYTES
            )

        while self._apply_plans and over_budget():
            oldest = min(
                self._apply_plans.values(), key=lambda item: (item.last_accessed_at, item.plan_id)
            )
            self._apply_plans.pop(oldest.plan_id, None)

    def store_apply_plan(
        self, plan: dict[str, Any], *, ttl_seconds: float | None = None
    ) -> dict[str, Any]:
        """Verify and retain an immutable, content-addressed apply plan."""
        plan_hash, byte_length = self._verified_plan_encoding(plan)
        if byte_length > self._MAX_APPLY_PLAN_BYTES:
            raise ApplyPlanError(
                "HOCUS732",
                f"Apply plan is {byte_length} bytes; the per-plan limit is "
                f"{self._MAX_APPLY_PLAN_BYTES} bytes.",
            )
        try:
            lifetime = self._APPLY_PLAN_TTL_SECONDS if ttl_seconds is None else float(ttl_seconds)
        except (TypeError, ValueError) as exc:
            raise ApplyPlanError("HOCUS733", "Apply plan TTL must be numeric.") from exc
        if lifetime <= 0 or lifetime > self._APPLY_PLAN_TTL_SECONDS:
            raise ApplyPlanError(
                "HOCUS733",
                f"Apply plan TTL must be greater than zero and no more than "
                f"{self._APPLY_PLAN_TTL_SECONDS} seconds.",
            )
        declared_plan_id = plan.get("planId")
        if declared_plan_id is not None and (
            not isinstance(declared_plan_id, str) or not declared_plan_id.strip()
        ):
            raise ApplyPlanError("HOCUS730", "Apply plan planId must be a non-empty string.")
        plan_id = declared_plan_id or plan_hash.removeprefix("sha256:")
        now = time.time()
        detached = copy.deepcopy(plan)
        with self._lock:
            self._prune_apply_plans_locked(now)
            record = self._apply_plans.get(plan_id)
            if record is None:
                self._prune_apply_plans_locked(now, incoming_bytes=byte_length)
                if byte_length > self._MAX_APPLY_PLAN_TOTAL_BYTES:
                    raise ApplyPlanError(
                        "HOCUS732",
                        f"Apply plan exceeds the {self._MAX_APPLY_PLAN_TOTAL_BYTES}-byte aggregate limit.",
                    )
                record = ApplyPlanRecord(
                    plan_id, plan_hash, detached, now, now + lifetime, now, byte_length
                )
                self._apply_plans[plan_id] = record
            else:
                # Identical content deduplicates without extending the security TTL.
                self._verified_plan_encoding(record.payload)
                if record.plan_hash != plan_hash:
                    raise ApplyPlanError(
                        "HOCUS731", "Apply plan ID is already bound to different immutable content."
                    )
                record.last_accessed_at = now
        return {
            "planId": plan_id,
            "planHash": plan_hash,
            "resourceUri": f"houdini://documents/plans/{plan_id}",
            "createdAt": record.created_at,
            "expiresAt": record.expires_at,
            "byteLength": record.byte_length,
        }

    def apply_plan(self, plan_id: str, *, expected_hash: str | None = None) -> dict[str, Any] | None:
        """Return a detached plan after expiry, identity, and content-integrity checks."""
        now = time.time()
        with self._lock:
            self._prune_apply_plans_locked(now)
            record = self._apply_plans.get(plan_id)
            if record is None:
                return None
            if expected_hash is not None and expected_hash != record.plan_hash:
                raise ApplyPlanError("HOCUS731", "Requested plan hash does not match the stored plan.")
            try:
                verified_hash, _ = self._verified_plan_encoding(record.payload)
            except ApplyPlanError:
                self._apply_plans.pop(plan_id, None)
                raise
            embedded_plan_id = record.payload.get("planId") or verified_hash.removeprefix("sha256:")
            if verified_hash != record.plan_hash or plan_id != embedded_plan_id:
                self._apply_plans.pop(plan_id, None)
                raise ApplyPlanError("HOCUS731", "Stored apply plan failed its content-integrity check.")
            record.last_accessed_at = now
            return copy.deepcopy(record.payload)

    def apply_plan_resource(self, plan_id: str) -> dict[str, Any] | None:
        plan = self.apply_plan(plan_id)
        if plan is None:
            return None
        with self._lock:
            record = self._apply_plans.get(plan_id)
            if record is None:
                return None
            return {
                "planId": plan_id,
                "planHash": record.plan_hash,
                "createdAt": record.created_at,
                "expiresAt": record.expires_at,
                "byteLength": record.byte_length,
                "plan": plan,
            }

    def discard_apply_plan(self, plan_id: str, *, expected_hash: str | None = None) -> bool:
        with self._lock:
            self._prune_apply_plans_locked(time.time())
            record = self._apply_plans.get(plan_id)
            if record is None:
                return False
            if expected_hash is not None and expected_hash != record.plan_hash:
                raise ApplyPlanError("HOCUS731", "Requested plan hash does not match the stored plan.")
            self._apply_plans.pop(plan_id, None)
            return True

    def apply_plan_stats(self) -> dict[str, int]:
        with self._lock:
            self._prune_apply_plans_locked(time.time())
            return {
                "count": len(self._apply_plans),
                "totalBytes": sum(item.byte_length for item in self._apply_plans.values()),
                "maxPlanBytes": self._MAX_APPLY_PLAN_BYTES,
                "maxTotalBytes": self._MAX_APPLY_PLAN_TOTAL_BYTES,
            }

    def _prune_idempotency_locked(self, now: float, *, reserve_slot: bool = False) -> None:
        for key, record in list(self._idempotency.items()):
            if now >= record.expires_at:
                self._idempotency.pop(key, None)
        limit = self._MAX_IDEMPOTENCY_RECORDS - (1 if reserve_slot else 0)
        while len(self._idempotency) > limit:
            evictable = [item for item in self._idempotency.values() if item.state != "reserved"]
            if not evictable:
                raise ApplyPlanError("HOCUS734", "All idempotency reservation slots are active.")
            oldest = min(evictable, key=lambda item: (item.updated_at, item.idempotency_key))
            self._idempotency.pop(oldest.idempotency_key, None)

    def reserve_apply_result(
        self, idempotency_key: str, *, plan_id: str, plan_hash: str
    ) -> dict[str, Any]:
        """Reserve execution or return the existing pending/completed retry state."""
        if not isinstance(idempotency_key, str) or not idempotency_key.strip():
            raise ApplyPlanError("HOCUS735", "Idempotency key must be a non-empty string.")
        now = time.time()
        with self._lock:
            self._prune_idempotency_locked(now)
            existing = self._idempotency.get(idempotency_key)
            if existing is not None:
                if (existing.plan_id, existing.plan_hash) != (plan_id, plan_hash):
                    raise ApplyPlanError(
                        "HOCUS736", "Idempotency key is already bound to a different apply plan."
                    )
                response: dict[str, Any] = {
                    "state": existing.state,
                    "planId": plan_id,
                    "planHash": plan_hash,
                }
                if existing.state == "committed":
                    response["result"] = copy.deepcopy(existing.result)
                return response
            self._prune_idempotency_locked(now, reserve_slot=True)
            reservation_id = str(uuid4())
            record = IdempotencyRecord(
                idempotency_key=idempotency_key,
                plan_id=plan_id,
                plan_hash=plan_hash,
                reservation_id=reservation_id,
                state="reserved",
                result=None,
                created_at=now,
                updated_at=now,
                expires_at=now + self._IDEMPOTENCY_TTL_SECONDS,
            )
            self._idempotency[idempotency_key] = record
            return {
                "state": "reserved",
                "reservationId": reservation_id,
                "planId": plan_id,
                "planHash": plan_hash,
            }

    def apply_result(
        self,
        idempotency_key: str,
        *,
        plan_id: str | None = None,
        plan_hash: str | None = None,
    ) -> dict[str, Any] | None:
        with self._lock:
            self._prune_idempotency_locked(time.time())
            record = self._idempotency.get(idempotency_key)
            if record is None:
                return None
            if plan_id is not None and plan_id != record.plan_id:
                raise ApplyPlanError("HOCUS736", "Idempotency key is bound to a different plan ID.")
            if plan_hash is not None and plan_hash != record.plan_hash:
                raise ApplyPlanError("HOCUS736", "Idempotency key is bound to a different plan hash.")
            payload: dict[str, Any] = {
                "state": record.state,
                "planId": record.plan_id,
                "planHash": record.plan_hash,
            }
            if record.state == "committed":
                payload["result"] = copy.deepcopy(record.result)
            return payload

    def commit_apply_result(self, reservation_id: str, result: dict[str, Any]) -> dict[str, Any]:
        now = time.time()
        with self._lock:
            record = next(
                (item for item in self._idempotency.values() if item.reservation_id == reservation_id), None
            )
            if record is None or record.state != "reserved":
                raise ApplyPlanError("HOCUS737", "Idempotency reservation is absent or no longer active.")
            record.result = copy.deepcopy(result)
            record.state = "committed"
            record.updated_at = now
            record.expires_at = now + self._IDEMPOTENCY_TTL_SECONDS
            return {"state": "committed", "result": copy.deepcopy(record.result)}

    def recover_apply_result(
        self,
        idempotency_key: str,
        *,
        plan_id: str,
        plan_hash: str,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        """Reconcile the volatile replay cache to an authoritative durable result."""

        if not isinstance(idempotency_key, str) or not idempotency_key.strip():
            raise ApplyPlanError("HOCUS735", "Idempotency key must be a non-empty string.")
        if not isinstance(result, dict):
            raise ApplyPlanError("HOCUS737", "Recovered apply result must be an object.")
        now = time.time()
        with self._lock:
            self._prune_idempotency_locked(now)
            record = self._idempotency.get(idempotency_key)
            if record is not None and (record.plan_id, record.plan_hash) != (plan_id, plan_hash):
                raise ApplyPlanError(
                    "HOCUS736", "Idempotency key is bound to a different apply plan."
                )
            if record is None:
                self._prune_idempotency_locked(now, reserve_slot=True)
                record = IdempotencyRecord(
                    idempotency_key=idempotency_key,
                    plan_id=plan_id,
                    plan_hash=plan_hash,
                    reservation_id=str(uuid4()),
                    state="committed",
                    result=copy.deepcopy(result),
                    created_at=now,
                    updated_at=now,
                    expires_at=now + self._IDEMPOTENCY_TTL_SECONDS,
                )
                self._idempotency[idempotency_key] = record
            else:
                record.result = copy.deepcopy(result)
                record.state = "committed"
                record.updated_at = now
                record.expires_at = now + self._IDEMPOTENCY_TTL_SECONDS
            return {"state": "committed", "result": copy.deepcopy(record.result)}

    def abort_apply_result(self, reservation_id: str) -> bool:
        """Release an uncommitted reservation so a later retry may execute."""
        with self._lock:
            for key, record in list(self._idempotency.items()):
                if record.reservation_id == reservation_id and record.state == "reserved":
                    self._idempotency.pop(key, None)
                    return True
            return False

    def acquire_scope_write_lease(
        self, scope: str, *, holder_id: str | None = None
    ) -> dict[str, Any]:
        normalized = scope.strip().rstrip("/") if isinstance(scope, str) else ""
        normalized = normalized or "/"
        if not normalized.startswith("/"):
            raise ApplyPlanError("HOCUS738", "Write-lease scope must be an absolute network path.")
        now = time.time()
        with self._lock:
            existing = next(
                (
                    record
                    for record in self._scope_write_leases.values()
                    if normalized == "/"
                    or record.scope == "/"
                    or normalized == record.scope
                    or normalized.startswith(record.scope.rstrip("/") + "/")
                    or record.scope.startswith(normalized.rstrip("/") + "/")
                ),
                None,
            )
            if existing is not None:
                raise ApplyPlanError(
                    "HOCUS739",
                    f"Network scope {normalized!r} overlaps active lease {existing.scope!r}.",
                )
            record = ScopeWriteLeaseRecord(normalized, str(uuid4()), holder_id, now)
            self._scope_write_leases[normalized] = record
            return {
                "scope": record.scope,
                "leaseId": record.lease_id,
                "holderId": record.holder_id,
                "acquiredAt": record.acquired_at,
            }

    def release_scope_write_lease(self, scope: str, lease_id: str) -> bool:
        normalized = scope.strip().rstrip("/") if isinstance(scope, str) else ""
        normalized = normalized or "/"
        with self._lock:
            record = self._scope_write_leases.get(normalized)
            if record is None:
                return False
            if record.lease_id != lease_id:
                raise ApplyPlanError("HOCUS739", "Write lease token does not match the active lease.")
            self._scope_write_leases.pop(normalized, None)
            return True

    @contextmanager
    def scope_write_lease(
        self, scope: str, *, holder_id: str | None = None
    ) -> Iterator[dict[str, Any]]:
        lease = self.acquire_scope_write_lease(scope, holder_id=holder_id)
        try:
            yield lease
        finally:
            self.release_scope_write_lease(scope, lease["leaseId"])

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
        try:
            self._persist_record(record)
        except Exception:
            with self._lock:
                if self._checkouts.get(checkout_id) is record:
                    self._checkouts.pop(checkout_id, None)
            raise
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
            removed = self._checkouts.get(checkout_id)
            if removed is None:
                removed = self._record_for_checkout(checkout_id)
            if removed is None:
                return False
            if self._store is not None:
                self._store.delete_checkout_record(checkout_id)
            if self._checkouts.get(checkout_id) is removed:
                self._checkouts.pop(checkout_id, None)
        self._logger.info("discarded document checkout %s", checkout_id)
        return True

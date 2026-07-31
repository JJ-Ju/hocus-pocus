"""Immutable plan and checkout persistence for the live graph store."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import sqlite3
import time
from typing import Any


class GraphStorePlanError(RuntimeError):
    """Raised when immutable-plan or apply-commit state is inconsistent."""


class GraphStorePlanMixin:
    """SQLite operations for checkout records and immutable plan lifecycles."""

    _DURABLE_TERMINAL_RETENTION_SECONDS = 24 * 60 * 60
    _MAX_DURABLE_PLAN_HISTORIES = 256
    _MAX_DURABLE_PLAN_HISTORY_BYTES = 256 * 1024 * 1024
    _DURABLE_TERMINAL_TRANSITION_MAX_BYTES = 32 * 1024 * 1024

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

    def _validate_immutable_plan_identity(
        self,
        payload: dict[str, Any],
        plan_id: str | None,
        session_id: str | None,
        root_path: str | None,
    ) -> tuple[str, str, str]:
        declared = (
            self._required_plan_string(payload, "planId"),
            self._required_plan_string(payload, "sessionId"),
            self._required_plan_string(payload, "rootPath"),
        )
        if not declared[2].startswith("/"):
            raise GraphStorePlanError("Immutable plan rootPath must be absolute.")
        provided = (plan_id, session_id, root_path)
        messages = (
            "plan_id does not match immutable plan planId.",
            "session_id does not match immutable plan sessionId.",
            "root_path does not match immutable plan rootPath.",
        )
        for value, expected, message in zip(provided, declared, messages):
            if value is not None and str(value).strip() != expected:
                raise GraphStorePlanError(message)
        return declared

    @staticmethod
    def _validate_optional_plan_label(payload: dict[str, Any], field: str) -> str | None:
        value = payload.get(field)
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise GraphStorePlanError(f"{field} must be null or a non-empty string.")
        if isinstance(value, str) and value != value.strip():
            raise GraphStorePlanError(f"{field} must not contain surrounding whitespace.")
        return value

    def _validate_immutable_plan_body(
        self, payload: dict[str, Any]
    ) -> tuple[str, int, int, list[str], dict[str, Any]]:
        baseline = payload.get("baseline")
        if not isinstance(baseline, dict):
            raise GraphStorePlanError("Immutable plan requires a baseline object.")
        document_id = self._required_plan_string(baseline, "documentId")
        document_revision = baseline.get("documentRevision")
        live_revision = baseline.get("liveRevision")
        if type(document_revision) is not int or document_revision < 0:
            raise GraphStorePlanError("baselineDocumentRevision must be a non-negative integer.")
        if type(live_revision) is not int or live_revision < 0:
            raise GraphStorePlanError("baselineLiveRevision must be a non-negative integer.")
        capabilities = payload.get("requiredCapabilities")
        execution_plan = payload.get("executionPlan")
        if not isinstance(execution_plan, dict):
            raise GraphStorePlanError("Immutable plan requires an executionPlan object.")
        if not isinstance(capabilities, list) or any(
            not isinstance(item, str) or not item or item != item.strip()
            for item in capabilities
        ):
            raise GraphStorePlanError(
                "requiredCapabilities must be an array of non-empty strings."
            )
        if len(set(capabilities)) != len(capabilities):
            raise GraphStorePlanError("requiredCapabilities must not contain duplicates.")
        return document_id, document_revision, live_revision, capabilities, execution_plan

    @staticmethod
    def _validate_immutable_plan_times(
        payload: dict[str, Any],
        created_at: float | None,
        expires_at: float | None,
    ) -> tuple[float, float]:
        declared_created = payload.get("createdAt")
        declared_expiry = payload.get("expiresAt")
        if not isinstance(declared_created, (int, float)) or isinstance(declared_created, bool):
            raise GraphStorePlanError("Immutable plan createdAt must be a number.")
        if not isinstance(declared_expiry, (int, float)) or isinstance(declared_expiry, bool):
            raise GraphStorePlanError("Immutable plan expiresAt must be a number.")
        created, expiry = float(declared_created), float(declared_expiry)
        if created_at is not None and float(created_at) != created:
            raise GraphStorePlanError("created_at does not match immutable plan createdAt.")
        if expires_at is not None and float(expires_at) != expiry:
            raise GraphStorePlanError("expires_at does not match immutable plan expiresAt.")
        if not math.isfinite(created) or not math.isfinite(expiry) or expiry <= created:
            raise GraphStorePlanError("expires_at must be finite and later than created_at.")
        return created, expiry

    @staticmethod
    def _durable_plan_history_rows(
        connection: sqlite3.Connection,
    ) -> list[sqlite3.Row]:
        return connection.execute(
            """
            SELECT
                plan.plan_id,
                plan.expires_at,
                plan_commit.plan_commit_id,
                plan_commit.state,
                plan_commit.updated_at,
                (
                    LENGTH(plan.required_capabilities_json)
                    + LENGTH(plan.execution_plan_json)
                    + LENGTH(plan.payload_json)
                    + COALESCE(LENGTH(plan_commit.pre_apply_snapshot_json), 0)
                    + COALESCE(LENGTH(plan_commit.inverse_plan_json), 0)
                    + COALESCE(LENGTH(plan_commit.result_json), 0)
                    + COALESCE(LENGTH(plan_commit.error_json), 0)
                    + COALESCE(events.json_bytes, 0)
                ) AS json_bytes,
                (
                    COALESCE(LENGTH(plan_commit.result_json), 0)
                    + COALESCE(LENGTH(plan_commit.error_json), 0)
                    + COALESCE(events.transition_bytes, 0)
                ) AS terminal_transition_bytes
            FROM immutable_apply_plans AS plan
            LEFT JOIN plan_apply_commits AS plan_commit
                ON plan_commit.plan_id = plan.plan_id
            LEFT JOIN (
                SELECT
                    plan_commit_id,
                    SUM(LENGTH(details_json)) AS json_bytes,
                    SUM(
                        CASE WHEN from_state IS NULL
                            THEN 0 ELSE LENGTH(details_json)
                        END
                    ) AS transition_bytes
                FROM plan_commit_events
                GROUP BY plan_commit_id
            ) AS events
                ON events.plan_commit_id = plan_commit.plan_commit_id
            ORDER BY plan.created_at, plan.plan_id
            """
        ).fetchall()

    @staticmethod
    def _delete_durable_plan_histories(
        connection: sqlite3.Connection,
        plan_ids: list[str],
    ) -> None:
        for plan_id in plan_ids:
            commit_rows = connection.execute(
                "SELECT plan_commit_id FROM plan_apply_commits WHERE plan_id = ?",
                (plan_id,),
            ).fetchall()
            for commit in commit_rows:
                connection.execute(
                    "DELETE FROM plan_commit_events WHERE plan_commit_id = ?",
                    (commit["plan_commit_id"],),
                )
            connection.execute(
                "DELETE FROM plan_apply_commits WHERE plan_id = ?",
                (plan_id,),
            )
            connection.execute(
                """
                DELETE FROM immutable_apply_plans
                WHERE plan_id = ?
                  AND NOT EXISTS (
                      SELECT 1 FROM plan_apply_commits
                      WHERE plan_apply_commits.plan_id = immutable_apply_plans.plan_id
                  )
                """,
                (plan_id,),
            )

    @classmethod
    def _durable_history_budget_bytes(cls, rows: list[sqlite3.Row]) -> int:
        total = 0
        for row in rows:
            actual = int(row["json_bytes"] or 0)
            total += actual
            if row["state"] in {"pending", "partial_or_unknown"}:
                used = int(row["terminal_transition_bytes"] or 0)
                total += max(
                    0,
                    cls._DURABLE_TERMINAL_TRANSITION_MAX_BYTES - used,
                )
        return total

    @classmethod
    def _durable_history_over_budget(
        cls,
        rows: list[sqlite3.Row],
        *,
        incoming_count: int,
        incoming_bytes: int,
    ) -> bool:
        return (
            len(rows) + incoming_count > cls._MAX_DURABLE_PLAN_HISTORIES
            or cls._durable_history_budget_bytes(rows) + incoming_bytes
            > cls._MAX_DURABLE_PLAN_HISTORY_BYTES
        )

    def _prune_durable_plan_history_locked(
        self,
        connection: sqlite3.Connection,
        *,
        now: float,
        incoming_count: int = 0,
        incoming_bytes: int = 0,
        reject_growth: bool,
    ) -> dict[str, int]:
        rows = self._durable_plan_history_rows(connection)
        expired_unclaimed = [
            str(row["plan_id"])
            for row in rows
            if row["plan_commit_id"] is None and float(row["expires_at"]) <= now
        ]
        self._delete_durable_plan_histories(connection, expired_unclaimed)
        rows = self._durable_plan_history_rows(connection)
        cutoff = now - self._DURABLE_TERMINAL_RETENTION_SECONDS
        aged_terminal = [
            str(row["plan_id"])
            for row in rows
            if row["state"] in {"committed", "aborted"}
            and float(row["updated_at"]) <= cutoff
        ]
        self._delete_durable_plan_histories(connection, aged_terminal)
        rows = self._durable_plan_history_rows(connection)
        pressure_candidates = sorted(
            (
                row
                for row in rows
                if row["state"] in {"committed", "aborted"}
            ),
            key=lambda row: (float(row["updated_at"]), str(row["plan_commit_id"])),
        )
        pressure_pruned: list[str] = []
        while pressure_candidates and self._durable_history_over_budget(
            rows,
            incoming_count=incoming_count,
            incoming_bytes=incoming_bytes,
        ):
            selected = pressure_candidates.pop(0)
            plan_id = str(selected["plan_id"])
            pressure_pruned.append(plan_id)
            self._delete_durable_plan_histories(connection, [plan_id])
            rows = self._durable_plan_history_rows(connection)
        if reject_growth and self._durable_history_over_budget(
            rows,
            incoming_count=incoming_count,
            incoming_bytes=incoming_bytes,
        ):
            raise GraphStorePlanError(
                "Durable immutable-plan retention is exhausted by active or "
                "unresolved recovery records."
            )
        return {
            "historyCount": len(rows),
            "retainedJsonBytes": sum(int(row["json_bytes"] or 0) for row in rows),
            "expiredUnclaimedPruned": len(expired_unclaimed),
            "agedTerminalPruned": len(aged_terminal),
            "pressurePruned": len(pressure_pruned),
        }

    def prune_durable_plan_history(
        self,
        *,
        now: float | None = None,
    ) -> dict[str, int]:
        timestamp = time.time() if now is None else float(now)
        if not math.isfinite(timestamp):
            raise GraphStorePlanError("Retention timestamp must be finite.")
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            return self._prune_durable_plan_history_locked(
                connection,
                now=timestamp,
                reject_growth=False,
            )

    def store_immutable_plan(
        self,
        *,
        payload: dict[str, Any],
        plan_id: str | None = None,
        session_id: str | None = None,
        root_path: str | None = None,
        expires_at: float | None = None,
        created_at: float | None = None,
        now: float | None = None,
    ) -> dict[str, Any]:
        """Persist one content-verified plan; an existing ID is never replaced."""
        if not isinstance(payload, dict):
            raise GraphStorePlanError("Immutable plan payload must be an object.")
        plan_payload = copy.deepcopy(payload)
        plan_id, session_id, root_path = self._validate_immutable_plan_identity(
            plan_payload, plan_id, session_id, root_path
        )
        plan_hash = self._required_plan_string(plan_payload, "planHash")
        try:
            computed_hash = self._plan_digest(plan_payload)
        except (TypeError, ValueError) as exc:
            raise GraphStorePlanError("Immutable plan payload is not canonical JSON.") from exc
        if plan_hash != computed_hash:
            raise GraphStorePlanError("Immutable plan hash does not match its payload.")
        source_digest = self._required_plan_string(plan_payload, "sourceDigest")
        catalog_fingerprint = self._required_plan_string(plan_payload, "catalogFingerprint")
        catalog_content_digest = self._validate_optional_plan_label(
            plan_payload, "catalogContentDigest"
        )
        ownership = self._validate_optional_plan_label(plan_payload, "ownership")
        (
            document_id,
            baseline_document_revision,
            baseline_live_revision,
            required_capabilities,
            execution_plan,
        ) = self._validate_immutable_plan_body(plan_payload)
        created, expiry = self._validate_immutable_plan_times(
            plan_payload, created_at, expires_at
        )
        timestamp = time.time() if now is None else float(now)
        if not math.isfinite(timestamp):
            raise GraphStorePlanError("Storage timestamp must be finite.")
        if expiry <= timestamp:
            raise GraphStorePlanError(
                "Cannot persist an immutable plan that is already expired."
            )

        capabilities_json = self._strict_plan_json(
            required_capabilities, "requiredCapabilities"
        )
        execution_json = self._strict_plan_json(execution_plan, "executionPlan")
        payload_json = self._strict_plan_json(plan_payload, "plan payload")
        incoming_bytes = len(capabilities_json) + len(execution_json) + len(payload_json)
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._prune_durable_plan_history_locked(
                connection,
                now=timestamp,
                incoming_count=1,
                incoming_bytes=incoming_bytes,
                reject_growth=True,
            )
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
                        baseline_live_revision, capabilities_json,
                        execution_json, payload_json,
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

    def delete_unclaimed_plan(
        self,
        plan_id: str,
        *,
        expected_hash: str,
    ) -> bool:
        """Delete a plan that was never returned and has no lifecycle claim."""

        normalized_id = str(plan_id).strip()
        normalized_hash = str(expected_hash).strip()
        if not normalized_id or not normalized_hash:
            raise GraphStorePlanError(
                "Plan ID and expected hash are required for unclaimed deletion."
            )
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT plan_hash FROM immutable_apply_plans WHERE plan_id = ?",
                (normalized_id,),
            ).fetchone()
            if row is None:
                return False
            if str(row["plan_hash"]) != normalized_hash:
                raise GraphStorePlanError(
                    "Plan hash does not match the unclaimed immutable plan."
                )
            claimed = connection.execute(
                "SELECT 1 FROM plan_apply_commits WHERE plan_id = ?",
                (normalized_id,),
            ).fetchone()
            if claimed is not None:
                raise GraphStorePlanError(
                    "Claimed immutable plans cannot be deleted as unclaimed."
                )
            connection.execute(
                "DELETE FROM immutable_apply_plans WHERE plan_id = ?",
                (normalized_id,),
            )
            return True

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

    def _claimable_plan_row(
        self,
        connection: sqlite3.Connection,
        *,
        plan_id: str,
        plan_hash: str,
        session_id: str,
        idempotency_key: str,
        timestamp: float,
    ) -> dict[str, Any] | None:
        plan = connection.execute(
            "SELECT * FROM immutable_apply_plans WHERE plan_id = ?", (plan_id,)
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
            "SELECT plan_commit_id FROM plan_apply_commits WHERE plan_id = ?", (plan_id,)
        ).fetchone()
        if previous is not None:
            raise GraphStorePlanError("Immutable plan has already been claimed for apply.")
        return None

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
        event_details_json = self._stable_json({"idempotencyKey": idempotency_key})
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._claimable_plan_row(
                connection,
                plan_id=plan_id,
                plan_hash=plan_hash,
                session_id=session_id,
                idempotency_key=idempotency_key,
                timestamp=timestamp,
            )
            if existing is not None:
                return existing
            self._prune_durable_plan_history_locked(
                connection,
                now=timestamp,
                incoming_bytes=(
                    len(snapshot_json)
                    + len(inverse_json or "")
                    + len(event_details_json)
                    + self._DURABLE_TERMINAL_TRANSITION_MAX_BYTES
                ),
                reject_growth=True,
            )
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
                    (plan_commit_id, event_details_json, timestamp),
                )
            except sqlite3.IntegrityError as exc:
                raise GraphStorePlanError("Plan commit identity conflicts with an existing record.") from exc
            row = connection.execute(
                "SELECT * FROM plan_apply_commits WHERE plan_commit_id = ?",
                (plan_commit_id,),
            ).fetchone()
            assert row is not None
            return self._decode_plan_commit_row(row)

    def _bounded_terminal_transition_json(
        self,
        *,
        result: dict[str, Any] | None,
        error: dict[str, Any] | None,
        event_details: dict[str, Any],
        label: str,
    ) -> tuple[str | None, str | None, str]:
        result_json = (
            self._strict_plan_json(result, f"{label} result")
            if result is not None
            else None
        )
        error_json = (
            self._strict_plan_json(error, f"{label} error")
            if error is not None
            else None
        )
        event_json = self._strict_plan_json(event_details, f"{label} event")
        byte_length = len(result_json or "") + len(error_json or "") + len(event_json)
        if byte_length > self._DURABLE_TERMINAL_TRANSITION_MAX_BYTES:
            raise GraphStorePlanError(
                f"{label} result, error, and event require {byte_length} bytes; "
                "the durable terminal transition limit is "
                f"{self._DURABLE_TERMINAL_TRANSITION_MAX_BYTES} bytes."
            )
        return result_json, error_json, event_json

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
        result_json, error_json, event_json = self._bounded_terminal_transition_json(
            result=result,
            error=error,
            event_details={
                "hasResult": result is not None,
                "hasError": error is not None,
            },
            label="Plan commit terminal transition",
        )
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
                    event_json,
                    timestamp,
                ),
            )
            updated = connection.execute(
                "SELECT * FROM plan_apply_commits WHERE plan_commit_id = ?",
                (plan_commit_id,),
            ).fetchone()
            assert updated is not None
            decoded = self._decode_plan_commit_row(updated)
            self._prune_durable_plan_history_locked(
                connection,
                now=timestamp,
                reject_growth=True,
            )
            return decoded

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
        result_json, _, event_json = self._bounded_terminal_transition_json(
            result=result,
            error=None,
            event_details={"recovered": True},
            label="Plan commit recovery",
        )
        assert result_json is not None
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
            prior_event_bytes = int(
                connection.execute(
                    """
                    SELECT COALESCE(SUM(LENGTH(details_json)), 0)
                    FROM plan_commit_events
                    WHERE plan_commit_id = ? AND from_state IS NOT NULL
                    """,
                    (plan_commit_id,),
                ).fetchone()[0]
            )
            if prior_event_bytes + len(result_json) + len(event_json) > (
                self._DURABLE_TERMINAL_TRANSITION_MAX_BYTES
            ):
                raise GraphStorePlanError(
                    "Plan commit recovery exceeds its reserved durable terminal "
                    "transition headroom."
                )
            connection.execute(
                "UPDATE plan_apply_commits SET state = ?, result_json = ?, error_json = NULL, updated_at = ? WHERE plan_commit_id = ? AND state = 'partial_or_unknown'",
                (state, result_json, timestamp, plan_commit_id),
            )
            connection.execute(
                "INSERT INTO plan_commit_events (plan_commit_id, from_state, to_state, details_json, created_at) VALUES (?, 'partial_or_unknown', ?, ?, ?)",
                (plan_commit_id, state, event_json, timestamp),
            )
            updated = connection.execute(
                "SELECT * FROM plan_apply_commits WHERE plan_commit_id = ?", (plan_commit_id,)
            ).fetchone()
            assert updated is not None
            decoded = self._decode_plan_commit_row(updated)
            self._prune_durable_plan_history_locked(
                connection,
                now=timestamp,
                reject_growth=True,
            )
            return decoded

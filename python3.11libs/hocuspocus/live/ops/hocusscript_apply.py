"""Durable HocusScript apply operations."""

from __future__ import annotations

import hmac
import time
from typing import Any
from uuid import uuid4

from hocuspocus.core.jsonrpc import INVALID_PARAMS, JsonRpcError
from hocuspocus.core.policy import require_capabilities

from ..context import RequestContext
from ..document_service import ApplyPlanError
from ..graph_store import GraphStorePlanError


class HocusScriptApplyOperationsMixin:
    def _hocus_quarantine_map(self) -> dict[str, dict[str, Any]]:
        value = getattr(self, "_hocus_apply_quarantines", None)
        if not isinstance(value, dict):
            value = {}
            self._hocus_apply_quarantines = value
            if hasattr(self._graph_store, "recoverable_plan_commits"):
                for commit in self._graph_store.recoverable_plan_commits():
                    plan = self._graph_store.load_immutable_plan(commit["plan_id"])
                    payload = plan.get("payload") if isinstance(plan, dict) else None
                    if isinstance(payload, dict):
                        value[str(payload.get("rootPath", "/"))] = {
                            "planId": commit["plan_id"],
                            "applyCommitId": commit["plan_commit_id"],
                            "reason": f"durable {commit['state']} apply requires recovery",
                            "createdAt": commit["created_at"],
                        }
        return value

    @staticmethod
    def _hocus_scopes_overlap(left: str, right: str) -> bool:
        left = left.rstrip("/") or "/"
        right = right.rstrip("/") or "/"
        return left == "/" or right == "/" or left == right or left.startswith(right + "/") or right.startswith(left + "/")

    def _hocus_assert_not_quarantined(self, scope: str) -> None:
        for quarantined, details in self._hocus_quarantine_map().items():
            if self._hocus_scopes_overlap(scope, quarantined):
                self._hocus_fail(
                    "HOCUS746", "The target scope overlaps quarantined apply state.",
                    family="conflict", scope=scope, quarantinedScope=quarantined, quarantine=details,
                )

    def _hocus_apply_test_checkpoint(self, stage: str) -> None:
        """Private failure-injection seam used only by offline/live rollback gates."""
        injection = getattr(self, "_hocus_apply_failure_injection", None)
        if callable(injection):
            injection(stage)
        elif injection == stage:
            raise RuntimeError(f"injected apply-stage failure: {stage}")

    def _hocus_apply_replay(
        self,
        plan_id: str,
        plan_hash: str,
        idempotency_key: str,
    ) -> dict[str, Any] | None:
        replay = self._hocus_service_call(
            lambda: self._documents.apply_result(
                idempotency_key, plan_id=plan_id, plan_hash=plan_hash
            )
        )
        durable_replay = self._hocus_store_call(
            lambda: self._graph_store.load_plan_commit(idempotency_key=idempotency_key)
        )
        if durable_replay is not None:
            if durable_replay.get("plan_id") != plan_id:
                self._hocus_fail("HOCUS736", "Idempotency key is durably bound to a different plan.", family="conflict")
            replay_plan = self._hocus_store_call(
                lambda: self._graph_store.load_immutable_plan(durable_replay["plan_id"])
            )
            if not isinstance(replay_plan, dict) or replay_plan.get("plan_hash") != plan_hash:
                self._hocus_fail(
                    "HOCUS731", "Submitted plan hash does not authenticate the durable replay record."
                )
            durable_result = durable_replay.get("result") or {}
            if durable_replay.get("state") == "committed" and durable_result.get("applied"):
                return {**durable_result, "idempotentReplay": True}
            if durable_replay.get("state") in {"aborted", "partial_or_unknown"}:
                self._hocus_fail(
                    str(durable_result.get("diagnosticCode", "HOCUS755")),
                    str(durable_result.get("message", "The prior durable apply attempt failed.")),
                    family="runtime", priorResult=durable_result, idempotentReplay=True,
                )
            self._hocus_fail(
                "HOCUS760", "A durable apply with this idempotency key is still pending recovery.",
                family="conflict", retryable=True,
            )
        if replay and replay.get("state") == "committed":
            result = replay.get("result") or {}
            if result.get("applied"):
                return {**result, "idempotentReplay": True}
            self._hocus_fail(
                str(result.get("diagnosticCode", "HOCUS755")),
                str(result.get("message", "The prior apply attempt failed.")),
                family=str(result.get("errorFamily", "runtime")),
                retryable=False,
                idempotentReplay=True,
                priorResult=result,
            )
        return None

    def _hocus_load_apply_plan(self, plan_id: str, plan_hash: str) -> dict[str, Any]:
        plan = self._hocus_service_call(
            lambda: self._documents.apply_plan(plan_id, expected_hash=plan_hash)
        )
        if plan is None:
            durable_record = self._hocus_store_call(lambda: self._graph_store.load_immutable_plan(plan_id))
            durable_plan = durable_record.get("payload") if isinstance(durable_record, dict) else None
            if isinstance(durable_plan, dict) and durable_plan.get("planHash") == plan_hash:
                remaining = float(durable_plan.get("expiresAt", 0)) - time.time()
                if remaining > 0:
                    self._hocus_service_call(
                        lambda: self._documents.store_apply_plan(durable_plan, ttl_seconds=remaining)
                    )
                    plan = self._hocus_service_call(
                        lambda: self._documents.apply_plan(plan_id, expected_hash=plan_hash)
                    )
        if plan is None:
            self._hocus_fail("HOCUS747", "Apply plan is absent, expired, revoked, or already consumed.")
        if plan.get("sessionId") != self._hocus_session_id():
            self._hocus_fail("HOCUS748", "Apply plan belongs to a different Houdini server session.")
        if time.time() >= float(plan.get("expiresAt", 0)):
            self._hocus_fail("HOCUS747", "Apply plan has expired.")
        if plan.get("policyFingerprint") != self._hocus_policy_fingerprint():
            self._hocus_fail("HOCUS749", "Server policy changed after the plan was created.", family="policy")
        return plan

    def _hocus_validate_apply_guards(
        self,
        plan: dict[str, Any],
        arguments: dict[str, Any],
        context: RequestContext,
    ) -> tuple[str, dict[str, Any]]:
        require_capabilities(context.permissions, tuple(plan.get("requiredCapabilities", [])))
        root_path = str(plan.get("rootPath", ""))
        self._hocus_assert_not_quarantined(root_path)
        expected_document_revision = arguments.get("expectedDocumentRevision")
        expected_live_revision = arguments.get("expectedLiveRevision")
        baseline_guard = plan["baseline"]
        if expected_document_revision != baseline_guard["documentRevision"] or expected_live_revision != baseline_guard["liveRevision"]:
            self._hocus_fail(
                "HOCUS750", "Caller revision guards do not match the immutable plan.",
                expectedDocumentRevision=baseline_guard["documentRevision"],
                expectedLiveRevision=baseline_guard["liveRevision"],
            )
        if plan.get("confirmationRequired"):
            supplied = arguments.get("confirmationToken")
            if not isinstance(supplied, str) or not hmac.compare_digest(
                self._hocus_canonical_digest(supplied), plan.get("confirmationTokenDigest", "")
            ):
                self._hocus_fail("HOCUS751", "A valid confirmation token is required for this plan.", family="policy")
        catalog = self._document_preview_live_catalog()
        if catalog.fingerprint != plan.get("catalogFingerprint"):
            self._hocus_fail(
                "HOCUS752", "The live Houdini catalog changed after planning.",
                expectedCatalogFingerprint=plan.get("catalogFingerprint"),
                liveCatalogFingerprint=catalog.fingerprint,
            )
        return root_path, baseline_guard

    def _hocus_reserve_apply_commit(
        self,
        plan: dict[str, Any],
        current: dict[str, Any],
        idempotency_key: str,
    ) -> tuple[str, str]:
        plan_id = plan["planId"]
        plan_hash = plan["planHash"]
        reservation = self._hocus_service_call(
            lambda: self._documents.reserve_apply_result(
                idempotency_key, plan_id=plan_id, plan_hash=plan_hash
            )
        )
        if reservation.get("state") != "reserved":
            self._hocus_fail(
                "HOCUS736",
                "An apply with this idempotency key is already in progress.",
                family="conflict",
                retryable=True,
            )
        reservation_id = reservation["reservationId"]
        apply_commit_id = str(uuid4())
        try:
            self._graph_store.begin_plan_commit(
                plan_commit_id=apply_commit_id,
                plan_id=plan_id,
                plan_hash=plan_hash,
                session_id=self._hocus_session_id(),
                idempotency_key=idempotency_key,
                pre_apply_snapshot=current,
                inverse_plan=plan["inversePlan"],
            )
        except GraphStorePlanError as exc:
            self._documents.abort_apply_result(reservation_id)
            self._hocus_fail(
                "HOCUS759",
                f"Could not begin the durable pending commit: {exc}",
                family="conflict",
            )
        return reservation_id, apply_commit_id

    def _document_apply_plan_impl(
        self,
        arguments: dict[str, Any],
        context: RequestContext,
    ) -> dict[str, Any]:
        plan_id = arguments.get("planId")
        plan_hash = arguments.get("planHash")
        idempotency_key = arguments.get("idempotencyKey")
        if not all(isinstance(value, str) and value for value in (plan_id, plan_hash, idempotency_key)):
            raise JsonRpcError(INVALID_PARAMS, "planId, planHash, and idempotencyKey are required strings.")
        replay = self._hocus_apply_replay(plan_id, plan_hash, idempotency_key)
        if replay is not None:
            return replay
        plan = self._hocus_load_apply_plan(plan_id, plan_hash)
        root_path, baseline_guard = self._hocus_validate_apply_guards(
            plan, arguments, context
        )
        context.raise_if_cancelled()
        with self._hocus_service_call(
            lambda: self._documents.scope_write_lease(root_path, holder_id=context.operation_id)
        ) as lease:
            self._hocus_assert_not_quarantined(root_path)
            current = self._document_current_network_payload(root_path, force_sync=True)
            current_live_revision = int(current.get("lastSyncedLiveRevision", current.get("baselineLiveRevision", 0)))
            if (
                current.get("documentId") != baseline_guard["documentId"]
                or current.get("documentRevision") != baseline_guard["documentRevision"]
                or current_live_revision != baseline_guard["liveRevision"]
                or self._hocus_canonical_digest(current) != baseline_guard["digest"]
            ):
                self._hocus_fail(
                    "HOCUS753", "The target network drifted after planning.",
                    family="conflict", retryable=False,
                    currentDocumentRevision=current.get("documentRevision"),
                    currentLiveRevision=current_live_revision,
                    currentDigest=self._hocus_canonical_digest(current),
                )
            # Rebuilding is a validation oracle only; the stored execution plan remains authoritative.
            validated = self._document_build_apply_plan(
                current, plan["targetDocument"], mode=plan["mode"]
            )
            if self._hocus_canonical_digest(validated) != self._hocus_canonical_digest(plan["executionPlan"]):
                self._hocus_fail("HOCUS754", "Ownership or normalized operation validation changed after planning.")
            context.raise_if_cancelled()
            final_gate = self._document_current_network_payload(root_path, force_sync=True)
            if self._hocus_canonical_digest(final_gate) != baseline_guard["digest"]:
                self._hocus_fail(
                    "HOCUS753", "The target network changed at the final pre-mutation checkpoint.",
                    family="conflict", currentDigest=self._hocus_canonical_digest(final_gate),
                )
            reservation_id, apply_commit_id = self._hocus_reserve_apply_commit(
                plan, current, idempotency_key
            )
            executed: list[dict[str, Any]] = []
            verification: dict[str, Any] | None = None
            rollback_verification: dict[str, Any] | None = None
            started = time.time()
            undo_label = f"HocusScript apply {plan_id}"
            try:
                self._hocus_apply_test_checkpoint("after_pending")
                context.raise_if_cancelled()
                hou_module = self._require_hou()
                with hou_module.undos.group(undo_label):
                    executed = self._document_execute_apply_plan(
                        plan["executionPlan"], current, checkpoint=context.raise_if_cancelled
                    )
                self._hocus_apply_test_checkpoint("after_execute")
                context.raise_if_cancelled()
                self._monitor.mark_dirty("tool:document.apply_plan", scope_path=root_path)
                refreshed = self._document_current_network_payload(root_path, force_sync=True)
                verification = self._document_verification_diff_payload(plan["targetDocument"], refreshed)
                if not self._document_diff_is_clean(verification):
                    raise RuntimeError(
                        f"Post-apply verification did not match the immutable target document: {verification.get('summary')}"
                    )
                self._hocus_apply_test_checkpoint("after_verify")
                context.raise_if_cancelled()
                self._hocus_apply_test_checkpoint("before_commit")
                result = {
                    "stage": "document_apply",
                    "planVersion": self._APPLY_PLAN_VERSION,
                    "planId": plan_id,
                    "planHash": plan_hash,
                    "applyCommitId": apply_commit_id,
                    "applied": True,
                    "verified": True,
                    "state": "committed",
                    "rootPath": root_path,
                    "leaseId": lease["leaseId"],
                    "executedOperations": executed,
                    "verification": verification,
                    "document": refreshed,
                    "elapsedMs": round((time.time() - started) * 1000.0, 3),
                    "idempotentReplay": False,
                }
                self._hocus_store_call(
                    lambda: self._graph_store.finish_plan_commit(
                        plan_commit_id=apply_commit_id,
                        state="committed",
                        result=result,
                        error=None,
                    )
                )
                try:
                    self._documents.commit_apply_result(reservation_id, result)
                except ApplyPlanError:
                    # The durable committed result is authoritative and supports restart replay.
                    self._logger.exception("could not cache committed apply result %s", apply_commit_id)
                self._documents.discard_apply_plan(plan_id, expected_hash=plan_hash)
                return result
            except Exception as exc:
                rolled_back = False
                rollback_error: str | None = None
                try:
                    undos = self._require_hou().undos
                    has_label_api = callable(getattr(undos, "undoLabels", None))
                    labels = tuple(undos.undoLabels()) if has_label_api else ()
                    if labels and labels[0] == undo_label:
                        undos.performUndo()
                    elif not has_label_api and callable(getattr(undos, "undo", None)):
                        # Test doubles and older hosts may expose a direct apply-owned undo method.
                        undos.undo()
                    self._monitor.mark_dirty("tool:document.apply_plan.rollback", scope_path=root_path)
                    restored = self._document_current_network_payload(root_path, force_sync=True)
                    rollback_verification = self._document_verification_diff_payload(
                        baseline_guard["document"], restored
                    )
                    rolled_back = self._document_diff_is_clean(rollback_verification)
                    if not rolled_back:
                        self._document_execute_apply_plan(
                            plan["inversePlan"], plan["targetDocument"], checkpoint=None
                        )
                        restored = self._document_current_network_payload(root_path, force_sync=True)
                        rollback_verification = self._document_verification_diff_payload(
                            baseline_guard["document"], restored
                        )
                        rolled_back = self._document_diff_is_clean(rollback_verification)
                except Exception as rollback_exc:
                    rollback_error = str(rollback_exc)
                state = "aborted" if rolled_back else "partial_or_unknown"
                durable_terminal = False
                durable_error: str | None = None
                failure = {
                    "stage": "document_apply",
                    "planId": plan_id,
                    "planHash": plan_hash,
                    "applyCommitId": apply_commit_id,
                    "applied": False,
                    "verified": False,
                    "state": state,
                    "rootPath": root_path,
                    "executedOperations": executed,
                    "verification": verification,
                    "rollbackVerification": rollback_verification,
                    "rolledBack": rolled_back,
                    "message": str(exc),
                    "diagnosticCode": "HOCUS755" if rolled_back else "HOCUS756",
                    "errorFamily": "cancelled" if context.is_cancelled() else "runtime",
                    "rollbackError": rollback_error,
                }
                try:
                    self._graph_store.finish_plan_commit(
                        plan_commit_id=apply_commit_id,
                        state=state,
                        result=failure,
                        error={"message": str(exc), "rollbackError": rollback_error},
                    )
                    durable_terminal = True
                except Exception as terminal_exc:
                    durable_error = str(terminal_exc)
                    failure["durableTerminalError"] = durable_error
                    failure["state"] = "partial_or_unknown"
                    failure["diagnosticCode"] = "HOCUS756"
                if not rolled_back or not durable_terminal:
                    self._hocus_quarantine_map()[root_path] = {
                        "planId": plan_id,
                        "applyCommitId": apply_commit_id,
                        "reason": durable_error or str(exc),
                        "createdAt": time.time(),
                    }
                cached = self._documents.apply_result(
                    idempotency_key, plan_id=plan_id, plan_hash=plan_hash
                )
                if cached is not None and cached.get("state") == "reserved":
                    try:
                        self._documents.commit_apply_result(reservation_id, failure)
                    except ApplyPlanError:
                        self._logger.exception("could not cache failed apply result %s", apply_commit_id)
                self._documents.discard_apply_plan(plan_id, expected_hash=plan_hash)
                diagnostic_code = str(failure["diagnosticCode"])
                self._hocus_fail(
                    diagnostic_code,
                    "Apply failed and rollback was verified." if rolled_back and durable_terminal else "Apply failed and the scope is in partial or unknown state.",
                    family=failure["errorFamily"],
                    retryable=False,
                    failure=failure,
                )

    def document_apply_plan(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._document_apply_plan_impl(arguments, context), context)
        return self._tool_response("Applied and verified the immutable HocusScript plan.", data)

from __future__ import annotations

import copy
import logging
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python3.11libs"))

from hocuspocus.core.jsonrpc import JsonRpcError
from hocuspocus.core.settings import ServerSettings
from hocuspocus.live.context import RequestContext
from hocuspocus.live.document_service import LiveDocumentService
from hocuspocus.live.graph_store import LiveGraphStore
from hocuspocus.live.graph_store import GraphStorePlanError
from hocuspocus.hocusscript.catalog import CategoryDefinition, FakeCatalogProvider
from test_hocusscript_document_lowering import _baseline, _bundle, _provider
from test_hocusscript_preview_operations import _Dispatcher, _PreviewOperations


class _Monitor:
    def mark_dirty(self, *_args, **_kwargs):
        return 1


class _Undos:
    def __init__(self, owner):
        self.owner = owner
        self.snapshot = None
        self.label = None

    @contextmanager
    def group(self, _label):
        self.snapshot = copy.deepcopy(self.owner.baseline)
        self.label = _label
        yield

    def undoLabels(self):
        return (self.label,) if self.label is not None else ()

    def performUndo(self):
        self.undo()

    def undo(self):
        if self.owner.fail_undo:
            raise RuntimeError("injected undo failure")
        if self.snapshot is None:
            raise RuntimeError("no apply-owned undo record")
        self.owner.baseline = copy.deepcopy(self.snapshot)
        self.snapshot = None
        self.label = None


class _Hou:
    def __init__(self, owner):
        self.undos = _Undos(owner)


class _PlanOperations(_PreviewOperations):
    def __init__(self, db_path: Path):
        self._dispatcher = _Dispatcher()
        self._settings = ServerSettings(enable_exec_tools=True)
        self._graph_store = LiveGraphStore(logging.getLogger("test.plan"), db_path)
        self._documents = LiveDocumentService(logging.getLogger("test.plan"), self._graph_store)
        self._monitor = _Monitor()
        self.baseline = copy.deepcopy(_baseline())
        self.catalog = _provider().catalog
        self._hou = _Hou(self)
        self.fail_execution = False
        self.fail_undo = False
        self.target_document = None

    def _require_hou(self):
        return self._hou

    def _document_plan_bundle_impl(self, arguments, context):
        result = super()._document_plan_bundle_impl(arguments, context)
        stored = self._documents.apply_plan(result["planId"], expected_hash=result["planHash"])
        self.target_document = copy.deepcopy(stored["targetDocument"])
        return result

    def _document_execute_apply_plan(self, plan, baseline, *, checkpoint=None):
        if checkpoint:
            checkpoint()
        self.baseline = copy.deepcopy(self.target_document)
        if self.fail_execution:
            self.fail_execution = False
            raise RuntimeError("injected execution failure")
        return [{"type": "fake_apply", "summary": copy.deepcopy(plan.get("summary", {}))}]


class HocusScriptGuardedPlanTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.operations = _PlanOperations(Path(self.temporary.name) / "graph.sqlite3")
        self.context = RequestContext(permissions=("edit_scene", "run_code"))

    def tearDown(self):
        self.temporary.cleanup()

    def _plan(self):
        return self.operations.document_plan_bundle(
            {"bundle": _bundle().to_dict(), "ttlSeconds": 300}, self.context
        )["structuredContent"]

    def _apply_arguments(self, planned, *, key="guarded-apply-0001"):
        return {
            "planId": planned["planId"],
            "planHash": planned["planHash"],
            "expectedDocumentRevision": planned["baseline"]["documentRevision"],
            "expectedLiveRevision": planned["baseline"]["liveRevision"],
            "confirmationToken": planned.get("confirmationToken"),
            "idempotencyKey": key,
        }

    def test_plan_is_durable_versioned_and_bound_to_all_guards(self):
        planned = self._plan()
        self.assertTrue(planned["readyForApply"])
        self.assertTrue(planned["confirmationRequired"])
        stored = self.operations._graph_store.load_immutable_plan(planned["planId"])["payload"]
        self.assertEqual(stored["planHash"], planned["planHash"])
        self.assertEqual(stored["sessionId"], self.operations._hocus_session_id())
        self.assertEqual(stored["baseline"]["digest"], stored["executionPlan"] and stored["baseline"]["digest"])
        self.assertEqual(stored["requiredCapabilities"], ["edit_scene", "run_code"])
        self.assertEqual(stored["projectUid"], "city")
        self.assertIn("inversePlan", stored)

    def test_apply_executes_stored_plan_and_idempotent_retry_replays(self):
        planned = self._plan()
        arguments = self._apply_arguments(planned)
        first = self.operations.document_apply_plan(arguments, self.context)["structuredContent"]
        second = self.operations.document_apply_plan(arguments, self.context)["structuredContent"]
        self.assertTrue(first["applied"] and first["verified"])
        self.assertFalse(first["idempotentReplay"])
        self.assertTrue(second["idempotentReplay"])
        commit = self.operations._graph_store.load_plan_commit(idempotency_key=arguments["idempotencyKey"])
        self.assertEqual(commit["state"], "committed")

    def test_tamper_revision_catalog_session_policy_and_confirmation_block_before_mutation(self):
        cases = (
            ("hash", lambda planned: self._apply_arguments({**planned, "planHash": "sha256:" + "0" * 64})),
            ("revision", lambda planned: {**self._apply_arguments(planned), "expectedDocumentRevision": 8}),
            ("confirmation", lambda planned: {**self._apply_arguments(planned), "confirmationToken": "wrong-token-value-that-is-long-enough"}),
        )
        for label, build in cases:
            with self.subTest(label=label):
                operations = _PlanOperations(Path(self.temporary.name) / f"{label}.sqlite3")
                planned = operations.document_plan_bundle({"bundle": _bundle().to_dict()}, self.context)["structuredContent"]
                before = copy.deepcopy(operations.baseline)
                with self.assertRaises(JsonRpcError):
                    operations.document_apply_plan(build(planned), self.context)
                self.assertEqual(operations.baseline, before)

        planned = self._plan()
        self.operations.catalog = FakeCatalogProvider.create(
            categories=(CategoryDefinition("Sop", "SOP", "sop"),), operators=()
        ).catalog
        with self.assertRaises(JsonRpcError):
            self.operations.document_apply_plan(self._apply_arguments(planned, key="catalog-drift-1"), self.context)

    def test_missing_run_code_is_policy_failure(self):
        with self.assertRaises(JsonRpcError) as captured:
            self.operations.document_plan_bundle(
                {"bundle": _bundle().to_dict()}, RequestContext(permissions=("edit_scene",))
            )
        self.assertEqual(captured.exception.family, "policy")

    def test_session_and_effective_policy_drift_block_before_mutation(self):
        for label in ("session", "policy"):
            with self.subTest(label=label):
                operations = _PlanOperations(Path(self.temporary.name) / f"drift-{label}.sqlite3")
                planned = operations.document_plan_bundle(
                    {"bundle": _bundle().to_dict()}, self.context
                )["structuredContent"]
                before = copy.deepcopy(operations.baseline)
                if label == "session":
                    operations._hocus_apply_session_id = str(uuid4())
                else:
                    operations._settings.policy_profile = "changed-after-planning"
                with self.assertRaises(JsonRpcError):
                    operations.document_apply_plan(
                        {
                            "planId": planned["planId"], "planHash": planned["planHash"],
                            "expectedDocumentRevision": 7, "expectedLiveRevision": 19,
                            "confirmationToken": planned.get("confirmationToken"),
                            "idempotencyKey": f"drift-{label}-key",
                        },
                        self.context,
                    )
                self.assertEqual(operations.baseline, before)

    def test_failure_uses_apply_owned_undo_and_returns_true_typed_failure(self):
        planned = self._plan()
        before = copy.deepcopy(self.operations.baseline)
        self.operations.fail_execution = True
        with self.assertRaises(JsonRpcError) as captured:
            self.operations.document_apply_plan(
                self._apply_arguments(planned, key="rollback-test-1"), self.context
            )
        self.assertEqual(captured.exception.data["diagnosticCode"], "HOCUS755")
        self.assertTrue(captured.exception.data["failure"]["rolledBack"])
        self.assertEqual(self.operations.baseline, before)
        commit = self.operations._graph_store.load_plan_commit(idempotency_key="rollback-test-1")
        self.assertEqual(commit["state"], "aborted")

    def test_failure_after_each_apply_lifecycle_stage_rolls_back(self):
        for stage in ("after_pending", "after_execute", "after_verify", "before_commit"):
            with self.subTest(stage=stage):
                operations = _PlanOperations(Path(self.temporary.name) / f"stage-{stage}.sqlite3")
                planned = operations.document_plan_bundle(
                    {"bundle": _bundle().to_dict()}, self.context
                )["structuredContent"]
                before = copy.deepcopy(operations.baseline)
                operations._hocus_apply_failure_injection = stage
                with self.assertRaises(JsonRpcError) as captured:
                    operations.document_apply_plan(
                        {
                            "planId": planned["planId"], "planHash": planned["planHash"],
                            "expectedDocumentRevision": 7, "expectedLiveRevision": 19,
                            "confirmationToken": planned.get("confirmationToken"),
                            "idempotencyKey": f"stage-failure-{stage}",
                        },
                        self.context,
                    )
                self.assertEqual(captured.exception.data["diagnosticCode"], "HOCUS755")
                self.assertEqual(operations.baseline, before)

    def test_legacy_document_apply_rejects_hocus_preview_document(self):
        planned = self._plan()
        stored = self.operations._graph_store.load_immutable_plan(planned["planId"])["payload"]
        with self.assertRaises(JsonRpcError) as captured:
            self.operations._document_apply_impl({"document": stored["targetDocument"]}, self.context)
        self.assertEqual(captured.exception.data["diagnosticCode"], "HOCUS758")
        stripped = copy.deepcopy(stored["targetDocument"])
        stripped["metadata"].pop("hocusPreview", None)
        with self.assertRaises(JsonRpcError) as stripped_failure:
            self.operations._document_apply_impl({"document": stripped}, self.context)
        self.assertEqual(stripped_failure.exception.data["diagnosticCode"], "HOCUS758")

    def test_durable_terminal_failure_rolls_back_and_quarantines_without_success_replay(self):
        planned = self._plan()
        original_finish = self.operations._graph_store.finish_plan_commit

        def fail_terminal_write(**_kwargs):
            raise GraphStorePlanError("injected durable terminal failure")

        self.operations._graph_store.finish_plan_commit = fail_terminal_write
        with self.assertRaises(JsonRpcError) as captured:
            self.operations.document_apply_plan(
                self._apply_arguments(planned, key="terminal-failure-key"), self.context
            )
        self.operations._graph_store.finish_plan_commit = original_finish
        self.assertEqual(captured.exception.data["diagnosticCode"], "HOCUS756")
        durable = self.operations._graph_store.load_plan_commit(idempotency_key="terminal-failure-key")
        self.assertEqual(durable["state"], "pending")
        cached = self.operations._documents.apply_result(
            "terminal-failure-key", plan_id=planned["planId"], plan_hash=planned["planHash"]
        )
        self.assertFalse(cached["result"]["applied"])
        self.assertEqual(
            self.operations.document_apply_quarantines({}, self.context)["structuredContent"]["count"], 1
        )

    def test_restart_replay_authenticates_submitted_plan_hash(self):
        planned = self._plan()
        arguments = self._apply_arguments(planned, key="restart-replay-key")
        self.operations.document_apply_plan(arguments, self.context)
        self.operations._documents = LiveDocumentService(
            logging.getLogger("test.plan.restart-replay"), self.operations._graph_store
        )
        with self.assertRaises(JsonRpcError) as captured:
            self.operations.document_apply_plan(
                {**arguments, "planHash": "sha256:" + "0" * 64}, self.context
            )
        self.assertEqual(captured.exception.data["diagnosticCode"], "HOCUS731")

    def test_reversibility_gate_blocks_opaque_network_delete_and_split_sop_output(self):
        base_execution = {
            "networkFamily": "sop", "protectedDeleteNodes": [], "replaceNodes": [],
            "deleteNodes": [], "outputGuard": {"sourceUid": None, "targetDisplayUids": []},
        }
        opaque_candidate = {"operations": [{
            "operationId": "op:000000", "sequence": 0, "action": "delete_node",
            "change": {"uid": "subnet", "isNetwork": True},
        }]}
        with self.assertRaises(JsonRpcError) as opaque:
            self.operations._hocus_validate_reversible_plan(opaque_candidate, base_execution)
        self.assertEqual(opaque.exception.data["diagnosticCode"], "HOCUS743")

        output_candidate = {"operations": [{
            "operationId": "op:000000", "sequence": 0, "action": "set_output", "change": {},
        }]}
        split_output = {
            **base_execution,
            "outputGuard": {"sourceUid": "node-b", "targetDisplayUids": ["node-a"]},
        }
        with self.assertRaises(JsonRpcError) as output:
            self.operations._hocus_validate_reversible_plan(output_candidate, split_output)
        self.assertEqual(output.exception.data["diagnosticCode"], "HOCUS761")

    def test_discard_is_a_durable_revocation_not_only_cache_eviction(self):
        planned = self._plan()
        discarded = self.operations.document_discard_plan(
            {"planId": planned["planId"], "planHash": planned["planHash"]}, self.context
        )["structuredContent"]
        self.assertTrue(discarded["discarded"])
        self.assertTrue(discarded["durableRevocation"])
        self.operations._documents = LiveDocumentService(
            logging.getLogger("test.plan.restart"), self.operations._graph_store
        )
        with self.assertRaises(JsonRpcError):
            self.operations.document_apply_plan(
                self._apply_arguments(planned, key="discarded-plan-retry"), self.context
            )

    def test_unverified_rollback_quarantines_until_explicit_state_classification(self):
        planned = self._plan()
        self.operations.fail_execution = True
        self.operations.fail_undo = True
        with self.assertRaises(JsonRpcError) as captured:
            self.operations.document_apply_plan(
                self._apply_arguments(planned, key="quarantine-test-1"), self.context
            )
        self.assertEqual(captured.exception.data["diagnosticCode"], "HOCUS756")
        quarantines = self.operations.document_apply_quarantines({}, self.context)["structuredContent"]
        self.assertEqual(quarantines["count"], 1)
        with self.assertRaises(JsonRpcError):
            self.operations._hocus_assert_not_quarantined("/obj/geo1/child")

        recovered = self.operations.document_recover_scope(
            {"rootPath": "/obj/geo1"}, self.context
        )["structuredContent"]
        self.assertEqual(recovered["recoveredCommits"][0]["classification"], "target")
        self.assertEqual(
            self.operations._graph_store.load_plan_commit(idempotency_key="quarantine-test-1")["state"],
            "committed",
        )
        self.assertEqual(
            self.operations.document_apply_quarantines({}, self.context)["structuredContent"]["count"], 0
        )


if __name__ == "__main__":
    unittest.main()

"""Exercise HS4 guarded plan/apply and rollback checkpoints in disposable SOP state.

Usage:
    hython scripts/smoke_hocusscript_apply.py
"""

from __future__ import annotations

import hashlib
import json
import logging
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON_LIBS = ROOT / "python3.11libs"
sys.path.insert(0, str(PYTHON_LIBS))

import hocuspocus
import hocuspocus.live
import hocuspocus.live.ops

for package, source in (
    (hocuspocus, PYTHON_LIBS / "hocuspocus"),
    (hocuspocus.live, PYTHON_LIBS / "hocuspocus" / "live"),
    (hocuspocus.live.ops, PYTHON_LIBS / "hocuspocus" / "live" / "ops"),
):
    source_text = str(source)
    if source_text not in package.__path__:
        package.__path__.insert(0, source_text)

# Houdini startup eagerly imports parts of an installed HocusPocus package.
# Reload every implementation surface exercised by this smoke from this checkout.
for module_name in tuple(sys.modules):
    if module_name.startswith("hocuspocus.hocusscript") or module_name in {
        "hocuspocus.live.document_service",
        "hocuspocus.live.graph_store",
        "hocuspocus.live.ops.document",
        "hocuspocus.live.ops.hocusscript",
        "hocuspocus.live.ops.node",
        "hocuspocus.live.ops.parm",
    }:
        sys.modules.pop(module_name, None)

import hou  # type: ignore

from hocuspocus.core.settings import ServerSettings
from hocuspocus.hocusscript import CompiledBundle, compile_source, resolve_graph
from hocuspocus.live.catalog_provider import LiveHoudiniCatalogProvider
from hocuspocus.live.context import OperationCancelledError, RequestContext
from hocuspocus.live.document_service import LiveDocumentService
from hocuspocus.live.graph_store import LiveGraphStore
from hocuspocus.live.ops.base import OperationBaseMixin
from hocuspocus.live.ops.document import DocumentOperationsMixin
from hocuspocus.live.ops.hocusscript import HocusScriptOperationsMixin
from hocuspocus.live.ops.node import NodeOperationsMixin
from hocuspocus.live.ops.parm import ParmOperationsMixin


def _digest(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


class _Dispatcher:
    @staticmethod
    def call(callback, _context):
        return callback()


class _Monitor:
    def mark_dirty(self, *_args, **_kwargs):
        return 1


class _ApplySmokeOperations(
    OperationBaseMixin,
    DocumentOperationsMixin,
    HocusScriptOperationsMixin,
    NodeOperationsMixin,
    ParmOperationsMixin,
):
    def __init__(self, root_path: str, catalog, db_path: Path):
        self._root_path = root_path
        self._catalog = catalog
        self._dispatcher = _Dispatcher()
        self._monitor = _Monitor()
        self._settings = ServerSettings(enable_exec_tools=False)
        self._graph_store = LiveGraphStore(logging.getLogger("hocus.apply.smoke"), db_path)
        self._documents = LiveDocumentService(logging.getLogger("hocus.apply.smoke"), self._graph_store)
        self._failure_checkpoint: int | None = None

    def _document_schema_path(self) -> Path:
        return ROOT / "docs" / "schemas" / "network-document-v1.schema.json"

    def _document_preview_live_catalog(self):
        return self._catalog

    def _graph_subgraph_payload(self, snapshot, root_path):
        if root_path != self._root_path:
            raise AssertionError(f"unexpected subgraph target {root_path}")
        return snapshot

    def _document_current_network_payload(self, root_path: str, **_kwargs):
        if root_path != self._root_path:
            raise AssertionError(f"unexpected apply target {root_path}")
        root = hou.node(root_path)
        if root is None:
            raise RuntimeError(f"missing apply root {root_path}")
        nodes = (root, *tuple(root.allSubChildren()))
        snapshot = {
            "revision": 1,
            "stats": {},
            "nodes": [self._node_summary(node) for node in nodes],
            "parms": [],
            "edges": [],
        }
        return self._document_live_network_payload(snapshot, root_path)

    def _document_execute_apply_plan(self, plan, baseline, *, checkpoint=None):
        failure_at = self._failure_checkpoint
        if failure_at is None:
            return super()._document_execute_apply_plan(plan, baseline, checkpoint=checkpoint)
        count = 0

        def injected_checkpoint():
            nonlocal count
            if checkpoint is not None:
                checkpoint()
            count += 1
            if count == failure_at:
                raise OperationCancelledError(f"injected cancellation checkpoint {failure_at}")

        return super()._document_execute_apply_plan(plan, baseline, checkpoint=injected_checkpoint)


def _checkpoint_count(plan: dict) -> int:
    count = sum(
        len(plan.get(key, []))
        for key in (
            "identityUpdates", "identityClears", "replaceNodes", "createNetworkContainers", "createNodes",
            "renameNodes", "reparentNodes", "connectionChanges", "parameterResets",
            "expressionUpdates", "codeBlobInstalls", "nodeUpdates", "deleteNodes",
        )
    )
    if plan.get("parameterAssignments"):
        count += 1
    if plan.get("rootNodeGuard"):
        count += 1
    if plan.get("outputChange"):
        count += 1
    return count + 1  # executor's final pre-return cancellation checkpoint


def main() -> int:
    success_only = "--success-only" in sys.argv[1:]
    target_path = "/obj/hocus_apply_smoke"
    if hou.node(target_path) is not None:
        raise RuntimeError(f"Refusing to reuse or delete existing node {target_path}")
    root = hou.node("/obj").createNode("geo", node_name="hocus_apply_smoke")
    temporary = tempfile.TemporaryDirectory()
    try:
        for child in tuple(root.children()):
            child.destroy()
        live = root.createNode("null", node_name="live")
        artist = root.createNode("null", node_name="artist")
        artist.setInput(0, live, 0)
        artist.setDisplayFlag(True)
        catalog = LiveHoudiniCatalogProvider(hou).get_catalog()
        operations = _ApplySmokeOperations(target_path, catalog, Path(temporary.name) / "graph.sqlite3")
        operations._document_stamp_live_node_metadata(live.path(), {
            "uid": "live-apply-external",
            "metadata": {"hocus": {
                "version": 1, "entityKind": "node", "projectUid": "live-apply",
                "sourceUri": "hocus-project://live-apply/previous.hocus",
                "sourceDigest": _digest("previous-source"), "bundleDigest": _digest("previous-bundle"),
                "compilerVersion": "0.2.0", "languageVersion": "0.1", "graphName": "previous",
                "symbol": "live", "ownership": "studio.apply", "jsonPointer": "/nodes/0",
                "span": {
                    "sourceUri": "hocus-project://live-apply/previous.hocus",
                    "start": {"line": 1, "column": 1, "offset": 0},
                    "end": {"line": 1, "column": 2, "offset": 1},
                },
            }},
        })
        source = f'''hocus 0.1;
graph guarded_apply {{
  target "{target_path}"; category Sop; mode merge; ownership "studio.apply";
  adopt live = "{live.path()}";
  node output: "null" {{ input[0] = live; }}
  display = output; render = output; output = output; layout = auto;
}}
'''
        source_uri = "hocus-project://live-apply/smoke.hocus"
        result = compile_source(source, "smoke.hocus", source_uri=source_uri)
        if not result.valid or result.graph_spec is None:
            raise RuntimeError(f"compile failed: {result.to_dict()['diagnostics']}")
        semantic = resolve_graph(result.graph_spec, catalog)
        if not semantic.valid:
            raise RuntimeError(f"semantic resolution failed: {semantic.to_dict()!r}")
        result.semantic_result = semantic
        result.source_kind = "project_file"
        result.project_uid = "live-apply"
        result.project_manifest_digest = _digest("live-apply-manifest")
        result.project_lock_digest = _digest("live-apply-lock")
        result.catalog_fingerprint = catalog.fingerprint
        result.catalog_content_digest = _digest(catalog.to_json())
        bundle = CompiledBundle.from_result(result).to_dict()
        context = RequestContext(permissions=("edit_scene",))
        original = operations._document_current_network_payload(target_path, force_sync=True)

        sample = operations.document_plan_bundle({"bundle": bundle}, context)["structuredContent"]
        sample_plan = operations._documents.apply_plan(sample["planId"], expected_hash=sample["planHash"])
        checkpoint_count = _checkpoint_count(sample_plan["executionPlan"])
        operations.document_discard_plan({"planId": sample["planId"], "planHash": sample["planHash"]}, context)

        for checkpoint in (() if success_only else range(1, checkpoint_count + 1)):
            planned = operations.document_plan_bundle({"bundle": bundle}, context)["structuredContent"]
            operations._failure_checkpoint = checkpoint
            try:
                operations.document_apply_plan({
                    "planId": planned["planId"], "planHash": planned["planHash"],
                    "expectedDocumentRevision": original["documentRevision"],
                    "expectedLiveRevision": original["lastSyncedLiveRevision"],
                    "confirmationToken": planned.get("confirmationToken"),
                    "idempotencyKey": f"live-rollback-{checkpoint}",
                }, context)
            except Exception as exc:
                data = getattr(exc, "data", {})
                if data.get("diagnosticCode") != "HOCUS755":
                    raise
            else:
                raise RuntimeError(f"checkpoint {checkpoint} did not interrupt apply")
            finally:
                operations._failure_checkpoint = None
            restored = operations._document_current_network_payload(target_path, force_sync=True)
            if operations._hocus_canonical_digest(restored) != operations._hocus_canonical_digest(original):
                raise RuntimeError(f"rollback checkpoint {checkpoint} did not restore the SOP network")

        apply_stages = ("after_pending", "after_execute", "after_verify", "before_commit")
        for stage in (() if success_only else apply_stages):
            planned = operations.document_plan_bundle({"bundle": bundle}, context)["structuredContent"]
            operations._hocus_apply_failure_injection = stage
            try:
                operations.document_apply_plan({
                    "planId": planned["planId"], "planHash": planned["planHash"],
                    "expectedDocumentRevision": original["documentRevision"],
                    "expectedLiveRevision": original["lastSyncedLiveRevision"],
                    "confirmationToken": planned.get("confirmationToken"),
                    "idempotencyKey": f"live-stage-{stage}",
                }, context)
            except Exception as exc:
                data = getattr(exc, "data", {})
                if data.get("diagnosticCode") != "HOCUS755":
                    raise
            else:
                raise RuntimeError(f"apply stage {stage} did not interrupt apply")
            finally:
                operations._hocus_apply_failure_injection = None
            restored = operations._document_current_network_payload(target_path, force_sync=True)
            if operations._hocus_canonical_digest(restored) != operations._hocus_canonical_digest(original):
                raise RuntimeError(f"apply-stage rollback {stage} did not restore the SOP network")

        planned = operations.document_plan_bundle({"bundle": bundle}, context)["structuredContent"]
        arguments = {
            "planId": planned["planId"], "planHash": planned["planHash"],
            "expectedDocumentRevision": original["documentRevision"],
            "expectedLiveRevision": original["lastSyncedLiveRevision"],
            "confirmationToken": planned.get("confirmationToken"),
            "idempotencyKey": "live-success-final",
        }
        try:
            applied = operations.document_apply_plan(arguments, context)["structuredContent"]
        except Exception as exc:
            failure = getattr(exc, "data", {}).get("failure", {})
            print("HS4_VERIFY_FAILURE=" + json.dumps(failure.get("verification"), sort_keys=True), flush=True)
            raise
        replay = operations.document_apply_plan(arguments, context)["structuredContent"]
        if not applied["applied"] or not applied["verified"] or not replay["idempotentReplay"]:
            raise RuntimeError(f"guarded apply/replay gate failed: {applied!r} {replay!r}")
        print(
            "HS4 live guarded apply smoke passed",
            f"catalog={catalog.fingerprint}",
            f"checkpoints={checkpoint_count}",
            f"applyStages={len(apply_stages)}",
            f"plan={planned['planHash']}",
            f"verified=true rollbackMatrix={'skipped' if success_only else 'true'} idempotentReplay=true",
        )
        return 0
    finally:
        temporary.cleanup()
        if root is not None:
            root.destroy()


if __name__ == "__main__":
    raise SystemExit(main())

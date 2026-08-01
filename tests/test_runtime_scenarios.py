from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import logging
import sqlite3
import sys
import tempfile
import time
import types
import unittest
from contextlib import closing, redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python3.11libs"))
from hocuspocus.core.mcp_types import ResourceRegistry, ToolRegistry
from hocuspocus.core.jsonrpc import JsonRpcError
from hocuspocus.hocusscript.document_lowering import _source_map_from_entity
from hocuspocus.live.catalog_provider import LiveHoudiniCatalogProvider
from hocuspocus.live.context import RequestContext
from hocuspocus.live.document_service import ApplyPlanError, LiveDocumentService
from hocuspocus.live.graph_store import GraphStorePlanError, LiveGraphStore
from hocuspocus.live.operations import LiveOperations
from hocuspocus.live.ops.base import OperationBaseMixin
from hocuspocus.live.ops.document import DocumentOperationsMixin
from hocuspocus.live.ops.document_apply_managed import identity_update_mismatches
from hocuspocus.live.ops.hocusscript_recovery import recovered_apply_result
from tests.hocusscript_hs7_resource_helpers import assert_hs7_fidelity_resource
from tests.runtime_checkout_delivery import assert_checkout_delivery
from tests.runtime_catalog_fixtures import CatalogHou
from tests.runtime_hda_capabilities import assert_hda_and_capability_contract
from tests.runtime_h5_provenance import (
    assert_managed_provenance_round_trip,
    assert_plan_persistence_failure_mapping,
)
from tests.runtime_object_bootstrap import assert_object_geometry_bootstrap
from tests.runtime_node_type_discovery import assert_node_type_discovery_contract
from tests.runtime_mutation_integrity import assert_mutation_integrity_contract
from tests.runtime_monitor_revision import assert_monitor_revision_contract
class _InlineDispatcher:
    @staticmethod
    def call(callback, _context):
        return callback()


class _DocumentTools(OperationBaseMixin, DocumentOperationsMixin):
    def __init__(self):
        self._dispatcher = _InlineDispatcher()

class _UserDataNode:
    def __init__(self):
        self.data = {"artist.note": "keep"}

    def userData(self, key):
        return self.data.get(key)

    def setUserData(self, key, value):
        self.data[key] = value

    def destroyUserData(self, key):
        self.data.pop(key, None)


def _h5_span(source_uri: str) -> dict:
    return {
        "sourceUri": source_uri,
        "start": {"line": 1, "column": 1, "offset": 0},
        "end": {"line": 1, "column": 2, "offset": 1},
    }


def _h5_stack_id(domain: str, frames: list[dict]) -> str:
    encoded = json.dumps(
        {"domain": domain, "frames": frames},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _h5_expansion_provenance() -> dict:
    module_uri = "hocus-project://city/module.hocus"
    source_uri = "hocus-project://city/main.hocus"
    module_frames = [{
        "moduleUri": module_uri,
        "sourceDigest": "sha256:" + "6" * 64,
        "moduleName": "Module",
        "instanceSymbol": "module",
        "instanceIdPath": ["module"],
        "importSpan": None,
        "useSpan": _h5_span(source_uri),
    }]
    control_frames = [{
        "kind": "if",
        "controlSymbol": "choice",
        "durableSeed": "choice",
        "declarationSpan": _h5_span(source_uri),
        "selectionSpan": _h5_span(source_uri),
        "yieldSpans": [_h5_span(source_uri)],
        "branch": "then",
    }]
    return {
        "format": "document-expansion-provenance-v0.1",
        "moduleStacks": [{
            "stackId": _h5_stack_id(
                "hocus-expansion-stack-v1", module_frames,
            ),
            "frames": module_frames,
        }],
        "controlStacks": [{
            "controlStackId": _h5_stack_id(
                "hocus-control-stack-v1", control_frames,
            ),
            "frames": control_frames,
        }],
    }


def _h5_node_provenance() -> dict:
    source_uri = "hocus-project://city/main.hocus"
    span = _h5_span(source_uri)
    expansion = _h5_expansion_provenance()
    return {
        "version": 1,
        "entityKind": "node",
        "projectUid": "city",
        "sourceUri": source_uri,
        "sourceDigest": "sha256:" + "3" * 64,
        "bundleDigest": "sha256:" + "4" * 64,
        "compilerVersion": "0.5.0",
        "languageVersion": "0.3",
        "graphName": "asset",
        "symbol": "node",
        "ownership": "studio.asset",
        "jsonPointer": "/nodes/0",
        "span": span,
        "originId": "sha256:" + "5" * 64,
        "originKind": "definition",
        "relatedOrigins": [{"role": "definition", "span": copy.deepcopy(span)}],
        "stackId": expansion["moduleStacks"][0]["stackId"],
        "controlStackId": expansion["controlStacks"][0]["controlStackId"],
    }


def _network_document() -> dict:
    return {
        "$schema": "hocuspocus://schemas/network-document/v1",
        "kind": "network_document",
        "documentId": "network:/obj/geo1",
        "documentRevision": 1,
        "rootPath": "/obj/geo1",
        "category": "Object",
        "nodes": [
            {
                "uid": "root",
                "name": "geo1",
                "typeName": "geo",
                "category": "Object",
                "path": "/obj/geo1",
                "parentPath": "/obj",
                "isNetwork": True,
                "position": [0.0, 0.0],
                "flags": {
                    "display": False,
                    "render": False,
                    "bypass": False,
                    "template": False,
                },
                "metadata": {},
            }
        ],
        "edges": [],
        "parameterBindings": [],
        "codeBlobs": [],
        "diagnostics": [],
    }


def _apply_plan(marker: str = "a") -> dict:
    plan = {
        "kind": "hocus_apply_plan",
        "planVersion": "1.0",
        "sessionId": "session:test",
        "scope": "/obj/geo1",
        "operations": [{"sequence": 0, "action": "create_node", "marker": marker}],
    }
    encoded = json.dumps(plan, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    plan["planHash"] = f"sha256:{hashlib.sha256(encoded.encode()).hexdigest()}"
    return plan


def _persistent_plan() -> dict:
    plan = {
        "kind": "hocus_apply_plan",
        "planVersion": "1.0",
        "planId": "plan-1",
        "sessionId": "session-1",
        "createdAt": 100.0,
        "expiresAt": 200.0,
        "sourceDigest": "sha256:source",
        "catalogFingerprint": "sha256:catalog",
        "catalogContentDigest": "sha256:catalog-content",
        "ownership": "studio.terrain",
        "rootPath": "/obj/geo1",
        "baseline": {
            "documentId": "network:/obj/geo1",
            "documentRevision": 4,
            "liveRevision": 9,
        },
        "requiredCapabilities": ["edit_scene"],
        "executionPlan": {
            "operations": [
                {"operationId": "op:000000", "action": "create_node", "label": "create"}
            ]
        },
    }
    encoded = json.dumps(plan, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    plan["planHash"] = f"sha256:{hashlib.sha256(encoded.encode()).hexdigest()}"
    return plan


class _ExportSnapshot:
    operators = (object(),)
    fingerprint = "sha256:" + "a" * 64

    def to_json(self):
        return json.dumps({"catalogFingerprint": self.fingerprint})


class _ExportProvider:
    def __init__(self, _hou_module):
        pass

    def get_catalog(self):
        return _ExportSnapshot()


def _assert_managed_apply_repairs(test, tools, baseline, metadata_plan):
    target = copy.deepcopy(baseline)
    for document in (baseline, target):
        document["metadata"] = {
            "hocusPreview": {"ownership": "studio.asset"}
        }
    baseline["parameterBindings"] = [{
        "uid": "binding:root:sx",
        "nodeUid": "root",
        "parmName": "sx",
        "valueMode": "literal",
        "value": 2,
        "metadata": {},
    }]
    target["parameterBindings"] = []
    baseline["nodes"][0]["metadata"]["hocus"]["managedFields"]["inputs"] = [3]
    managed_edge = {
        "uid": "edge:data:root:3",
        "kind": "data",
        "from": {"nodeUid": "root", "portIndex": 0},
        "to": {"nodeUid": "root", "portIndex": 3},
        "metadata": {"connectionOrder": 3},
    }
    artist_edge = copy.deepcopy(managed_edge)
    artist_edge["uid"] = "edge:data:root:5"
    artist_edge["to"]["portIndex"] = 5
    artist_edge["metadata"]["connectionOrder"] = 5
    baseline["edges"] = [managed_edge, artist_edge]
    target["edges"] = [artist_edge]
    plan = tools._document_build_apply_plan(
        baseline, target, mode="reconcile"
    )
    test.assertEqual(
        [item["parmName"] for item in plan["parameterResets"]], ["sx"]
    )
    test.assertEqual(
        [(item["inputIndex"], item["sourceUid"])
         for item in plan["connectionChanges"]],
        [(3, None)],
    )

    strict_reset_calls = []
    parm = SimpleNamespace(default=False)
    parm.isAtDefault = lambda **arguments: (
        strict_reset_calls.append(arguments) or parm.default
    )
    tools._parm_revert_to_permanent_default_impl = lambda _arguments: setattr(
        parm, "default", True
    )
    tools._require_parm_by_path = lambda _path: parm
    executed = []
    tools._document_execute_bindings(
        plan, tools._document_apply_state(baseline), executed, lambda: None
    )
    test.assertTrue(parm.default)
    test.assertTrue(executed[0]["verifiedDefault"])
    test.assertEqual(
        strict_reset_calls,
        [{
            "compare_temporary_defaults": False,
            "compare_expressions": True,
        }],
    )

    flag_updates = []
    tools._node_set_flags_impl = lambda arguments: flag_updates.append(arguments)
    executed = []
    tools._document_execute_finalizers(
        {"outputChange": {
            "rootPath": "/obj/geo1",
            "beforeSourceUid": "root",
            "sourceUid": None,
        }},
        tools._document_apply_state(baseline),
        executed,
        lambda: None,
    )
    test.assertEqual(flag_updates, [{"path": "/obj/geo1", "display": False}])
    test.assertEqual(executed[0]["previousSourcePath"], "/obj/geo1")

    candidate = {"operations": [{
        "action": "update_node_provenance",
        "entityUid": "root",
    }]}
    test.assertEqual(
        identity_update_mismatches(candidate, metadata_plan, baseline), []
    )
    test.assertTrue(
        identity_update_mismatches(
            {"operations": []}, metadata_plan, baseline
        )
    )
    transferred = copy.deepcopy(metadata_plan)
    transferred["identityUpdates"][0]["metadata"]["hocus"]["ownership"] = (
        "studio.other"
    )
    test.assertEqual(
        identity_update_mismatches(
            candidate, transferred, baseline
        )[0]["reason"],
        "identity_transition",
    )
    artist_baseline = copy.deepcopy(baseline)
    artist_baseline["nodes"][0]["metadata"].pop("hocus")
    adopt = {"operations": [{
        "action": "adopt_node",
        "entityUid": "root",
    }]}
    test.assertEqual(
        identity_update_mismatches(
            adopt, metadata_plan, artist_baseline
        ),
        [],
    )
    test.assertTrue(
        identity_update_mismatches(
            candidate, metadata_plan, artist_baseline
        )
    )


class RuntimeScenarios(unittest.TestCase):
    def test_document_validation_accepts_a_network_and_rejects_an_ambiguous_edge(self):
        assert_hda_and_capability_contract(self)
        tools = _DocumentTools()
        assert_mutation_integrity_contract(self, _DocumentTools(), _network_document)
        valid = tools.document_validate(
            {"document": _network_document()}, RequestContext(permissions=("edit_scene",)),
        )
        self.assertTrue(valid["structuredContent"]["valid"])
        self.assertTrue(valid["structuredContent"]["capabilityReady"])
        code_document = _network_document()
        code_document["parameterBindings"] = [{"valueMode": "code_reference"}]
        code_preflight = tools.document_validate(
            {"document": code_document}, RequestContext(permissions=("edit_scene",)),
        )["structuredContent"]
        self.assertEqual(
            code_preflight["requiredCapabilities"], ["edit_scene", "run_code"],
        )
        self.assertEqual(code_preflight["missingCapabilities"], ["run_code"])

        invalid_document = _network_document()
        invalid_document["edges"] = [
            {
                "uid": "edge:a",
                "kind": "data",
                "from": {"nodeUid": "root"},
                "to": {"nodeUid": "root", "portIndex": 0},
            }
        ]
        invalid = tools.document_validate({"document": invalid_document}, RequestContext())
        self.assertFalse(invalid["structuredContent"]["valid"])
        self.assertIn(
            "edge.port_index.missing",
            {item["code"] for item in invalid["structuredContent"]["diagnostics"]},
        )

        root = _UserDataNode()
        tools._require_node_by_path = lambda _path: root
        tools._require_hou = lambda: SimpleNamespace(node=lambda _path: root)
        expansion = _h5_expansion_provenance()
        baseline, target = _network_document(), _network_document()
        baseline["metadata"] = {"artist": "kept"}
        target["metadata"] = {
            "artist": "kept",
            "hocusExpansion": copy.deepcopy(expansion),
        }
        plan = tools._document_build_apply_plan(baseline, target, mode="merge")
        self.assertEqual(plan["summary"]["rootProvenanceChangeCount"], 1)
        executed = tools._document_execute_apply_plan(plan, baseline)
        self.assertEqual(executed[-1]["type"], "stamp_root_expansion_provenance")
        self.assertEqual(
            tools._document_live_expansion_provenance("/obj/geo1"), expansion
        )
        self.assertEqual(root.userData("artist.note"), "keep")
        tools._graph_subgraph_payload = lambda _snapshot, _root: {
            "nodes": [{
                "path": "/obj/geo1",
                "name": "geo1",
                "typeName": "geo",
                "category": "Object",
                "parentPath": "/obj",
                "isNetwork": True,
                "position": [0.0, 0.0],
                "flags": {},
            }],
            "parms": [],
            "stats": {},
        }
        canonical = tools._document_live_network_payload(
            {"revision": 7}, "/obj/geo1"
        )
        self.assertEqual(canonical["metadata"]["hocusExpansion"], expansion)

        inverse = tools._document_build_apply_plan(target, baseline, mode="merge")
        tools._document_execute_apply_plan(inverse, target)
        self.assertIsNone(
            root.userData(tools._DOCUMENT_EXPANSION_PROVENANCE_KEY)
        )
        self.assertEqual(root.userData("artist.note"), "keep")

        tools._document_stamp_live_expansion_provenance("/obj/geo1", expansion)
        root.setUserData(
            tools._DOCUMENT_EXPANSION_PROVENANCE_KEY,
            root.userData(tools._DOCUMENT_EXPANSION_PROVENANCE_KEY) + " ",
        )
        self.assertIsNone(
            tools._document_live_expansion_provenance("/obj/geo1")
        )
        malformed_raw = json.dumps(
            {"version": 1, "hocusExpansion": {"bad": True}}
        )
        root.setUserData(tools._DOCUMENT_EXPANSION_PROVENANCE_KEY, malformed_raw)
        root.setUserData(
            tools._DOCUMENT_EXPANSION_PROVENANCE_DIGEST_KEY,
            hashlib.sha256(malformed_raw.encode()).hexdigest(),
        )
        self.assertIsNone(
            tools._document_live_expansion_provenance("/obj/geo1")
        )
        oversized = "x" * (
            tools._MAX_DOCUMENT_EXPANSION_PROVENANCE_BYTES + 1
        )
        root.setUserData(tools._DOCUMENT_EXPANSION_PROVENANCE_KEY, oversized)
        root.setUserData(
            tools._DOCUMENT_EXPANSION_PROVENANCE_DIGEST_KEY,
            hashlib.sha256(oversized.encode()).hexdigest(),
        )
        self.assertIsNone(
            tools._document_live_expansion_provenance("/obj/geo1")
        )
        malformed = copy.deepcopy(target)
        malformed["metadata"]["hocusExpansion"]["moduleStacks"] = [{}]
        with self.assertRaises(JsonRpcError):
            tools._document_build_apply_plan(baseline, malformed, mode="merge")

        verification = tools._document_verification_diff_payload(
            target, baseline
        )
        self.assertEqual(
            verification["summary"]["changedDocumentMetadataCount"], 1
        )
        self.assertFalse(tools._document_diff_is_clean(verification))

        hocus = _h5_node_provenance()
        malformed_hocus = copy.deepcopy(hocus)
        malformed_hocus.pop("controlStackId")
        with self.assertRaises(JsonRpcError):
            tools._document_stamp_live_node_metadata(
                "/obj/geo1",
                {"uid": "root", "metadata": {"hocus": malformed_hocus}},
            )
        tools._document_stamp_live_node_metadata(
            "/obj/geo1", {"uid": "root", "metadata": {"hocus": hocus}}
        )
        restored = tools._document_live_node_provenance(
            root, "root", "persistent_user_data"
        )
        for field in (
            "originId", "originKind", "relatedOrigins", "stackId",
            "controlStackId",
        ):
            self.assertEqual(restored[field], hocus[field])
            self.assertEqual(
                _source_map_from_entity({"metadata": {"hocus": hocus}})[field],
                hocus[field],
            )

        managed_baseline = _network_document()
        managed_target = copy.deepcopy(managed_baseline)
        managed_hocus = _h5_node_provenance()
        managed_hocus["managedFields"] = {
            "type": True,
            "inputs": [],
            "parameters": ["sx"],
            "flags": {},
            "nodeUid": "root",
        }
        managed_baseline["nodes"][0]["metadata"] = {
            "identityMode": "persistent_user_data",
            "hocus": copy.deepcopy(managed_hocus),
        }
        managed_target["nodes"][0]["metadata"] = copy.deepcopy(
            managed_baseline["nodes"][0]["metadata"]
        )
        managed_target["nodes"][0]["metadata"]["hocus"]["sourceDigest"] = (
            "sha256:" + "6" * 64
        )
        metadata_plan = tools._document_build_apply_plan(
            managed_baseline, managed_target, mode="merge"
        )
        self.assertEqual(
            [update["uid"] for update in metadata_plan["identityUpdates"]],
            ["root"],
        )
        managed_live = copy.deepcopy(managed_target)
        managed_live["nodes"][0]["metadata"]["hocus"]["managedFields"][
            "parameters"
        ] = []
        managed_diff = tools._document_verification_diff_payload(
            managed_target, managed_live
        )
        self.assertFalse(tools._document_diff_is_clean(managed_diff))

        _assert_managed_apply_repairs(
            self, tools, copy.deepcopy(managed_baseline), metadata_plan
        )
        assert_managed_provenance_round_trip(
            self,
            _DocumentTools(),
            _UserDataNode(),
            _UserDataNode(),
            _h5_node_provenance(),
            _h5_expansion_provenance(),
            _network_document,
        )

        unmanaged_position = _network_document()
        unmanaged_position["nodes"][0]["position"] = None
        auto_positioned = copy.deepcopy(unmanaged_position)
        auto_positioned["nodes"][0]["position"] = [3.25, 0.0]
        self.assertTrue(tools._document_diff_is_clean(
            tools._document_verification_diff_payload(
                unmanaged_position, auto_positioned
            )
        ))
        authored_position = copy.deepcopy(unmanaged_position)
        authored_position["nodes"][0]["position"] = [1.0, 2.0]
        self.assertFalse(tools._document_diff_is_clean(
            tools._document_verification_diff_payload(
                authored_position, auto_positioned
            )
        ))

    def test_document_artifacts_and_apply_plans_are_content_addressed_and_detached(self):
        service = LiveDocumentService(logging.getLogger("test.documents"))
        assert_checkout_delivery(self, _DocumentTools(), _network_document())
        assert_object_geometry_bootstrap(self)
        preview_payload = {
            "kind": "hocus_document_preview",
            "document": {"nodes": [{"uid": "node:a"}]},
        }
        preview = service.store_preview_artifact(preview_payload)
        self.assertEqual(preview, service.store_preview_artifact(preview_payload))
        preview_payload["document"]["nodes"].clear()
        self.assertEqual(len(service.preview_artifact(preview["previewId"])["document"]["nodes"]), 1)

        plan_payload = _apply_plan()
        plan = service.store_apply_plan(plan_payload)
        plan_payload["operations"].clear()
        loaded = service.apply_plan(plan["planId"], expected_hash=plan["planHash"])
        self.assertEqual(len(loaded["operations"]), 1)

        tools, resources = ToolRegistry(), ResourceRegistry()
        LiveOperations.__new__(LiveOperations).register(tools, resources)
        for operation in ("scene.undo", "scene.redo"):
            definition = tools.get(operation)
            self.assertIsNotNone(definition)
            self.assertEqual(
                definition.input_schema["properties"]["expected_label"]["maxLength"],
                512,
            )
        self.assertIsNotNone(tools.get("hda.set_instance_parms"))
        self.assertEqual(
            tools.get("hda.promote_parm").required_capabilities,
            ("edit_scene", "write_files"),
        )
        self.assertEqual(
            tools.get("hda.set_definition_version").required_capabilities,
            ("edit_scene", "write_files"),
        )
        hda_schema = tools.get("hda.promote_parm").input_schema
        self.assertTrue(hda_schema["properties"]["preserve_source_value"]["default"])
        for tool_name in ("document.validate", "document.diff", "document.apply"):
            document_schema = tools.get(tool_name).input_schema["properties"]["document"]
            self.assertEqual(document_schema["x-schemaResources"], [
                "hocuspocus://schemas/network-document/v1",
                "hocuspocus://schemas/network-document/v2",
            ])
        for version in ("v1", "v2"):
            alias = resources.get(
                f"houdini://documents/schema/network-document/{version}",
            )
            canonical = resources.get(
                f"hocuspocus://schemas/network-document/{version}",
            )
            self.assertIsNotNone(canonical)
            alias_text = alias.reader(RequestContext())["contents"][0]["text"]
            canonical_text = canonical.reader(RequestContext())["contents"][0]["text"]
            self.assertEqual(canonical_text, alias_text)
        assert_node_type_discovery_contract(self, tools)
        assert_hs7_fidelity_resource(self, resources)
        control_schemas = {
            "houdini://documents/schema/graph-spec/v0.4": (
                "hocuspocus://schemas/graph-spec/v0.4"
            ),
            "houdini://documents/schema/expansion-map/v2": (
                "hocuspocus://schemas/expansion-map/v2"
            ),
            "houdini://documents/schema/resolved-module-set/v2": (
                "hocuspocus://schemas/resolved-module-set/v2"
            ),
            "houdini://documents/schema/compiled-bundle/v0.4": (
                "hocuspocus://schemas/compiled-bundle/v0.4"
            ),
            "houdini://documents/schema/preview-bundle-input/v1": (
                "hocuspocus://schemas/document-preview-bundle-input/v1"
            ),
            "houdini://documents/schema/plan-bundle-input/v1": (
                "hocuspocus://schemas/document-plan-bundle-input/v1"
            ),
            "houdini://documents/schema/apply-plan/v1": (
                "hocuspocus://schemas/hocus-apply-plan/v1"
            ),
        }
        control_schemas.update({"houdini://documents/schema/graph-spec/v0.5": "hocuspocus://schemas/graph-spec/v0.5", "houdini://documents/schema/expansion-map/v3": "hocuspocus://schemas/expansion-map/v3", "houdini://documents/schema/resolved-module-set/v3": "hocuspocus://schemas/resolved-module-set/v3", "houdini://documents/schema/compiled-bundle/v0.5": "hocuspocus://schemas/compiled-bundle/v0.5"})
        for uri, schema_id in control_schemas.items():
            definition = resources.get(uri)
            self.assertIsNotNone(definition)
            self.assertTrue(definition.payload_summary)
            self.assertTrue(definition.examples)
            content = definition.reader(RequestContext())["contents"][0]
            self.assertEqual(content["uri"], uri)
            payload = json.loads(content["text"])
            self.assertEqual(payload["$id"], schema_id)
            if uri.endswith(("preview-bundle-input/v1", "plan-bundle-input/v1")):
                self.assertEqual(
                    payload["properties"]["bundle"]["properties"]["bundleVersion"]["enum"],
                    ["0.2", "0.3", "0.4", "0.5"],
                )
            if uri.endswith("apply-plan/v1"):
                self.assertEqual(
                    payload["properties"]["bundleVersion"]["enum"],
                    ["0.3", "0.4", "0.5"],
                )
                self.assertIn("resolverPolicyDigest", payload["properties"])
        assert_plan_persistence_failure_mapping(
            self, LiveOperations.__new__(LiveOperations), service,
            _persistent_plan(), _network_document,
        )

    def test_document_apply_replays_results_and_excludes_overlapping_writes(self):
        service = LiveDocumentService(logging.getLogger("test.documents"))
        plan = service.store_apply_plan(_apply_plan())
        reserved = service.reserve_apply_result(
            "request-1", plan_id=plan["planId"], plan_hash=plan["planHash"]
        )
        service.commit_apply_result(reserved["reservationId"], {"status": "applied"})
        replay = service.reserve_apply_result(
            "request-1", plan_id=plan["planId"], plan_hash=plan["planHash"]
        )
        self.assertEqual(replay["state"], "committed")

        recovery_plan = {
            "planVersion": "1.0",
            "planId": plan["planId"],
            "planHash": plan["planHash"],
            "rootPath": "/obj/geo1",
        }
        recovered = recovered_apply_result(
            plan=recovery_plan,
            plan_commit_id="commit:recovered",
            document=_network_document(),
            classification="target",
            verification={"summary": {"totalChangeCount": 0}},
        )
        service.recover_apply_result(
            "request-2",
            plan_id=plan["planId"],
            plan_hash=plan["planHash"],
            result=recovered,
        )
        recovered_replay = service.apply_result(
            "request-2", plan_id=plan["planId"], plan_hash=plan["planHash"]
        )
        self.assertTrue(recovered_replay["result"]["applied"])
        self.assertTrue(recovered_replay["result"]["verified"])
        self.assertTrue(recovered_replay["result"]["recovered"])
        baseline_recovery = recovered_apply_result(
            plan=recovery_plan,
            plan_commit_id="commit:baseline",
            document=_network_document(),
            classification="baseline",
            verification={"summary": {"totalChangeCount": 0}},
        )
        self.assertEqual(baseline_recovery["diagnosticCode"], "HOCUS755")
        self.assertFalse(baseline_recovery["applied"])

        lease = service.acquire_scope_write_lease("/obj/geo1", holder_id="apply:a")
        with self.assertRaisesRegex(ApplyPlanError, "overlaps"):
            service.acquire_scope_write_lease("/obj/geo1/subnet")
        self.assertTrue(service.release_scope_write_lease("/obj/geo1", lease["leaseId"]))

    def test_catalog_export_writes_only_to_the_project_manifest_destination(self):
        script = ROOT / "scripts" / "export_houdini_catalog.py"
        spec = importlib.util.spec_from_file_location("runtime_catalog_exporter", script)
        assert spec is not None and spec.loader is not None
        exporter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(exporter)

        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            (project / "hocus.project.toml").write_text(
                'schema_version = 2\n[project]\nuid = "export-test"\n'
                '[lock]\npolicy = "required"\npath = "hocus.lock.json"\n'
                '[catalog]\npath = "artifacts/catalog-v1.json"\n',
                encoding="utf-8",
            )
            fake_hou = types.ModuleType("hou")
            with (
                mock.patch.dict(sys.modules, {"hou": fake_hou}),
                mock.patch.object(exporter, "LiveHoudiniCatalogProvider", _ExportProvider),
                redirect_stdout(StringIO()),
            ):
                self.assertEqual(exporter.main(["--project", str(project)]), 0)

            output = project / "artifacts" / "catalog-v1.json"
            self.assertEqual(output.read_text(encoding="utf-8"), _ExportSnapshot().to_json() + "\n")
            self.assertFalse((project / "catalog-v1.json").exists())

    def test_graph_store_upgrades_existing_documents_without_data_loss(self):
        fixture = ROOT / "tests" / "fixtures" / "graph_store" / "v1.sql"
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "graph.sqlite3"
            with closing(sqlite3.connect(path)) as connection:
                connection.executescript(fixture.read_text(encoding="utf-8"))
                connection.commit()

            store = LiveGraphStore(logging.getLogger("test.store"), db_path=path)
            self.assertEqual(
                store.get_document_by_id("fixture:/geo"),
                {"documentId": "fixture:/geo", "kind": "network"},
            )
            document = _network_document()
            first = store.upsert_document_from_live(
                document, live_revision=2, source="test"
            )
            second = store.upsert_document_from_live(
                document, live_revision=3, source="test"
            )
            third = store.upsert_document_from_live(
                document, live_revision=3, source="test"
            )
            self.assertEqual(second, third)
            self.assertEqual(
                second["baselineLiveRevision"],
                first["baselineLiveRevision"],
            )
            changed = copy.deepcopy(document)
            changed["nodes"][0]["flags"]["bypass"] = True
            fourth = store.upsert_document_from_live(
                changed, live_revision=4, source="test"
            )
            self.assertEqual(
                fourth["documentRevision"], third["documentRevision"] + 1
            )
            self.assertEqual(fourth["baselineLiveRevision"], 3)

    def test_graph_store_persists_an_idempotent_plan_commit_lifecycle(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = LiveGraphStore(
                logging.getLogger("test.store"), db_path=Path(temp_dir) / "graph.sqlite3"
            )
            plan = _persistent_plan()
            store.store_immutable_plan(
                plan_id="plan-1",
                session_id="session-1",
                root_path="/obj/geo1",
                expires_at=200.0,
                created_at=100.0,
                now=150.0,
                payload=plan,
            )
            pending = store.begin_plan_commit(
                plan_commit_id="commit-1",
                plan_id="plan-1",
                plan_hash=plan["planHash"],
                session_id="session-1",
                idempotency_key="request-1",
                pre_apply_snapshot={"documentRevision": 4},
                inverse_plan={"operations": []},
                now=150.0,
            )
            replay = store.begin_plan_commit(
                plan_commit_id="ignored",
                plan_id="plan-1",
                plan_hash=plan["planHash"],
                session_id="session-1",
                idempotency_key="request-1",
                pre_apply_snapshot={},
                inverse_plan=None,
                now=151.0,
            )
            self.assertEqual(pending, replay)
            committed = store.finish_plan_commit(
                plan_commit_id="commit-1",
                state="committed",
                result={"verified": True},
                error=None,
                now=160.0,
            )
            self.assertEqual(
                store.load_plan_commit(idempotency_key="request-1")["state"], "committed"
            )
            self.assertEqual(committed["result"], {"verified": True})

            def retention_plan(
                plan_id: str,
                created_at: float,
                expires_at: float,
            ) -> dict:
                payload = _persistent_plan()
                payload.update(
                    planId=plan_id,
                    sessionId=f"session:{plan_id}",
                    createdAt=created_at,
                    expiresAt=expires_at,
                    rootPath=f"/obj/{plan_id}",
                )
                payload["baseline"]["documentId"] = f"network:/obj/{plan_id}"
                payload.pop("planHash", None)
                encoded = json.dumps(
                    payload,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                payload["planHash"] = (
                    f"sha256:{hashlib.sha256(encoded.encode()).hexdigest()}"
                )
                return payload

            def store_and_begin(
                plan_id: str,
                *,
                created_at: float,
                expires_at: float,
                commit_at: float,
            ) -> dict:
                payload = retention_plan(plan_id, created_at, expires_at)
                store.store_immutable_plan(payload=payload, now=commit_at)
                store.begin_plan_commit(
                    plan_commit_id=f"commit:{plan_id}",
                    plan_id=plan_id,
                    plan_hash=payload["planHash"],
                    session_id=payload["sessionId"],
                    idempotency_key=f"request:{plan_id}",
                    pre_apply_snapshot={"documentRevision": 4},
                    inverse_plan={"operations": []},
                    now=commit_at,
                )
                return payload

            now = time.time()
            store_and_begin(
                "protected-pending",
                created_at=now - 100,
                expires_at=now + 100,
                commit_at=now - 90,
            )
            store_and_begin(
                "protected-partial",
                created_at=now - 100,
                expires_at=now + 100,
                commit_at=now - 80,
            )
            store.finish_plan_commit(
                plan_commit_id="commit:protected-partial",
                state="partial_or_unknown",
                result={"verified": False},
                error={"message": "unknown"},
                now=now - 70,
            )
            store_and_begin(
                "fresh-terminal",
                created_at=now - 100,
                expires_at=now + 100,
                commit_at=now - 60,
            )
            store.finish_plan_commit(
                plan_commit_id="commit:fresh-terminal",
                state="committed",
                result={"verified": True},
                error=None,
                now=now - 10,
            )
            expired = retention_plan("expired-unclaimed", now - 100, now + 1)
            store.store_immutable_plan(payload=expired, now=now)
            store_and_begin(
                "aged-terminal",
                created_at=now - 90_000,
                expires_at=now + 100,
                commit_at=now - 86_500,
            )
            store.finish_plan_commit(
                plan_commit_id="commit:aged-terminal",
                state="aborted",
                result={"verified": False},
                error={"message": "rolled back"},
                now=now - 86_401,
            )
            self.assertIsNotNone(store.load_immutable_plan("expired-unclaimed"))

            retention = store.prune_durable_plan_history(now=now + 2)
            self.assertEqual(retention["expiredUnclaimedPruned"], 1)
            self.assertEqual(retention["agedTerminalPruned"], 1)
            self.assertIsNone(store.load_immutable_plan("expired-unclaimed"))
            self.assertIsNone(store.load_immutable_plan("aged-terminal"))
            self.assertIsNotNone(store.load_immutable_plan("protected-pending"))
            self.assertIsNotNone(store.load_immutable_plan("protected-partial"))
            self.assertIsNotNone(store.load_immutable_plan("fresh-terminal"))

            with mock.patch.object(
                LiveGraphStore, "_MAX_DURABLE_PLAN_HISTORIES", 2
            ):
                pressure = store.prune_durable_plan_history(now=now)
            self.assertEqual(pressure["pressurePruned"], 1)
            self.assertIsNone(store.load_immutable_plan("fresh-terminal"))

            protected = store.prune_durable_plan_history(now=now)
            with mock.patch.object(
                LiveGraphStore,
                "_MAX_DURABLE_PLAN_HISTORY_BYTES",
                protected["retainedJsonBytes"],
            ):
                with self.assertRaises(GraphStorePlanError):
                    store.store_immutable_plan(
                        payload=retention_plan(
                            "rejected-growth",
                            now,
                            now + 100,
                        )
                    )
            self.assertIsNotNone(store.load_immutable_plan("protected-pending"))
            self.assertIsNotNone(store.load_immutable_plan("protected-partial"))

            with mock.patch.object(
                LiveGraphStore,
                "_DURABLE_TERMINAL_TRANSITION_MAX_BYTES",
                256,
            ):
                store_and_begin(
                    "bounded-finish",
                    created_at=now,
                    expires_at=now + 100,
                    commit_at=now,
                )
                with self.assertRaises(GraphStorePlanError):
                    store.finish_plan_commit(
                        plan_commit_id="commit:bounded-finish",
                        state="committed",
                        result={"payload": "x" * 512},
                        error=None,
                        now=now + 1,
                    )
                self.assertEqual(
                    store.load_plan_commit(
                        plan_commit_id="commit:bounded-finish"
                    )["state"],
                    "pending",
                )

                store_and_begin(
                    "bounded-recovery",
                    created_at=now,
                    expires_at=now + 100,
                    commit_at=now,
                )
                store.finish_plan_commit(
                    plan_commit_id="commit:bounded-recovery",
                    state="partial_or_unknown",
                    result={"verified": False},
                    error=None,
                    now=now + 1,
                )
                with self.assertRaises(GraphStorePlanError):
                    store.resolve_plan_commit_recovery(
                        plan_commit_id="commit:bounded-recovery",
                        state="committed",
                        result={"payload": "x" * 220},
                        now=now + 2,
                    )
                self.assertEqual(
                    store.load_plan_commit(
                        plan_commit_id="commit:bounded-recovery"
                    )["state"],
                    "partial_or_unknown",
                )

    def test_live_catalog_is_portable_stable_and_changes_with_the_hda(self):
        snapshots = []
        with tempfile.TemporaryDirectory() as first_dir, tempfile.TemporaryDirectory() as second_dir:
            for directory in (first_dir, second_dir):
                hda = Path(directory) / "asset.hda"
                hda.write_bytes(b"same definition")
                snapshots.append(
                    LiveHoudiniCatalogProvider(CatalogHou(hda), package_directories=()).get_catalog()
                )

            self.assertEqual(snapshots[0].fingerprint, snapshots[1].fingerprint)
            self.assertNotIn(first_dir, snapshots[0].to_json())
            changed_hda = Path(second_dir) / "asset.hda"
            changed_hda.write_bytes(b"changed definition")
            changed = LiveHoudiniCatalogProvider(
                CatalogHou(changed_hda), package_directories=()
            ).get_catalog()
            self.assertNotEqual(snapshots[1].fingerprint, changed.fingerprint)

    def test_scene_monitor_coalesces_network_edits_and_observes_new_children(self):
        assert_monitor_revision_contract(self)


if __name__ == "__main__":
    unittest.main()

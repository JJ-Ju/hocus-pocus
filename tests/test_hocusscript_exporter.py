from __future__ import annotations

import copy
import hashlib
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python3.11libs"))

from hocuspocus.hocusscript import (
    CompiledBundle,
    compile_source,
    export_network_document,
    lower_bundle_to_document,
    resolve_graph,
)
from hocuspocus.hocusscript.catalog import (
    CategoryDefinition,
    ConnectorDefinition,
    DefinitionSource,
    FakeCatalogProvider,
    OperatorDefinition,
    ParameterDefinition,
)


OWNERSHIP = "studio.environment.export"


def _owned(kind: str) -> dict:
    return {"hocus": {"entityKind": kind, "ownership": OWNERSHIP, "projectUid": "city"}}


def _node(uid: str, name: str, type_name: str, *, root: bool = False, display=False, render=False) -> dict:
    path = "/obj/geo1" if root else f"/obj/geo1/{name}"
    return {
        "uid": uid,
        "name": "geo1" if root else name,
        "typeName": "geo" if root else type_name,
        "category": "Object" if root else "Sop",
        "path": path,
        "parentPath": "/obj" if root else "/obj/geo1",
        "isNetwork": root,
        "position": [0.0, 0.0],
        "flags": {"display": display, "render": render, "bypass": False, "template": False},
        "metadata": {"identityMode": "persistent_user_data"} if root else {
            **_owned("node"),
            "identityMode": "persistent_user_data",
        },
    }


def _set_manifest(node: dict, *, inputs=(), parameters=(), output=False) -> None:
    node["metadata"]["hocus"]["managedFields"] = {
        "type": True,
        "inputs": list(inputs),
        "parameters": list(parameters),
        "flags": {"display": bool(node["flags"]["display"]), "render": bool(node["flags"]["render"]), "output": output},
        "nodeUid": node["uid"],
    }


def _document() -> dict:
    source_uid, sink_uid, root_uid = "asset.source-01", "asset.sink-01", "root-stable"
    binding_scale = {
        "uid": f"binding:{source_uid}:sx", "nodeUid": source_uid, "parmName": "sx",
        "valueMode": "literal", "value": 2, "metadata": _owned("parameter_binding"),
    }
    binding_code = {
        "uid": f"binding:{sink_uid}:snippet", "nodeUid": sink_uid, "parmName": "snippet",
        "valueMode": "code_reference", "codeBlobUid": f"code:{sink_uid}:snippet",
        "metadata": _owned("parameter_binding"),
    }
    code = {
        "uid": f"code:{sink_uid}:snippet", "language": "vex",
        "target": {"nodeUid": sink_uid, "parmName": "snippet", "bindingUid": binding_code["uid"]},
        "body": "@P *= 2;", "metadata": _owned("code_blob"),
    }
    document = {
        "$schema": "hocuspocus://schemas/network-document/v1",
        "kind": "network_document",
        "documentId": "network:/obj/geo1",
        "documentRevision": 7,
        "baselineLiveRevision": 19,
        "lastSyncedLiveRevision": 19,
        "rootPath": "/obj/geo1",
        "category": "Object",
        "metadata": {},
        "nodes": [
            _node(root_uid, "geo1", "geo", root=True),
            _node(source_uid, "source", "acme::source::1.0"),
            _node(sink_uid, "sink", "sink", display=True, render=True),
        ],
        "ports": [],
        "edges": [
            {
                "uid": f"edge:data:{sink_uid}:0", "kind": "data",
                "from": {"nodeUid": source_uid, "portIndex": 1, "portName": "points"},
                "to": {"nodeUid": sink_uid, "portIndex": 0, "portName": "source"},
                "metadata": _owned("edge"),
            },
            {
                "uid": f"edge:output:{root_uid}", "kind": "output_flag",
                "from": {"nodeUid": sink_uid}, "to": {"nodeUid": root_uid},
                "metadata": _owned("output_flag"),
            },
        ],
        "parameterBindings": [binding_scale, binding_code],
        "codeBlobs": [code],
        "diagnostics": [],
    }
    _set_manifest(document["nodes"][1], parameters=("sx",))
    _set_manifest(document["nodes"][2], inputs=(0,), parameters=("snippet",), output=True)
    return document


def _provider() -> FakeCatalogProvider:
    out0 = ConnectorDefinition(0, "geometry", "Geometry", data_types=("geometry",))
    out1 = ConnectorDefinition(1, "points", "Points", data_types=("geometry",))
    input0 = ConnectorDefinition(0, "source", "Source", data_types=("geometry",))
    return FakeCatalogProvider.create(
        categories=(CategoryDefinition("Sop", "SOP", "sop"),),
        operators=(
            OperatorDefinition(
                "acme::source::1.0", "source", "acme", "1.0", "Sop", (), DefinitionSource("builtin"),
                (ParameterDefinition("scale", "Scale", "float", 3, ("sx", "sy", "sz"), (1.0, 1.0, 1.0)),),
                (), (out0, out1),
            ),
            OperatorDefinition(
                "sink", "sink", None, None, "Sop", (), DefinitionSource("builtin"),
                (ParameterDefinition("snippet", "Snippet", "code", 1, (), "", code_surface="vex"),),
                (input0,), (out0,),
            ),
        ),
    )


def _digest(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _bundle_from_export(source: str, provider: FakeCatalogProvider, source_uri: str) -> CompiledBundle:
    result = compile_source(source, "exported.hocus", source_uri=source_uri)
    assert result.valid and result.graph_spec is not None
    result.semantic_result = resolve_graph(result.graph_spec, provider)
    assert result.semantic_result.valid and result.semantic_result.ready_for_document_lowering
    result.source_kind = "project_file"
    result.project_uid = "city"
    result.project_manifest_digest = _digest("manifest")
    result.project_lock_digest = _digest("lock")
    result.catalog_fingerprint = provider.catalog.fingerprint
    result.catalog_content_digest = _digest(provider.catalog.to_json())
    return CompiledBundle.from_result(result)


def _clean_baseline(document: dict) -> dict:
    baseline = copy.deepcopy(document)
    baseline["nodes"] = [item for item in baseline["nodes"] if item["path"] == baseline["rootPath"]]
    for field in ("ports", "edges", "parameterBindings", "codeBlobs"):
        baseline[field] = []
    return baseline


class HocusScriptExporterTests(unittest.TestCase):
    def test_blocker_manifest_is_bounded_with_exact_omission_sentinel(self) -> None:
        document = _document()
        document["ports"] = [
            {
                "uid": f"port:asset.source-01:output:{index}",
                "kind": "opaque",
                "nodeUid": "asset.source-01",
                "direction": "output",
                "index": index,
                "metadata": _owned("port"),
            }
            for index in range(600)
        ]
        result = export_network_document(document)
        self.assertFalse(result.valid)
        self.assertIsNone(result.source)
        self.assertEqual(len(result.diagnostics), 500)
        sentinel = next(item for item in result.diagnostics if item.code == "HOCUS819")
        self.assertEqual(result.diagnostics[-1].code, "HOCUS819")
        self.assertEqual(sentinel.details, {"omittedCount": 101, "limit": 500})
        self.assertIn("101 additional", sentinel.message)

    def test_export_response_budget_fails_closed_with_minimal_provenance(self) -> None:
        with patch("hocuspocus.hocusscript.exporter.MAX_EXPORT_RESPONSE_BYTES", 1024):
            result = export_network_document(_document())
        self.assertFalse(result.valid)
        self.assertIsNone(result.source)
        self.assertEqual([item.code for item in result.diagnostics], ["HOCUS820"])
        self.assertEqual(result.provenance["entities"], {})
        self.assertEqual(result.provenance["managedFields"], {})
        self.assertEqual(result.provenance["preservedState"], [])

    def test_supported_document_exports_deterministically_and_recompiles_semantically(self) -> None:
        document = _document()
        original = copy.deepcopy(document)
        provider = _provider()
        first = export_network_document(document, graph_name="exported_geo", catalog=provider)
        second = export_network_document(copy.deepcopy(document), graph_name="exported_geo", catalog=provider.catalog)

        self.assertTrue(first.valid, [item.to_dict() for item in first.diagnostics])
        self.assertEqual(first.to_dict(), second.to_dict())
        self.assertEqual(document, original)
        self.assertEqual(
            first.source,
            (ROOT / "tests" / "fixtures" / "hocusscript" / "v0.1" / "export_supported.golden.hocus")
            .read_text(encoding="utf-8"),
        )
        self.assertIn('node source @id("asset.source-01"): "acme::source::1.0"', first.source)
        self.assertIn("input[0] = source.output[1];", first.source)
        self.assertIn("ownership \"studio.environment.export\";", first.source)

        compiled = compile_source(first.source, "exported.hocus", source_uri="hocus-memory://exported.hocus")
        self.assertTrue(compiled.valid, [item.to_dict() for item in compiled.diagnostics])
        self.assertEqual([item.explicit_id for item in compiled.graph_spec.nodes],
                         ["asset.sink-01", "asset.source-01"])
        semantic = resolve_graph(compiled.graph_spec, provider)
        self.assertTrue(semantic.valid, [item.to_dict() for item in semantic.diagnostics])
        self.assertEqual(
            {(item.node_symbol, item.qualified_name) for item in semantic.operator_selections},
            {("source", "acme::source::1.0"), ("sink", "sink")},
        )
        self.assertEqual(
            [(item.node_symbol, item.authored_token, item.component_index) for item in semantic.parameter_selections],
            [("sink", "snippet", None), ("source", "sx", 0)],
        )
        connection = semantic.connection_selections[0]
        self.assertEqual((connection.source_symbol, connection.output_index, connection.input_index),
                         ("source", 1, 0))
        self.assertEqual((compiled.graph_spec.display, compiled.graph_spec.render, compiled.graph_spec.output),
                         ("sink", "sink", "sink"))

        provenance = first.provenance
        self.assertEqual(provenance["catalogFingerprint"], provider.catalog.fingerprint)
        self.assertEqual(provenance["identityMode"], "explicit_id_and_sidecar")
        self.assertEqual(set(provenance["entities"]), {
            "root-stable", "asset.source-01", "asset.sink-01", "edge:data:asset.sink-01:0",
            "edge:output:root-stable", "binding:asset.source-01:sx",
            "binding:asset.sink-01:snippet", "code:asset.sink-01:snippet",
        })
        self.assertEqual(provenance["managedFields"]["asset.source-01"]["parameters"], ["sx"])
        self.assertEqual(provenance["managedFields"]["asset.sink-01"]["inputs"], [0])
        self.assertEqual(provenance["managedFields"]["asset.sink-01"]["flags"],
                         {"display": True, "render": True, "output": True})
        self.assertEqual(provenance["managedFields"]["asset.source-01"]["flags"],
                         {"display": False, "render": False, "output": False})
        self.assertEqual(provenance["managedFields"]["asset.source-01"]["preservedFields"],
                         ["position"])

    def test_exported_symbol_rename_recompiles_and_lowers_as_same_managed_uid(self) -> None:
        provider = _provider()
        original = _document()
        first_export = export_network_document(original, graph_name="exported_geo", catalog=provider)
        self.assertTrue(first_export.valid)
        first = lower_bundle_to_document(
            _bundle_from_export(first_export.source, provider, "hocus-project://city/original.hocus"),
            _clean_baseline(original),
        )
        self.assertTrue(first.valid, first.diagnostics)

        renamed = _document()
        renamed["documentRevision"] = first.document["documentRevision"]
        source_node = next(item for item in renamed["nodes"] if item["uid"] == "asset.source-01")
        source_node["name"] = "renamed_source"
        source_node["path"] = "/obj/geo1/renamed_source"
        renamed_export = export_network_document(renamed, graph_name="exported_geo", catalog=provider)
        self.assertTrue(renamed_export.valid, [item.to_dict() for item in renamed_export.diagnostics])
        self.assertIn('node renamed_source @id("asset.source-01"):', renamed_export.source)

        second = lower_bundle_to_document(
            _bundle_from_export(renamed_export.source, provider, "hocus-project://city/relocated.hocus"),
            first.document,
        )
        self.assertTrue(second.valid, second.diagnostics)
        self.assertEqual(second.diff["createdNodes"], [])
        self.assertEqual(second.diff["deletedNodes"], [])
        changed = next(item for item in second.diff["changedNodes"] if item["uid"] == "asset.source-01")
        self.assertEqual(changed["before"]["name"], "source")
        self.assertEqual(changed["after"]["name"], "renamed_source")
        operation = next(item for item in second.candidate_plan["operations"]
                         if item["entityUid"] == "asset.source-01")
        self.assertEqual(operation["action"], "rename_node")

    def test_catalog_semantic_failure_becomes_typed_export_blocker(self) -> None:
        incomplete_catalog = FakeCatalogProvider.create(
            categories=(CategoryDefinition("Sop", "SOP", "sop"),),
            operators=(),
        )
        result = export_network_document(_document(), catalog=incomplete_catalog)

        self.assertIsNone(result.source)
        blockers = [item for item in result.diagnostics if item.code == "HOCUS813"]
        self.assertTrue(blockers)
        self.assertIn("HOCUS624", {item.details["originalCode"] for item in blockers})
        self.assertEqual(result.provenance["catalogFingerprint"], incomplete_catalog.catalog.fingerprint)

    def test_hostile_numeric_literal_fails_closed_without_formatter_exception(self) -> None:
        document = _document()
        document["parameterBindings"][0]["value"] = 10 ** 1000

        result = export_network_document(document)

        self.assertIsNone(result.source)
        self.assertIn("HOCUS808", {item.code for item in result.diagnostics})

        document = _document()
        document["parameterBindings"][0]["value"] = "\ud800"
        result = export_network_document(document)
        self.assertIsNone(result.source)
        self.assertIn("HOCUS808", {item.code for item in result.diagnostics})

    def test_unsupported_constructs_return_all_typed_blockers_and_no_source(self) -> None:
        document = _document()
        document["nodes"][1]["uid"] = "bad/id"
        document["nodes"][2]["isNetwork"] = True
        document["nodes"][2]["flags"]["bypass"] = True
        document["parameterBindings"][0]["valueMode"] = "expression"
        document["parameterBindings"][0]["expression"] = "$F"
        document["edges"].append({
            "uid": "edge:opaque", "kind": "dependency",
            "from": {"nodeUid": "asset.source-01"}, "to": {"nodeUid": "asset.sink-01"},
            "metadata": {},
        })
        document["codeBlobs"].append({
            "uid": "code:orphan", "language": "vex",
            "target": {"nodeUid": "asset.sink-01", "parmName": "unused"},
            "body": "@P = 0;", "metadata": {},
        })

        result = export_network_document(document)

        self.assertFalse(result.valid)
        self.assertIsNone(result.source)
        codes = {item.code for item in result.diagnostics}
        self.assertTrue({"HOCUS803", "HOCUS805", "HOCUS807", "HOCUS808", "HOCUS809"} <= codes)
        self.assertGreaterEqual(len(result.diagnostics), 5)

    def test_incomplete_or_mixed_ownership_is_never_broadened(self) -> None:
        incomplete = _document()
        incomplete["parameterBindings"][0]["metadata"] = {}
        result = export_network_document(incomplete)
        self.assertIsNone(result.source)
        self.assertIn("HOCUS810", {item.code for item in result.diagnostics})

        mixed = _document()
        mixed["edges"][0]["metadata"]["hocus"]["ownership"] = "studio.other"
        result = export_network_document(mixed)
        self.assertIsNone(result.source)
        ownership = next(item for item in result.diagnostics if item.code == "HOCUS810")
        self.assertEqual(ownership.details["ownerships"], ["studio.environment.export", "studio.other"])

    def test_missing_and_duplicate_persistent_ids_fail_closed(self) -> None:
        missing = _document()
        missing["nodes"][1]["uid"] = ""
        self.assertIn("HOCUS803", {item.code for item in export_network_document(missing).diagnostics})

        duplicate = _document()
        duplicate["nodes"][2]["uid"] = duplicate["nodes"][1]["uid"]
        result = export_network_document(duplicate)
        self.assertIsNone(result.source)
        self.assertIn("HOCUS803", {item.code for item in result.diagnostics})

        noncanonical = _document()
        noncanonical["parameterBindings"][0]["uid"] = "binding:legacy"
        result = export_network_document(noncanonical)
        derived = [item for item in result.diagnostics if item.code == "HOCUS803" and item.details]
        self.assertIn("binding:asset.source-01:sx", {item.details.get("expectedUid") for item in derived})

    def test_root_and_artist_state_is_explicitly_preserved_not_exported(self) -> None:
        document = _document()
        root_uid = document["nodes"][0]["uid"]
        source_uid = document["nodes"][1]["uid"]
        document["parameterBindings"].extend((
            {"uid": f"binding:{root_uid}:tx", "nodeUid": root_uid, "parmName": "tx",
             "valueMode": "literal", "value": 12, "metadata": {}},
            {"uid": f"binding:{source_uid}:sy", "nodeUid": source_uid, "parmName": "sy",
             "valueMode": "literal", "value": 9, "metadata": {}},
        ))

        result = export_network_document(document, catalog=_provider())

        self.assertTrue(result.valid, [item.to_dict() for item in result.diagnostics])
        self.assertNotIn("tx =", result.source)
        self.assertNotIn("sy =", result.source)
        self.assertEqual(
            {(item["kind"], item["field"], item["reason"]) for item in result.provenance["preservedState"]},
            {
                ("parameter_binding", "tx", "root_container_state"),
                ("parameter_binding", "sy", "artist_or_default_not_source_managed"),
            },
        )

    def test_transient_identity_is_never_treated_as_explicit_id(self) -> None:
        for node_index in (0, 1):
            document = _document()
            document["nodes"][node_index]["metadata"]["identityMode"] = "session_fallback"
            result = export_network_document(document)
            blockers = [item for item in result.diagnostics if item.code == "HOCUS803"]
            self.assertTrue(blockers)
            self.assertTrue(any((item.details or {}).get("rootPolicy") for item in blockers))


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import copy
import hashlib
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python3.11libs"))

from hocuspocus.hocusscript import (
    BundleValidationError,
    CompiledBundle,
    DocumentLoweringError,
    compile_source,
    decode_compiled_bundle,
    lower_bundle_to_document,
    graph_spec_from_dict,
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


def _digest(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _provider() -> FakeCatalogProvider:
    geometry_out = ConnectorDefinition(0, "geometry", "Geometry", data_types=("geometry",))
    points_out = ConnectorDefinition(1, "points", "Points", data_types=("geometry",))
    geometry_in = ConnectorDefinition(0, "source", "Source", data_types=("geometry",))
    return FakeCatalogProvider.create(
        categories=(CategoryDefinition("Sop", "SOP", "sop"),),
        operators=(
            OperatorDefinition(
                "acme::source::1.0", "source", "acme", "1.0", "Sop", (),
                DefinitionSource("builtin"),
                (ParameterDefinition("scale", "Scale", "float", 3, ("sx", "sy", "sz"),
                                     (1.0, 1.0, 1.0)),),
                (), (geometry_out, points_out),
            ),
            OperatorDefinition(
                "sink", "sink", None, None, "Sop", (), DefinitionSource("builtin"),
                (ParameterDefinition("snippet", "Snippet", "code", 1, (), "", code_surface="vex"),),
                (geometry_in,), (geometry_out,),
            ),
        ),
    )


def _bundle(
    *, mode: str = "merge", extra: str = "", source_id: str | None = None,
    sink_id: str | None = None, source_symbol: str = "source", sink_symbol: str = "sink",
    source_uri: str = "hocus-project://city/assets/rocks.hocus",
) -> CompiledBundle:
    provider = _provider()
    ownership = ' ownership "studio.environment.rocks";' if mode == "reconcile" else ""
    source_identity = f' @id("{source_id}")' if source_id is not None else ""
    sink_identity = f' @id("{sink_id}")' if sink_id is not None else ""
    source = f'''hocus 0.1;
graph rocks {{
  target "/obj/geo1"; category Sop; mode {mode};{ownership}
  node {source_symbol}{source_identity}: "acme::source::1.0" {{ sx = 2; }}
  node {sink_symbol}{sink_identity}: sink {{ input[0] = {source_symbol}.output[1]; snippet = vex`@P *= 2;`; }}
  display = {sink_symbol}; render = {sink_symbol}; output = {sink_symbol}; {extra}
}}
'''
    result = compile_source(source, "assets/rocks.hocus", source_uri=source_uri)
    assert result.valid and result.graph_spec is not None
    semantic = resolve_graph(result.graph_spec, provider)
    assert semantic.valid and semantic.ready_for_document_lowering
    result.semantic_result = semantic
    result.source_uri = source_uri
    result.source_kind = "project_file"
    result.project_uid = "city"
    result.project_manifest_digest = _digest("manifest")
    result.project_lock_digest = _digest("lock")
    result.catalog_fingerprint = provider.catalog.fingerprint
    result.catalog_content_digest = _digest(provider.catalog.to_json())
    return CompiledBundle.from_result(result)


def _node(uid: str, name: str, path: str, *, metadata=None):
    return {
        "uid": uid, "name": name, "typeName": "null", "category": "Sop", "path": path,
        "parentPath": path.rsplit("/", 1)[0] or "/", "isNetwork": path == "/obj/geo1",
        "position": [1.0, 2.0],
        "flags": {"display": False, "render": False, "bypass": False, "template": False},
        "metadata": metadata or {},
    }


def _baseline(*, extras=()):
    return {
        "$schema": "hocuspocus://schemas/network-document/v1", "kind": "network_document",
        "documentId": "network:/obj/geo1", "documentRevision": 7,
        "baselineLiveRevision": 19, "lastSyncedLiveRevision": 19,
        "rootPath": "/obj/geo1", "category": "Sop", "metadata": {"artist": "kept"},
        "nodes": [_node("root-stable", "geo1", "/obj/geo1"), *copy.deepcopy(list(extras))],
        "ports": [], "edges": [], "parameterBindings": [], "codeBlobs": [], "diagnostics": [],
    }


class HocusScriptDocumentLoweringTests(unittest.TestCase):
    def test_strict_bundle_graph_rehydrates_without_losing_semantics_or_spans(self) -> None:
        graph = _bundle().payload["graphSpec"]
        self.assertEqual(graph_spec_from_dict(graph).to_dict(), graph)

    def test_lowering_is_deterministic_schema_valid_and_source_mapped(self) -> None:
        bundle = _bundle()
        baseline = _baseline(extras=(_node("artist-node", "artist", "/obj/geo1/artist"),))
        first = lower_bundle_to_document(bundle, baseline)
        second = lower_bundle_to_document(bundle.to_dict(), copy.deepcopy(baseline))
        self.assertEqual(first.to_dict(), second.to_dict())
        self.assertTrue(first.valid)
        self.assertFalse(first.to_dict()["readyForApply"])
        self.assertEqual(first.document["metadata"]["artist"], "kept")
        self.assertIn("artist-node", {item["uid"] for item in first.document["nodes"]})
        self.assertEqual(first.document["documentRevision"], 8)

        nodes = {item["name"]: item for item in first.document["nodes"]}
        self.assertEqual(nodes["source"]["typeName"], "acme::source::1.0")
        self.assertTrue(nodes["sink"]["flags"]["display"])
        self.assertEqual(nodes["source"]["metadata"]["hocus"]["managedFields"], {
            "type": True, "inputs": [], "parameters": ["sx"],
            "flags": {"display": False, "render": False, "output": False},
            "nodeUid": nodes["source"]["uid"],
        })
        self.assertEqual(nodes["sink"]["metadata"]["hocus"]["managedFields"], {
            "type": True, "inputs": [0], "parameters": ["snippet"],
            "flags": {"display": True, "render": True, "output": True},
            "nodeUid": nodes["sink"]["uid"],
        })
        edge = next(item for item in first.document["edges"] if item["kind"] == "data")
        self.assertEqual(edge["from"]["portIndex"], 1)
        self.assertEqual(edge["from"]["portName"], "points")
        self.assertEqual(edge["to"]["portIndex"], 0)
        self.assertEqual(edge["to"]["portName"], "source")
        self.assertEqual({item["name"] for item in first.document["ports"]}, {"points", "source"})

        bindings = {item["parmName"]: item for item in first.document["parameterBindings"]}
        self.assertEqual(bindings["sx"]["value"], 2)
        self.assertEqual(bindings["snippet"]["valueMode"], "code_reference")
        self.assertEqual(first.document["codeBlobs"][0]["language"], "vex")
        self.assertEqual(first.provenance["entrySource"]["uri"],
                         "hocus-project://city/assets/rocks.hocus")
        self.assertNotIn(str(ROOT), json.dumps(first.provenance))
        self.assertTrue(first.source_maps["entities"])
        self.assertTrue(first.source_maps["operations"])
        self.assertEqual(first.candidate_plan["planHash"], second.candidate_plan["planHash"])
        output_edge = next(item for item in first.document["edges"] if item["kind"] == "output_flag")
        self.assertEqual(output_edge["from"]["nodeUid"], nodes["sink"]["uid"])
        self.assertIn("set_output", {item["action"] for item in first.candidate_plan["operations"]})

        try:
            from jsonschema import Draft202012Validator
        except ImportError:
            return
        schema = json.loads((ROOT / "docs" / "schemas" / "network-document-v1.schema.json").read_text("utf-8"))
        Draft202012Validator(schema).validate(first.document)

    def test_explicit_node_ids_select_document_uids_and_defaults_stay_deterministic(self) -> None:
        explicit = lower_bundle_to_document(
            _bundle(source_id="asset.rock:source-01", sink_id="asset.rock:sink-01"),
            _baseline(),
        )
        explicit_nodes = {item["name"]: item for item in explicit.document["nodes"]}
        self.assertEqual(explicit_nodes["source"]["uid"], "asset.rock:source-01")
        self.assertEqual(explicit_nodes["sink"]["uid"], "asset.rock:sink-01")

        first_default = lower_bundle_to_document(_bundle(), _baseline())
        second_default = lower_bundle_to_document(_bundle(), _baseline())
        first_uids = {item["name"]: item["uid"] for item in first_default.document["nodes"]}
        second_uids = {item["name"]: item["uid"] for item in second_default.document["nodes"]}
        self.assertEqual(first_uids, second_uids)
        self.assertTrue(first_uids["source"].startswith("hocus-node:"))

    def test_explicit_node_ids_survive_source_symbol_renames(self) -> None:
        before = lower_bundle_to_document(
            _bundle(source_id="asset.rock:source-01", sink_id="asset.rock:sink-01"),
            _baseline(),
        )
        after = lower_bundle_to_document(
            _bundle(
                source_id="asset.rock:source-01",
                sink_id="asset.rock:sink-01",
                source_symbol="renamed_source",
                source_uri="hocus-project://city/relocated/rocks.hocus",
            ),
            before.document,
        )
        self.assertTrue(after.valid, after.diagnostics)
        nodes = {item["uid"]: item for item in after.document["nodes"]}
        self.assertEqual(nodes["asset.rock:source-01"]["path"], "/obj/geo1/renamed_source")
        self.assertEqual(nodes["asset.rock:source-01"]["metadata"]["hocus"]["sourceUri"],
                         "hocus-project://city/relocated/rocks.hocus")
        self.assertEqual(after.diff["createdNodes"], [])
        self.assertEqual(after.diff["deletedNodes"], [])
        renamed = next(item for item in after.diff["changedNodes"]
                       if item["uid"] == "asset.rock:source-01")
        self.assertEqual(renamed["before"]["path"], "/obj/geo1/source")
        self.assertEqual(renamed["after"]["path"], "/obj/geo1/renamed_source")
        operation = next(item for item in after.candidate_plan["operations"]
                         if item["entityUid"] == "asset.rock:source-01")
        self.assertEqual(operation["action"], "rename_node")

    def test_managed_explicit_rename_still_obeys_destination_collision_gate(self) -> None:
        before = lower_bundle_to_document(
            _bundle(source_id="asset.rock:source-01", sink_id="asset.rock:sink-01"), _baseline()
        ).document
        before["nodes"].append(_node("artist-destination", "renamed_source", "/obj/geo1/renamed_source"))
        after = lower_bundle_to_document(
            _bundle(source_id="asset.rock:source-01", sink_id="asset.rock:sink-01",
                    source_symbol="renamed_source"),
            before,
        )
        self.assertFalse(after.valid)
        self.assertIsNone(after.candidate_plan)
        self.assertIn("HOCUS706", {item["code"] for item in after.diagnostics})

    def test_explicit_node_id_cannot_alias_a_different_baseline_path(self) -> None:
        collision = _node("asset.rock:source-01", "artist", "/obj/geo1/artist")
        preview = lower_bundle_to_document(
            _bundle(source_id="asset.rock:source-01"),
            _baseline(extras=(collision,)),
        )
        self.assertFalse(preview.valid)
        self.assertIsNone(preview.candidate_plan)
        self.assertIn("HOCUS706", {item["code"] for item in preview.diagnostics})

    def test_bundle_boundary_rejects_invalid_and_duplicate_explicit_node_ids(self) -> None:
        def rehash(payload):
            unsigned = copy.deepcopy(payload)
            unsigned.pop("bundleDigest")
            payload["bundleDigest"] = _digest(
                json.dumps(unsigned, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
            )

        invalid = _bundle(source_id="asset.rock:source-01", sink_id="asset.rock:sink-01").to_dict()
        invalid["graphSpec"]["nodes"][0]["explicitId"] = "bad/id"
        rehash(invalid)
        with self.assertRaises(BundleValidationError) as invalid_error:
            decode_compiled_bundle(invalid)
        self.assertEqual(invalid_error.exception.code, "HOCUS520")

        duplicate = _bundle(source_id="asset.rock:source-01", sink_id="asset.rock:sink-01").to_dict()
        duplicate["graphSpec"]["nodes"][1]["explicitId"] = "asset.rock:source-01"
        rehash(duplicate)
        with self.assertRaises(BundleValidationError) as duplicate_error:
            decode_compiled_bundle(duplicate)
        self.assertEqual(duplicate_error.exception.code, "HOCUS520")

    def test_bundle_version_pairs_decode_only_explicitly_safe_graphspec_contracts(self) -> None:
        def rehash(payload):
            unsigned = copy.deepcopy(payload)
            unsigned.pop("bundleDigest")
            payload["bundleDigest"] = _digest(
                json.dumps(unsigned, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
            )

        safe_legacy = _bundle().to_dict()
        safe_legacy["compilerVersion"] = "0.2.0"
        safe_legacy["graphSpecVersion"] = "0.1"
        safe_legacy["graphSpec"]["$schema"] = "hocuspocus://schemas/graph-spec/v0.1"
        safe_legacy["graphSpec"]["graphSpecVersion"] = "0.1"
        rehash(safe_legacy)
        self.assertEqual(decode_compiled_bundle(safe_legacy).payload["graphSpecVersion"], "0.1")

        mixed = _bundle(source_id="asset.rock:source-01").to_dict()
        mixed["compilerVersion"] = "0.2.0"
        rehash(mixed)
        with self.assertRaises(BundleValidationError) as mixed_error:
            decode_compiled_bundle(mixed)
        self.assertEqual(mixed_error.exception.code, "HOCUS507")

        smuggled = _bundle(source_id="asset.rock:source-01").to_dict()
        smuggled["compilerVersion"] = "0.2.0"
        smuggled["graphSpecVersion"] = "0.1"
        smuggled["graphSpec"]["$schema"] = "hocuspocus://schemas/graph-spec/v0.1"
        smuggled["graphSpec"]["graphSpecVersion"] = "0.1"
        rehash(smuggled)
        with self.assertRaises(BundleValidationError) as smuggled_error:
            decode_compiled_bundle(smuggled)
        self.assertEqual(smuggled_error.exception.code, "HOCUS520")

    def test_live_round_trip_does_not_duplicate_or_reapply_authored_state(self) -> None:
        bundle = _bundle()
        first = lower_bundle_to_document(bundle, _baseline())
        imported = copy.deepcopy(first.document)
        imported["metadata"] = {"graphRevision": 20}
        imported["lastSyncedLiveRevision"] = 20
        imported["baselineLiveRevision"] = 20
        for field in ("nodes", "ports", "edges", "parameterBindings", "codeBlobs"):
            for entity in imported.get(field, []):
                entity["metadata"] = {}
                entity.pop("definitionRef", None)

        second = lower_bundle_to_document(bundle, imported)

        self.assertTrue(second.valid)
        self.assertEqual(second.diff["summary"]["totalChangeCount"], 0)
        self.assertEqual(second.candidate_plan["operations"], [])
        self.assertEqual(len(second.document["parameterBindings"]), 2)
        self.assertEqual(len(second.document["edges"]), 2)
        binding_keys = {
            (item["nodeUid"], item["parmName"])
            for item in second.document["parameterBindings"]
        }
        self.assertEqual(len(binding_keys), len(second.document["parameterBindings"]))

    def test_auto_layout_lowers_to_deterministic_node_positions(self) -> None:
        occupied = _node("artist", "artist", "/obj/geo1/artist")
        occupied["position"] = [0.0, 0.0]
        first = lower_bundle_to_document(_bundle(extra="layout = auto;"), _baseline(extras=(occupied,)))
        second = lower_bundle_to_document(_bundle(extra="layout = auto;"), _baseline(extras=(occupied,)))
        positions = {item["name"]: item["position"] for item in first.document["nodes"]}
        self.assertEqual(positions["artist"], [0.0, 0.0])
        self.assertEqual(positions["source"], [3.25, 0.0])
        self.assertEqual(positions["sink"], [6.5, 0.0])
        self.assertEqual(first.to_dict(), second.to_dict())

    def test_changed_input_and_output_edges_emit_reconnect_operations(self) -> None:
        bundle = _bundle()
        baseline = lower_bundle_to_document(bundle, _baseline()).document
        nodes = {item["name"]: item for item in baseline["nodes"]}
        artist = _node("artist", "artist", "/obj/geo1/artist")
        baseline["nodes"].append(artist)
        data_edge = next(item for item in baseline["edges"] if item["kind"] == "data")
        data_edge["from"] = {"nodeUid": "artist", "portIndex": 0}
        output_edge = next(item for item in baseline["edges"] if item["kind"] == "output_flag")
        output_edge["from"] = {"nodeUid": nodes["source"]["uid"]}

        preview = lower_bundle_to_document(bundle, baseline)

        self.assertEqual(
            {item["after"]["kind"] for item in preview.diff["changedEdges"]},
            {"data", "output_flag"},
        )
        changed_uids = {item["uid"] for item in preview.diff["changedEdges"]}
        operations = [
            item for item in preview.candidate_plan["operations"]
            if item["entityUid"] in changed_uids
        ]
        self.assertEqual({item["action"] for item in operations}, {"connect", "set_output"})
        self.assertTrue(all("sourceMap" in item for item in operations))

        new_source_uid = nodes["source"]["uid"]
        redirect_baseline = copy.deepcopy(baseline)
        redirect_baseline["nodes"] = [item for item in redirect_baseline["nodes"] if item["uid"] != new_source_uid]
        redirect_baseline["ports"] = [item for item in redirect_baseline["ports"] if item["nodeUid"] != new_source_uid]
        redirect_baseline["parameterBindings"] = [
            item for item in redirect_baseline["parameterBindings"] if item["nodeUid"] != new_source_uid
        ]
        next(item for item in redirect_baseline["edges"] if item["kind"] == "output_flag")["from"] = {
            "nodeUid": "artist"
        }
        redirected = lower_bundle_to_document(bundle, redirect_baseline)
        create_sequence = next(
            item["sequence"] for item in redirected.candidate_plan["operations"]
            if item["action"] == "create_node" and item["entityUid"] == new_source_uid
        )
        reconnect_sequences = [
            item["sequence"] for item in redirected.candidate_plan["operations"]
            if item["action"] == "connect"
            and item["change"].get("after", item["change"]).get("from", {}).get("nodeUid") == new_source_uid
        ]
        self.assertTrue(reconnect_sequences)
        self.assertTrue(all(create_sequence < sequence for sequence in reconnect_sequences))

    def test_display_and_render_directives_model_displaced_live_flags(self) -> None:
        artist = _node("artist", "artist", "/obj/geo1/artist")
        artist["flags"]["display"] = True
        artist["flags"]["render"] = True
        preview = lower_bundle_to_document(_bundle(), _baseline(extras=(artist,)))

        nodes = {item["uid"]: item for item in preview.document["nodes"]}
        self.assertFalse(nodes["artist"]["flags"]["display"])
        self.assertFalse(nodes["artist"]["flags"]["render"])
        changed = {item["uid"] for item in preview.diff["changedNodes"]}
        self.assertIn("artist", changed)
        self.assertEqual(preview.destructive_summary["displacedDisplayNodeUids"], ["artist"])
        self.assertEqual(preview.destructive_summary["displacedRenderNodeUids"], ["artist"])
        operation = next(item for item in preview.candidate_plan["operations"] if item["entityUid"] == "artist")
        self.assertIn("sourceMap", operation)

    def test_reconcile_removes_only_matching_owned_state(self) -> None:
        bundle = _bundle(mode="reconcile")
        owned = _node(
            "old-owned", "old", "/obj/geo1/old",
            metadata={"hocus": {
                "ownership": "studio.environment.rocks",
                "sourceUri": "hocus-project://city/assets/old.hocus",
                "jsonPointer": "/nodes/0",
                "span": {"sourceUri": "hocus-project://city/assets/old.hocus", "start": {"line": 1, "column": 1, "offset": 0}, "end": {"line": 1, "column": 2, "offset": 1}},
            }},
        )
        other = _node(
            "other-owned", "other", "/obj/geo1/other",
            metadata={"hocus": {"ownership": "studio.characters"}},
        )
        artist = _node("artist", "artist", "/obj/geo1/artist")
        preview = lower_bundle_to_document(bundle, _baseline(extras=(owned, other, artist)))
        uids = {item["uid"] for item in preview.document["nodes"]}
        self.assertNotIn("old-owned", uids)
        self.assertIn("other-owned", uids)
        self.assertIn("artist", uids)
        self.assertEqual(preview.destructive_summary["deletedNodeUids"], ["old-owned"])
        self.assertTrue(preview.destructive_summary["destructive"])
        delete = next(item for item in preview.candidate_plan["operations"] if item["action"] == "delete_node")
        self.assertEqual(delete["sourceMap"]["sourceUri"], "hocus-project://city/assets/old.hocus")

    def test_reconcile_blocks_owned_deletion_without_durable_source_provenance(self) -> None:
        bundle = _bundle(mode="reconcile")
        owned = _node(
            "old-owned", "old", "/obj/geo1/old",
            metadata={"hocus": {"ownership": "studio.environment.rocks"}},
        )
        preview = lower_bundle_to_document(bundle, _baseline(extras=(owned,)))
        self.assertFalse(preview.valid)
        self.assertIsNone(preview.candidate_plan)
        self.assertIn("HOCUS713", {item["code"] for item in preview.diagnostics})

    def test_reconcile_blocks_unowned_dependencies_on_owned_nodes(self) -> None:
        owned = _node(
            "old-owned", "old", "/obj/geo1/old",
            metadata={"hocus": {"ownership": "studio.environment.rocks"}},
        )
        baseline = _baseline(extras=(owned,))
        baseline["edges"] = [{
            "uid": "artist-edge", "kind": "data", "from": {"nodeUid": "old-owned", "portIndex": 0},
            "to": {"nodeUid": "root-stable", "portIndex": 0}, "metadata": {},
        }]
        preview = lower_bundle_to_document(_bundle(mode="reconcile"), baseline)
        self.assertFalse(preview.valid)
        self.assertIsNone(preview.candidate_plan)
        self.assertIn("HOCUS709", {item["code"] for item in preview.diagnostics})

    def test_unowned_path_collision_blocks_candidate_plan(self) -> None:
        collision = _node("artist-source", "source", "/obj/geo1/source")
        preview = lower_bundle_to_document(_bundle(), _baseline(extras=(collision,)))
        self.assertFalse(preview.valid)
        self.assertIsNone(preview.candidate_plan)
        self.assertEqual([item["code"] for item in preview.diagnostics], ["HOCUS706"])
        self.assertIn("artist-source", {item["uid"] for item in preview.document["nodes"]})

    def test_whole_tuple_is_precisely_blocked_instead_of_emitting_list_binding(self) -> None:
        bundle = _bundle(extra="")
        payload = bundle.to_dict()
        source_uri = "hocus-project://city/assets/tuple.hocus"
        source = '''hocus 0.1; graph rocks { target "/obj/geo1"; category Sop;
          node source: "acme::source::1.0" { scale = [2, 3, 4]; }
          node sink: sink { input[0] = source; }
        }'''
        result = compile_source(source, "assets/tuple.hocus", source_uri=source_uri)
        provider = _provider()
        assert result.graph_spec is not None
        result.semantic_result = resolve_graph(result.graph_spec, provider)
        self.assertTrue(result.semantic_result.ready_for_document_lowering)
        result.source_kind = "project_file"
        result.project_uid = "city"
        result.project_manifest_digest = _digest("manifest")
        result.project_lock_digest = _digest("lock")
        result.catalog_fingerprint = provider.catalog.fingerprint
        result.catalog_content_digest = _digest(provider.catalog.to_json())
        tuple_bundle = CompiledBundle.from_result(result)
        preview = lower_bundle_to_document(tuple_bundle, _baseline())
        self.assertFalse(preview.valid)
        self.assertIsNone(preview.candidate_plan)
        self.assertIn("HOCUS708", {item["code"] for item in preview.diagnostics})
        self.assertFalse(any(isinstance(item.get("value"), list)
                             for item in preview.document["parameterBindings"]))

    def test_wrong_baseline_and_unresolved_bundle_are_rejected(self) -> None:
        baseline = _baseline()
        baseline["rootPath"] = "/obj/other"
        with self.assertRaises(DocumentLoweringError) as context:
            lower_bundle_to_document(_bundle(), baseline)
        self.assertEqual(context.exception.code, "HOCUS703")

    def test_pure_lowerer_blocks_expected_revision_drift(self) -> None:
        bundle = _bundle().to_dict()
        bundle["graphSpec"]["expectedRevision"] = 999
        unsigned = dict(bundle)
        unsigned.pop("bundleDigest")
        bundle["bundleDigest"] = _digest(json.dumps(unsigned, ensure_ascii=False, separators=(",", ":"), sort_keys=True))
        preview = lower_bundle_to_document(bundle, _baseline())
        self.assertFalse(preview.valid)
        self.assertIsNone(preview.candidate_plan)
        self.assertIn("HOCUS721", {item["code"] for item in preview.diagnostics})

    def test_public_compiled_bundle_constructor_cannot_bypass_strict_decode(self) -> None:
        forged = CompiledBundle("{}", "sha256:" + ("0" * 64))
        with self.assertRaises(BundleValidationError):
            lower_bundle_to_document(forged, _baseline())


if __name__ == "__main__":
    unittest.main()

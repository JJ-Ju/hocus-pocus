from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYTHON_LIBS = ROOT / "python3.11libs"
if str(PYTHON_LIBS) not in sys.path:
    sys.path.insert(0, str(PYTHON_LIBS))

from hocuspocus.live.ops.document import DocumentOperationsMixin


class _DocumentHarness(DocumentOperationsMixin):
    def _document_schema_path(self) -> Path:
        return ROOT / "docs" / "schemas" / "network-document-v1.schema.json"

    def _document_root_live_node(self, root_path: str):
        return None


class _FakeConnection:
    def __init__(self, source, input_index: int, output_index: int, input_name: str, output_name: str):
        self._source = source
        self._input_index = input_index
        self._output_index = output_index
        self._input_name = input_name
        self._output_name = output_name

    def inputNode(self):
        return self._source

    def inputIndex(self):
        return self._input_index

    def outputIndex(self):
        return self._output_index

    def inputName(self):
        return self._input_name

    def outputName(self):
        return self._output_name


class _FakeLiveNode:
    def __init__(self, path: str, uid: str | None = None):
        self._path = path
        self._user_data = {} if uid is None else {"hpmcp.uid": uid}
        self._connections = []
        self.set_user_data_calls = []

    def path(self):
        return self._path

    def userData(self, key: str):
        return self._user_data.get(key)

    def setUserData(self, key: str, value: str):
        self.set_user_data_calls.append((key, value))
        self._user_data[key] = value

    def inputConnections(self):
        return list(self._connections)


class _FakeHou:
    def __init__(self, nodes: list[_FakeLiveNode]):
        self.nodes = {node.path(): node for node in nodes}

    def node(self, path: str):
        return self.nodes.get(path)


class _LiveDocumentHarness(_DocumentHarness):
    def __init__(self, nodes: list[_FakeLiveNode]):
        self.hou = _FakeHou(nodes)
        self.connect_calls = []

    def _require_hou(self):
        return self.hou

    def _require_node_by_path(self, path: str, **_kwargs):
        return self.hou.node(path)

    @staticmethod
    def _safe_value(callable_or_value, fallback):
        try:
            return callable_or_value() if callable(callable_or_value) else callable_or_value
        except Exception:
            return fallback

    @staticmethod
    def _graph_subgraph_payload(snapshot, _root_path):
        return snapshot

    def _node_connect_impl(self, arguments):
        self.connect_calls.append(arguments)
        return {"connected": True}

    def _node_create_impl(self, arguments):
        path = f"{arguments['parent_path']}/{arguments['node_name']}"
        self.hou.nodes[path] = _FakeLiveNode(path)
        return {"path": path, "typeName": arguments["node_type_name"]}

    @staticmethod
    def _node_rename_impl(arguments):
        return {"path": f"{arguments['path'].rsplit('/', 1)[0]}/{arguments['new_name']}"}

    @staticmethod
    def _node_disconnect_impl(_arguments):
        return {"disconnected": True}


def _node(uid: str = "root", path: str = "/obj/geo1") -> dict:
    return {
        "uid": uid,
        "name": path.rsplit("/", 1)[-1],
        "typeName": "geo",
        "category": "Object",
        "path": path,
        "parentPath": path.rsplit("/", 1)[0],
        "isNetwork": True,
        "position": [0.0, 0.0],
        "flags": {"display": False, "render": False, "bypass": False, "template": False},
        "metadata": {},
    }


def _binding(name: str, value=0.0, *, value_mode: str = "literal") -> dict:
    binding = {
        "uid": f"parm:/obj/geo1/{name}",
        "nodeUid": "root",
        "parmName": name,
        "valueMode": value_mode,
        "metadata": {"path": f"/obj/geo1/{name}"},
    }
    if value_mode == "literal":
        binding["value"] = value
    return binding


def _managed_hocus(ownership: str, symbol: str = "managed") -> dict:
    return {
        "version": 1,
        "entityKind": "node",
        "projectUid": "test-project",
        "sourceUri": "hocus-project://test-project/main.hocus",
        "sourceDigest": "sha256:" + ("1" * 64),
        "bundleDigest": "sha256:" + ("2" * 64),
        "compilerVersion": "0.2.0",
        "languageVersion": "0.1",
        "graphName": "test_graph",
        "symbol": symbol,
        "ownership": ownership,
        "jsonPointer": "/nodes/0",
        "span": {
            "sourceUri": "hocus-project://test-project/main.hocus",
            "start": {"line": 1, "column": 1, "offset": 0},
            "end": {"line": 1, "column": 2, "offset": 1},
        },
    }


def _document(bindings: list[dict]) -> dict:
    return {
        "$schema": "hocuspocus://schemas/network-document/v1",
        "kind": "network_document",
        "documentId": "network:/obj/geo1",
        "documentRevision": 1,
        "rootPath": "/obj/geo1",
        "category": "Object",
        "nodes": [_node()],
        "edges": [],
        "parameterBindings": bindings,
        "codeBlobs": [],
        "diagnostics": [],
    }


def _connected_document(edges: list[dict]) -> dict:
    document = _document([])
    document["nodes"] = [
        _node("root", "/obj/geo1"),
        {**_node("source", "/obj/geo1/source"), "name": "source", "typeName": "split", "isNetwork": False, "parentPath": "/obj/geo1"},
        {**_node("merge", "/obj/geo1/merge"), "name": "merge", "typeName": "merge", "isNetwork": False, "parentPath": "/obj/geo1"},
    ]
    document["edges"] = edges
    return document


class DocumentFidelityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.operations = _DocumentHarness()

    def test_locked_schema_and_runtime_reject_unsupported_compound_modes(self) -> None:
        schema = json.loads((ROOT / "docs" / "schemas" / "network-document-v1.schema.json").read_text(encoding="utf-8"))
        modes = schema["$defs"]["parameterBinding"]["properties"]["valueMode"]["enum"]
        self.assertEqual(modes, ["literal", "expression", "channel_reference", "code_reference"])
        try:
            from jsonschema import Draft202012Validator
        except ImportError:
            Draft202012Validator = None
        if Draft202012Validator is not None:
            Draft202012Validator.check_schema(schema)
            validator = Draft202012Validator(schema)

        for mode in ("ramp", "multiparm"):
            document = _document([_binding("shape", value_mode=mode)])
            if Draft202012Validator is not None:
                self.assertTrue(list(validator.iter_errors(document)))
            diagnostics = self.operations._document_validate_network_document(document)
            codes = {item["code"] for item in diagnostics}
            self.assertIn("document.schema_violation", codes)
            self.assertIn("binding.value_mode.invalid", codes)

    def test_compound_literal_is_precisely_rejected_and_scalar_tuple_components_are_valid(self) -> None:
        compound = _document([_binding("size", [1.0, 2.0, 3.0])])
        try:
            from jsonschema import Draft202012Validator
        except ImportError:
            Draft202012Validator = None
        if Draft202012Validator is not None:
            schema = self.operations._document_schema_payload()
            self.assertTrue(list(Draft202012Validator(schema).iter_errors(compound)))
        diagnostics = self.operations._document_validate_network_document(compound)
        diagnostic = next(item for item in diagnostics if item["code"] == "binding.compound_value.unsupported")
        self.assertEqual(diagnostic["details"]["policy"], "scalar_component_bindings")
        self.assertEqual(diagnostic["jsonPointer"], "/parameterBindings/0/value")

        components = _document([
            _binding("sizex", 1.0),
            _binding("sizey", 2.0),
            _binding("sizez", 3.0),
        ])
        component_codes = {item["code"] for item in self.operations._document_validate_network_document(components)}
        self.assertNotIn("document.schema_violation", component_codes)
        self.assertNotIn("binding.compound_value.unsupported", component_codes)

    def test_runtime_shape_validation_uses_locked_schema(self) -> None:
        document = _document([])
        document["unexpected"] = True
        document["nodes"][0]["flags"]["display"] = "yes"
        diagnostics = self.operations._document_validate_network_document(document)
        schema_pointers = {
            item["jsonPointer"]
            for item in diagnostics
            if item["code"] == "document.schema_violation"
        }
        self.assertIn("/unexpected", schema_pointers)
        self.assertIn("/nodes/0/flags/display", schema_pointers)

    def test_schema_and_runtime_require_value_mode_payloads(self) -> None:
        schema = self.operations._document_schema_payload()
        try:
            from jsonschema import Draft202012Validator
        except ImportError:
            Draft202012Validator = None
        validator = Draft202012Validator(schema) if Draft202012Validator is not None else None
        cases = []
        literal = _binding("tx", 1.0)
        literal.pop("value")
        cases.append(literal)
        cases.append(_binding("tx", value_mode="expression"))
        cases.append(_binding("tx", value_mode="channel_reference"))
        cases.append(_binding("tx", value_mode="code_reference"))
        for binding in cases:
            with self.subTest(mode=binding["valueMode"]):
                document = _document([binding])
                if validator is not None:
                    self.assertTrue(list(validator.iter_errors(document)))
                diagnostics = self.operations._document_validate_network_document(document)
                self.assertIn("document.schema_violation", {item["code"] for item in diagnostics})

    def test_emitted_diagnostics_omit_schema_invalid_null_optionals(self) -> None:
        cleaned = self.operations._document_clean_diagnostics([
            {
                "severity": "error",
                "code": "example",
                "message": "Example diagnostic.",
                "path": None,
                "entityUid": None,
                "details": {"optional": None},
            }
        ])
        self.assertNotIn("path", cleaned[0])
        self.assertNotIn("entityUid", cleaned[0])
        self.assertEqual(cleaned[0]["details"], {"optional": None})

    def test_sparse_bindings_preserve_unauthored_values_and_verify_cleanly(self) -> None:
        baseline = _document([_binding("tx", 0.0), _binding("artist_detail", 7.5)])
        authored = _document([_binding("tx", 2.0)])

        plan = self.operations._document_build_apply_plan(baseline, authored, mode="reconcile")
        self.assertEqual([item["parmName"] for item in plan["parameterAssignments"]], ["tx"])
        self.assertEqual(plan["parameterResets"], [])

        refreshed = copy.deepcopy(authored)
        refreshed["parameterBindings"].append(_binding("artist_detail", 7.5))
        verification = self.operations._document_verification_diff_payload(authored, refreshed)
        self.assertTrue(self.operations._document_diff_is_clean(verification))

        ordinary_diff = self.operations._document_diff_payload(authored, refreshed)
        self.assertEqual(ordinary_diff["summary"]["changedBindingCount"], 1)

    def test_reconcile_deletes_only_nodes_in_the_explicit_ownership_namespace(self) -> None:
        owned = {
            **_node("owned", "/obj/geo1/owned"),
            "name": "owned",
            "isNetwork": False,
            "parentPath": "/obj/geo1",
            "metadata": {"hocus": {"ownership": "studio.rocks"}},
        }
        artist = {
            **_node("artist", "/obj/geo1/artist"),
            "name": "artist",
            "isNetwork": False,
            "parentPath": "/obj/geo1",
        }
        baseline = _document([])
        baseline["nodes"].extend([owned, artist])
        target = _document([])
        target["metadata"] = {"hocusPreview": {"ownership": "studio.rocks"}}

        plan = self.operations._document_build_apply_plan(baseline, target, mode="reconcile")

        self.assertEqual(plan["deleteNodes"], [{"uid": "owned", "currentPath": "/obj/geo1/owned"}])
        self.assertEqual(plan["protectedDeleteNodes"], [{"uid": "artist", "currentPath": "/obj/geo1/artist"}])
        self.assertEqual(plan["summary"]["protectedDeleteNodeCount"], 1)

    def test_reconcile_without_ownership_never_schedules_omission_deletes(self) -> None:
        baseline = _document([])
        baseline["nodes"].append({
            **_node("artist", "/obj/geo1/artist"),
            "name": "artist",
            "isNetwork": False,
            "parentPath": "/obj/geo1",
        })
        plan = self.operations._document_build_apply_plan(baseline, _document([]), mode="reconcile")
        self.assertEqual(plan["deleteNodes"], [])
        self.assertEqual(plan["summary"]["protectedDeleteNodeCount"], 1)

    def test_reconcile_authority_does_not_expand_from_preserved_foreign_entities(self) -> None:
        baseline = _document([])
        for uid, owner in (("rock-old", "studio.rocks"), ("character-kept", "studio.characters"), ("character-old", "studio.characters")):
            baseline["nodes"].append({
                **_node(uid, f"/obj/geo1/{uid}"),
                "name": uid,
                "isNetwork": False,
                "parentPath": "/obj/geo1",
                "metadata": {"hocus": {"ownership": owner}},
            })
        target = copy.deepcopy(baseline)
        target["nodes"] = [item for item in target["nodes"] if item["uid"] not in {"rock-old", "character-old"}]
        target["metadata"] = {"hocusPreview": {"ownership": "studio.rocks"}}

        plan = self.operations._document_build_apply_plan(baseline, target, mode="reconcile")
        self.assertEqual([item["uid"] for item in plan["deleteNodes"]], ["rock-old"])
        self.assertEqual([item["uid"] for item in plan["protectedDeleteNodes"]], ["character-old"])

    def test_managed_provenance_round_trips_and_authorizes_same_owner_reconcile(self) -> None:
        root = _FakeLiveNode("/obj/geo1", "root")
        managed = _FakeLiveNode("/obj/geo1/managed")
        operations = _LiveDocumentHarness([root, managed])
        payload = {
            **_node("managed-uid", "/obj/geo1/managed"),
            "metadata": {"hocus": _managed_hocus("studio.rocks")},
        }
        operations._document_stamp_live_node_metadata(managed.path(), payload)
        snapshot = {
            "revision": 9,
            "stats": {},
            "parms": [],
            "edges": [],
            "nodes": [
                {"path": root.path(), "name": "geo1", "typeName": "geo", "category": "Object", "parentPath": "/obj", "isNetwork": True},
                {"path": managed.path(), "name": "managed", "typeName": "null", "category": "Sop", "parentPath": root.path(), "isNetwork": False},
            ],
        }
        imported = operations._document_live_network_payload(snapshot, root.path())
        imported_managed = next(item for item in imported["nodes"] if item["uid"] == "managed-uid")
        self.assertEqual(imported_managed["metadata"]["hocus"], _managed_hocus("studio.rocks"))

        target = copy.deepcopy(imported)
        target["nodes"] = [item for item in target["nodes"] if item["uid"] != "managed-uid"]
        target["metadata"]["hocusPreview"] = {"ownership": "studio.rocks"}
        plan = operations._document_build_apply_plan(imported, target, mode="reconcile")
        self.assertEqual(plan["deleteNodes"], [{"uid": "managed-uid", "currentPath": managed.path()}])

        managed._user_data["hpmcp.provenance_sha256"] = "0" * 64
        untrusted = operations._document_live_network_payload(snapshot, root.path())
        untrusted_managed = next(item for item in untrusted["nodes"] if item["uid"] == "managed-uid")
        self.assertNotIn("hocus", untrusted_managed["metadata"])

    def test_authored_code_blob_body_participates_in_verification(self) -> None:
        binding = _binding("snippet", value_mode="code_reference")
        binding["codeBlobUid"] = "code:/obj/geo1/snippet"
        authored = _document([binding])
        authored["nodes"][0]["typeName"] = "attribwrangle"
        authored["codeBlobs"] = [{
            "uid": "code:/obj/geo1/snippet",
            "language": "vex",
            "target": {"nodeUid": "root", "parmName": "snippet", "bindingUid": binding["uid"]},
            "body": "@Cd = 1;",
            "metadata": {},
        }]
        refreshed = copy.deepcopy(authored)
        refreshed["codeBlobs"][0]["body"] = "@Cd = 0;"
        refreshed["parameterBindings"].append(_binding("artist_detail", 7.5))

        verification = self.operations._document_verification_diff_payload(authored, refreshed)
        self.assertEqual(verification["summary"]["changedBindingCount"], 0)
        self.assertEqual(verification["summary"]["changedCodeBlobCount"], 1)
        self.assertFalse(self.operations._document_diff_is_clean(verification))

    def test_live_import_is_read_only_and_reuses_fallback_node_uids(self) -> None:
        live_node = _FakeLiveNode("/obj/geo1")
        operations = _LiveDocumentHarness([live_node])

        first = operations._document_live_node_uid("/obj/geo1")
        second = operations._document_live_node_uid("/obj/geo1")

        self.assertTrue(first.startswith("node:"))
        self.assertEqual(second, first)
        self.assertIsNone(live_node.userData("hpmcp.uid"))
        self.assertEqual(live_node.set_user_data_calls, [])

    def test_explicit_adoption_schedules_and_executes_persistent_uid_stamp(self) -> None:
        root = _FakeLiveNode("/obj/geo1", "root")
        adopted = _FakeLiveNode("/obj/geo1/artist")
        operations = _LiveDocumentHarness([root, adopted])
        baseline = _connected_document([])
        baseline["nodes"] = [
            _node("root", "/obj/geo1"),
            {
                **_node("node:/obj/geo1/artist", "/obj/geo1/artist"),
                "name": "artist",
                "typeName": "null",
                "isNetwork": False,
                "parentPath": "/obj/geo1",
                "metadata": {"identityMode": "path_fallback"},
            },
        ]
        target = copy.deepcopy(baseline)
        target["nodes"][1]["metadata"]["hocus"] = {"entityKind": "adopted_node", "ownership": "studio.rocks"}

        plan = operations._document_build_apply_plan(baseline, target, mode="merge")
        self.assertEqual(len(plan["identityUpdates"]), 1)
        self.assertEqual(plan["identityUpdates"][0]["uid"], "node:/obj/geo1/artist")
        self.assertEqual(plan["identityUpdates"][0]["path"], "/obj/geo1/artist")
        executed = operations._document_execute_apply_plan(plan, baseline)
        self.assertIn(
            ("hpmcp.uid", "node:/obj/geo1/artist"),
            adopted.set_user_data_calls,
        )
        self.assertIn(("hpmcp.owner", "studio.rocks"), adopted.set_user_data_calls)
        self.assertEqual(executed[0]["type"], "stamp_node_uid")

    def test_document_created_nodes_are_stamped_with_authored_uid(self) -> None:
        operations = _LiveDocumentHarness([_FakeLiveNode("/obj/geo1", "root")])
        created = operations._document_create_live_node(
            {"uid": "node:authored", "path": "/obj/geo1/new_node", "parentPath": "/obj/geo1", "name": "new_node", "typeName": "null"}
        )
        self.assertEqual(created["path"], "/obj/geo1/new_node")
        self.assertEqual(operations.hou.node(created["path"]).userData("hpmcp.uid"), "node:authored")

    def test_live_import_reports_uids_duplicated_by_node_copy(self) -> None:
        root = _FakeLiveNode("/obj/geo1", "uid-root")
        first = _FakeLiveNode("/obj/geo1/a", "uid-copied")
        copied = _FakeLiveNode("/obj/geo1/a_copy", "uid-copied")
        operations = _LiveDocumentHarness([root, first, copied])
        snapshot = {
            "revision": 3,
            "stats": {},
            "parms": [],
            "edges": [],
            "nodes": [
                {"path": root.path(), "name": "geo1", "typeName": "geo", "category": "Object", "parentPath": "/obj", "isNetwork": True},
                {"path": first.path(), "name": "a", "typeName": "null", "category": "Sop", "parentPath": root.path(), "isNetwork": False},
                {"path": copied.path(), "name": "a_copy", "typeName": "null", "category": "Sop", "parentPath": root.path(), "isNetwork": False},
            ],
        }

        document = operations._document_live_network_payload(snapshot, root.path())

        duplicate = next(item for item in document["diagnostics"] if item["code"] == "node.uid.live_duplicate")
        self.assertEqual(duplicate["entityUid"], "uid-copied")
        self.assertEqual(duplicate["details"]["paths"], [first.path(), copied.path()])

    def test_connector_identity_and_variadic_slots_survive_import_plan_and_execute(self) -> None:
        root = _FakeLiveNode("/obj/geo1", "root")
        source = _FakeLiveNode("/obj/geo1/source", "source")
        merge = _FakeLiveNode("/obj/geo1/merge", "merge")
        merge._connections = [
            _FakeConnection(source, 12, 2, "groups", "inputs"),
            _FakeConnection(source, 37, 1, "remainder", "inputs"),
        ]
        operations = _LiveDocumentHarness([root, source, merge])
        snapshot = {
            "revision": 7,
            "stats": {},
            "parms": [],
            "edges": [],
            "nodes": [
                {"path": root.path(), "name": "geo1", "typeName": "geo", "category": "Object", "parentPath": "/obj", "isNetwork": True},
                {"path": source.path(), "name": "source", "typeName": "split", "category": "Sop", "parentPath": root.path(), "isNetwork": False},
                {"path": merge.path(), "name": "merge", "typeName": "merge", "category": "Sop", "parentPath": root.path(), "isNetwork": False},
            ],
        }
        imported = operations._document_live_network_payload(snapshot, root.path())
        self.assertEqual(
            [
                (edge["from"]["portIndex"], edge["from"]["portName"], edge["to"]["portIndex"], edge["to"]["portName"])
                for edge in imported["edges"]
            ],
            [(2, "groups", 12, "inputs"), (1, "remainder", 37, "inputs")],
        )
        self.assertEqual(
            {
                (port["direction"], port["index"], port["name"])
                for port in imported["ports"]
            },
            {
                ("output", 2, "groups"),
                ("output", 1, "remainder"),
                ("input", 12, "inputs"),
                ("input", 37, "inputs"),
            },
        )

        baseline = _connected_document([])
        target = _connected_document(copy.deepcopy(imported["edges"]))
        plan = operations._document_build_apply_plan(baseline, target, mode="merge")
        changes = plan["connectionChanges"]
        self.assertEqual([(item["inputIndex"], item["sourceOutputIndex"]) for item in changes], [(12, 2), (37, 1)])
        operations._document_execute_apply_plan(plan, baseline)
        self.assertEqual(
            [(call["dest_input_index"], call["source_output_index"]) for call in operations.connect_calls],
            [(12, 2), (37, 1)],
        )

    def test_data_edges_require_explicit_unique_endpoint_indexes(self) -> None:
        missing = _connected_document(
            [{"uid": "edge:missing", "kind": "data", "from": {"nodeUid": "source"}, "to": {"nodeUid": "merge", "portIndex": 3}}]
        )
        self.assertIn(
            "edge.port_index.missing",
            {item["code"] for item in self.operations._document_validate_network_document(missing)},
        )
        try:
            from jsonschema import Draft202012Validator
        except ImportError:
            Draft202012Validator = None
        if Draft202012Validator is not None:
            self.assertTrue(list(Draft202012Validator(self.operations._document_schema_payload()).iter_errors(missing)))

        duplicate = _connected_document(
            [
                {"uid": "edge:a", "kind": "data", "from": {"nodeUid": "source", "portIndex": 0}, "to": {"nodeUid": "merge", "portIndex": 3}},
                {"uid": "edge:b", "kind": "data", "from": {"nodeUid": "source", "portIndex": 1}, "to": {"nodeUid": "merge", "portIndex": 3}},
            ]
        )
        self.assertIn(
            "edge.destination.duplicate",
            {item["code"] for item in self.operations._document_validate_network_document(duplicate)},
        )


if __name__ == "__main__":
    unittest.main()

"""Private runtime assertions for H5 live provenance round-trips."""

from __future__ import annotations

import copy
import logging
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from hocuspocus.core.jsonrpc import JsonRpcError
from hocuspocus.hocusscript.document_reconcile import (
    protected_owned_dependencies,
    reconcile_owned_state,
)
from hocuspocus.live.context import OperationCancelledError, RequestContext
from hocuspocus.live.graph_store import (
    GraphStorePlanError,
    GraphStoreSchemaError,
    LiveGraphStore,
)
from hocuspocus.live.ops.graph import GraphOperationsMixin
from hocuspocus.live.ops.document_network_families import (
    connection_mismatch,
    network_family_policy,
    resolve_network_family,
)


def assert_managed_provenance_round_trip(
    test,
    tools,
    root,
    managed,
    node_hocus,
    expansion,
    network_document,
):
    strict_default_calls = []

    class StrictDefaultParm:
        def isAtDefault(self, **arguments):
            strict_default_calls.append(arguments)
            return True

    class FailingDefaultParm:
        @staticmethod
        def isAtDefault(**_arguments):
            raise RuntimeError("unavailable")

    test.assertTrue(
        GraphOperationsMixin._parm_is_strict_default(
            tools,
            StrictDefaultParm(),
        )
    )
    test.assertEqual(
        strict_default_calls,
        [{
            "compare_temporary_defaults": False,
            "compare_expressions": True,
        }],
    )
    test.assertFalse(
        GraphOperationsMixin._parm_is_strict_default(
            tools,
            FailingDefaultParm(),
        )
    )

    nodes_by_path = {"/obj/geo1": root, "/obj/geo1/managed": managed}
    tools._require_hou = lambda: SimpleNamespace(
        node=lambda path: nodes_by_path.get(path)
    )
    tools._require_node_by_path = lambda path: nodes_by_path[path]
    root.setUserData(tools._DOCUMENT_NODE_UID_KEY, "root")

    node_hocus["managedFields"] = {
        "type": True,
        "inputs": [0],
        "parameters": ["snippet"],
        "flags": {"output": True},
        "nodeUid": "managed",
    }
    tools._document_stamp_live_node_metadata(
        "/obj/geo1/managed",
        {"uid": "managed", "metadata": {"hocus": node_hocus}},
    )
    tools._document_stamp_live_expansion_provenance("/obj/geo1", expansion)

    def derived(kind, pointer, offset):
        hocus = copy.deepcopy(node_hocus)
        hocus.pop("managedFields")
        hocus["entityKind"] = kind
        hocus["jsonPointer"] = pointer
        hocus["span"]["start"]["offset"] = offset
        hocus["span"]["start"]["column"] = offset + 1
        hocus["span"]["end"]["offset"] = offset + 1
        hocus["span"]["end"]["column"] = offset + 2
        return {"hocus": hocus}

    target = network_document()
    target["nodes"].append({
        "uid": "managed",
        "name": "managed",
        "typeName": "attribwrangle",
        "category": "Sop",
        "path": "/obj/geo1/managed",
        "parentPath": "/obj/geo1",
        "isNetwork": False,
        "position": [1.0, 0.0],
        "flags": {
            "display": True,
            "render": False,
            "bypass": False,
            "template": False,
        },
        "metadata": {"hocus": copy.deepcopy(node_hocus)},
    })
    target["ports"] = [
        {
            "uid": f"port:managed:{direction}:0",
            "nodeUid": "managed",
            "direction": direction,
            "name": "",
            "index": 0,
            "kind": "data",
            "metadata": derived("port", "/nodes/0/inputs/0", 10),
        }
        for direction in ("input", "output")
    ]
    target["edges"] = [{
        "uid": "edge:data:managed:0",
        "kind": "data",
        "from": {"nodeUid": "managed", "portIndex": 0},
        "to": {"nodeUid": "managed", "portIndex": 0},
        "metadata": derived("edge", "/nodes/0/inputs/0", 20),
    }, {
        "uid": "edge:output:root",
        "kind": "output_flag",
        "from": {"nodeUid": "managed"},
        "to": {"nodeUid": "root"},
        "metadata": derived("output_flag", "/output", 30),
    }]
    target["parameterBindings"] = [{
        "uid": "binding:managed:snippet",
        "nodeUid": "managed",
        "parmName": "snippet",
        "valueMode": "code_reference",
        "codeBlobUid": "code:managed:snippet",
        "metadata": derived(
            "parameter_binding", "/nodes/0/parameters/0", 40
        ),
    }]
    target["codeBlobs"] = [{
        "uid": "code:managed:snippet",
        "language": "vex",
        "target": {
            "nodeUid": "managed",
            "parmName": "snippet",
            "bindingUid": "binding:managed:snippet",
        },
        "body": "@P *= 2;",
        "metadata": derived(
            "code_blob", "/nodes/0/parameters/0/value", 50
        ),
    }]
    target["metadata"] = {"hocusExpansion": expansion}
    change = tools._document_plan_root_entity_provenance(
        network_document(), target
    )
    tools._document_execute_root_entity_provenance(
        {"rootEntityProvenanceChange": change}, [], lambda: None
    )

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
            "outputNodePath": "/obj/geo1/managed",
        }, {
            "path": "/obj/geo1/managed",
            "name": "managed",
            "typeName": "attribwrangle",
            "category": "Sop",
            "parentPath": "/obj/geo1",
            "isNetwork": False,
            "position": [1.0, 0.0],
            "flags": {"display": True},
        }],
        "parms": [{
            "nodePath": "/obj/geo1/managed",
            "path": "/obj/geo1/managed/snippet",
            "name": "snippet",
            "rawValue": "@P *= 2;",
            "templateType": "string",
            "isAtDefault": True,
        }],
        "stats": {},
    }
    tools._document_live_input_connections = (
        lambda path, ignored_input_item_names=None: (
        [{
            "sourcePath": "/obj/geo1/managed",
            "inputIndex": 0,
            "outputIndex": 0,
            "connectionOrder": 0,
        }]
        if path == "/obj/geo1/managed"
        else []
        )
    )
    snapshot = tools._document_live_network_payload(
        {"revision": 9}, "/obj/geo1"
    )
    expected = {
        entity["uid"]: entity["metadata"]["hocus"]
        for field in ("ports", "edges", "parameterBindings", "codeBlobs")
        for entity in target[field]
    }
    restored = {
        entity["uid"]: entity["metadata"].get("hocus")
        for field in ("ports", "edges", "parameterBindings", "codeBlobs")
        for entity in snapshot[field]
    }
    test.assertEqual(restored, expected)
    snapshot_binding = snapshot["parameterBindings"][0]
    test.assertTrue(snapshot_binding["metadata"]["isAtDefault"])

    default_observation = copy.deepcopy(snapshot_binding)
    default_observation["uid"] = "binding:managed:cacheinput"
    default_observation["parmName"] = "cacheinput"
    default_observation["metadata"].pop("hocus", None)
    protected_baseline = copy.deepcopy(snapshot)
    protected_baseline["parameterBindings"].append(default_observation)
    references, _ = protected_owned_dependencies(
        protected_baseline,
        "studio.asset",
        set(),
        set(),
    )
    test.assertEqual(references, [])
    protected_baseline["parameterBindings"][-1]["metadata"][
        "isAtDefault"
    ] = False
    protected_baseline["parameterBindings"][-1]["valueMode"] = "expression"
    protected_baseline["parameterBindings"][-1]["expression"] = "$F"
    references, _ = protected_owned_dependencies(
        protected_baseline,
        "studio.asset",
        set(),
        set(),
    )
    test.assertEqual(
        [(field, uid) for field, _, uid in references],
        [("parameterBindings", "binding:managed:cacheinput")],
    )

    repeatable = copy.deepcopy(snapshot)
    test.assertEqual(
        reconcile_owned_state(
            repeatable,
            "studio.asset",
            set(),
            {"managed"},
        ),
        [],
    )

    top_container = SimpleNamespace(
        childTypeCategory=lambda: SimpleNamespace(name=lambda: "Top")
    )
    test.assertEqual(
        resolve_network_family(
            SimpleNamespace(node=lambda _path: top_container),
            "/obj/topnet1",
            "Object",
        ),
        "top",
    )
    test.assertEqual(
        resolve_network_family(None, "/obj/dopnet1", "Dop"),
        "dop",
    )
    for family in ("sop", "mat", "lop", "top"):
        test.assertTrue(network_family_policy(family).structural_indexed_apply)
    for family in ("object", "rop", "dop", "cop", "chop", "generic"):
        test.assertFalse(network_family_policy(family).structural_indexed_apply)

    output_context = {
        "rootUid": "root",
        "rootPath": "/stage",
        "after": {
            "root": {"path": "/stage", "flags": {}},
            "managed": {"path": "/stage/managed", "flags": {"display": True}},
        },
    }
    test.assertEqual(
        tools._document_plan_output(target, target, output_context, "lop"),
        (None, None),
    )
    with test.assertRaises(JsonRpcError):
        tools._document_execute_finalizers(
            {
                "networkFamily": "lop",
                "outputChange": {"rootPath": "/stage", "sourceUid": "managed"},
            },
            {"uidToPath": {"managed": "/stage/managed"}},
            [],
            lambda: None,
        )

    expected_connection = {
        "sourcePath": "/stage/source",
        "inputIndex": 2,
        "sourceOutputIndex": 1,
        "sourceOutputName": "surface",
        "destInputName": "material",
    }
    observed_connection = {
        "sourcePath": "/stage/source",
        "inputIndex": 2,
        "outputIndex": 1,
        "outputName": "surface",
        "inputName": "material",
    }
    test.assertIsNone(
        connection_mismatch(expected_connection, observed_connection)
    )
    for field, value in (
        ("outputIndex", 0),
        ("outputName", "volume"),
        ("inputName", "displacement"),
    ):
        drifted = {**observed_connection, field: value}
        test.assertIsNotNone(
            connection_mismatch(expected_connection, drifted)
        )


def assert_plan_persistence_failure_mapping(
    test, operations, service, plan, network_document,
):
    durable: dict[str, dict] = {}
    deleted: list[str] = []

    def delete_unclaimed(plan_id, *, expected_hash):
        test.assertEqual(expected_hash, plan["planHash"])
        durable.pop(plan_id, None)
        deleted.append(plan_id)
        return True

    def fail_after_insert(*, payload):
        durable[payload["planId"]] = copy.deepcopy(payload)
        raise sqlite3.OperationalError("database or disk is full")

    operations._documents = service
    operations._graph_store = SimpleNamespace(
        store_immutable_plan=fail_after_insert,
        delete_unclaimed_plan=delete_unclaimed,
    )
    with test.assertRaises(JsonRpcError) as raised:
        operations._hocus_persist_apply_plan(
            plan, 60.0, RequestContext()
        )
    test.assertEqual(raised.exception.data["diagnosticCode"], "HOCUS759")
    test.assertIsNone(
        service.apply_plan(plan["planId"], expected_hash=plan["planHash"])
    )
    test.assertEqual(durable, {})

    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / "domain-adapter.sqlite3"
        store = LiveGraphStore(logging.getLogger("test.adapter"), path)
        operations._graph_store = store
        with mock.patch(
            "hocuspocus.live.graph_store_sqlite.sqlite3.connect",
            side_effect=sqlite3.OperationalError("unable to open database file"),
        ):
            with test.assertRaises(JsonRpcError) as connect_error:
                operations._hocus_store_call(
                    lambda: store.load_immutable_plan("missing")
                )
        test.assertEqual(
            connect_error.exception.data["diagnosticCode"], "HOCUS759"
        )

        with closing(sqlite3.connect(str(path))) as connection:
            connection.execute("DROP TABLE plan_apply_commits")
            connection.commit()
        with test.assertRaises(JsonRpcError) as recovery_error:
            operations._hocus_store_call(
                lambda: store.load_plan_commit(plan_commit_id="missing")
            )
        test.assertEqual(
            recovery_error.exception.data["diagnosticCode"], "HOCUS759"
        )

        with test.assertRaises(GraphStoreSchemaError):
            operations._hocus_store_call(
                lambda: _raise_schema_error_inside(store)
            )
    test.assertEqual(deleted, [plan["planId"]])

    cancelled = RequestContext()

    def insert_then_cancel(*, payload):
        durable[payload["planId"]] = copy.deepcopy(payload)
        cancelled.cancel()

    operations._graph_store = SimpleNamespace(
        store_immutable_plan=insert_then_cancel,
        delete_unclaimed_plan=delete_unclaimed,
    )
    with test.assertRaises(OperationCancelledError):
        operations._hocus_persist_apply_plan(plan, 60.0, cancelled)
    test.assertIsNone(
        service.apply_plan(plan["planId"], expected_hash=plan["planHash"])
    )
    test.assertEqual(durable, {})

    def fail_recovery_scan():
        raise GraphStorePlanError("recovery query failed")

    operations._graph_store = SimpleNamespace(
        recoverable_plan_commits=fail_recovery_scan
    )
    if hasattr(operations, "_hocus_apply_quarantines"):
        del operations._hocus_apply_quarantines
    with test.assertRaises(JsonRpcError) as hydration_error:
        operations._hocus_quarantine_map()
    test.assertEqual(
        hydration_error.exception.data["diagnosticCode"], "HOCUS759"
    )
    test.assertFalse(hasattr(operations, "_hocus_apply_quarantines"))

    quarantine = {"/obj/keep": {"reason": "durable recovery required"}}
    operations._hocus_apply_quarantines = copy.deepcopy(quarantine)
    operations._document_current_network_payload = (
        lambda _scope, force_sync: network_document()
    )
    operations._document_validate_network_document = lambda _document: []
    with test.assertRaises(JsonRpcError) as recover_error:
        operations.document_recover_scope(
            {"rootPath": "/obj/geo1"}, RequestContext()
        )
    test.assertEqual(
        recover_error.exception.data["diagnosticCode"], "HOCUS759"
    )
    test.assertEqual(operations._hocus_apply_quarantines, quarantine)

    discard_calls: list[str] = []

    def begin_discard(**_arguments):
        discard_calls.append("begin")

    def fail_discard_finish(**_arguments):
        discard_calls.append("finish")
        raise GraphStorePlanError("discard terminalization failed")

    def fail_discard_verification(**_arguments):
        discard_calls.append("verify")
        raise GraphStorePlanError("discard verification failed")

    discard_plan = copy.deepcopy(plan)
    discard_plan["baseline"]["document"] = network_document()
    discard_plan["inversePlan"] = {"operations": []}
    operations._graph_store = SimpleNamespace(
        load_immutable_plan=lambda _plan_id: {
            "payload": copy.deepcopy(discard_plan)
        },
        begin_plan_commit=begin_discard,
        finish_plan_commit=fail_discard_finish,
        load_plan_commit=fail_discard_verification,
    )
    with test.assertRaises(JsonRpcError) as discard_error:
        operations.document_discard_plan(
            {"planId": plan["planId"], "planHash": plan["planHash"]},
            RequestContext(),
        )
    test.assertEqual(
        discard_error.exception.data["diagnosticCode"], "HOCUS759"
    )
    test.assertEqual(discard_calls, ["begin", "finish", "verify"])


def _raise_schema_error_inside(store):
    with store._connect():
        raise GraphStoreSchemaError("explicit schema inconsistency")

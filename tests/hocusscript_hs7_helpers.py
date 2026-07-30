from __future__ import annotations

import hashlib
import json
import tempfile
import copy
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from hocuspocus.hocusscript import (
    ControlResolverLimits,
    FakeCatalogProvider,
    expand_control_graph,
    export_network_document,
    format_syntax,
    graph_spec_from_dict,
    parse_syntax,
    resolve_graph,
)
from hocuspocus.hocusscript.catalog import ParameterDefinition
from hocuspocus.hocusscript.bundle import BundleValidationError
from hocuspocus.hocusscript.bundle_graph_validation import validate_graph_spec
from hocuspocus.hocusscript.bundle_semantic_validation import (
    _validate_connection_selections,
)
from hocuspocus.hocusscript.control_artifact import _compile_control_bundle
from hocuspocus.hocusscript._document_bundle_boundary import (
    _decode_document_bundle_content,
)
from hocuspocus.hocusscript.document_bundle_lowering import (
    _lower_decoded_document_bundle_to_document,
)
from hocuspocus.hocusscript.document_lowering import (
    DocumentLoweringError,
    _append_diff_operations,
    _document_diff,
)
from hocuspocus.hocusscript.document_baseline_entities import destructive_summary
from tests.hocusscript_hs7_live_value_helpers import (
    assert_h21_ramp_adapter_surface,
)
from hocuspocus.live.ops.document_editor_entities import (
    _comment_uid,
    _document_sticky_text_size,
    _disconnect_dot_outputs,
    _dot_outputs,
    _hom_sticky_text_size,
    _snapshot_box,
)
from hocuspocus.live.ops.hocusscript import HocusScriptOperationsMixin
from tests import hocusscript_hs7_runtime_helpers as runtime_helpers
from hocuspocus.hocusscript.document_editor_lowering import lower_editor_entities
from hocuspocus.hocusscript.export_editor_entities import render_editor_entities


def _digest(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _without_source_locations(value):
    if isinstance(value, dict):
        return {
            key: _without_source_locations(item)
            for key, item in value.items()
            if key not in {"span", "bodySpan", "offsetMap"}
        }
    if isinstance(value, list):
        return [_without_source_locations(item) for item in value]
    return value


def _assert_full_typed_binding_diff(testcase, operations) -> None:
    common = {
        "uid": "binding", "nodeUid": "node", "parmName": "value",
        "valueMode": "literal", "metadata": {
            "parameterSelection": {"valueAdapter": {"kind": "literal"}}
        },
    }
    cases = (
        ("menuToken", "a", "b"),
        ("raw", "$HIP/a", "$HIP/b"),
        ("canonicalMagnitude", 1.0, 2.0),
        ("points", [{"position": 0.0}], [{"position": 1.0}]),
        ("instances", [{"instanceId": "a"}], [{"instanceId": "b"}]),
        ("parameterSelection", common["metadata"]["parameterSelection"], {
            "valueAdapter": {"kind": "quantity"}
        }),
    )
    for field, before_value, after_value in cases:
        before, after = copy.deepcopy(common), copy.deepcopy(common)
        if field == "parameterSelection":
            before["metadata"][field] = before_value
            after["metadata"][field] = after_value
        else:
            before[field], after[field] = before_value, after_value
        changed = operations._document_changed_bindings(
            {("node", "value"): before}, {("node", "value"): after}
        )
        testcase.assertEqual(len(changed), 1, field)
        testcase.assertIn(field, changed[0]["changes"])
    before, after = copy.deepcopy(common), copy.deepcopy(common)
    before["metadata"].update(path="/obj/g/value", label="Value")
    after["metadata"].update(path="/obj/g/value", isAtDefault=True)
    testcase.assertEqual(
        operations._document_changed_bindings(
            {("node", "value"): before}, {("node", "value"): after}
        ),
        [],
    )


def assert_catalog_tuple_namespace_rejected(testcase, snapshot) -> None:
    operator = next(
        item for item in snapshot.operators
        if any(parameter.tuple_names for parameter in item.parameters)
    )
    tuple_parameter = next(
        item for item in operator.parameters if item.tuple_names
    )
    colliding_root = next(
        item.token for item in operator.parameters
        if item.token != tuple_parameter.token
    )
    collision = FakeCatalogProvider.create(
        categories=snapshot.categories,
        operators=tuple(
            replace(
                item,
                parameters=tuple(
                    replace(
                        parameter,
                        tuple_names=(
                            colliding_root,
                            *parameter.tuple_names[1:],
                        ),
                    )
                    if parameter.token == tuple_parameter.token
                    else parameter
                    for parameter in item.parameters
                ),
            )
            if item == operator else item
            for item in snapshot.operators
        ),
        packages=snapshot.packages,
        catalog_version=snapshot.catalog_version,
    )
    values = ", ".join(
        "1.0" for _ in range(tuple_parameter.tuple_size)
    )
    source = (
        f'hocus 0.4; graph G {{ target "/obj/g"; category {operator.category}; '
        f'node n: "{operator.qualified_name}" {{ '
        f"{tuple_parameter.token} = [{values}]; }} }}"
    )
    graph = graph_spec_from_dict(
        expand_control_graph(
            source.encode("utf-8"),
            "hocus-project://test/tuple-collision.hocus",
            {},
            {},
        )
    )
    semantic = resolve_graph(graph, collision)
    testcase.assertFalse(semantic.valid)
    testcase.assertIn("HOCUS931", {item.code for item in semantic.diagnostics})
    _assert_named_ports(testcase, snapshot)
    _assert_editor_entities(testcase)
    from tests.hocusscript_hs7_runtime_helpers import (
        assert_managed_spare_and_animation_contract,
    )
    assert_managed_spare_and_animation_contract(testcase)
    _assert_runtime_source_lane(testcase, snapshot)


def _assert_runtime_source_lane(testcase, snapshot) -> None:
    from hocuspocus.hocusscript.document_provenance import (
        DocumentProvenanceIndex,
    )
    from hocuspocus.hocusscript.document_runtime_lowering import (
        lower_work_runtime_entities,
    )
    from hocuspocus.hocusscript.export_runtime_entities import (
        render_runtime_entities,
    )
    from hocuspocus.hocusscript.runtime_semantic import (
        validate_runtime_evidence,
    )

    operator = next(
        item for item in snapshot.operators
        if any(
            parm.value_type in {"float", "tuple"}
            and parm.tuple_names
            for parm in item.parameters
        )
    )
    component = next(
        parm.tuple_names[0] for parm in operator.parameters
        if parm.value_type in {"float", "tuple"}
        and parm.tuple_names
    )
    rich = FakeCatalogProvider.create(
        categories=snapshot.categories,
        operators=tuple(
            replace(
                item, spare_parameter_policy="allowed",
                locked=False, editable=True, instance_network=False,
            )
            for item in snapshot.operators
        ),
        packages=snapshot.packages,
        catalog_version=2,
    )
    source = (
        'hocus 0.4; graph Runtime { target "/obj/g"; '
        f"category {operator.category}; ownership \"team\"; "
        f'node n @id("node.n"): "{operator.qualified_name}" {{ '
        'spare gain @id("spare.gain") { label = "Gain"; type = "float"; '
        'tuple_size = 1; default = [0.0]; menu_items = []; } '
        f'animate {component} @id("anim.value") {{ value_type = "float"; '
        'value = 0.0; authored_fps = 24.0; display_fps = 24.0; '
        'extrapolation = ["constant", "linear"]; '
        'keys = [[0.0, 0.0, "linear"], '
        '[1.0, 1.0, "bezier", 1.0, 1.0]]; } } }'
    )
    syntax = parse_syntax(source, "runtime.hocus")
    formatted = format_syntax(syntax)
    testcase.assertEqual(
        format_syntax(parse_syntax(formatted, "runtime.hocus")), formatted,
    )
    encoded = expand_control_graph(
        source.encode(), "hocus-project://test/runtime.hocus", {}, {},
    )
    graph = graph_spec_from_dict(encoded)
    semantic = resolve_graph(graph, rich)
    testcase.assertTrue(semantic.valid, semantic.diagnostics)
    semantic_payload = semantic.to_dict()
    testcase.assertEqual(
        {item["kind"] for item in semantic_payload["runtimeSelections"]},
        {"spare", "animation"},
    )
    validate_runtime_evidence(
        encoded, semantic_payload["runtimeSelections"],
        semantic_payload["parameterSelections"],
    )
    runtime_helpers.assert_runtime_semantic_trust(testcase, encoded, semantic_payload)
    with testcase.assertRaises(ValueError):
        validate_runtime_evidence(encoded, [])
    node_symbol = encoded["nodes"][0]["symbol"]
    document = {
        "$schema": "hocuspocus://schemas/network-document/v2",
        "kind": "network_document", "documentId": "network:/obj/g",
        "documentRevision": 0, "rootPath": "/obj/g",
        "nodes": [{"uid": "node.n", "path": "/obj/g/n"}],
        "parameterBindings": [{
            "uid": "binding", "nodeUid": "node.n",
            "parmName": component, "valueMode": "literal", "value": 0.0,
        }],
        "spareParameters": [], "animations": [],
    }
    payload = {
        "projectUid": "test", "compilerVersion": "0.6.0",
        "languageVersion": "0.4",
        "entrySource": {
            "uri": "hocus-project://test/runtime.hocus",
            "digest": _digest(source),
        },
        "dependencies": [],
    }
    work = SimpleNamespace(
        graph=encoded, payload=payload, bundle_digest=_digest("bundle"),
        document=document, baseline=copy.deepcopy(document),
        generated_by_symbol={
            node_symbol: {"uid": "node.n", "path": "/obj/g/n"}
        },
        ownership="team", document_provenance=(
            DocumentProvenanceIndex.from_graph(encoded)
        ),
        source_map_entities={},
    )
    lower_work_runtime_entities(work)
    testcase.assertEqual(
        work.document["spareParameters"][0]["metadata"]["hocus"]["ownership"],
        "team",
    )
    lines, targets, errors = render_runtime_entities(
        work.document, {"node.n": "n"}, "team",
    )
    testcase.assertFalse(errors)
    testcase.assertIn(("node.n", component), targets)
    testcase.assertIn('spare gain @id("spare.gain")', "\n".join(lines["node.n"]))
    _assert_runtime_fold_identity(testcase, operator)


def _assert_runtime_fold_identity(testcase, operator) -> None:
    source = (
        'hocus 0.4; graph Fold { target "/obj/g"; '
        f"category {operator.category}; ownership \"team\"; "
        'for series @id("series") (i in range(2)) '
        'carry (value: int = 0) { '
        f'node n @id("n"): "{operator.qualified_name}" {{ '
        'spare gain @id("spare.gain") { label = "Gain"; type = "float"; '
        'tuple_size = 1; default = [0.0]; menu_items = []; } } '
        'yield value = iter.i; } }'
    )
    graph = expand_control_graph(
        source.encode(), "hocus-project://test/fold-runtime.hocus", {}, {},
    )
    testcase.assertTrue(all(
        item["explicitId"].startswith("hocus.")
        and item["explicitId"] != "n"
        for item in graph["nodes"]
    ))
    identities = [item["explicitId"] for item in graph["spareParameters"]]
    testcase.assertEqual(len(set(identities)), 2)
    mappings = [
        item for item in graph["expansionMap"]["mappings"]
        if item["generatedPointer"].startswith("/spareParameters/")
    ]
    testcase.assertEqual(len(mappings), 2)
    testcase.assertTrue(all(item["controlStackId"] for item in mappings))


def _assert_named_ports(testcase, snapshot) -> None:
    rich = FakeCatalogProvider.create(
        categories=snapshot.categories,
        operators=tuple(
            replace(item, instance_network=False)
            for item in snapshot.operators
        ),
        packages=snapshot.packages,
        catalog_version=2,
    )
    source = (
        'hocus 0.4; graph Named { target "/obj/g"; category Sop; '
        'node a: "acme::source::1.0" {} node b: "sink" { '
        'input["source"] = a.output["geometry"]; } }'
    )
    syntax = parse_syntax(source, "named.hocus")
    testcase.assertIn(
        'input["source"] = a.output["geometry"];', format_syntax(syntax)
    )
    encoded = expand_control_graph(
        source.encode(), "hocus-project://test/named.hocus", {}, {},
    )
    authored = encoded["nodes"][1]["inputs"][0]
    testcase.assertEqual(
        (authored["name"], authored["source"]["outputName"]),
        ("source", "geometry"),
    )
    validate_graph_spec(
        encoded, graph_spec_version="0.5",
        module_dependencies={},
        entry_source_uri="hocus-project://test/named.hocus",
    )
    ambiguous = copy.deepcopy(encoded)
    ambiguous["nodes"][1]["inputs"][0]["index"] = 0
    with testcase.assertRaises(BundleValidationError):
        validate_graph_spec(
            ambiguous, graph_spec_version="0.5",
            module_dependencies={},
            entry_source_uri="hocus-project://test/named.hocus",
        )
    graph = graph_spec_from_dict(encoded)
    semantic = resolve_graph(graph, rich)
    testcase.assertTrue(semantic.valid, semantic.diagnostics)
    selection = semantic.connection_selections[0]
    testcase.assertEqual(
        (
            selection.input_index, selection.input_name,
            selection.output_index, selection.output_name,
        ),
        (0, "source", 0, "geometry"),
    )
    records = [selection.to_dict()]
    _validate_connection_selections(records, encoded)
    forged = copy.deepcopy(records)
    forged[0]["outputName"] = "wrong"
    with testcase.assertRaises(BundleValidationError):
        _validate_connection_selections(forged, encoded)
    dynamic = FakeCatalogProvider.create(
        categories=rich.catalog.categories,
        operators=tuple(
            replace(
                item,
                outputs=tuple(
                    replace(port, cardinality="many")
                    if item.qualified_name == "acme::source::1.0"
                    and port.name == "geometry" else port
                    for port in item.outputs
                ),
            )
            for item in rich.catalog.operators
        ),
        packages=rich.catalog.packages,
        catalog_version=2,
    )
    rejected = resolve_graph(graph, dynamic)
    testcase.assertFalse(rejected.valid)
    testcase.assertIn("HOCUS641", {item.code for item in rejected.diagnostics})


def _assert_editor_entities(testcase) -> None:
    source = '''hocus 0.4;
graph Editor {
  target "/obj/g";
  ownership "team";
  layout = auto;
  node src @id("src"): "null" {}
  node dst @id("dst"): "null" {}
  network_dot @id("dot.route") {
    position = [1, 2];
    input = node src.output[0];
    outputs = [node dst.input[0]];
  }
  network_box @id("box.main") {
    label = "Main";
    position = [0, 0];
    size = [6, 4];
    items = [node src, dot "dot.route"];
  }
  sticky_note @id("note.main") {
    text = "Managed";
    position = [4, 2];
    size = [3, 2];
  }
  node_comment @id("comment.src") {
    node = node src;
    text = "Source";
  }
  layout_constraint @id("layout.row") {
    kind = "align_y";
    items = [node dst, dot "dot.route"];
    anchor = node src;
  }
}
'''
    uri = "hocus-project://test/editor.hocus"
    syntax = parse_syntax(source, uri)
    formatted = format_syntax(syntax)
    testcase.assertIn(
        "outputs = [node dst.input[0]];", formatted,
    )
    encoded = expand_control_graph(source.encode(), uri, {}, {})
    testcase.assertEqual(len(encoded["editorEntities"]), 5)
    testcase.assertEqual(
        [item["explicitId"] for item in encoded["nodes"]],
        ["src", "dst"],
    )
    legacy = expand_control_graph(
        (
            'hocus 0.3; graph Legacy { target "/obj/g"; '
            'node src @id("src"): "null" {} }'
        ).encode(),
        "hocus-project://test/editor-legacy.hocus",
        {},
        {},
    )
    testcase.assertNotEqual(legacy["nodes"][0]["explicitId"], "src")
    testcase.assertEqual(
        graph_spec_from_dict(encoded).to_dict()["editorEntities"],
        encoded["editorEntities"],
    )
    validate_graph_spec(encoded, graph_spec_version="0.5")
    forged = copy.deepcopy(encoded)
    forged["nodes"][1]["inputs"] = [{
        "index": 0,
        "source": {
            "symbol": forged["nodes"][0]["symbol"],
            "outputIndex": 0,
            "span": forged["nodes"][0]["span"],
        },
        "span": forged["nodes"][1]["span"],
    }]
    with testcase.assertRaises(BundleValidationError):
        validate_graph_spec(forged, graph_spec_version="0.5")
    colliding = copy.deepcopy(encoded)
    colliding["editorEntities"][0]["explicitId"] = (
        colliding["nodes"][0]["explicitId"]
    )
    with testcase.assertRaises(BundleValidationError):
        validate_graph_spec(colliding, graph_spec_version="0.5")
    node_ids = {
        name: encoded["nodes"][index]["explicitId"]
        for index, name in enumerate(("src", "dst"))
    }
    symbols = {
        node_ids[name]: encoded["nodes"][index]["symbol"]
        for index, name in enumerate(("src", "dst"))
    }
    nodes = {
        symbol: {
            "uid": identity, "position": [0.0, 0.0] if identity == node_ids["src"]
            else [3.0, 2.0],
        }
        for identity, symbol in symbols.items()
    }
    document = {
        "$schema": "hocuspocus://schemas/network-document/v2",
        "nodes": list(nodes.values()),
        "networkBoxes": [], "stickyNotes": [], "nodeComments": [],
        "networkDots": [], "layoutConstraints": [],
    }
    payload = {
        "projectUid": "test", "compilerVersion": "0.6.0",
        "languageVersion": "0.4",
        "entrySource": {"uri": uri, "digest": _digest(source)},
        "dependencies": [],
    }
    lowered = lower_editor_entities(
        graph=encoded,
        payload=payload,
        bundle_digest=_digest("bundle"),
        document=document,
        generated_by_symbol=nodes,
        external_by_symbol={},
        document_provenance=None,
    )
    dot = lowered["dot.route"]
    testcase.assertEqual(
        document["networkBoxes"][0]["color"],
        [0.5199999809265137] * 3,
    )
    testcase.assertEqual(
        document["stickyNotes"][0]["color"],
        [1.0, 0.968999981880188, 0.5220000147819519],
    )
    testcase.assertEqual(
        dot["outputs"], [{"nodeUid": node_ids["dst"], "inputIndex": 0}]
    )
    testcase.assertNotIn("edges", document)
    testcase.assertEqual(nodes[symbols[node_ids["dst"]]]["position"][1], 0.0)
    lines, errors = render_editor_entities(
        document, {node_ids["src"]: "src", node_ids["dst"]: "dst"}, "team",
    )
    testcase.assertFalse(errors)
    testcase.assertIn(
        "    outputs = [node dst.input[0]];", lines,
    )
    recompiled = expand_control_graph(
        (
            'hocus 0.4; graph Editor { target "/obj/g"; ownership "team"; '
            'node src @id("src"): "null" {} '
            'node dst @id("dst"): "null" {}\n'
            + "\n".join(lines)
            + "\n}"
        ).encode(),
        "hocus-project://test/editor-export.hocus",
        {},
        {},
    )
    route = next(
        item for item in recompiled["editorEntities"]
        if item["kind"] == "network_dot"
    )
    testcase.assertEqual(route["outputs"][0]["inputIndex"], 0)
    testcase.assertEqual(
        route["outputs"][0]["nodeRef"]["identity"],
        recompiled["nodes"][1]["symbol"],
    )
    _assert_editor_live_adapter_contract(testcase)
    _assert_complete_document_diff(testcase)


def _assert_editor_live_adapter_contract(testcase) -> None:
    testcase.assertEqual(_hom_sticky_text_size(0.0), 1.0)
    for text_size in (0.1, 1.0, 1.25, 10.0):
        testcase.assertEqual(
            _hom_sticky_text_size(
                _document_sticky_text_size(text_size)
            ),
            text_size,
        )

    class Dot:
        name = lambda self: "managed_dot"

    dot = Dot()

    class Node:
        def __init__(self, source=None) -> None:
            self.disconnected = []
            self.source = source or Dot()

        def path(self):
            return "/obj/g/dst"

        def inputsWithIndices(self):
            return ((self.source, 7, 3),)

        def setInput(self, index, value):
            self.disconnected.append((index, value))

    node = Node()
    parent = SimpleNamespace(children=lambda: (node,))
    testcase.assertEqual(
        _dot_outputs(parent, dot, {"/obj/g/dst": "dst"}),
        [{"nodeUid": "dst", "inputIndex": 3}],
    )
    _disconnect_dot_outputs(dot, {"dst": node})
    testcase.assertEqual(node.disconnected, [(3, None)])
    wrong = Node(SimpleNamespace(name=lambda: "managed_dot"))
    _disconnect_dot_outputs(dot, {"dst": wrong})
    testcase.assertEqual(wrong.disconnected, [])

    class Item:
        def __init__(self, name):
            self._name = name

        def name(self):
            return self._name

        def path(self):
            return f"/obj/g/{self._name}"

    class Box:
        comment = lambda self: "Outer"
        position = lambda self: (0.0, 0.0)
        size = lambda self: (4.0, 2.0)
        color = lambda self: None
        name = lambda self: "outer"

        def items(self, recurse=True):
            return (
                (Item("direct"), Item("nested"))
                if recurse else (Item("direct"),)
            )

    box = Box()
    snapshot = _snapshot_box(
        box,
        {"outer": "box", "direct": "direct", "nested": "nested"},
        {},
        {},
    )
    testcase.assertEqual(snapshot["itemUids"], ["direct"])
    testcase.assertEqual(
        _comment_uid(
            "src",
            {"comment.src": {
                "entityKind": "node_comment",
                "nodeUid": "src",
            }},
        ),
        "comment.src",
    )


def _assert_complete_document_diff(testcase) -> None:
    collections = (
        "networkBoxes", "stickyNotes", "nodeComments", "networkDots",
        "layoutConstraints", "spareParameters", "animations",
    )
    empty = {field: [] for field in collections}
    before = {
        field: [{"uid": field, "value": "before"}]
        for field in collections
    }
    after = {
        field: [{"uid": field, "value": "after"}]
        for field in collections
    }
    created = _document_diff(empty, after)
    changed = _document_diff(before, after)
    deleted = _document_diff(after, empty)
    testcase.assertEqual(created["summary"]["totalChangeCount"], 7)
    testcase.assertEqual(changed["summary"]["totalChangeCount"], 7)
    testcase.assertEqual(deleted["summary"]["totalChangeCount"], 7)
    testcase.assertEqual(created["summary"]["createdNetworkBoxCount"], 1)
    testcase.assertEqual(changed["summary"]["changedSpareParameterCount"], 1)
    testcase.assertEqual(deleted["summary"]["deletedAnimationCount"], 1)

    action_counts = []
    for diff in (created, changed, deleted):
        operations = []
        _append_diff_operations(
            operations, {"entities": {}, "operations": {}}, diff, 0,
        )
        action_counts.append([item["action"] for item in operations])
    testcase.assertEqual(action_counts[0].count("create_editor_entity"), 5)
    testcase.assertIn("create_spare_parameter", action_counts[0])
    testcase.assertIn("create_animation", action_counts[0])
    testcase.assertEqual(action_counts[1].count("update_editor_entity"), 5)
    testcase.assertIn("update_spare_parameter", action_counts[1])
    testcase.assertIn("update_animation", action_counts[1])
    testcase.assertEqual(action_counts[2].count("delete_editor_entity"), 5)
    testcase.assertIn("remove_spare_parameter", action_counts[2])
    testcase.assertIn("clear_animation", action_counts[2])

    summary = destructive_summary(changed, set())
    testcase.assertTrue(summary["destructive"])
    testcase.assertEqual(summary["changedEditorEntityCount"], 5)
    testcase.assertEqual(summary["updatedSpareParameterCount"], 1)
    testcase.assertEqual(summary["updatedAnimationCount"], 1)
    for action in (
        "update_editor_entity", "remove_spare_parameter", "clear_animation",
    ):
        testcase.assertTrue(
            HocusScriptOperationsMixin._hocus_confirmation_required(
                {"operations": [{"action": action}]}, {},
            )
        )


def assert_heuristic_tuple_evidence_rejected(testcase, provider) -> None:
    source = (
        'hocus 0.4; graph G { target "/obj/g"; category Sop; '
        'node source: "acme::source::1.0" { scale = [1.0, 2.0, 3.0]; } }'
    )
    graph = graph_spec_from_dict(
        expand_control_graph(
            source.encode("utf-8"),
            "hocus-project://test/tuple-evidence.hocus",
            {},
            {},
        )
    )
    inconsistent = FakeCatalogProvider.create(
        categories=provider.catalog.categories,
        operators=tuple(
            replace(
                operator,
                parameters=tuple(
                    replace(
                        parameter,
                        tags={**parameter.tags, "elementType": "int"},
                    )
                    if parameter.token == "scale"
                    else parameter
                    for parameter in operator.parameters
                ),
            )
            for operator in provider.catalog.operators
        ),
        catalog_version=provider.catalog.catalog_version,
    )
    for candidate in (provider, inconsistent):
        semantic = resolve_graph(graph, candidate)
        testcase.assertFalse(semantic.valid)
        testcase.assertIn("HOCUS931", {item.code for item in semantic.diagnostics})


def value_bundle(provider):
    operators = tuple(
        replace(
            operator,
            parameters=tuple(
                replace(
                    parameter,
                    tags=(
                        {**parameter.tags, "elementType": "float"}
                        if parameter.token == "scale" else parameter.tags
                    ),
                    value_contract=None,
                )
                for parameter in operator.parameters
            ),
            instance_network=(
                operator.source.kind == "hda"
                and operator.category == "Sop"
            ),
        )
        for operator in provider.catalog.operators
    )
    rich = FakeCatalogProvider.create(
        categories=provider.catalog.categories,
        operators=operators,
        packages=provider.catalog.packages,
        catalog_version=2,
    )
    source = (
        'hocus 0.4; graph G { target "/obj/geo1"; category Sop; '
        'node source @id("source"): "acme::source::1.0" { '
        'scale = [2.0, 3.0, 4.0]; } display = source; render = source; '
        'output = source; }'
    )
    uri = "hocus-project://city/assets/value.hocus"
    graph = expand_control_graph(source.encode("utf-8"), uri, {}, {})
    digest = lambda value: "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()
    resolved = {
        "$schema": "hocuspocus://schemas/resolved-module-set/v3",
        "kind": "hocus_resolved_module_set",
        "schemaVersion": 3,
        "languageVersion": "0.4",
        "projectUid": "city",
        "entrySourceUri": uri,
        "projectManifestDigest": digest("value-manifest"),
        "projectLockDigest": digest("value-lock"),
        "resolverPolicyDigest": digest("value-policy"),
        "limits": ControlResolverLimits().to_dict(),
        "modules": [],
    }
    bundle = _compile_control_bundle(
        graph,
        resolved,
        entry_source_digest=digest(source),
        catalog=rich,
        catalog_content_digest=digest(rich.catalog.to_json()),
        catalog_fingerprint=rich.catalog.fingerprint,
        admitted_required_capabilities=("edit_scene",),
    )
    return bundle.to_dict(), rich


def assert_tagged_value_pipeline(
    testcase, operations_type, context_type, provider,
) -> None:
    direct_source = (
        'hocus 0.4; graph DirectIdentity { target "/obj/direct"; '
        'node source @id("stable.root"): "acme::source::1.0" {} }'
    )
    direct_graph = expand_control_graph(
        direct_source.encode(),
        "hocus-project://city/assets/direct-identity.hocus",
        {},
        {},
    )
    testcase.assertEqual(direct_graph["nodes"][0]["symbol"], "source")
    testcase.assertEqual(direct_graph["nodes"][0]["explicitId"], "stable.root")
    frozen_graph = expand_control_graph(
        direct_source.replace("hocus 0.4", "hocus 0.3").encode(),
        "hocus-project://city/assets/frozen-identity.hocus",
        {},
        {},
    )
    testcase.assertTrue(frozen_graph["nodes"][0]["symbol"].startswith("__hocus_"))
    testcase.assertNotEqual(
        frozen_graph["nodes"][0]["explicitId"], "stable.root",
    )
    additions = (
        ParameterDefinition("reset_value", "Reset", "float", 1, (), 0.0),
        ParameterDefinition(
            "file_value", "File", "file_path", 1, (), "",
        ),
        ParameterDefinition(
            "distance", "Distance", "float", 1, (), 0.0,
            value_contract={
                "kind": "quantity",
                "dimension": "length",
                "canonicalUnit": "m",
                "units": [{"unit": "m", "scale": 1.0, "offset": 0.0}],
            },
        ),
        ParameterDefinition(
            "integer_pair", "Integer Pair", "tuple", 2,
            ("integer_pairx", "integer_pairy"), (0, 0),
            tags={"elementType": "int"},
            value_contract={
                "kind": "quantity",
                "dimension": "count",
                "canonicalUnit": "item",
                "units": [
                    {"unit": "item", "scale": 1.0, "offset": 0.0},
                    {"unit": "half", "scale": 0.5, "offset": 0.0},
                ],
            },
        ),
        ParameterDefinition("expr_value", "Expr", "float", 1, (), 0.0),
        ParameterDefinition("linked", "Linked", "float", 1, (), 0.0),
        ParameterDefinition(
            "curve", "Curve", "ramp", 1, (), None,
            assignable=False,
            value_contract={
                "kind": "ramp",
                "rampKind": "float",
                "allowedBases": ["linear"],
            },
        ),
        ParameterDefinition(
            "items", "Items", "multiparm", 1, (), None,
            assignable=False,
            value_contract={
                "kind": "multiparm",
                "instanceStart": 0,
                "minInstances": 0,
                "maxInstances": 8,
                "fields": [{
                    "name": "count",
                    "tokenTemplate": "count#",
                    "valueType": "int",
                    "tupleSize": 1,
                    "elementType": None,
                }, {
                    "name": "file",
                    "tokenTemplate": "file#",
                    "valueType": "file_path",
                    "tupleSize": 1,
                    "elementType": None,
                }],
            },
        ),
    )
    operators = tuple(
        replace(
            operator,
            parameters=tuple(
                replace(parameter, value_contract=None)
                for parameter in operator.parameters
            ) + (additions if operator.qualified_name == "acme::source::1.0" else ()),
            instance_network=(
                operator.source.kind == "hda"
                and operator.category == "Sop"
            ),
        )
        for operator in provider.catalog.operators
    )
    rich = FakeCatalogProvider.create(
        categories=provider.catalog.categories,
        operators=operators,
        packages=provider.catalog.packages,
        catalog_version=2,
    )
    quantity_cases = {
        "whole": "integer_pair = quantity(2.0, \"half\");",
        "fractional": "integer_pairx = quantity(1.0, \"half\");",
    }
    for label, assignment in quantity_cases.items():
        candidate = (
            'hocus 0.4; graph Quantity { target "/obj/geo1"; '
            'category Sop; node source: "acme::source::1.0" { '
            f"{assignment} }} }}"
        )
        rejected = resolve_graph(
            graph_spec_from_dict(expand_control_graph(
                candidate.encode(),
                f"hocus-project://city/assets/{label}.hocus", {}, {},
            )),
            rich,
        )
        testcase.assertFalse(rejected.valid, label)
        testcase.assertIn(
            "HOCUS932", {item.code for item in rejected.diagnostics}, label
        )
    component_source = (
        'hocus 0.4; graph Quantity { target "/obj/geo1"; category Sop; '
        'node source: "acme::source::1.0" { '
        'integer_pairx = quantity(2.0, "half"); } }'
    )
    component_semantic = resolve_graph(
        graph_spec_from_dict(expand_control_graph(
            component_source.encode(),
            "hocus-project://city/assets/component.hocus", {}, {},
        )),
        rich,
    )
    testcase.assertTrue(component_semantic.valid, component_semantic.diagnostics)
    testcase.assertIs(
        component_semantic.parameter_selections[0]
        .value_adapter["canonicalMagnitude"],
        1,
    )
    source = '''hocus 0.4;
graph Typed {
  target "/obj/geo1";
  category Sop;
  node source @id("source"): "acme::source::1.0" {
    reset_value = reset();
    file_value = raw_path(file, "$HIP/a.bgeo");
    distance = quantity(2.0, "m");
    expr_value = expression(hscript`$F * 2`);
    linked = channel(source, sx);
    curve = ramp(points = [[0.0, 0.0], [1.0, 1.0]], basis = ["linear", "linear"]);
    items = multiparm(instances = [instance("a", {
      count = 3; file = raw_path(file, "$HIP/item.bgeo");
    })]);
  }
}
'''
    formatted = format_syntax(parse_syntax(source, "typed.hocus"))
    testcase.assertEqual(
        format_syntax(parse_syntax(formatted, "typed.hocus")), formatted
    )
    uri = "hocus-project://city/assets/typed.hocus"
    graph = expand_control_graph(source.encode("utf-8"), uri, {}, {})
    wrong_path = source.replace(
        'raw_path(file, "$HIP/item.bgeo")',
        'raw_path(node, "/obj/item")',
    )
    wrong_semantic = resolve_graph(
        graph_spec_from_dict(
            expand_control_graph(wrong_path.encode("utf-8"), uri, {}, {})
        ),
        rich,
    )
    testcase.assertFalse(wrong_semantic.valid)
    testcase.assertIn("HOCUS932", {
        item.code for item in wrong_semantic.diagnostics
    })
    resolved = {
        "$schema": "hocuspocus://schemas/resolved-module-set/v3",
        "kind": "hocus_resolved_module_set",
        "schemaVersion": 3,
        "languageVersion": "0.4",
        "projectUid": "city",
        "entrySourceUri": uri,
        "projectManifestDigest": _digest("typed-manifest"),
        "projectLockDigest": _digest("typed-lock"),
        "resolverPolicyDigest": _digest("typed-policy"),
        "limits": ControlResolverLimits().to_dict(),
        "modules": [],
    }
    carrier = _compile_control_bundle(
        graph,
        resolved,
        entry_source_digest=_digest(source),
        catalog=rich,
        catalog_content_digest=_digest(rich.catalog.to_json()),
        catalog_fingerprint=rich.catalog.fingerprint,
        admitted_required_capabilities=("edit_scene",),
    ).to_dict()
    operations = operations_type(catalog=rich.catalog)
    assert_h21_ramp_adapter_surface(testcase)
    decoded = _decode_document_bundle_content(carrier)
    with testcase.assertRaises(DocumentLoweringError) as missing_trust:
        _lower_decoded_document_bundle_to_document(
            decoded, operations.baseline
        )
    testcase.assertEqual(missing_trust.exception.code, "HOCUS701")
    forged_carrier = copy.deepcopy(carrier)
    forged_selection = next(
        item for item in forged_carrier["semanticResolution"]
        ["parameterSelections"]
        if item.get("valueAdapter", {}).get("kind") == "quantity"
    )
    forged_selection["valueAdapter"]["canonicalMagnitude"] = 9.0
    unsigned = copy.deepcopy(forged_carrier)
    unsigned.pop("bundleDigest")
    encoded = json.dumps(
        unsigned, ensure_ascii=False, separators=(",", ":"),
        sort_keys=True, allow_nan=False,
    ).encode()
    forged_carrier["bundleDigest"] = (
        "sha256:" + hashlib.sha256(encoded).hexdigest()
    )
    forged_preview = operations.document_preview_bundle(
        {"bundle": forged_carrier}, context_type()
    )["structuredContent"]
    testcase.assertFalse(forged_preview["valid"])
    testcase.assertEqual(
        forged_preview["diagnostics"][0]["code"], "HOCUS722"
    )
    preview = operations.document_preview_bundle(
        {"bundle": carrier}, context_type()
    )["structuredContent"]
    testcase.assertTrue(preview["valid"], preview["diagnostics"])
    document = preview["preview"]["document"]
    bindings = {
        item["parmName"]: item for item in document["parameterBindings"]
    }
    nodes = {item["uid"]: item for item in document["nodes"]}
    testcase.assertTrue(all(
        binding["parmName"]
        in nodes[binding["nodeUid"]]["metadata"]["hocus"]
        ["managedFields"]["parameters"]
        for binding in bindings.values()
    ))
    testcase.assertEqual(
        {item["valueMode"] for item in bindings.values()},
        {
            "reset", "raw_path", "quantity", "expression",
            "channel_reference", "ramp", "multiparm",
        },
    )
    export_document = copy.deepcopy(document)
    for node in export_document["nodes"]:
        node["metadata"]["identityMode"] = "persistent_user_data"
    exported = export_network_document(
        export_document, graph_name="Typed", catalog=rich,
    )
    testcase.assertTrue(
        exported.valid,
        [item.to_dict() for item in exported.diagnostics],
    )
    exported_graph = expand_control_graph(
        exported.source.encode(),
        "hocus-project://city/assets/typed-export.hocus",
        {},
        {},
    )
    expected_values = {
        item["name"]: _without_source_locations(item["value"])
        for item in graph["nodes"][0]["parms"]
    }
    round_trip_values = {
        item["name"]: _without_source_locations(item["value"])
        for item in exported_graph["nodes"][0]["parms"]
    }
    testcase.assertEqual(round_trip_values, expected_values)
    plan = operations._document_build_apply_plan(
        operations.baseline, document, mode="merge"
    )
    testcase.assertEqual(plan["summary"]["parameterResetCount"], 1)
    testcase.assertEqual(plan["summary"]["parameterAssignmentCount"], 2)
    testcase.assertEqual(plan["summary"]["expressionUpdateCount"], 2)
    testcase.assertEqual(plan["summary"]["typedValueUpdateCount"], 2)
    _assert_full_typed_binding_diff(testcase, operations)
    forged = copy.deepcopy(document)
    quantity = next(
        item for item in forged["parameterBindings"]
        if item["valueMode"] == "quantity"
    )
    quantity["canonicalMagnitude"] = 9.0
    diagnostics = operations._document_validate_network_document(forged)
    testcase.assertIn("binding.v2.invalid", {
        item["code"] for item in diagnostics
    })


def assert_value_preview_bindings(testcase, preview) -> None:
    bindings = preview["preview"]["document"]["parameterBindings"]
    selected = {item["parmName"]: item["value"] for item in bindings}
    testcase.assertEqual(
        {key: selected[key] for key in ("sx", "sy", "sz")},
        {"sx": 2.0, "sy": 3.0, "sz": 4.0},
    )


def assert_value_plan_apply(
    testcase,
    operations_type,
    context_type,
    apply_arguments,
    provider,
) -> None:
    carrier, rich = value_bundle(provider)
    with tempfile.TemporaryDirectory() as temporary:
        operations = operations_type(Path(temporary) / "value.sqlite3")
        operations.catalog = rich.catalog
        context = context_type(permissions=("edit_scene",))
        plan = operations.document_plan_bundle(
            {"bundle": carrier},
            context,
        )["structuredContent"]
        testcase.assertEqual(plan["stage"], "document_plan")
        result = operations.document_apply_plan(
            apply_arguments(plan, "apply-value"),
            context,
        )["structuredContent"]
        testcase.assertEqual(operations.catalog_request, "0.5")
        testcase.assertTrue(result["applied"])
        testcase.assertTrue(result["verified"])

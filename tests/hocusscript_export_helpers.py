"""Focused assertions for normalized source-export identity behavior."""

from __future__ import annotations

import copy
from dataclasses import replace
from typing import Any

from hocuspocus.hocusscript import compile_source, export_network_document
from hocuspocus.hocusscript.catalog import (
    CategoryDefinition,
    FakeCatalogProvider,
)
from hocuspocus.hocusscript.document_live_names import live_node_names
from hocuspocus.hocusscript.export_editor_entities import _ref as _editor_ref


def assert_managed_export_symbol_identity(
    case: Any,
    live_document: dict[str, Any],
    provider: Any,
) -> bool:
    """Prove flat export retains the authenticated managed graph symbol."""

    case.assertEqual(_editor_ref("box", {}, {"box": "network_box"}), 'box "box"')
    case.assertEqual(_editor_ref("note", {}, {"note": "sticky_note"}), 'sticky "note"')
    case.assertEqual(_editor_ref("dot", {}, {"dot": "network_dot"}), 'dot "dot"')
    expanded_document = copy.deepcopy(live_document)
    expanded_source = next(
        node for node in expanded_document["nodes"] if node["name"] == "source"
    )
    expanded_symbol = "__hocus_" + "a" * 64
    expanded_source["metadata"]["hocus"]["symbol"] = expanded_symbol
    expanded_name = live_node_names([{"symbol": expanded_symbol}])[
        expanded_symbol
    ]
    expanded_source["name"] = expanded_name
    expanded_source["path"] = (
        expanded_source["parentPath"].rstrip("/") + "/" + expanded_name
    )
    exported = export_network_document(
        expanded_document,
        graph_name="exported_rocks",
        catalog=provider,
    )
    case.assertTrue(
        exported.valid,
        [item.to_dict() for item in exported.diagnostics],
    )
    case.assertIn(
        f'node {expanded_symbol} @id("asset.source-01"):',
        exported.source,
    )
    case.assertIn(
        f"input[0] = {expanded_symbol}.output[1];",
        exported.source,
    )
    compiled = compile_source(exported.source, "expanded_identity_export.hocus")
    case.assertTrue(
        compiled.valid,
        [item.to_dict() for item in compiled.diagnostics],
    )
    case.assertIn(
        expanded_symbol,
        {node.symbol for node in compiled.graph_spec.nodes},
    )
    case.assertEqual(
        exported.provenance["managedFields"]["asset.source-01"]["symbol"],
        expanded_symbol,
    )
    forged_document = copy.deepcopy(expanded_document)
    forged_source = next(
        node
        for node in forged_document["nodes"]
        if node["uid"] == "asset.source-01"
    )
    forged_source["metadata"]["hocus"]["symbol"] = "invalid symbol"
    forged = export_network_document(
        forged_document,
        graph_name="exported_rocks",
        catalog=provider,
    )
    case.assertFalse(forged.valid)
    case.assertIn("HOCUS803", {item.code for item in forged.diagnostics})
    stale_document = copy.deepcopy(expanded_document)
    stale_source = next(
        node
        for node in stale_document["nodes"]
        if node["uid"] == "asset.source-01"
    )
    stale_source["metadata"]["hocus"]["symbol"] = "__hocus_" + "b" * 64
    stale = export_network_document(
        stale_document,
        graph_name="exported_rocks",
        catalog=provider,
    )
    case.assertFalse(stale.valid)
    case.assertIn("HOCUS803", {item.code for item in stale.diagnostics})
    collision_document = copy.deepcopy(live_document)
    collision_source = next(
        node for node in collision_document["nodes"] if node["name"] == "source"
    )
    collision_sink = next(
        node for node in collision_document["nodes"] if node["name"] == "sink"
    )
    collision_symbol = "__hocus_" + "c" * 64
    generated_base = live_node_names([{"symbol": collision_symbol}])[
        collision_symbol
    ]
    collision_source["metadata"]["hocus"]["symbol"] = collision_symbol
    collision_sink["metadata"]["hocus"]["symbol"] = generated_base
    collision_names = live_node_names([
        {"symbol": collision_symbol},
        {"symbol": generated_base},
    ])
    for node, symbol in (
        (collision_source, collision_symbol),
        (collision_sink, generated_base),
    ):
        node["name"] = collision_names[symbol]
        node["path"] = node["parentPath"].rstrip("/") + "/" + node["name"]
    collision = export_network_document(
        collision_document,
        graph_name="exported_rocks",
        catalog=provider,
    )
    case.assertTrue(
        collision.valid,
        [item.to_dict() for item in collision.diagnostics],
    )
    case.assertIn(f"node {collision_symbol} @id(", collision.source)
    case.assertIn(f"node {generated_base} @id(", collision.source)
    _assert_named_v2_export(case, expanded_document, provider)
    assert_fixed_family_export_contract(case, live_document, provider)
    return True


def _assert_named_v2_export(
    case: Any, document: dict[str, Any], provider: Any,
) -> None:
    snapshot = provider.get_catalog()
    rich = FakeCatalogProvider.create(
        categories=snapshot.categories,
        operators=tuple(
            replace(item, instance_network=bool(item.instance_network))
            for item in snapshot.operators
        ),
        packages=snapshot.packages,
        catalog_version=2,
    )
    typed = copy.deepcopy(document)
    typed["$schema"] = "hocuspocus://schemas/network-document/v2"
    exported = export_network_document(
        typed, graph_name="exported_rocks", catalog=rich,
    )
    case.assertTrue(exported.valid, [item.to_dict() for item in exported.diagnostics])
    case.assertEqual(exported.to_dict()["languageVersion"], "0.4")
    case.assertIn('input["source"] = ', exported.source)
    case.assertIn('.output["points"];', exported.source)
    foreign = copy.deepcopy(typed)
    node_uid = next(
        item["uid"] for item in foreign["nodes"]
        if not item.get("isNetwork")
    )
    foreign["spareParameters"] = [{
        "uid": "spare:foreign", "nodeUid": node_uid, "name": "foreign",
        "label": "Foreign", "type": "float", "tupleSize": 1,
        "default": [0.0], "menuItems": [],
        "metadata": {"hocus": {"ownership": "another-team"}},
    }]
    case.assertFalse(export_network_document(
        foreign, graph_name="exported_rocks", catalog=rich,
    ).valid)


def assert_fixed_family_export_contract(
    case: Any,
    live_document: dict[str, Any],
    provider: Any,
) -> None:
    """Exercise exact category emission and indexed fixed-port denial."""

    document = copy.deepcopy(live_document)
    document["documentId"] = "network:/stage"
    document["rootPath"] = "/stage"
    document["category"] = "Manager"
    document.setdefault("metadata", {})["networkFamily"] = "lop"
    root = next(node for node in document["nodes"] if node.get("isNetwork"))
    root.update({
        "name": "stage", "path": "/stage", "parentPath": "/",
        "category": "Manager",
    })
    for node in document["nodes"]:
        if node is root:
            continue
        node["category"] = "Lop"
        node["parentPath"] = "/stage"
        node["path"] = "/stage/" + node["name"]
        node["flags"].update({"display": False, "render": False})
    document["edges"] = [
        item for item in document["edges"] if item.get("kind") == "data"
    ]
    snapshot = provider.get_catalog()
    operators = []
    for operator in snapshot.operators:
        operators.append(replace(
            operator,
            category="Lop",
            inputs=tuple(
                replace(item, categories=("Lop",))
                for item in operator.inputs
            ),
            outputs=tuple(
                replace(item, categories=("Lop",))
                for item in operator.outputs
            ),
            network_families=("lop",),
        ))
    lop_provider = FakeCatalogProvider.create(
        categories=(CategoryDefinition("Lop", "LOP", "lop"),),
        operators=tuple(operators),
    )
    exported = export_network_document(
        document, graph_name="exported_lop", catalog=lop_provider,
    )
    case.assertTrue(
        exported.valid,
        [item.to_dict() for item in exported.diagnostics],
    )
    case.assertIn("  category Lop;", exported.source)

    unnamed = copy.deepcopy(document)
    for edge in unnamed["edges"]:
        edge["from"].pop("portName", None)
        edge["to"].pop("portName", None)
    for port in unnamed["ports"]:
        port["name"] = ""
    unnamed_operators = tuple(
        replace(
            operator,
            inputs=tuple(replace(item, name=None) for item in operator.inputs),
            outputs=tuple(replace(item, name=None) for item in operator.outputs),
        )
        for operator in operators
    )
    unnamed_provider = FakeCatalogProvider.create(
        categories=(CategoryDefinition("Lop", "LOP", "lop"),),
        operators=unnamed_operators,
    )
    unnamed_export = export_network_document(
        unnamed, graph_name="exported_lop_unnamed", catalog=unnamed_provider,
    )
    case.assertTrue(
        unnamed_export.valid,
        [item.to_dict() for item in unnamed_export.diagnostics],
    )

    source_uid = next(
        edge["from"]["nodeUid"]
        for edge in unnamed["edges"]
        if edge.get("kind") == "data"
    )
    source_type = next(
        node["typeName"]
        for node in unnamed["nodes"]
        if node.get("uid") == source_uid
    )
    dynamic_operators = tuple(
        replace(
            operator,
            outputs=(
                replace(
                    operator.outputs[0],
                    index=None,
                    name="variadic",
                    cardinality="many",
                ),
            ),
        )
        if operator.qualified_name == source_type and operator.outputs
        else operator
        for operator in unnamed_operators
    )
    dynamic_provider = FakeCatalogProvider.create(
        categories=(CategoryDefinition("Lop", "LOP", "lop"),),
        operators=dynamic_operators,
    )
    rejected = export_network_document(
        unnamed, graph_name="exported_lop_dynamic", catalog=dynamic_provider,
    )
    case.assertFalse(rejected.valid)
    case.assertTrue(
        {"HOCUS807", "HOCUS813"}.intersection(
            item.code for item in rejected.diagnostics
        )
    )

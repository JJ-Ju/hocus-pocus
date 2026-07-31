"""HS7 whole-tuple lowering into scalar network-document v1 bindings."""

from __future__ import annotations

from typing import Any

from .document_provenance import (
    entity_metadata,
    entity_source_map,
)


def lower_tuple_bindings(
    work: Any,
    node_spec: dict[str, Any],
    target_node: dict[str, Any],
    parm: dict[str, Any],
    pointer: str,
    selection: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    tokens = selection.get("componentTokens")
    items = parm["value"].get("items")
    if (
        work.payload.get("bundleVersion") != "0.5"
        or not isinstance(tokens, list)
        or not isinstance(items, list)
        or selection.get("tupleSize") != len(tokens)
        or len(tokens) != len(items)
    ):
        work.diagnostics.append({
            "severity": "error",
            "code": "HOCUS708",
            "message": (
                f"Whole-tuple parameter '{selection['parameterToken']}' lacks "
                "authenticated component-token evidence."
            ),
            "jsonPointer": f"/graphSpec{pointer}/value",
            "path": target_node["path"],
            "entityUid": target_node["uid"],
        })
        return [], {}
    bindings: list[dict[str, Any]] = []
    source_maps: dict[str, dict[str, Any]] = {}
    for index, (token, item) in enumerate(zip(tokens, items)):
        binding_uid = f"binding:{target_node['uid']}:{token}"
        item_pointer = f"{pointer}/value/items/{index}"
        metadata = entity_metadata(
            work.payload, work.bundle_digest, work.graph, node_spec["symbol"],
            item_pointer, item.get("span"), work.ownership,
            work.document_provenance, entity_kind="parameter_binding",
        )
        metadata["parameterSelection"] = {
            "authoredToken": selection["authoredToken"],
            "parameterToken": selection["parameterToken"],
            "componentIndex": index,
            "componentToken": token,
            "tupleSize": selection["tupleSize"],
            "elementType": selection["elementType"],
            "conversion": selection["conversion"],
            "menuToken": selection["menuToken"],
        }
        bindings.append({
            "uid": binding_uid,
            "nodeUid": target_node["uid"],
            "parmName": token,
            "valueMode": "literal",
            "value": _literal_value(item),
            "metadata": metadata,
        })
        source_maps[binding_uid] = entity_source_map(
            work.payload, item_pointer, item.get("span"),
            work.document_provenance,
        )
    return bindings, source_maps


def _literal_value(value: dict[str, Any]) -> Any:
    if value.get("kind") != "literal":
        raise ValueError("HS7 tuple components must be scalar literals.")
    return value.get("value")

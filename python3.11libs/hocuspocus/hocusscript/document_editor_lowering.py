"""Pure GraphSpec 0.5 editor-entity lowering into network-document v2."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from .document_editor_entities import (
    DocumentEditorEntityError,
    apply_editor_entity_plan,
    editor_entities_from_document,
    editor_entities_to_document,
    plan_editor_entities,
    resolve_layout_constraints,
)
from .document_provenance import entity_metadata

_DEFAULT_BOX_COLOR = [
    0.5199999809265137,
    0.5199999809265137,
    0.5199999809265137,
]
_DEFAULT_STICKY_COLOR = [
    1.0,
    0.968999981880188,
    0.5220000147819519,
]

EDITOR_DOCUMENT_COLLECTIONS = (
    ("NetworkBoxes", "NetworkBox", "networkBoxes"),
    ("StickyNotes", "StickyNote", "stickyNotes"),
    ("NodeComments", "NodeComment", "nodeComments"),
    ("NetworkDots", "NetworkDot", "networkDots"),
    ("LayoutConstraints", "LayoutConstraint", "layoutConstraints"),
)
EDITOR_DELETE_OPERATION_SPECS = (
    ("network_box", "delete_editor_entity", "deletedNetworkBoxes"),
    ("sticky_note", "delete_editor_entity", "deletedStickyNotes"),
    ("node_comment", "delete_editor_entity", "deletedNodeComments"),
    ("network_dot", "delete_editor_entity", "deletedNetworkDots"),
    ("layout_constraint", "delete_editor_entity", "deletedLayoutConstraints"),
)
EDITOR_UPSERT_OPERATION_SPECS = (
    ("network_box", "create_editor_entity", "createdNetworkBoxes"),
    ("sticky_note", "create_editor_entity", "createdStickyNotes"),
    ("node_comment", "create_editor_entity", "createdNodeComments"),
    ("network_dot", "create_editor_entity", "createdNetworkDots"),
    ("layout_constraint", "create_editor_entity", "createdLayoutConstraints"),
    ("network_box", "update_editor_entity", "changedNetworkBoxes"),
    ("sticky_note", "update_editor_entity", "changedStickyNotes"),
    ("node_comment", "update_editor_entity", "changedNodeComments"),
    ("network_dot", "update_editor_entity", "changedNetworkDots"),
    ("layout_constraint", "update_editor_entity", "changedLayoutConstraints"),
)


class DocumentEditorLoweringError(ValueError):
    pass


def lower_work_editor_entities(work: Any) -> None:
    try:
        lowered = lower_editor_entities(
            graph=work.graph,
            payload=work.payload,
            bundle_digest=work.bundle_digest,
            document=work.document,
            generated_by_symbol=work.generated_by_symbol,
            external_by_symbol=work.external_by_symbol,
            document_provenance=work.document_provenance,
        )
    except DocumentEditorLoweringError as exc:
        work.diagnostics.append({
            "severity": "error",
            "code": "HOCUS717",
            "message": str(exc),
            "jsonPointer": "/graphSpec/editorEntities",
            "path": work.target,
        })
        return
    for uid, entity in lowered.items():
        work.source_map_entities[uid] = {
            "kind": "editor_entity",
            "jsonPointer": entity["metadata"]["hocus"]["jsonPointer"],
            "sourceUri": entity["metadata"]["hocus"]["sourceUri"],
        }


def lower_editor_entities(
    *,
    graph: Mapping[str, Any],
    payload: Mapping[str, Any],
    bundle_digest: str,
    document: dict[str, Any],
    generated_by_symbol: Mapping[str, dict[str, Any]],
    external_by_symbol: Mapping[str, dict[str, Any]],
    document_provenance: Any,
) -> dict[str, dict[str, Any]]:
    """Lower, constraint-resolve, and ownership-scope all editor entities."""

    if graph.get("graphSpecVersion") != "0.5":
        return {}
    node_by_symbol = {**external_by_symbol, **generated_by_symbol}
    node_uids = {
        str(item["uid"]) for item in document.get("nodes", [])
        if isinstance(item, dict) and isinstance(item.get("uid"), str)
    }
    desired = [
        _lower_entity(
            item,
            index=index,
            graph=graph,
            payload=payload,
            bundle_digest=bundle_digest,
            node_by_symbol=node_by_symbol,
            document_provenance=document_provenance,
        )
        for index, item in enumerate(graph.get("editorEntities", []))
    ]
    if any(item["uid"] in node_uids for item in desired):
        raise DocumentEditorLoweringError(
            "Editor entity IDs must not collide with document node UIDs."
        )
    _resolve_constraints(desired, document, node_by_symbol, node_uids)
    try:
        baseline = editor_entities_from_document(document, node_uids=node_uids)
        plan = plan_editor_entities(
            baseline,
            desired,
            mode=str(graph["mode"]),
            reconcile_ownerships=(
                [str(graph["ownership"])]
                if graph["mode"] == "reconcile" else []
            ),
            node_uids=node_uids,
        )
        applied = apply_editor_entity_plan(
            baseline, plan, node_uids=node_uids,
        )
        collections = editor_entities_to_document(applied)
    except DocumentEditorEntityError as exc:
        raise DocumentEditorLoweringError(str(exc)) from exc
    document.update(collections)
    return {
        str(item["uid"]): copy.deepcopy(item)
        for item in desired
    }


def _lower_entity(
    item: Mapping[str, Any],
    *,
    index: int,
    graph: Mapping[str, Any],
    payload: Mapping[str, Any],
    bundle_digest: str,
    node_by_symbol: Mapping[str, dict[str, Any]],
    document_provenance: Any,
) -> dict[str, Any]:
    kind, identity = str(item["kind"]), str(item["explicitId"])
    result: dict[str, Any] = {
        "uid": identity,
        "kind": kind,
        "metadata": entity_metadata(
            payload,
            bundle_digest,
            graph,
            identity,
            f"/editorEntities/{index}",
            item.get("span"),
            graph.get("ownership"),
            document_provenance,
            entity_kind=kind,
        ),
    }
    if kind == "network_box":
        result.update({
            "label": item["label"],
            "position": copy.deepcopy(item["position"]),
            "size": copy.deepcopy(item["size"]),
            "color": copy.deepcopy(
                item["color"]
                if item["color"] is not None else _DEFAULT_BOX_COLOR
            ),
            "itemUids": [
                _reference_uid(ref, node_by_symbol) for ref in item["itemRefs"]
            ],
        })
    elif kind == "sticky_note":
        result.update({
            "text": item["text"],
            "position": copy.deepcopy(item["position"]),
            "size": copy.deepcopy(item["size"]),
            "color": copy.deepcopy(
                item["color"]
                if item["color"] is not None else _DEFAULT_STICKY_COLOR
            ),
            "textSize": item["textSize"],
            "drawBackground": item["drawBackground"],
            "minimized": item["minimized"],
        })
    elif kind == "node_comment":
        node_uid = _reference_uid(item["nodeRef"], node_by_symbol)
        result["metadata"]["hocus"]["nodeUid"] = node_uid
        result.update({
            "nodeUid": node_uid,
            "text": item["text"],
            "visible": item["visible"],
        })
    elif kind == "network_dot":
        connection = item["input"]
        result.update({
            "position": copy.deepcopy(item["position"]),
            "pinned": item["pinned"],
            "input": (
                {
                    "itemUid": _reference_uid(
                        connection["item"], node_by_symbol
                    ),
                    "outputIndex": connection["outputIndex"],
                }
                if connection is not None else None
            ),
            "outputs": [
                {
                    "nodeUid": _reference_uid(
                        output["nodeRef"], node_by_symbol
                    ),
                    "inputIndex": output["inputIndex"],
                }
                for output in item["outputs"]
            ],
        })
    else:
        result.update({
            "constraintKind": item["constraintKind"],
            "itemUids": [
                _reference_uid(ref, node_by_symbol) for ref in item["itemRefs"]
            ],
            "anchorUid": (
                _reference_uid(item["anchorRef"], node_by_symbol)
                if item["anchorRef"] is not None else None
            ),
            "offset": copy.deepcopy(item["offset"]),
            "spacing": item["spacing"],
            "padding": copy.deepcopy(item["padding"]),
            "priority": item["priority"],
        })
    return result


def _reference_uid(
    ref: Mapping[str, Any],
    node_by_symbol: Mapping[str, dict[str, Any]],
) -> str:
    if ref["kind"] == "node":
        node = node_by_symbol.get(str(ref["identity"]))
        if node is None or not isinstance(node.get("uid"), str):
            raise DocumentEditorLoweringError(
                "Editor entity references a node omitted by document lowering."
            )
        return str(node["uid"])
    return str(ref["identity"])


def _resolve_constraints(
    entities: list[dict[str, Any]],
    document: dict[str, Any],
    node_by_symbol: Mapping[str, dict[str, Any]],
    node_uids: set[str],
) -> None:
    positions = {
        str(node["uid"]): copy.deepcopy(node["position"])
        for node in node_by_symbol.values()
        if isinstance(node.get("uid"), str)
        and isinstance(node.get("position"), list)
        and len(node["position"]) == 2
    }
    sizes = {
        str(item["uid"]): copy.deepcopy(item["size"])
        for item in entities
        if item["kind"] in {"network_box", "sticky_note"}
    }
    try:
        resolved = resolve_layout_constraints(
            entities,
            positions,
            item_sizes=sizes,
            node_uids=node_uids,
        )
    except DocumentEditorEntityError as exc:
        raise DocumentEditorLoweringError(str(exc)) from exc
    by_uid = {
        str(item["uid"]): item
        for item in entities
        if "position" in item
    }
    nodes = {
        str(item["uid"]): item
        for item in document.get("nodes", [])
        if isinstance(item, dict) and isinstance(item.get("uid"), str)
    }
    for uid, position in resolved.items():
        target = by_uid.get(uid) or nodes.get(uid)
        if target is not None:
            target["position"] = copy.deepcopy(position)

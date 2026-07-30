"""Pure GraphSpec-0.5 runtime-entity lowering into network-document v2."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from .document_provenance import entity_metadata, entity_source_map
from .document_runtime_contract import attach_runtime_contract

RUNTIME_DOCUMENT_COLLECTIONS = (
    ("SpareParameters", "SpareParameter", "spareParameters"),
    ("Animations", "Animation", "animations"),
)
RUNTIME_DELETE_OPERATION_SPECS = (
    ("spare_parameter", "remove_spare_parameter", "deletedSpareParameters"),
    ("animation", "clear_animation", "deletedAnimations"),
)
RUNTIME_UPSERT_OPERATION_SPECS = (
    ("spare_parameter", "create_spare_parameter", "createdSpareParameters"),
    ("spare_parameter", "update_spare_parameter", "changedSpareParameters"),
    ("animation", "create_animation", "createdAnimations"),
    ("animation", "update_animation", "changedAnimations"),
)


class DocumentRuntimeLoweringError(ValueError):
    pass


def lower_work_runtime_entities(work: Any) -> None:
    if work.graph.get("graphSpecVersion") != "0.5":
        return
    desired_spares = [
        _lower_spare(work, item, index)
        for index, item in enumerate(work.graph.get("spareParameters", []))
    ]
    desired_animations = [
        _lower_animation(work, item, index)
        for index, item in enumerate(work.graph.get("animations", []))
    ]
    spares = _compose(
        work, "spareParameters", desired_spares, "spare_parameter",
    )
    animations = _compose(
        work, "animations", desired_animations, "animation",
    )
    work.document = attach_runtime_contract(
        work.document, spare_parameters=spares, animations=animations,
    )
    for table, desired in (
        ("spareParameters", desired_spares),
        ("animations", desired_animations),
    ):
        for item in desired:
            pointer = item["metadata"]["hocus"]["jsonPointer"]
            work.source_map_entities[item["uid"]] = entity_source_map(
                work.payload, pointer, item["metadata"]["hocus"]["span"],
                work.document_provenance,
            )


def _lower_spare(
    work: Any, item: Mapping[str, Any], index: int,
) -> dict[str, Any]:
    node = _node(work, item)
    pointer = f"/spareParameters/{index}"
    return {
        "uid": item["explicitId"], "nodeUid": node["uid"],
        "name": item["name"], "label": item["label"], "type": item["type"],
        "tupleSize": item["tupleSize"], "default": copy.deepcopy(item["default"]),
        "menuItems": copy.deepcopy(item["menuItems"]),
        "metadata": _metadata(
            work, item, pointer, "spare_parameter",
        ),
    }


def _lower_animation(
    work: Any, item: Mapping[str, Any], index: int,
) -> dict[str, Any]:
    node = _node(work, item)
    pointer = f"/animations/{index}"
    return {
        "uid": item["explicitId"], "nodeUid": node["uid"],
        "parmName": item["parmName"], "valueType": item["valueType"],
        "value": item["value"], "authoredFps": item["authoredFps"],
        "displayFps": item["displayFps"],
        "extrapolation": copy.deepcopy(item["extrapolation"]),
        "keys": copy.deepcopy(item["keys"]),
        "metadata": _metadata(work, item, pointer, "animation"),
    }


def _node(work: Any, item: Mapping[str, Any]) -> Mapping[str, Any]:
    node = work.generated_by_symbol.get(item["nodeSymbol"])
    if node is None:
        raise DocumentRuntimeLoweringError(
            "Runtime entity references a node omitted by document lowering."
        )
    return node


def _metadata(
    work: Any,
    item: Mapping[str, Any],
    pointer: str,
    entity_kind: str,
) -> dict[str, Any]:
    return entity_metadata(
        work.payload, work.bundle_digest, work.graph,
        str(item["nodeSymbol"]), pointer, item["span"], work.ownership,
        work.document_provenance, entity_kind=entity_kind,
    )


def _compose(
    work: Any,
    table: str,
    desired: list[dict[str, Any]],
    entity_kind: str,
) -> list[dict[str, Any]]:
    desired_by_uid = {item["uid"]: item for item in desired}
    desired_targets = {
        _target(item, table): item["uid"] for item in desired
    }
    retained: dict[str, dict[str, Any]] = {}
    for item in work.baseline.get(table, []):
        if not isinstance(item, dict) or not isinstance(item.get("uid"), str):
            continue
        owner, kind = _managed_identity(item)
        uid, target = item["uid"], _target(item, table)
        collision = uid in desired_by_uid or target in desired_targets
        if target in desired_targets and desired_targets[target] != uid:
            raise DocumentRuntimeLoweringError(
                f"Runtime {table} target has a different durable identity."
            )
        if collision and (owner != work.ownership or kind != entity_kind):
            raise DocumentRuntimeLoweringError(
                f"Runtime {table} collides with differently owned baseline state."
            )
        if collision:
            continue
        if work.graph["mode"] == "reconcile" and (
            owner == work.ownership and kind == entity_kind
        ):
            continue
        retained[uid] = copy.deepcopy(item)
    retained.update(desired_by_uid)
    return sorted(
        retained.values(), key=lambda item: (item["nodeUid"], item["uid"]),
    )


def _target(item: Mapping[str, Any], table: str) -> tuple[Any, Any]:
    return (
        item.get("nodeUid"),
        item.get("name" if table == "spareParameters" else "parmName"),
    )


def _managed_identity(item: Mapping[str, Any]) -> tuple[Any, Any]:
    metadata = item.get("metadata")
    hocus = metadata.get("hocus") if isinstance(metadata, dict) else None
    return (
        hocus.get("ownership") if isinstance(hocus, dict) else None,
        hocus.get("entityKind") if isinstance(hocus, dict) else None,
    )

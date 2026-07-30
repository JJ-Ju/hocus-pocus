"""Pure, bounded runtime model for network-editor entities.

The public document schema deliberately does not leak into this module.  Callers
can convert the five document collections to the normalized ``kind``-tagged
shape here, plan a reconcile, and convert the result back.  No function imports
Houdini or performs I/O.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import struct
from collections.abc import Iterable, Mapping, Sequence
from typing import Any


EDITOR_COLLECTIONS = {
    "networkBoxes": "network_box",
    "stickyNotes": "sticky_note",
    "nodeComments": "node_comment",
    "networkDots": "network_dot",
    "layoutConstraints": "layout_constraint",
}
_COLLECTION_BY_KIND = {kind: name for name, kind in EDITOR_COLLECTIONS.items()}
_MAX_ENTITIES = 16_384
_MAX_BOX_ITEMS = 4_096
_MAX_CONSTRAINTS = 512
_MAX_CONSTRAINT_ITEMS = 256
_MAX_TEXT = 65_536
_MAX_UID = 512
_MAX_COORDINATE = 1_000_000.0
_MAX_SIZE = 100_000.0
_MAX_JSON_DEPTH = 16
_MAX_JSON_ITEMS = 65_536
_IDENTITY_FIELDS = (
    "entityKind",
    "projectUid",
    "graphName",
    "symbol",
    "ownership",
)
_LAYOUT_KINDS = {
    "align_x",
    "align_y",
    "offset",
    "distribute_x",
    "distribute_y",
    "contain",
}


class DocumentEditorEntityError(ValueError):
    """A deterministic validation, planning, or pure-apply failure."""

    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.code = code
        self.details = details


def editor_entities_from_document(
    document: Mapping[str, Any],
    *,
    node_uids: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    """Normalize the five optional document collections into one entity table."""

    entities: list[dict[str, Any]] = []
    for collection, kind in EDITOR_COLLECTIONS.items():
        raw = document.get(collection, [])
        if not isinstance(raw, list):
            _fail("editor.collection", f"{collection} must be an array.")
        for value in raw:
            if not isinstance(value, dict):
                _fail("editor.entity", f"{collection} entries must be objects.")
            tagged = {"kind": kind, **value}
            if value.get("kind") not in (None, kind):
                _fail(
                    "editor.kind",
                    f"{collection} contains an entity with the wrong kind.",
                    uid=value.get("uid"),
                )
            entities.append(tagged)
    return normalize_editor_entities(entities, node_uids=node_uids)


def editor_entities_to_document(
    entities: Sequence[Mapping[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Split normalized entities into deterministic document collections."""

    normalized = normalize_editor_entities(entities)
    result = {name: [] for name in EDITOR_COLLECTIONS}
    for entity in normalized:
        payload = copy.deepcopy(entity)
        collection = _COLLECTION_BY_KIND[payload.pop("kind")]
        result[collection].append(payload)
    return result


def normalize_editor_entities(
    entities: Sequence[Mapping[str, Any]],
    *,
    node_uids: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    """Strictly validate and canonicalize the normalized entity table."""

    if (
        not isinstance(entities, (list, tuple))
        or len(entities) > _MAX_ENTITIES
    ):
        _fail("editor.limit", "Editor entity table exceeds its bounded limit.")
    known_nodes = _uid_set(node_uids or (), "node_uids")
    normalized: list[dict[str, Any]] = []
    identities: set[str] = set()
    for raw in entities:
        entity = _normalize_entity(raw)
        uid = entity["uid"]
        if uid in identities:
            _fail("editor.uid_duplicate", "Editor entity uid is duplicated.", uid=uid)
        identities.add(uid)
        normalized.append(entity)
    if sum(item["kind"] == "layout_constraint" for item in normalized) > _MAX_CONSTRAINTS:
        _fail("editor.constraint_limit", "Layout constraint count exceeds its limit.")
    _validate_references(
        normalized, known_nodes, strict_external=node_uids is not None
    )
    return sorted(normalized, key=lambda item: (item["kind"], item["uid"]))


def snapshot_editor_entities(
    entities: Sequence[Mapping[str, Any]],
    *,
    node_uids: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Return a canonical pure snapshot with a stable content digest."""

    normalized = normalize_editor_entities(entities, node_uids=node_uids)
    return {
        "format": "hocus-editor-entities-v1",
        "digest": _digest(normalized),
        "entities": normalized,
    }


def diff_editor_entities(
    before: Sequence[Mapping[str, Any]],
    after: Sequence[Mapping[str, Any]],
    *,
    node_uids: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Return a compact, deterministic full-state diff."""

    old = _by_uid(normalize_editor_entities(before, node_uids=node_uids))
    new = _by_uid(normalize_editor_entities(after, node_uids=node_uids))
    created = [copy.deepcopy(new[uid]) for uid in sorted(set(new) - set(old))]
    deleted = [copy.deepcopy(old[uid]) for uid in sorted(set(old) - set(new))]
    changed = [
        {
            "uid": uid,
            "kind": new[uid]["kind"],
            "before": copy.deepcopy(old[uid]),
            "after": copy.deepcopy(new[uid]),
        }
        for uid in sorted(set(old) & set(new))
        if old[uid] != new[uid]
    ]
    return {
        "summary": {
            "createdCount": len(created),
            "changedCount": len(changed),
            "deletedCount": len(deleted),
        },
        "created": created,
        "changed": changed,
        "deleted": deleted,
    }


def plan_editor_entities(
    baseline: Sequence[Mapping[str, Any]],
    target: Sequence[Mapping[str, Any]],
    *,
    mode: str,
    reconcile_ownerships: Iterable[str] = (),
    node_uids: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Plan managed creates/updates and ownership-scoped reconcile deletes.

    Unmanaged target observations are retained for comparison but never mutated.
    A target managed entity may update only an entity with the same durable Hocus
    identity.  This prevents a source-owned UID from taking over an artist item.
    """

    if mode not in {"merge", "reconcile"}:
        _fail("editor.mode", "Editor entity mode must be merge or reconcile.")
    owners = _uid_set(reconcile_ownerships, "reconcile_ownerships")
    old_list = normalize_editor_entities(baseline, node_uids=node_uids)
    new_list = normalize_editor_entities(target, node_uids=node_uids)
    old, new = _by_uid(old_list), _by_uid(new_list)
    operations: list[dict[str, Any]] = []
    for uid in sorted(new):
        desired = new[uid]
        current = old.get(uid)
        owner = _owner(desired)
        if current is None:
            if owner is not None:
                operations.append(_operation("create", None, desired))
            continue
        if current == desired:
            continue
        _require_update_authority(current, desired)
        operations.append(_operation("update", current, desired))
    if mode == "reconcile":
        for uid in sorted(set(old) - set(new)):
            current = old[uid]
            if _owner(current) in owners:
                operations.append(_operation("delete", current, None))
    operations.sort(key=_operation_sort_key)
    inverse = [_invert_operation(item) for item in reversed(operations)]
    applied = copy.deepcopy(old)
    for operation in operations:
        _apply_pure_operation(applied, operation)
    applied_list = normalize_editor_entities(
        list(applied.values()), node_uids=node_uids
    )
    authored_by_uid = _by_uid(new_list)
    applied_by_uid = _by_uid(applied_list)
    return {
        "format": "hocus-editor-entity-plan-v1",
        "mode": mode,
        "baselineDigest": _digest(old_list),
        "targetDigest": _digest(new_list),
        "appliedTargetDigest": _digest(applied_list),
        "reconcileOwnerships": sorted(owners),
        "operations": operations,
        "inverseOperations": inverse,
        "summary": {
            "createCount": sum(item["action"] == "create" for item in operations),
            "updateCount": sum(item["action"] == "update" for item in operations),
            "deleteCount": sum(item["action"] == "delete" for item in operations),
            "preservedArtistCount": len({
                uid for uid in set(authored_by_uid) | set(applied_by_uid)
                if authored_by_uid.get(uid) != applied_by_uid.get(uid)
            }),
        },
    }


def apply_editor_entity_plan(
    baseline: Sequence[Mapping[str, Any]],
    plan: Mapping[str, Any],
    *,
    inverse: bool = False,
    node_uids: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    """Purely apply a plan with exact before-state guards."""

    plan = validate_editor_entity_plan(plan)
    current = _by_uid(normalize_editor_entities(baseline, node_uids=node_uids))
    expected = (
        plan.get("appliedTargetDigest") if inverse
        else plan.get("baselineDigest")
    )
    if expected != _digest(list(current.values())):
        _fail("editor.plan_stale", "Editor entity plan baseline digest is stale.")
    key = "inverseOperations" if inverse else "operations"
    operations = plan.get(key)
    if not isinstance(operations, list):
        _fail("editor.plan", "Editor entity plan operations are malformed.")
    for operation in operations:
        _apply_pure_operation(current, operation)
    result = normalize_editor_entities(list(current.values()), node_uids=node_uids)
    result_digest = (
        plan.get("baselineDigest") if inverse
        else plan.get("appliedTargetDigest")
    )
    if _digest(result) != result_digest:
        _fail("editor.plan_result", "Editor entity plan produced an invalid digest.")
    return result


def validate_editor_entity_plan(
    plan: Mapping[str, Any],
) -> dict[str, Any]:
    """Strict-decode the self-contained editor plan envelope."""

    fields = {
        "format", "mode", "baselineDigest", "targetDigest",
        "appliedTargetDigest", "reconcileOwnerships", "operations",
        "inverseOperations", "summary",
    }
    if (
        not isinstance(plan, Mapping)
        or set(plan) != fields
        or plan.get("format") != "hocus-editor-entity-plan-v1"
        or plan.get("mode") not in {"merge", "reconcile"}
    ):
        _fail("editor.plan", "Editor entity plan envelope is malformed.")
    for name in ("baselineDigest", "targetDigest", "appliedTargetDigest"):
        value = plan.get(name)
        if (
            not isinstance(value, str)
            or len(value) != 64
            or any(char not in "0123456789abcdef" for char in value)
        ):
            _fail("editor.plan_digest", f"{name} is not a SHA-256 digest.")
    owners = plan.get("reconcileOwnerships")
    if not isinstance(owners, list) or owners != sorted(set(owners)):
        _fail("editor.plan_owners", "Plan reconcile ownerships are not canonical.")
    _uid_set(owners, "reconcileOwnerships")
    operations = _normalize_operations(plan.get("operations"))
    inverse = _normalize_operations(plan.get("inverseOperations"))
    expected_inverse = [_invert_operation(item) for item in reversed(operations)]
    if inverse != expected_inverse:
        _fail("editor.plan_inverse", "Editor entity inverse operations do not match.")
    summary = plan.get("summary")
    expected_counts = {
        "createCount": sum(item["action"] == "create" for item in operations),
        "updateCount": sum(item["action"] == "update" for item in operations),
        "deleteCount": sum(item["action"] == "delete" for item in operations),
    }
    if (
        not isinstance(summary, Mapping)
        or set(summary) != {*expected_counts, "preservedArtistCount"}
        or any(summary.get(name) != value for name, value in expected_counts.items())
        or type(summary.get("preservedArtistCount")) is not int
        or summary["preservedArtistCount"] < 0
    ):
        _fail("editor.plan_summary", "Editor entity plan summary is malformed.")
    result = copy.deepcopy(dict(plan))
    result["operations"] = operations
    result["inverseOperations"] = inverse
    result["summary"] = dict(summary)
    return result


def resolve_layout_constraints(
    entities: Sequence[Mapping[str, Any]],
    item_positions: Mapping[str, Sequence[float]],
    *,
    item_sizes: Mapping[str, Sequence[float]] | None = None,
    node_uids: Iterable[str] | None = None,
    max_passes: int = 8,
) -> dict[str, list[float]]:
    """Resolve supported constraints in at most eight deterministic passes."""

    if type(max_passes) is not int or not 1 <= max_passes <= 8:
        _fail("editor.layout_passes", "Layout passes must be between one and eight.")
    normalized = normalize_editor_entities(entities, node_uids=node_uids)
    positions = {
        _uid(uid, "position uid"): _vector(value, "position", signed=True)
        for uid, value in item_positions.items()
    }
    sizes = {
        _uid(uid, "size uid"): _vector(value, "size", positive=True)
        for uid, value in (item_sizes or {}).items()
    }
    for entity in normalized:
        if "position" in entity:
            positions.setdefault(entity["uid"], copy.deepcopy(entity["position"]))
        if "size" in entity:
            sizes.setdefault(entity["uid"], copy.deepcopy(entity["size"]))
    constraints = sorted(
        (
            item for item in normalized
            if item["kind"] == "layout_constraint"
        ),
        key=lambda item: (item["priority"], item["uid"]),
    )
    changed = False
    for _pass in range(max_passes):
        changed = False
        for constraint in constraints:
            changed |= _apply_constraint(constraint, positions, sizes)
        if not changed:
            return positions
    if changed:
        _fail(
            "editor.layout_conflict",
            "Layout constraints did not converge within the bounded pass limit.",
        )
    return positions


def _normalize_entity(raw: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        _fail("editor.entity", "Editor entity must be an object.")
    kind = raw.get("kind")
    if kind == "network_box":
        return _normalize_box(raw)
    if kind == "sticky_note":
        return _normalize_sticky(raw)
    if kind == "node_comment":
        return _normalize_comment(raw)
    if kind == "network_dot":
        return _normalize_dot(raw)
    if kind == "layout_constraint":
        return _normalize_constraint(raw)
    _fail("editor.kind", "Editor entity kind is unsupported.", kind=kind)


def _base(raw: Mapping[str, Any], kind: str, allowed: set[str]) -> dict[str, Any]:
    required = {"uid", "kind", "metadata"}
    if set(raw) - allowed or not required.issubset(raw):
        _fail(
            "editor.fields",
            "Editor entity fields do not match its normalized shape.",
            uid=raw.get("uid"),
            kind=kind,
        )
    metadata = raw.get("metadata")
    if not isinstance(metadata, Mapping):
        _fail("editor.metadata", "Editor entity metadata must be an object.")
    _bounded_json(metadata)
    result = {
        "uid": _uid(raw.get("uid"), "uid"),
        "kind": kind,
        "metadata": copy.deepcopy(dict(metadata)),
    }
    hocus = result["metadata"].get("hocus")
    if hocus is not None:
        if not isinstance(hocus, dict) or hocus.get("entityKind") != kind:
            _fail(
                "editor.provenance",
                "Managed editor entity provenance has the wrong entity kind.",
                uid=result["uid"],
            )
        _uid(hocus.get("ownership"), "metadata.hocus.ownership")
    return result


def _normalize_box(raw: Mapping[str, Any]) -> dict[str, Any]:
    allowed = {
        "uid", "kind", "label", "position", "size", "color", "itemUids",
        "metadata",
    }
    result = _base(raw, "network_box", allowed)
    result.update({
        "label": _text(raw.get("label", ""), "label", 4_096),
        "position": _vector(raw.get("position"), "position", signed=True),
        "size": _vector(raw.get("size"), "size", positive=True),
        "color": _color(raw.get("color")),
        "itemUids": sorted(
            _uid_list(raw.get("itemUids", []), _MAX_BOX_ITEMS)
        ),
    })
    return result


def _normalize_sticky(raw: Mapping[str, Any]) -> dict[str, Any]:
    allowed = {
        "uid", "kind", "text", "position", "size", "color", "textSize",
        "drawBackground", "minimized", "metadata",
    }
    result = _base(raw, "sticky_note", allowed)
    result.update({
        "text": _text(raw.get("text", ""), "text", _MAX_TEXT),
        "position": _vector(raw.get("position"), "position", signed=True),
        "size": _vector(raw.get("size"), "size", positive=True),
        "color": _color(raw.get("color")),
        "textSize": _finite(raw.get("textSize", 1.0), "textSize", 0.1, 10.0),
        "drawBackground": _boolean(raw.get("drawBackground", True), "drawBackground"),
        "minimized": _boolean(raw.get("minimized", False), "minimized"),
    })
    return result


def _normalize_comment(raw: Mapping[str, Any]) -> dict[str, Any]:
    allowed = {"uid", "kind", "nodeUid", "text", "visible", "metadata"}
    result = _base(raw, "node_comment", allowed)
    result.update({
        "nodeUid": _uid(raw.get("nodeUid"), "nodeUid"),
        "text": _text(raw.get("text", ""), "text", _MAX_TEXT),
        "visible": _boolean(raw.get("visible", True), "visible"),
    })
    return result


def _normalize_dot(raw: Mapping[str, Any]) -> dict[str, Any]:
    allowed = {
        "uid", "kind", "position", "pinned", "input", "outputs", "metadata",
    }
    result = _base(raw, "network_dot", allowed)
    source = raw.get("input")
    if source is not None:
        if not isinstance(source, Mapping) or set(source) != {"itemUid", "outputIndex"}:
            _fail("editor.dot_input", "Network dot input is malformed.")
        source = {
            "itemUid": _uid(source.get("itemUid"), "input.itemUid"),
            "outputIndex": _integer(
                source.get("outputIndex"), "input.outputIndex", 0, 65_535
            ),
        }
    outputs = raw.get("outputs", [])
    if (
        not isinstance(outputs, (list, tuple))
        or len(outputs) > _MAX_CONSTRAINT_ITEMS
    ):
        _fail("editor.dot_outputs", "Network dot outputs are malformed.")
    normalized_outputs = []
    output_coordinates: set[tuple[str, int]] = set()
    for output in outputs:
        if (
            not isinstance(output, Mapping)
            or set(output) != {"nodeUid", "inputIndex"}
        ):
            _fail("editor.dot_outputs", "Network dot output is malformed.")
        normalized = {
            "nodeUid": _uid(output.get("nodeUid"), "outputs.nodeUid"),
            "inputIndex": _integer(
                output.get("inputIndex"), "outputs.inputIndex", 0, 65_535
            ),
        }
        coordinate = (normalized["nodeUid"], normalized["inputIndex"])
        if coordinate in output_coordinates:
            _fail("editor.dot_outputs", "Network dot output is duplicated.")
        output_coordinates.add(coordinate)
        normalized_outputs.append(normalized)
    result.update({
        "position": _vector(raw.get("position"), "position", signed=True),
        "pinned": _boolean(raw.get("pinned", False), "pinned"),
        "input": source,
        "outputs": sorted(
            normalized_outputs,
            key=lambda item: (item["nodeUid"], item["inputIndex"]),
        ),
    })
    return result


def _normalize_constraint(raw: Mapping[str, Any]) -> dict[str, Any]:
    allowed = {
        "uid", "kind", "constraintKind", "itemUids", "anchorUid", "offset",
        "spacing", "padding", "priority", "metadata",
    }
    result = _base(raw, "layout_constraint", allowed)
    constraint_kind = raw.get("constraintKind")
    if constraint_kind not in _LAYOUT_KINDS:
        _fail("editor.constraint_kind", "Layout constraint kind is unsupported.")
    result.update({
        "constraintKind": constraint_kind,
        "itemUids": _uid_list(raw.get("itemUids", []), _MAX_CONSTRAINT_ITEMS),
        "anchorUid": (
            _uid(raw["anchorUid"], "anchorUid")
            if raw.get("anchorUid") is not None else None
        ),
        "offset": (
            _vector(raw["offset"], "offset", signed=True)
            if raw.get("offset") is not None else None
        ),
        "spacing": (
            _finite(raw["spacing"], "spacing", 0.0, _MAX_SIZE)
            if raw.get("spacing") is not None else None
        ),
        "padding": (
            _vector(raw["padding"], "padding", allow_zero=True)
            if raw.get("padding") is not None else [0.0, 0.0]
        ),
        "priority": _integer(raw.get("priority", 50), "priority", 0, 100),
    })
    _validate_constraint_shape(result)
    return result


def _validate_constraint_shape(entity: dict[str, Any]) -> None:
    kind, items = entity["constraintKind"], entity["itemUids"]
    if kind in {"distribute_x", "distribute_y"} and len(items) < 3:
        _fail("editor.constraint_items", "Distribute constraints require three items.")
    if kind not in {"distribute_x", "distribute_y"} and not items:
        _fail("editor.constraint_items", "Layout constraint requires an item.")
    if kind in {"align_x", "align_y", "offset", "contain"} and not entity["anchorUid"]:
        _fail("editor.constraint_anchor", f"{kind} requires anchorUid.")
    if kind == "offset" and entity["offset"] is None:
        _fail("editor.constraint_offset", "Offset constraint requires offset.")
    if kind == "offset" and entity["anchorUid"] in items:
        _fail("editor.constraint_cycle", "Offset anchor cannot offset itself.")
    if kind == "contain" and entity["anchorUid"] in items:
        _fail("editor.constraint_cycle", "Containment anchor cannot contain itself.")


def _validate_references(
    entities: list[dict[str, Any]],
    node_uids: set[str],
    *,
    strict_external: bool,
) -> None:
    by_uid = _by_uid(entities)
    _validate_unique_dot_destinations(entities)
    movable = {
        uid for uid, value in by_uid.items()
        if value["kind"] in {"network_box", "sticky_note", "network_dot"}
    } | node_uids
    for entity in entities:
        kind, uid = entity["kind"], entity["uid"]
        if (
            kind == "node_comment"
            and strict_external
            and entity["nodeUid"] not in node_uids
        ):
            _fail("editor.dangling_node", "Node comment target is missing.", uid=uid)
        if kind == "network_dot":
            source = entity["input"]
            if (
                source
                and source["itemUid"] not in movable
                and strict_external
            ):
                _fail("editor.dangling_dot", "Network dot input is missing.", uid=uid)
            if (
                strict_external
                and any(
                    output["nodeUid"] not in node_uids
                    for output in entity["outputs"]
                )
            ):
                _fail(
                    "editor.dangling_dot",
                    "Network dot output is missing.",
                    uid=uid,
                )
        if kind == "network_box":
            if uid in entity["itemUids"] or (
                strict_external
                and any(item not in movable for item in entity["itemUids"])
            ):
                _fail("editor.dangling_box", "Network box membership is invalid.", uid=uid)
        if kind == "layout_constraint":
            refs = set(entity["itemUids"])
            if entity["anchorUid"]:
                refs.add(entity["anchorUid"])
            if strict_external and not refs <= movable:
                _fail("editor.dangling_constraint", "Layout constraint target is missing.", uid=uid)
    _reject_cycles(
        {
            uid: [value["input"]["itemUid"]]
            for uid, value in by_uid.items()
            if value["kind"] == "network_dot" and value["input"]
            and value["input"]["itemUid"] in by_uid
            and by_uid[value["input"]["itemUid"]]["kind"] == "network_dot"
        },
        "Network dot topology contains a cycle.",
    )
    _reject_cycles(
        {
            uid: [
                item for item in value["itemUids"]
                if item in by_uid and by_uid[item]["kind"] == "network_box"
            ]
            for uid, value in by_uid.items()
            if value["kind"] == "network_box"
        },
        "Network box membership contains a cycle.",
    )


def _validate_unique_dot_destinations(
    entities: list[dict[str, Any]],
) -> None:
    destinations: dict[tuple[str, int], str] = {}
    for entity in entities:
        if entity["kind"] != "network_dot":
            continue
        for output in entity["outputs"]:
            coordinate = (output["nodeUid"], output["inputIndex"])
            claimed_by = destinations.get(coordinate)
            if claimed_by is not None:
                _fail(
                    "editor.dot_destination_conflict",
                    "Network dot outputs must claim unique node inputs.",
                    uid=entity["uid"],
                    conflictingUid=claimed_by,
                    nodeUid=coordinate[0],
                    inputIndex=coordinate[1],
                )
            destinations[coordinate] = entity["uid"]


def _reject_cycles(graph: Mapping[str, list[str]], message: str) -> None:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(start: str) -> None:
        stack: list[tuple[str, bool]] = [(start, False)]
        while stack:
            uid, exiting = stack.pop()
            if exiting:
                visiting.discard(uid)
                visited.add(uid)
                continue
            if uid in visited:
                continue
            if uid in visiting:
                _fail("editor.cycle", message, uid=uid)
            visiting.add(uid)
            stack.append((uid, True))
            stack.extend((child, False) for child in reversed(graph.get(uid, [])))

    for uid in sorted(graph):
        visit(uid)


def _apply_constraint(
    constraint: dict[str, Any],
    positions: dict[str, list[float]],
    sizes: dict[str, list[float]],
) -> bool:
    kind = constraint["constraintKind"]
    items = constraint["itemUids"]
    _require_positions(items, positions, constraint["uid"])
    anchor_uid = constraint["anchorUid"]
    if anchor_uid is not None:
        _require_positions([anchor_uid], positions, constraint["uid"])
    if kind in {"align_x", "align_y"}:
        axis = 0 if kind == "align_x" else 1
        return _align(items, positions[anchor_uid], positions, axis)
    if kind == "offset":
        desired = [
            positions[anchor_uid][axis] + constraint["offset"][axis]
            for axis in (0, 1)
        ]
        return _place_all(items, desired, positions)
    if kind in {"distribute_x", "distribute_y"}:
        axis = 0 if kind == "distribute_x" else 1
        return _distribute(items, positions, axis, constraint["spacing"])
    if kind == "contain":
        if anchor_uid not in sizes:
            _fail("editor.layout_size", "Containment anchor size is missing.")
        return _contain(
            items, positions, sizes, anchor_uid, constraint["padding"]
        )
    return False


def _align(
    items: list[str],
    anchor: list[float],
    positions: dict[str, list[float]],
    axis: int,
) -> bool:
    changed = False
    for uid in items:
        if positions[uid][axis] != anchor[axis]:
            positions[uid][axis] = anchor[axis]
            changed = True
    return changed


def _place_all(
    items: list[str],
    desired: list[float],
    positions: dict[str, list[float]],
) -> bool:
    changed = False
    for uid in items:
        if positions[uid] != desired:
            positions[uid] = copy.deepcopy(desired)
            changed = True
    return changed


def _distribute(
    items: list[str],
    positions: dict[str, list[float]],
    axis: int,
    spacing: float | None,
) -> bool:
    first = positions[items[0]][axis]
    step = (
        spacing if spacing is not None
        else (positions[items[-1]][axis] - first) / (len(items) - 1)
    )
    changed = False
    subjects = items[1:] if spacing is not None else items[1:-1]
    for index, uid in enumerate(subjects, start=1):
        value = _coordinate(first + (step * index), "distributed position")
        if positions[uid][axis] != value:
            positions[uid][axis] = value
            changed = True
    return changed


def _contain(
    items: list[str],
    positions: dict[str, list[float]],
    sizes: dict[str, list[float]],
    anchor_uid: str,
    padding: list[float],
) -> bool:
    origin, extent = positions[anchor_uid], sizes[anchor_uid]
    changed = False
    for uid in items:
        item_size = sizes.get(uid, [0.0, 0.0])
        desired: list[float] = []
        for axis in (0, 1):
            low = origin[axis] + padding[axis]
            high = origin[axis] + extent[axis] - padding[axis] - item_size[axis]
            if high < low:
                _fail("editor.layout_fit", "Contained item cannot fit inside its anchor.")
            desired.append(min(max(positions[uid][axis], low), high))
        if desired != positions[uid]:
            positions[uid] = desired
            changed = True
    return changed


def _require_positions(
    uids: Iterable[str],
    positions: Mapping[str, list[float]],
    constraint_uid: str,
) -> None:
    missing = sorted(uid for uid in uids if uid not in positions)
    if missing:
        _fail(
            "editor.layout_position",
            "Layout constraint references an item without a position.",
            uid=constraint_uid,
            missing=missing,
        )


def _require_update_authority(
    current: dict[str, Any], desired: dict[str, Any],
) -> None:
    current_hocus = _hocus(current)
    desired_hocus = _hocus(desired)
    if desired_hocus is None:
        _fail(
            "editor.artist_update",
            "Unmanaged editor entities are observations and cannot be mutated.",
            uid=desired["uid"],
        )
    if current_hocus is None:
        _fail(
            "editor.artist_collision",
            "Managed editor entity cannot overwrite an artist-owned item.",
            uid=desired["uid"],
        )
    if current["kind"] != desired["kind"] or any(
        current_hocus.get(field) != desired_hocus.get(field)
        for field in _IDENTITY_FIELDS
    ):
        _fail(
            "editor.identity_drift",
            "Stable Hocus identity cannot change during an editor update.",
            uid=desired["uid"],
        )


def _operation(
    action: str,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
) -> dict[str, Any]:
    entity = after or before or {}
    return {
        "action": action,
        "uid": entity.get("uid"),
        "kind": entity.get("kind"),
        "before": copy.deepcopy(before),
        "after": copy.deepcopy(after),
    }


def _invert_operation(operation: Mapping[str, Any]) -> dict[str, Any]:
    inverse_action = {
        "create": "delete",
        "update": "update",
        "delete": "create",
    }.get(operation.get("action"))
    if inverse_action is None:
        _fail("editor.plan_action", "Editor plan action is unsupported.")
    return _operation(inverse_action, operation.get("after"), operation.get("before"))


def _operation_sort_key(operation: Mapping[str, Any]) -> tuple[int, str, str]:
    action_order = {"delete": 0, "create": 1, "update": 2}
    kind_order = {
        "node_comment": 0,
        "layout_constraint": 1,
        "network_dot": 2,
        "sticky_note": 3,
        "network_box": 4,
    }
    return (
        action_order.get(str(operation.get("action")), 99),
        f"{kind_order.get(str(operation.get('kind')), 99):02d}",
        str(operation.get("uid", "")),
    )


def _apply_pure_operation(
    current: dict[str, dict[str, Any]], operation: Any,
) -> None:
    if not isinstance(operation, Mapping):
        _fail("editor.plan_operation", "Editor plan operation must be an object.")
    action, uid = operation.get("action"), operation.get("uid")
    before, after = operation.get("before"), operation.get("after")
    if current.get(uid) != before:
        _fail(
            "editor.plan_operation_stale",
            "Editor plan operation before-state does not match.",
            uid=uid,
        )
    if action == "delete" and after is None:
        current.pop(uid, None)
    elif action in {"create", "update"} and isinstance(after, dict):
        current[uid] = copy.deepcopy(after)
    else:
        _fail("editor.plan_operation", "Editor plan operation is malformed.", uid=uid)


def _normalize_operations(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) > (_MAX_ENTITIES * 2):
        _fail("editor.plan_operations", "Editor plan operation table exceeds its limit.")
    result: list[dict[str, Any]] = []
    for raw in value:
        if (
            not isinstance(raw, Mapping)
            or set(raw) != {"action", "uid", "kind", "before", "after"}
        ):
            _fail("editor.plan_operation", "Editor plan operation is malformed.")
        action = raw.get("action")
        before = (
            _normalize_entity(raw["before"]) if raw.get("before") is not None
            else None
        )
        after = (
            _normalize_entity(raw["after"]) if raw.get("after") is not None
            else None
        )
        shapes = {
            "create": before is None and after is not None,
            "update": before is not None and after is not None,
            "delete": before is not None and after is None,
        }
        entity = after or before or {}
        if (
            not shapes.get(action, False)
            or raw.get("uid") != entity.get("uid")
            or raw.get("kind") != entity.get("kind")
            or (
                before is not None
                and after is not None
                and (
                    before["uid"] != after["uid"]
                    or before["kind"] != after["kind"]
                )
            )
        ):
            _fail(
                "editor.plan_operation",
                "Editor plan operation identity or state shape is malformed.",
            )
        result.append(_operation(str(action), before, after))
    return result


def _hocus(entity: Mapping[str, Any]) -> dict[str, Any] | None:
    metadata = entity.get("metadata")
    hocus = metadata.get("hocus") if isinstance(metadata, Mapping) else None
    return hocus if isinstance(hocus, dict) else None


def _owner(entity: Mapping[str, Any]) -> str | None:
    hocus = _hocus(entity)
    value = hocus.get("ownership") if hocus else None
    return str(value).strip() if isinstance(value, str) and value.strip() else None


def _by_uid(
    entities: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    return {str(item["uid"]): copy.deepcopy(dict(item)) for item in entities}


def _digest(entities: Sequence[Mapping[str, Any]]) -> str:
    ordered = sorted(entities, key=lambda item: (str(item["kind"]), str(item["uid"])))
    encoded = json.dumps(
        ordered,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _uid_set(values: Iterable[str], label: str) -> set[str]:
    if isinstance(values, (str, bytes)):
        _fail("editor.uid_set", f"{label} must be an iterable of identities.")
    return {_uid(value, label) for value in values}


def _uid_list(value: Any, limit: int) -> list[str]:
    if not isinstance(value, list) or len(value) > limit:
        _fail("editor.uid_list", "Editor entity identity list exceeds its limit.")
    result = [_uid(item, "item uid") for item in value]
    if len(result) != len(set(result)):
        _fail("editor.uid_list", "Editor entity identity list contains duplicates.")
    return result


def _uid(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or value != value.strip()
        or len(value) > _MAX_UID
        or any(ord(char) < 32 for char in value)
    ):
        _fail("editor.uid", f"{label} is not a valid bounded identity.")
    return value


def _text(value: Any, label: str, limit: int) -> str:
    if not isinstance(value, str) or len(value) > limit:
        _fail("editor.text", f"{label} exceeds its bounded text limit.")
    return value


def _boolean(value: Any, label: str) -> bool:
    if type(value) is not bool:
        _fail("editor.boolean", f"{label} must be boolean.")
    return value


def _integer(value: Any, label: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        _fail("editor.integer", f"{label} is outside its bounded integer range.")
    return value


def _finite(value: Any, label: str, minimum: float, maximum: float) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or not minimum <= float(value) <= maximum
    ):
        _fail("editor.number", f"{label} is outside its bounded numeric range.")
    return float(value)


def _coordinate(value: Any, label: str) -> float:
    return _finite(value, label, -_MAX_COORDINATE, _MAX_COORDINATE)


def _vector(
    value: Any,
    label: str,
    *,
    signed: bool = False,
    positive: bool = False,
    allow_zero: bool = False,
) -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        _fail("editor.vector", f"{label} must contain exactly two numbers.")
    minimum = -_MAX_COORDINATE if signed else (0.0 if allow_zero else 0.000001)
    maximum = _MAX_COORDINATE if signed else _MAX_SIZE
    result = [_finite(item, label, minimum, maximum) for item in value]
    if positive and any(item <= 0.0 for item in result):
        _fail("editor.vector", f"{label} components must be positive.")
    return result


def _color(value: Any) -> list[float] | None:
    if value is None:
        return None
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        _fail("editor.color", "Color must be null or three normalized channels.")
    return [
        struct.unpack("!f", struct.pack("!f", _finite(
            item, "color", 0.0, 1.0,
        )))[0]
        for item in value
    ]


def _bounded_json(value: Any) -> None:
    stack = [(value, 0)]
    count = 0
    while stack:
        current, depth = stack.pop()
        count += 1
        if count > _MAX_JSON_ITEMS or depth > _MAX_JSON_DEPTH:
            _fail("editor.metadata_limit", "Editor metadata exceeds its bounded limit.")
        if current is None or type(current) in {bool, int, str}:
            continue
        if isinstance(current, float):
            if not math.isfinite(current):
                _fail("editor.metadata_number", "Editor metadata contains a non-finite number.")
            continue
        if isinstance(current, list):
            stack.extend((item, depth + 1) for item in current)
            continue
        if isinstance(current, Mapping) and all(
            isinstance(key, str) for key in current
        ):
            stack.extend((item, depth + 1) for item in current.values())
            continue
        _fail("editor.metadata_type", "Editor metadata is not bounded JSON.")


def _fail(code: str, message: str, **details: Any) -> None:
    raise DocumentEditorEntityError(code, message, **details)

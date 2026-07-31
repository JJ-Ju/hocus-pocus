"""Houdini adapter for normalized network-editor entities.

This module is intentionally registration-free.  The document runtime can call
it from its existing undo group, persist the returned live-name identities in
the document entity table, and include the returned normalized snapshot in
network-document v2.  Only graph-editor APIs are used; no node is cooked.
"""

from __future__ import annotations

import copy
import hashlib
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from hocuspocus.hocusscript.document_editor_entities import (
    normalize_editor_entities,
    validate_editor_entity_plan,
)


class EditorEntityLiveApplyError(RuntimeError):
    """Live editor apply failed, with explicit rollback state."""

    def __init__(
        self,
        message: str,
        *,
        rolled_back: bool,
        rollback_error: str | None = None,
    ) -> None:
        super().__init__(message)
        self.rolled_back = rolled_back
        self.rollback_error = rollback_error


def snapshot_live_editor_entities(
    parent: Any,
    *,
    node_uid_by_path: Mapping[str, str],
    identity_by_live_name: Mapping[tuple[str, str], str] | None = None,
    provenance_by_uid: Mapping[str, Mapping[str, Any]] | None = None,
    layout_constraints: Sequence[Mapping[str, Any]] = (),
    display_comment_flag: Any = None,
) -> list[dict[str, Any]]:
    """Snapshot boxes, stickies, comments, and topology-aware network dots."""

    identities = dict(identity_by_live_name or {})
    provenance = dict(provenance_by_uid or {})
    boxes = list(_call(parent, "networkBoxes", default=()))
    stickies = list(_call(parent, "stickyNotes", default=()))
    dots = list(_call(parent, "networkDots", default=()))
    editor_items = [
        ("network_box", item) for item in boxes
    ] + [
        ("sticky_note", item) for item in stickies
    ] + [
        ("network_dot", item) for item in dots
    ]
    uid_by_name: dict[str, str] = {}
    for kind, item in editor_items:
        name = _item_name(item)
        uid = identities.get(
            (kind, name), _artist_uid(kind, name)
        )
        previous = uid_by_name.setdefault(name, uid)
        if previous != uid:
            raise RuntimeError(
                f"Houdini editor item live name is not unique: {name}"
            )
    entities = [
        _snapshot_box(item, uid_by_name, node_uid_by_path, provenance)
        for item in boxes
    ]
    entities.extend(
        _snapshot_sticky(item, uid_by_name, provenance) for item in stickies
    )
    entities.extend(
        _snapshot_dot(
            parent, item, uid_by_name, node_uid_by_path, provenance
        )
        for item in dots
    )
    entities.extend(
        _snapshot_comments(
            parent,
            node_uid_by_path,
            provenance,
            display_comment_flag,
        )
    )
    entities.extend(copy.deepcopy(list(layout_constraints)))
    return normalize_editor_entities(
        entities, node_uids=node_uid_by_path.values()
    )


def apply_live_editor_entity_plan(
    parent: Any,
    plan: Mapping[str, Any],
    *,
    node_by_uid: Mapping[str, Any],
    live_name_by_uid: Mapping[str, Mapping[str, str]] | None = None,
    display_comment_flag: Any = None,
    checkpoint: Callable[[], None] | None = None,
) -> dict[str, Any]:
    """Apply a pure editor plan and roll back partial progress on failure.

    The caller remains responsible for the existing outer Houdini undo group.
    Newly created live names are returned so the root provenance table can bind
    durable Hocus UIDs to HOM items across save/reload.
    """

    plan = validate_editor_entity_plan(plan)
    operations = plan["operations"]
    names = {
        str(uid): {
            "kind": str(value.get("kind", "")),
            "liveName": str(value.get("liveName", "")),
        }
        for uid, value in (live_name_by_uid or {}).items()
        if isinstance(value, Mapping)
    }
    item_by_uid = _resolve_live_items(parent, names, node_by_uid)
    executed: list[dict[str, Any]] = []
    rollback: list[dict[str, Any]] = []
    check = checkpoint or (lambda: None)
    try:
        precreated = _precreate_live_items(
            parent, operations, item_by_uid, names, rollback, check
        )
        for operation in operations:
            check()
            if not (
                operation.get("action") == "create"
                and operation.get("uid") in precreated
            ):
                rollback.append(_inverse(operation))
            _execute_live_operation(
                parent,
                operation,
                item_by_uid,
                node_by_uid,
                names,
                display_comment_flag,
            )
            executed.append({
                "action": operation.get("action"),
                "uid": operation.get("uid"),
                "kind": operation.get("kind"),
            })
    except Exception as exc:
        rollback_error = _rollback_live_operations(
            parent,
            rollback,
            item_by_uid,
            node_by_uid,
            names,
            display_comment_flag,
        )
        raise EditorEntityLiveApplyError(
            str(exc),
            rolled_back=rollback_error is None,
            rollback_error=rollback_error,
        ) from exc
    return {
        "executed": executed,
        "liveIdentities": [
            {"uid": uid, **copy.deepcopy(value)}
            for uid, value in sorted(names.items())
        ],
        "noCooks": True,
    }


def _snapshot_box(
    item: Any,
    uid_by_name: Mapping[str, str],
    node_uid_by_path: Mapping[str, str],
    provenance: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    uid = uid_by_name[_item_name(item)]
    members = [
        _live_item_uid(member, uid_by_name, node_uid_by_path)
        for member in _call(item, "items", False, default=())
    ]
    return {
        "uid": uid,
        "kind": "network_box",
        "label": str(_call(item, "comment", default="") or ""),
        "position": _vec(_call(item, "position", default=None)),
        "size": _vec(_call(item, "size", default=None)),
        "color": _rgb(_call(item, "color", default=None)),
        "itemUids": sorted(members),
        "metadata": _metadata(uid, provenance, _item_name(item)),
    }


def _snapshot_sticky(
    item: Any,
    uid_by_name: Mapping[str, str],
    provenance: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    uid = uid_by_name[_item_name(item)]
    return {
        "uid": uid,
        "kind": "sticky_note",
        "text": str(_call(item, "text", default="") or ""),
        "position": _vec(_call(item, "position", default=None)),
        "size": _vec(_call(item, "size", default=None)),
        "color": _rgb(_call(item, "color", default=None)),
        "textSize": _hom_sticky_text_size(
            _call(item, "textSize", default=0.0)
        ),
        "drawBackground": bool(
            _call(item, "drawBackground", default=True)
        ),
        "minimized": bool(_call(item, "isMinimized", default=False)),
        "metadata": _metadata(uid, provenance, _item_name(item)),
    }


def _snapshot_dot(
    parent: Any,
    item: Any,
    uid_by_name: Mapping[str, str],
    node_uid_by_path: Mapping[str, str],
    provenance: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    uid = uid_by_name[_item_name(item)]
    source, output_index = _dot_input(item)
    input_value = None
    if source is not None:
        input_value = {
            "itemUid": _live_item_uid(
                source, uid_by_name, node_uid_by_path
            ),
            "outputIndex": output_index,
        }
    return {
        "uid": uid,
        "kind": "network_dot",
        "position": _vec(_call(item, "position", default=None)),
        "pinned": bool(_call(item, "isPinned", default=False)),
        "input": input_value,
        "outputs": _dot_outputs(parent, item, node_uid_by_path),
        "metadata": _metadata(uid, provenance, _item_name(item)),
    }


def _snapshot_comments(
    parent: Any,
    node_uid_by_path: Mapping[str, str],
    provenance: Mapping[str, Mapping[str, Any]],
    display_comment_flag: Any,
) -> list[dict[str, Any]]:
    comments: list[dict[str, Any]] = []
    for node in _call(parent, "children", default=()):
        path = _node_path(node)
        node_uid = node_uid_by_path.get(path)
        if node_uid is None:
            continue
        text = str(_call(node, "comment", default="") or "")
        visible = _comment_visible(node, display_comment_flag)
        uid = _comment_uid(node_uid, provenance)
        if not text and not visible and uid not in provenance:
            continue
        comments.append({
            "uid": uid,
            "kind": "node_comment",
            "nodeUid": node_uid,
            "text": text,
            "visible": visible,
            "metadata": _metadata(uid, provenance),
        })
    return comments


def _precreate_live_items(
    parent: Any,
    operations: list[Any],
    item_by_uid: dict[str, Any],
    names: dict[str, dict[str, str]],
    rollback: list[dict[str, Any]],
    checkpoint: Callable[[], None],
) -> set[str]:
    """Create all movable items before wiring dots or box membership."""

    created: set[str] = set()
    for operation in operations:
        if not isinstance(operation, Mapping) or operation.get("action") != "create":
            continue
        kind, uid = operation.get("kind"), str(operation.get("uid", ""))
        if kind in {"node_comment", "layout_constraint"}:
            continue
        checkpoint()
        if uid in item_by_uid:
            raise RuntimeError(f"Editor item already exists: {uid}")
        item = _create_live_item(parent, str(kind))
        item_by_uid[uid] = item
        rollback.append(_inverse(operation))
        live_name = _entity_live_name(
            operation.get("after"), str(kind), uid
        )
        _set_item_name(item, live_name)
        names[uid] = {"kind": str(kind), "liveName": live_name}
        created.add(uid)
    return created


def _execute_live_operation(
    parent: Any,
    operation: Mapping[str, Any],
    item_by_uid: dict[str, Any],
    node_by_uid: Mapping[str, Any],
    names: dict[str, dict[str, str]],
    display_comment_flag: Any,
) -> None:
    action = operation.get("action")
    uid, kind = str(operation.get("uid", "")), str(operation.get("kind", ""))
    if action == "delete":
        _delete_live_entity(
            operation.get("before"), item_by_uid, node_by_uid,
            names, display_comment_flag,
        )
        return
    if action not in {"create", "update"}:
        raise RuntimeError(f"Unsupported editor plan action: {action}")
    entity = operation.get("after")
    if not isinstance(entity, Mapping):
        raise RuntimeError(f"Editor plan after-state is missing: {uid}")
    if kind == "layout_constraint":
        return
    if kind == "node_comment":
        _configure_comment(entity, node_by_uid, display_comment_flag)
        return
    item = item_by_uid.get(uid)
    if item is None:
        item = _create_live_item(parent, kind)
        live_name = _entity_live_name(entity, kind, uid)
        _set_item_name(item, live_name)
        item_by_uid[uid] = item
        names[uid] = {"kind": kind, "liveName": live_name}
    _configure_live_item(item, entity, item_by_uid, node_by_uid)


def _delete_live_entity(
    entity: Any,
    item_by_uid: dict[str, Any],
    node_by_uid: Mapping[str, Any],
    names: dict[str, dict[str, str]],
    display_comment_flag: Any,
) -> None:
    if not isinstance(entity, Mapping):
        raise RuntimeError("Editor delete before-state is missing.")
    uid, kind = str(entity.get("uid", "")), entity.get("kind")
    if kind == "layout_constraint":
        return
    if kind == "node_comment":
        node = node_by_uid.get(str(entity.get("nodeUid", "")))
        if node is None:
            raise RuntimeError(f"Node comment target is missing: {uid}")
        _call_required(node, "setComment", "")
        _set_comment_visible(node, False, display_comment_flag)
        return
    item = item_by_uid.pop(uid, None)
    if item is None:
        raise RuntimeError(f"Editor item is missing: {uid}")
    if kind == "network_dot":
        _disconnect_dot_outputs(item, node_by_uid)
    _call_required(item, "destroy")
    names.pop(uid, None)


def _configure_live_item(
    item: Any,
    entity: Mapping[str, Any],
    item_by_uid: Mapping[str, Any],
    node_by_uid: Mapping[str, Any],
) -> None:
    kind = entity.get("kind")
    _set_vector(item, "setPosition", "position", entity["position"])
    if kind == "network_box":
        _configure_box(item, entity, item_by_uid, node_by_uid)
    elif kind == "sticky_note":
        _configure_sticky(item, entity)
    elif kind == "network_dot":
        _configure_dot(item, entity, item_by_uid, node_by_uid)
    else:
        raise RuntimeError(f"Unsupported live editor entity kind: {kind}")


def _configure_box(
    item: Any,
    entity: Mapping[str, Any],
    item_by_uid: Mapping[str, Any],
    node_by_uid: Mapping[str, Any],
) -> None:
    _call_required(item, "setAutoFit", False)
    _call_required(item, "setComment", entity["label"])
    _set_vector(item, "setSize", "size", entity["size"])
    _set_color(item, entity.get("color"))
    clear = getattr(item, "removeAllItems", None)
    if callable(clear):
        clear()
    else:
        for member in list(_call(item, "items", default=())):
            _call_required(item, "removeItem", member)
    for uid in entity["itemUids"]:
        member = item_by_uid.get(uid) or node_by_uid.get(uid)
        if member is None:
            raise RuntimeError(f"Network box member is missing: {uid}")
        _call_required(item, "addItem", member)


def _configure_sticky(item: Any, entity: Mapping[str, Any]) -> None:
    _call_required(item, "setText", entity["text"])
    _set_vector(item, "setSize", "size", entity["size"])
    _set_color(item, entity.get("color"))
    _call_required(
        item, "setTextSize",
        _document_sticky_text_size(entity["textSize"]),
    )
    _call_required(item, "setDrawBackground", entity["drawBackground"])
    _call_required(item, "setMinimized", entity["minimized"])


def _hom_sticky_text_size(value: Any) -> float:
    """Map Houdini's zero default sentinel into the document default."""

    observed = float(value)
    return 1.0 if observed == 0.0 else observed


def _document_sticky_text_size(value: Any) -> float:
    """Map the bounded document value into Houdini's numeric API."""

    return float(value)


def _configure_dot(
    item: Any,
    entity: Mapping[str, Any],
    item_by_uid: Mapping[str, Any],
    node_by_uid: Mapping[str, Any],
) -> None:
    _call_required(item, "setPinned", entity["pinned"])
    _disconnect_dot_outputs(item, node_by_uid)
    source = entity.get("input")
    if source is None:
        _call_required(item, "setInput", None)
    else:
        source_item = (
            item_by_uid.get(source["itemUid"])
            or node_by_uid.get(source["itemUid"])
        )
        if source_item is None:
            raise RuntimeError(
                f"Network dot input is missing: {source['itemUid']}"
            )
        _call_required(item, "setInput", source_item, source["outputIndex"])
    for output in entity["outputs"]:
        destination = node_by_uid.get(output["nodeUid"])
        if destination is None:
            raise RuntimeError(
                f"Network dot output is missing: {output['nodeUid']}"
            )
        _call_required(destination, "setInput", output["inputIndex"], item, 0)


def _configure_comment(
    entity: Mapping[str, Any],
    node_by_uid: Mapping[str, Any],
    display_comment_flag: Any,
) -> None:
    node = node_by_uid.get(str(entity.get("nodeUid", "")))
    if node is None:
        raise RuntimeError(f"Node comment target is missing: {entity.get('uid')}")
    _call_required(node, "setComment", entity["text"])
    _set_comment_visible(node, entity["visible"], display_comment_flag)


def _rollback_live_operations(
    parent: Any,
    rollback: list[dict[str, Any]],
    item_by_uid: dict[str, Any],
    node_by_uid: Mapping[str, Any],
    names: dict[str, dict[str, str]],
    display_comment_flag: Any,
) -> str | None:
    errors: list[str] = []
    operations = list(reversed(rollback))
    for operation in operations:
        if (
            operation.get("action") != "create"
            or operation.get("kind") in {"node_comment", "layout_constraint"}
        ):
            continue
        uid, kind = str(operation.get("uid", "")), str(operation.get("kind", ""))
        if uid in item_by_uid:
            continue
        try:
            item = _create_live_item(parent, kind)
            entity = operation.get("after")
            live_name = _entity_live_name(entity, kind, uid)
            _set_item_name(item, live_name)
            item_by_uid[uid] = item
            names[uid] = {"kind": kind, "liveName": live_name}
        except Exception as exc:
            errors.append(str(exc))
    for operation in operations:
        try:
            _execute_live_operation(
                parent,
                operation,
                item_by_uid,
                node_by_uid,
                names,
                display_comment_flag,
            )
        except Exception as exc:
            errors.append(str(exc))
    return "; ".join(errors) if errors else None


def _resolve_live_items(
    parent: Any,
    names: Mapping[str, Mapping[str, str]],
    node_by_uid: Mapping[str, Any],
) -> dict[str, Any]:
    by_key: dict[tuple[str, str], Any] = {}
    for kind, method in (
        ("network_box", "networkBoxes"),
        ("sticky_note", "stickyNotes"),
        ("network_dot", "networkDots"),
    ):
        for item in _call(parent, method, default=()):
            by_key[(kind, _item_name(item))] = item
    result = dict(node_by_uid)
    for uid, identity in names.items():
        key = (identity.get("kind", ""), identity.get("liveName", ""))
        item = by_key.get(key)
        if item is not None:
            result[uid] = item
    return result


def _create_live_item(parent: Any, kind: str) -> Any:
    method = {
        "network_box": "createNetworkBox",
        "sticky_note": "createStickyNote",
        "network_dot": "createNetworkDot",
    }.get(kind)
    if method is None:
        raise RuntimeError(f"Cannot create editor entity kind: {kind}")
    return _call_required(parent, method)


def _inverse(operation: Mapping[str, Any]) -> dict[str, Any]:
    action = {"create": "delete", "delete": "create", "update": "update"}.get(
        operation.get("action")
    )
    if action is None:
        raise RuntimeError("Editor plan operation cannot be inverted.")
    return {
        "action": action,
        "uid": operation.get("uid"),
        "kind": operation.get("kind"),
        "before": copy.deepcopy(operation.get("after")),
        "after": copy.deepcopy(operation.get("before")),
    }


def _dot_input(item: Any) -> tuple[Any | None, int]:
    value = _call(item, "input", default=None)
    if isinstance(value, (tuple, list)):
        source = value[0] if value else None
        index = value[1] if len(value) > 1 else 0
        return source, int(index or 0)
    if value is not None:
        index = _call(item, "inputItemOutputIndex", default=0)
        return value, int(index or 0)
    source = _call(item, "inputItem", default=None)
    index = _call(item, "inputItemOutputIndex", default=0)
    return source, int(index or 0)


def _dot_outputs(
    parent: Any,
    item: Any,
    node_uid_by_path: Mapping[str, str],
) -> list[dict[str, Any]]:
    outputs = []
    for node in _call(parent, "children", default=()):
        node_uid = node_uid_by_path.get(_node_path(node))
        if node_uid is None:
            continue
        for connection in _call(node, "inputsWithIndices", default=()):
            if not isinstance(connection, (tuple, list)) or len(connection) < 3:
                continue
            source, input_index = connection[0], connection[2]
            if _same_editor_item(source, item):
                outputs.append({
                    "nodeUid": node_uid,
                    "inputIndex": int(input_index),
                })
    return sorted(
        outputs, key=lambda value: (value["nodeUid"], value["inputIndex"])
    )


def _disconnect_dot_outputs(
    item: Any,
    node_by_uid: Mapping[str, Any],
) -> None:
    for node in node_by_uid.values():
        for connection in tuple(
            _call(node, "inputsWithIndices", default=())
        ):
            if not isinstance(connection, (tuple, list)) or len(connection) < 3:
                continue
            source, input_index = connection[0], connection[2]
            if _same_editor_item(source, item):
                _call_required(node, "setInput", int(input_index), None)


def _same_editor_item(left: Any, right: Any) -> bool:
    if left is right:
        return True
    if not (_is_network_dot(left) and _is_network_dot(right)):
        return False
    left_name = str(_call(left, "name", default="") or "").strip()
    right_name = str(_call(right, "name", default="") or "").strip()
    return bool(left_name and left_name == right_name)


def _is_network_dot(item: Any) -> bool:
    item_type = _call(item, "networkItemType", default=None)
    names = (type(item).__name__, str(_call(item_type, "name", default="") or ""))
    return any(name.replace("_", "").lower() in {"dot", "networkdot", "opnetworkdot"}
               for name in names)


def _live_item_uid(
    item: Any,
    uid_by_name: Mapping[str, str],
    node_uid_by_path: Mapping[str, str],
) -> str:
    path = _node_path(item)
    uid = node_uid_by_path.get(path)
    if uid is not None:
        return uid
    name = str(_call(item, "name", default="") or "").strip()
    uid = uid_by_name.get(name)
    if uid is None:
        raise RuntimeError(f"Editor item reference is outside the network: {path}")
    return uid


def _comment_uid(
    node_uid: str,
    provenance: Mapping[str, Mapping[str, Any]],
) -> str:
    matches = [
        uid for uid, hocus in provenance.items()
        if hocus.get("entityKind") == "node_comment"
        and hocus.get("nodeUid") == node_uid
    ]
    return matches[0] if len(matches) == 1 else f"artist:node_comment:{node_uid}"


def _metadata(
    uid: str,
    provenance: Mapping[str, Mapping[str, Any]],
    live_name: str | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    hocus = provenance.get(uid)
    if isinstance(hocus, Mapping):
        result["hocus"] = copy.deepcopy(dict(hocus))
    if live_name:
        result["liveName"] = live_name
    return result


def _set_item_name(item: Any, name: str) -> None:
    method = getattr(item, "setName", None)
    if not callable(method):
        raise RuntimeError("Houdini editor item cannot persist a live name.")
    try:
        method(name, False)
    except TypeError:
        method(name)
    if _item_name(item) != name:
        raise RuntimeError(
            "Houdini changed a managed editor item name; exact identity failed."
        )


def _set_vector(item: Any, setter: str, getter: str, value: Any) -> None:
    current = _call(item, getter, default=None)
    _call_required(item, setter, _coerce_like(current, value))


def _set_color(item: Any, value: Any) -> None:
    if value is None:
        return
    current = _call(item, "color", default=None)
    _call_required(item, "setColor", _coerce_like(current, value))


def _coerce_like(current: Any, value: Any) -> Any:
    if current is None:
        return tuple(value)
    constructor = type(current)
    try:
        return constructor(tuple(value))
    except (TypeError, ValueError):
        return tuple(value)


def _set_comment_visible(
    node: Any, visible: bool, display_comment_flag: Any
) -> None:
    direct = getattr(node, "setCommentVisible", None)
    if callable(direct):
        direct(bool(visible))
        return
    if display_comment_flag is None:
        raise RuntimeError("Display-comment flag is required for this Houdini build.")
    _call_required(node, "setGenericFlag", display_comment_flag, bool(visible))


def _comment_visible(node: Any, display_comment_flag: Any) -> bool:
    direct = getattr(node, "isCommentVisible", None)
    if callable(direct):
        return bool(direct())
    if display_comment_flag is None:
        return bool(_call(node, "comment", default=""))
    return bool(
        _call(node, "isGenericFlagSet", display_comment_flag, default=False)
    )


def _managed_live_name(kind: str, uid: str) -> str:
    token = hashlib.sha256(uid.encode("utf-8")).hexdigest()[:24]
    prefix = {
        "network_box": "box",
        "sticky_note": "sticky",
        "network_dot": "dot",
    }.get(kind, "item")
    return f"hocus_{prefix}_{token}"


def _entity_live_name(entity: Any, kind: str, uid: str) -> str:
    metadata = entity.get("metadata") if isinstance(entity, Mapping) else None
    value = metadata.get("liveName") if isinstance(metadata, Mapping) else None
    return (
        str(value).strip()
        if isinstance(value, str) and value.strip()
        else _managed_live_name(kind, uid)
    )


def _artist_uid(kind: str, live_name: str) -> str:
    return f"artist:{kind}:{live_name}"


def _item_name(item: Any) -> str:
    name = str(_call(item, "name", default="") or "").strip()
    if not name:
        raise RuntimeError("Houdini editor item has no stable live name.")
    return name


def _node_path(node: Any) -> str:
    return str(_call(node, "path", default="") or "").strip()


def _vec(value: Any) -> list[float]:
    if value is None:
        raise RuntimeError("Houdini editor item has no vector value.")
    return [float(value[0]), float(value[1])]


def _rgb(value: Any) -> list[float] | None:
    if value is None:
        return None
    rgb = _call(value, "rgb", default=value)
    return [float(rgb[0]), float(rgb[1]), float(rgb[2])]


def _call(
    target: Any,
    method_name: str,
    *args: Any,
    default: Any,
) -> Any:
    method = getattr(target, method_name, None)
    if not callable(method):
        return default
    try:
        return method(*args)
    except Exception:
        return default


def _call_required(target: Any, method_name: str, *args: Any) -> Any:
    method = getattr(target, method_name, None)
    if not callable(method):
        raise RuntimeError(f"Houdini editor API is unavailable: {method_name}")
    return method(*args)

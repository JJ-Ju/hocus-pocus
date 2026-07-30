"""HOM adapter for managed instance spares and bounded numeric animation."""

from __future__ import annotations

import copy
import hashlib
import hmac
import json
import math
import re
from typing import Any, Callable

from hocuspocus.core.jsonrpc import INVALID_PARAMS, JsonRpcError
from hocuspocus.hocusscript.document_runtime_contract import (
    DocumentRuntimeContractError,
    validate_runtime_json_envelope,
)


_SPARE_UID_TAG = "hocuspocus.managed_spare_uid"
_RUNTIME_RECEIPT_KEY = "hpmcp.runtime_contract"
_RUNTIME_RECEIPT_DIGEST_KEY = "hpmcp.runtime_contract_sha256"
_RECEIPT_VERSION = 1
_MAX_RECEIPT_BYTES = 4 * 1024 * 1024
_MAX_RECEIPT_ITEMS = 100_000
_RECEIPT_UID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_PARM_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
_KEY_FUNCTIONS = {
    "constant": "constant()",
    "linear": "linear()",
    "bezier": "bezier()",
}
_KEY_FUNCTION_PATTERN = re.compile(r"^(constant|linear|bezier)\(\)$")
_EXTRAPOLATION_NAMES = {
    "constant": "Hold",
    "linear": "Slope",
    "cycle": "Cycle",
    "cycle_offset": "CycleOffset",
    "oscillate": "Oscillate",
}
_KEY_GETTERS = {
    "slope": "slope",
    "accel": "accel",
    "slopeAuto": "isSlopeAuto",
    "accelAuto": "isAccelAuto",
    "slopeTied": "isSlopeTied",
    "accelTied": "isAccelTied",
    "slopeUsed": "isSlopeUsed",
    "accelUsed": "isAccelUsed",
}
_KEY_SETTERS = {
    "slope": "setSlope",
    "accel": "setAccel",
    "slopeAuto": "setSlopeAuto",
    "accelAuto": "setAccelAuto",
    "slopeTied": "setSlopeTied",
    "accelTied": "setAccelTied",
    "slopeUsed": "setSlopeUsed",
    "accelUsed": "setAccelUsed",
}


def plan_runtime_changes(
    baseline: dict[str, Any],
    target: dict[str, Any],
    *,
    mode: str,
    target_nodes: dict[str, dict[str, Any]],
    create_uids: set[str],
) -> dict[str, list[dict[str, Any]]]:
    """Build deterministic instance-interface and animation operations."""

    before_spares = _by_uid(baseline.get("spareParameters", []))
    after_spares = _by_uid(target.get("spareParameters", []))
    before_animations = _by_uid(baseline.get("animations", []))
    after_animations = _by_uid(target.get("animations", []))
    ownership = _runtime_target_ownership(
        target, (*after_spares.values(), *after_animations.values())
    )
    _reject_runtime_ownership_transfers(
        before_spares, after_spares, ownership
    )
    _reject_runtime_ownership_transfers(
        before_animations, after_animations, ownership
    )
    spare_changes: list[dict[str, Any]] = []
    for uid in sorted(after_spares):
        item = after_spares[uid]
        if item.get("nodeUid") in create_uids or before_spares.get(uid) != item:
            spare_changes.append(_runtime_entry(
                "upsert", item, target_nodes, "declaration"
            ))
    if mode == "reconcile":
        for uid in sorted(set(before_spares) - set(after_spares)):
            item = before_spares[uid]
            if (
                item.get("nodeUid") in target_nodes
                and _runtime_entity_ownership(item) == ownership
            ):
                spare_changes.append(_runtime_entry(
                    "remove", item, target_nodes, "declaration"
                ))

    clears: list[dict[str, Any]] = []
    updates: list[dict[str, Any]] = []
    for uid in sorted(after_animations):
        item = after_animations[uid]
        previous = before_animations.get(uid)
        if item.get("nodeUid") in create_uids or previous != item:
            if previous is not None:
                clears.append(_runtime_entry(
                    "clear", previous, target_nodes, "animation"
                ))
            updates.append(_runtime_entry(
                "set", item, target_nodes, "animation"
            ))
    if mode == "reconcile":
        for uid in sorted(set(before_animations) - set(after_animations)):
            item = before_animations[uid]
            if (
                item.get("nodeUid") in target_nodes
                and _runtime_entity_ownership(item) == ownership
            ):
                clears.append(_runtime_entry(
                    "clear", item, target_nodes, "animation"
                ))
    return {
        "spareParameterChanges": spare_changes,
        "animationClears": clears,
        "animationUpdates": updates,
    }


def _runtime_target_ownership(
    target: dict[str, Any],
    entities: tuple[dict[str, Any], ...],
) -> str | None:
    metadata = target.get("metadata")
    preview = metadata.get("hocusPreview") if isinstance(metadata, dict) else None
    root_owner = preview.get("ownership") if isinstance(preview, dict) else None
    owners = {
        owner
        for item in entities
        if (owner := _runtime_entity_ownership(item)) is not None
    }
    if isinstance(root_owner, str) and root_owner:
        owners.add(root_owner)
    if len(owners) > 1:
        raise _invalid(
            "Managed runtime entities cannot cross ownership namespaces."
        )
    return next(iter(owners), None)


def _runtime_entity_ownership(item: dict[str, Any]) -> str | None:
    metadata = item.get("metadata")
    hocus = metadata.get("hocus") if isinstance(metadata, dict) else None
    ownership = hocus.get("ownership") if isinstance(hocus, dict) else None
    return ownership if isinstance(ownership, str) and ownership else None


def _reject_runtime_ownership_transfers(
    before: dict[str, dict[str, Any]],
    after: dict[str, dict[str, Any]],
    ownership: str | None,
) -> None:
    before_by_target = {
        target: item
        for item in before.values()
        if (target := _runtime_target(item)) is not None
    }
    for uid, item in sorted(after.items()):
        target = _runtime_target(item)
        prior_entities = (before.get(uid), before_by_target.get(target))
        for previous in prior_entities:
            if previous is not None and (
                (previous_owner := _runtime_entity_ownership(previous))
                is not None
                and previous_owner != ownership
            ):
                raise _invalid(
                    f"Managed runtime entity '{uid}' belongs to another "
                    "ownership namespace."
                )


def _runtime_target(item: dict[str, Any]) -> tuple[str, str] | None:
    node_uid = item.get("nodeUid")
    name = item.get("name", item.get("parmName"))
    if not isinstance(node_uid, str) or not isinstance(name, str):
        return None
    return node_uid, name


def runtime_plan_summary(
    changes: dict[str, list[dict[str, Any]]],
) -> dict[str, int]:
    return {
        "spareParameterChangeCount": len(
            changes["spareParameterChanges"]
        ),
        "animationClearCount": len(changes["animationClears"]),
        "animationUpdateCount": len(changes["animationUpdates"]),
    }


def execute_runtime_bindings(
    operations: Any,
    plan: dict[str, Any],
    state: dict[str, Any],
    executed: list[dict[str, Any]],
    checkpoint: Callable[[], None],
) -> None:
    """Execute the ownership-sensitive runtime/binding phase in fixed order."""

    spare_changes = plan.get("spareParameterChanges", [])
    execute_spare_changes(
        operations,
        [item for item in spare_changes if item.get("action") == "upsert"],
        state,
        executed,
        checkpoint,
    )
    execute_animation_clears(
        operations, plan.get("animationClears", []),
        state, executed, checkpoint,
    )
    operations._document_execute_bindings(
        plan, state, executed, checkpoint
    )
    execute_animation_updates(
        operations, plan.get("animationUpdates", []),
        state, executed, checkpoint,
    )
    execute_spare_changes(
        operations,
        [item for item in spare_changes if item.get("action") == "remove"],
        state,
        executed,
        checkpoint,
    )


def execute_spare_changes(
    operations: Any,
    changes: list[dict[str, Any]],
    state: dict[str, Any],
    executed: list[dict[str, Any]],
    checkpoint: Callable[[], None],
) -> None:
    """Reconcile each touched node's instance PTG once."""

    grouped: dict[str, list[dict[str, Any]]] = {}
    for change in changes:
        grouped.setdefault(str(change.get("nodeUid", "")), []).append(change)
    for node_uid in sorted(grouped):
        checkpoint()
        node = _runtime_node(operations, state, grouped[node_uid][0])
        _assert_instance_editable(node)
        group = _call_required(node, "parmTemplateGroup")()
        receipt = _runtime_receipt(node)
        managed, names = _managed_spare_templates(node, receipt)
        spare_receipts = receipt.setdefault("spareParameters", {})
        for change in grouped[node_uid]:
            declaration = change["declaration"]
            uid = declaration["uid"]
            current = managed.get(uid)
            if change["action"] == "remove":
                if current is not None:
                    _call_required(group, "remove")(current["name"])
                spare_receipts.pop(uid, None)
                continue
            collision = names.get(declaration["name"])
            if collision is not None and collision["uid"] != uid:
                raise _invalid(
                    f"Managed spare '{declaration['name']}' conflicts with an "
                    "artist-owned or differently managed instance spare."
                )
            template = _spare_template(operations._require_hou(), declaration)
            if current is None:
                _call_required(group, "append")(template)
            else:
                _call_required(group, "replace")(current["name"], template)
            spare_receipts[uid] = {
                "name": declaration["name"],
                "metadata": copy.deepcopy(declaration["metadata"]),
            }
        setter = _call_required(node, "setParmTemplateGroup")
        setter(group, rename_conflicting_parms=False)
        _write_runtime_receipt(node, receipt)
        _verify_spare_changes(node, grouped[node_uid])
        executed.extend({
            "type": (
                "remove_managed_spare"
                if item["action"] == "remove"
                else "upsert_managed_spare"
            ),
            "uid": item["declaration"]["uid"],
            "nodeUid": node_uid,
            "nodePath": str(node.path()),
            "parmName": item["declaration"]["name"],
        } for item in grouped[node_uid])


def execute_animation_clears(
    operations: Any,
    changes: list[dict[str, Any]],
    state: dict[str, Any],
    executed: list[dict[str, Any]],
    checkpoint: Callable[[], None],
) -> None:
    for change in changes:
        checkpoint()
        node = _runtime_node(operations, state, change)
        _assert_instance_editable(node)
        animation = change["animation"]
        parm = _runtime_parm(node, animation["parmName"])
        _call_required(parm, "deleteAllKeyframes")()
        if tuple(_call_required(parm, "keyframes")()):
            raise _invalid("Managed animation could not be cleared exactly.")
        receipt = _runtime_receipt(node)
        receipt.setdefault("animations", {}).pop(animation["uid"], None)
        _write_runtime_receipt(node, receipt)
        executed.append({
            "type": "clear_numeric_animation",
            "uid": animation["uid"],
            "nodeUid": animation["nodeUid"],
            "parmPath": str(parm.path()),
        })


def execute_animation_updates(
    operations: Any,
    changes: list[dict[str, Any]],
    state: dict[str, Any],
    executed: list[dict[str, Any]],
    checkpoint: Callable[[], None],
) -> None:
    hou_module = operations._require_hou()
    for change in changes:
        checkpoint()
        node = _runtime_node(operations, state, change)
        _assert_instance_editable(node)
        animation = change["animation"]
        parm = _runtime_parm(node, animation["parmName"])
        _assert_animation_parm_type(parm, animation["valueType"])
        _call_required(parm, "deleteAllKeyframes")()
        for carried in animation["keys"]:
            keyframe = _new_keyframe(hou_module, carried)
            _call_required(parm, "setKeyframe")(keyframe)
        _set_extrapolation(hou_module, parm, animation["extrapolation"])
        receipt = _runtime_receipt(node)
        receipt.setdefault("animations", {})[animation["uid"]] = {
            key: copy.deepcopy(animation[key])
            for key in (
                "parmName", "valueType", "value", "authoredFps",
                "displayFps", "metadata",
            )
        }
        receipt["animations"][animation["uid"]]["tangentFields"] = [
            sorted(set(key) & set(_KEY_SETTERS))
            for key in animation["keys"]
        ]
        _write_runtime_receipt(node, receipt)
        observed, diagnostics = _snapshot_animation(
            node, animation["uid"],
            receipt["animations"][animation["uid"]],
            hou_module,
            animation["nodeUid"],
        )
        if diagnostics or observed != animation:
            raise _invalid("Managed animation could not be verified exactly.")
        executed.append({
            "type": "set_numeric_animation",
            "uid": animation["uid"],
            "nodeUid": animation["nodeUid"],
            "parmPath": str(parm.path()),
            "keyCount": len(animation["keys"]),
        })


def snapshot_runtime_contract(
    operations: Any,
    document: dict[str, Any],
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    set[tuple[str, str]],
]:
    """Snapshot only Hocus-managed instance spares and animations."""

    spares: list[dict[str, Any]] = []
    animations: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    binding_targets: set[tuple[str, str]] = set()
    hou_module = operations._require_hou()
    for item in document.get("nodes", []):
        if not isinstance(item, dict):
            continue
        path = str(item.get("path", "")).strip()
        node_uid = str(item.get("uid", "")).strip()
        node = operations._safe_value(lambda path=path: hou_module.node(path), None)
        if node is None:
            continue
        receipt = _runtime_receipt(node)
        receipt_spares = receipt.get("spareParameters", {})
        managed_spares, _ = _managed_spare_templates(node, receipt)
        for uid, managed in sorted(managed_spares.items()):
            component_names = {
                str(_safe_call(parm, "name", "") or "")
                for parm in managed["components"]
            }
            component_names.discard("")
            if not component_names:
                component_names.add(str(managed["name"]))
            binding_targets.update(
                (node_uid, name) for name in component_names
            )
            try:
                spares.append(_snapshot_spare(
                    managed["template"], uid, node_uid,
                    receipt_spares.get(uid, {}),
                ))
            except (KeyError, TypeError, ValueError) as exc:
                diagnostics.append(_diagnostic(
                    "spare_parameter.live_unsupported", str(exc),
                    node_uid, path,
                ))
        for uid, carried in sorted(receipt.get("animations", {}).items()):
            parm_name = str(carried.get("parmName", "")).strip()
            if parm_name:
                binding_targets.add((node_uid, parm_name))
            observed, errors = _snapshot_animation(
                node, uid, carried, hou_module, node_uid,
            )
            if observed is not None:
                animations.append(observed)
            diagnostics.extend(
                _diagnostic(
                    "animation.live_unsupported", message, node_uid, path,
                )
                for message in errors
            )
    return (
        sorted(spares, key=lambda item: (item["nodeUid"], item["uid"])),
        sorted(animations, key=lambda item: (item["nodeUid"], item["uid"])),
        diagnostics,
        binding_targets,
    )


def _runtime_entry(
    action: str,
    item: dict[str, Any],
    nodes: dict[str, dict[str, Any]],
    field: str,
) -> dict[str, Any]:
    node_uid = str(item.get("nodeUid", ""))
    return {
        "action": action,
        "nodeUid": node_uid,
        "nodePath": str(nodes.get(node_uid, {}).get("path", "")),
        field: copy.deepcopy(item),
    }


def _by_uid(values: Any) -> dict[str, dict[str, Any]]:
    return {
        str(item["uid"]): item
        for item in values
        if isinstance(item, dict) and isinstance(item.get("uid"), str)
    } if isinstance(values, list) else {}


def _runtime_node(operations: Any, state: dict[str, Any], item: dict[str, Any]) -> Any:
    path = operations._document_apply_state_current_path(
        state, str(item.get("nodeUid", "")), item.get("nodePath"),
    )
    node = operations._require_hou().node(path) if path else None
    if node is None:
        raise _invalid("Managed runtime entity target node is unavailable.")
    return node


def _runtime_parm(node: Any, name: str) -> Any:
    parm = _call_required(node, "parm")(name)
    if parm is None:
        raise _invalid(f"Managed animation parameter '{name}' is unavailable.")
    template = _call_required(parm, "parmTemplate")()
    if bool(_safe_call(template, "isMultiParmInstance", False)):
        raise _invalid("Multiparm components cannot carry managed animation.")
    return parm


def _assert_instance_editable(node: Any) -> None:
    if bool(_safe_call(node, "isInsideLockedHDA", False)):
        raise _invalid(
            "Managed runtime edits reject locked internal nodes; HDA "
            "definition edits and implicit unlock are not permitted."
        )


def _managed_spare_templates(
    node: Any,
    receipt: dict[str, Any] | None = None,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    trusted = receipt if receipt is not None else _runtime_receipt(node)
    trusted_spares = trusted["spareParameters"]
    managed: dict[str, dict[str, Any]] = {}
    names: dict[str, dict[str, Any]] = {}
    seen: set[str] = set()
    for parm in tuple(_safe_call(node, "spareParms", ()) or ()):
        if not bool(_safe_call(parm, "isSpare", False)):
            continue
        template = _call_required(parm, "parmTemplate")()
        name = str(_call_required(template, "name")())
        existing = names.get(name)
        if existing is not None:
            existing["components"].append(parm)
            continue
        if name in seen:
            continue
        seen.add(name)
        tags = _safe_call(template, "tags", {}) or {}
        tag_uid = str(tags.get(_SPARE_UID_TAG, "")).strip()
        trusted_entry = trusted_spares.get(tag_uid)
        uid = (
            tag_uid
            if isinstance(trusted_entry, dict)
            and trusted_entry.get("name") == name
            else ""
        )
        record = {
            "uid": uid, "tagUid": tag_uid,
            "name": name, "template": template,
            "components": [parm],
        }
        names[name] = record
        if uid:
            if uid in managed:
                raise _invalid("Duplicate managed spare uid exists on one node.")
            managed[uid] = record
    return managed, names


def _spare_template(hou_module: Any, declaration: dict[str, Any]) -> Any:
    name, label = declaration["name"], declaration["label"]
    spare_type = declaration["type"]
    default = declaration["default"]
    if spare_type == "float":
        template = hou_module.FloatParmTemplate(
            name, label, declaration["tupleSize"],
            default_value=tuple(float(item) for item in default),
        )
    elif spare_type == "int":
        template = hou_module.IntParmTemplate(
            name, label, 1, default_value=(int(default),),
        )
    elif spare_type == "string":
        template = hou_module.StringParmTemplate(
            name, label, 1, default_value=(default,),
        )
    elif spare_type == "toggle":
        template = hou_module.ToggleParmTemplate(
            name, label, default_value=bool(default),
        )
    elif spare_type == "menu":
        items = declaration["menuItems"]
        tokens = tuple(item["token"] for item in items)
        labels = tuple(item["label"] for item in items)
        template = hou_module.MenuParmTemplate(
            name, label, tokens, menu_labels=labels,
            default_value=tokens.index(default),
        )
        menu_use_token = getattr(template, "setMenuUseToken", None)
        if callable(menu_use_token):
            menu_use_token(True)
    else:
        raise _invalid(f"Unsupported managed spare type: {spare_type}.")
    tags = dict(_safe_call(template, "tags", {}) or {})
    tags[_SPARE_UID_TAG] = declaration["uid"]
    _call_required(template, "setTags")(tags)
    return template


def _snapshot_spare(
    template: Any,
    uid: str,
    node_uid: str,
    receipt: dict[str, Any],
) -> dict[str, Any]:
    type_name = _enum_name(_call_required(template, "type")()).lower()
    name = str(_call_required(template, "name")())
    label = str(_call_required(template, "label")())
    tuple_size = int(_safe_call(template, "numComponents", 1))
    default = _safe_call(template, "defaultValue", None)
    menu_items: list[dict[str, str]] = []
    if type_name == "float":
        spare_type = "float"
        carried_default: Any = [float(item) for item in tuple(default)]
    elif type_name == "int":
        spare_type, tuple_size = "int", 1
        carried_default = int(tuple(default)[0])
    elif type_name == "string":
        spare_type, tuple_size = "string", 1
        carried_default = str(tuple(default)[0])
    elif type_name == "toggle":
        spare_type, tuple_size = "toggle", 1
        carried_default = bool(default)
    elif type_name == "menu":
        spare_type, tuple_size = "menu", 1
        tokens = tuple(_call_required(template, "menuItems")())
        labels = tuple(_call_required(template, "menuLabels")())
        menu_items = [
            {"token": str(token), "label": str(menu_label)}
            for token, menu_label in zip(tokens, labels)
        ]
        carried_default = (
            default if isinstance(default, str) else str(tokens[int(default)])
        )
    else:
        raise ValueError(f"Managed spare template type '{type_name}' is unsupported.")
    return {
        "uid": uid,
        "nodeUid": node_uid,
        "name": name,
        "label": label,
        "type": spare_type,
        "tupleSize": tuple_size,
        "default": carried_default,
        "menuItems": menu_items,
        "metadata": copy.deepcopy(receipt.get("metadata", {"managed": True})),
    }


def _new_keyframe(hou_module: Any, carried: dict[str, Any]) -> Any:
    keyframe_class = getattr(hou_module, "Keyframe", None)
    if not callable(keyframe_class):
        raise _invalid("This Houdini build lacks numeric Keyframe support.")
    keyframe = keyframe_class()
    _call_required(keyframe, "setTime")(float(carried["timeSeconds"]))
    _call_required(keyframe, "setValue")(carried["value"])
    language = getattr(getattr(hou_module, "exprLanguage", None), "Hscript", None)
    if language is None:
        raise _invalid("This Houdini build lacks fixed HScript key functions.")
    _call_required(keyframe, "setExpression")(
        _KEY_FUNCTIONS[carried["interpolation"]], language,
    )
    for field, setter_name in _KEY_SETTERS.items():
        if field in carried:
            _call_required(keyframe, setter_name)(carried[field])
    return keyframe


def _set_extrapolation(
    hou_module: Any, parm: Any, extrapolation: dict[str, str],
) -> None:
    enum = getattr(hou_module, "parmExtrapolate", None)
    setter = _call_required(parm, "setKeyframeExtrapolation")
    if enum is None:
        raise _invalid("This Houdini build lacks keyframe extrapolation support.")
    for before, field in ((True, "before"), (False, "after")):
        value = getattr(enum, _EXTRAPOLATION_NAMES[extrapolation[field]], None)
        if value is None:
            raise _invalid("Requested extrapolation is unavailable in this build.")
        setter(before, value)


def _snapshot_animation(
    node: Any,
    uid: str,
    carried: dict[str, Any],
    hou_module: Any,
    node_uid: str,
) -> tuple[dict[str, Any] | None, list[str]]:
    try:
        parm = _runtime_parm(node, str(carried["parmName"]))
        value_type = str(carried["valueType"])
        _assert_animation_parm_type(parm, value_type)
        keyframes = tuple(_call_required(parm, "keyframes")())
        if not keyframes:
            raise _invalid("Managed animation receipt has no live keyframes.")
        keys = [
            _snapshot_keyframe(item, hou_module, value_type)
            for item in keyframes
        ]
        keys.sort(key=lambda item: item["timeSeconds"])
        tangent_fields = carried.get("tangentFields", [])
        if isinstance(tangent_fields, list) and len(tangent_fields) == len(keys):
            for key, fields in zip(keys, tangent_fields):
                allowed = set(fields) if isinstance(fields, list) else set()
                for field in _KEY_SETTERS:
                    if field not in allowed:
                        key.pop(field, None)
        extrapolation = {
            "before": _snapshot_extrapolation(parm, True),
            "after": _snapshot_extrapolation(parm, False),
        }
        return {
            "uid": uid,
            "nodeUid": node_uid,
            "parmName": str(carried["parmName"]),
            "valueType": value_type,
            "value": copy.deepcopy(carried["value"]),
            "authoredFps": carried["authoredFps"],
            "displayFps": carried["displayFps"],
            "extrapolation": extrapolation,
            "keys": keys,
            "metadata": copy.deepcopy(carried.get("metadata", {})),
        }, []
    except (JsonRpcError, KeyError, TypeError, ValueError) as exc:
        return None, [str(exc)]


def _snapshot_keyframe(
    keyframe: Any, hou_module: Any, value_type: str,
) -> dict[str, Any]:
    if keyframe.__class__.__name__ == "StringKeyframe":
        raise _invalid("StringKeyframe is explicitly unsupported.")
    language = _safe_call(keyframe, "expressionLanguage", None)
    hscript = getattr(getattr(hou_module, "exprLanguage", None), "Hscript", None)
    if language is not None and hscript is not None and language != hscript:
        raise _invalid("Python keyframe expressions are explicitly unsupported.")
    expression = str(_call_required(keyframe, "expression")()).strip()
    match = _KEY_FUNCTION_PATTERN.fullmatch(expression)
    if match is None:
        raise _invalid("Arbitrary HScript keyframe expressions are unsupported.")
    value: Any = _call_required(keyframe, "value")()
    if value_type == "int":
        if isinstance(value, bool) or int(value) != value:
            raise _invalid("Animated int key values must remain integral.")
        value = int(value)
    else:
        value = float(value)
    result = {
        "timeSeconds": float(_call_required(keyframe, "time")()),
        "value": value,
        "interpolation": match.group(1),
    }
    for field, getter_name in _KEY_GETTERS.items():
        getter = getattr(keyframe, getter_name, None)
        if callable(getter):
            result[field] = getter()
    return result


def _snapshot_extrapolation(parm: Any, before: bool) -> str:
    value = _call_required(parm, "keyframeExtrapolation")(before)
    name = _enum_name(value)
    reverse = {item: key for key, item in _EXTRAPOLATION_NAMES.items()}
    if name not in reverse:
        raise _invalid(f"Keyframe extrapolation '{name}' is unsupported.")
    return reverse[name]


def _assert_animation_parm_type(parm: Any, expected: str) -> None:
    template = _call_required(parm, "parmTemplate")()
    type_name = _enum_name(_call_required(template, "type")()).lower()
    if type_name != expected:
        raise _invalid(
            "Only scalar float and integral int parameter components may be animated."
        )


def _verify_spare_changes(node: Any, changes: list[dict[str, Any]]) -> None:
    managed, _ = _managed_spare_templates(node, _runtime_receipt(node))
    for change in changes:
        declaration = change["declaration"]
        present = declaration["uid"] in managed
        if present != (change["action"] != "remove"):
            raise _invalid("Managed spare reconciliation verification failed.")
        if present:
            observed = _snapshot_spare(
                managed[declaration["uid"]]["template"],
                declaration["uid"],
                declaration["nodeUid"],
                {"metadata": declaration["metadata"]},
            )
            if observed != declaration:
                raise _invalid("Managed spare declaration was not represented exactly.")


def _runtime_receipt(node: Any) -> dict[str, Any]:
    raw = _safe_call(node, "userData", None, _RUNTIME_RECEIPT_KEY)
    digest = _safe_call(
        node, "userData", None, _RUNTIME_RECEIPT_DIGEST_KEY
    )
    if not raw and not digest:
        return {
            "version": _RECEIPT_VERSION,
            "spareParameters": {},
            "animations": {},
        }
    if (
        not isinstance(raw, str)
        or not isinstance(digest, str)
        or len(raw.encode("utf-8")) > _MAX_RECEIPT_BYTES
        or not hmac.compare_digest(_receipt_digest(raw), digest)
    ):
        raise _invalid("Managed runtime receipt authentication failed.")
    try:
        value = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise _invalid("Managed runtime receipt is malformed.") from exc
    if (
        not isinstance(value, dict)
        or set(value) != {
            "version", "spareParameters", "animations",
        }
        or value.get("version") != _RECEIPT_VERSION
        or not isinstance(value.get("spareParameters"), dict)
        or not isinstance(value.get("animations"), dict)
    ):
        raise _invalid("Managed runtime receipt has an unsupported shape.")
    try:
        validate_runtime_json_envelope(
            value,
            label="managed runtime receipt",
            max_items=_MAX_RECEIPT_ITEMS,
            max_text_bytes=_MAX_RECEIPT_BYTES,
            max_depth=16,
        )
    except DocumentRuntimeContractError as exc:
        raise _invalid(str(exc)) from exc
    _validate_receipt_entries(value)
    return value


def _write_runtime_receipt(node: Any, receipt: dict[str, Any]) -> None:
    encoded = json.dumps(
        receipt, ensure_ascii=False, separators=(",", ":"), sort_keys=True,
        allow_nan=False,
    )
    if len(encoded.encode("utf-8")) > _MAX_RECEIPT_BYTES:
        raise _invalid("Managed runtime receipt exceeds 4 MiB.")
    _call_required(node, "setUserData")(_RUNTIME_RECEIPT_KEY, encoded)
    _call_required(node, "setUserData")(
        _RUNTIME_RECEIPT_DIGEST_KEY, _receipt_digest(encoded)
    )


def _receipt_digest(encoded: str) -> str:
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _validate_receipt_entries(value: dict[str, Any]) -> None:
    if (
        len(value["spareParameters"]) > 16_384
        or len(value["animations"]) > 16_384
    ):
        raise _invalid("Managed runtime receipt entry count is out of bounds.")
    for uid, entry in value["spareParameters"].items():
        if (
            not isinstance(uid, str)
            or _RECEIPT_UID.fullmatch(uid) is None
            or not isinstance(entry, dict)
            or set(entry) != {"name", "metadata"}
            or not isinstance(entry["name"], str)
            or _PARM_NAME.fullmatch(entry["name"]) is None
            or not isinstance(entry["metadata"], dict)
        ):
            raise _invalid("Managed spare receipt entry is malformed.")
    animation_fields = {
        "parmName", "valueType", "value", "authoredFps", "displayFps",
        "metadata", "tangentFields",
    }
    for uid, entry in value["animations"].items():
        tangent_fields = entry.get("tangentFields")
        if (
            not isinstance(uid, str)
            or _RECEIPT_UID.fullmatch(uid) is None
            or not isinstance(entry, dict)
            or set(entry) != animation_fields
            or not isinstance(entry["parmName"], str)
            or _PARM_NAME.fullmatch(entry["parmName"]) is None
            or entry["valueType"] not in {"float", "int"}
            or not isinstance(entry["metadata"], dict)
            or not isinstance(tangent_fields, list)
            or len(tangent_fields) > 4_096
            or any(
                not isinstance(fields, list)
                or len(fields) > len(_KEY_SETTERS)
                or len(fields) != len(set(fields))
                or not set(fields) <= set(_KEY_SETTERS)
                for fields in tangent_fields
            )
            or not _receipt_numeric(
                entry["value"], entry["valueType"]
            )
            or any(
                not _finite_positive_fps(entry[field])
                for field in ("authoredFps", "displayFps")
            )
        ):
            raise _invalid("Managed animation receipt entry is malformed.")


def _receipt_numeric(value: Any, value_type: str) -> bool:
    if value_type == "int":
        return type(value) is int
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(value)
    )


def _finite_positive_fps(value: Any) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(value)
        and 0 < value <= 1_000
    )


def _enum_name(value: Any) -> str:
    name = getattr(value, "name", None)
    return str(name() if callable(name) else name or value).rsplit(".", 1)[-1]


def _safe_call(
    value: Any, name: str, default: Any, *arguments: Any,
) -> Any:
    callback = getattr(value, name, None)
    if not callable(callback):
        return default
    try:
        return callback(*arguments)
    except Exception:
        return default


def _call_required(value: Any, name: str) -> Callable[..., Any]:
    callback = getattr(value, name, None)
    if not callable(callback):
        raise _invalid(f"Required HOM method '{name}' is unavailable.")
    return callback


def _diagnostic(
    code: str, message: str, node_uid: str, path: str,
) -> dict[str, Any]:
    return {
        "severity": "error",
        "code": code,
        "message": message,
        "entityUid": node_uid,
        "path": path,
    }


def _invalid(message: str) -> JsonRpcError:
    return JsonRpcError(INVALID_PARAMS, message)

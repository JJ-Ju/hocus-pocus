"""Closed HS7 carrier contract for managed spares and numeric animation."""

from __future__ import annotations

import copy
import math
import re
from typing import Any, Iterable


MAX_SPARE_PARAMETERS = 16_384
MAX_ANIMATIONS = 16_384
MAX_KEYS_PER_ANIMATION = 4_096
MAX_ABS_TIME_SECONDS = 1_000_000_000.0
MAX_FPS = 1_000.0
MAX_RUNTIME_ENVELOPE_ITEMS = 250_000
MAX_RUNTIME_ENVELOPE_TEXT_BYTES = 8 * 1024 * 1024

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
_ENTITY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_SPARE_TYPES = {"float", "int", "string", "toggle", "menu"}
_INTERPOLATIONS = {"constant", "linear", "bezier"}
_EXTRAPOLATIONS = {
    "constant", "linear", "cycle", "cycle_offset", "oscillate",
}
_SPARE_FIELDS = {
    "uid", "nodeUid", "name", "label", "type", "tupleSize", "default",
    "menuItems", "metadata",
}
_ANIMATION_FIELDS = {
    "uid", "nodeUid", "parmName", "valueType", "value", "authoredFps",
    "displayFps", "extrapolation", "keys", "metadata",
}
_KEY_REQUIRED = {"timeSeconds", "value", "interpolation"}
_KEY_TANGENTS = {
    "slope", "accel", "slopeAuto", "accelAuto", "slopeTied",
    "accelTied", "slopeUsed", "accelUsed",
}


class DocumentRuntimeContractError(ValueError):
    """Typed rejection for malformed spare/animation carrier content."""


def attach_runtime_contract(
    document: dict[str, Any],
    *,
    spare_parameters: Iterable[dict[str, Any]] = (),
    animations: Iterable[dict[str, Any]] = (),
) -> dict[str, Any]:
    """Return a validated v2 document carrying source-lowered runtime entities.

    This is the source-lowering seam: parser/GraphSpec owners can lower their
    authenticated declarations independently, then attach the exact entities
    here without importing any Houdini runtime module.
    """

    result = copy.deepcopy(document)
    result["$schema"] = "hocuspocus://schemas/network-document/v2"
    result["spareParameters"] = sorted(
        (copy.deepcopy(item) for item in spare_parameters),
        key=lambda item: (str(item.get("nodeUid", "")), str(item.get("uid", ""))),
    )
    result["animations"] = sorted(
        (copy.deepcopy(item) for item in animations),
        key=lambda item: (str(item.get("nodeUid", "")), str(item.get("uid", ""))),
    )
    validate_runtime_contract(result, _node_uids(result))
    return result


def validate_runtime_contract(
    document: dict[str, Any],
    node_uids: set[str] | None = None,
) -> None:
    """Validate the optional closed runtime contract on a v2 document."""

    nodes = node_uids if node_uids is not None else _node_uids(document)
    spares = document.get("spareParameters", [])
    animations = document.get("animations", [])
    if not isinstance(spares, list) or len(spares) > MAX_SPARE_PARAMETERS:
        _fail("spareParameters exceeds its closed carrier bound.")
    if not isinstance(animations, list) or len(animations) > MAX_ANIMATIONS:
        _fail("animations exceeds its closed carrier bound.")
    validate_runtime_json_envelope(
        {"spareParameters": spares, "animations": animations},
        label="runtime contract",
    )
    if "timeSamples" in document:
        _fail("USD time samples are not supported by the HS7 runtime contract.")

    spare_uids: set[str] = set()
    spare_targets: set[tuple[str, str]] = set()
    spares_by_target: dict[tuple[str, str], dict[str, Any]] = {}
    for spare in spares:
        _validate_spare(spare, nodes, spare_uids, spare_targets)
        spares_by_target[(spare["nodeUid"], spare["name"])] = spare

    animation_uids: set[str] = set()
    animation_targets: set[tuple[str, str]] = set()
    bindings = {
        (item.get("nodeUid"), item.get("parmName")): item
        for item in document.get("parameterBindings", [])
        if _is_managed_parameter_binding(item)
    }
    for animation in animations:
        _validate_animation(
            animation,
            nodes,
            animation_uids,
            animation_targets,
            spares_by_target,
            bindings,
        )


def _is_managed_parameter_binding(value: Any) -> bool:
    """Return whether a binding carries authenticated Hocus ownership."""

    if not isinstance(value, dict):
        return False
    metadata = value.get("metadata")
    if not isinstance(metadata, dict):
        return False
    hocus = metadata.get("hocus")
    return (
        isinstance(hocus, dict)
        and hocus.get("entityKind") == "parameter_binding"
    )


def _validate_spare(
    value: Any,
    node_uids: set[str],
    uids: set[str],
    targets: set[tuple[str, str]],
) -> None:
    if not isinstance(value, dict) or set(value) != _SPARE_FIELDS:
        _fail("Managed spare declaration has an invalid closed shape.")
    uid = _entity_id(value["uid"], "spare uid")
    node_uid = _node_uid(value["nodeUid"], node_uids)
    name = _identifier(value["name"], "spare name")
    _text(value["label"], "spare label", 512)
    spare_type = value["type"]
    tuple_size = value["tupleSize"]
    if spare_type not in _SPARE_TYPES:
        _fail("Managed spare type is unsupported.")
    if type(tuple_size) is not int or not 1 <= tuple_size <= 16:
        _fail("Managed spare tupleSize is outside [1, 16].")
    if not isinstance(value["metadata"], dict):
        _fail("Managed spare metadata must be an object.")
    _validate_spare_default(value)
    target = (node_uid, name)
    if uid in uids or target in targets:
        _fail("Managed spare ids and node/name targets must be unique.")
    uids.add(uid)
    targets.add(target)


def _validate_spare_default(value: dict[str, Any]) -> None:
    spare_type = value["type"]
    tuple_size = value["tupleSize"]
    default = value["default"]
    menu_items = value["menuItems"]
    if not isinstance(menu_items, list) or len(menu_items) > 256:
        _fail("Managed spare menuItems is invalid.")
    if spare_type == "float":
        if (
            not isinstance(default, list)
            or len(default) != tuple_size
            or any(not _finite(item) for item in default)
            or menu_items
        ):
            _fail("Float spare defaults must be an exact finite tuple.")
        return
    if tuple_size != 1:
        _fail("Only float spares may declare tupleSize greater than one.")
    if spare_type == "int":
        valid = type(default) is int and not menu_items
    elif spare_type == "string":
        valid = isinstance(default, str) and not menu_items
    elif spare_type == "toggle":
        valid = type(default) is bool and not menu_items
    else:
        valid = _validate_menu(default, menu_items)
    if not valid:
        _fail(f"{spare_type} spare default/menu contract is invalid.")


def _validate_menu(default: Any, menu_items: list[Any]) -> bool:
    if not isinstance(default, str) or not menu_items:
        return False
    tokens: set[str] = set()
    for item in menu_items:
        if (
            not isinstance(item, dict)
            or set(item) != {"token", "label"}
            or not isinstance(item["token"], str)
            or not item["token"]
            or len(item["token"].encode("utf-8")) > 512
            or item["token"] in tokens
            or not isinstance(item["label"], str)
            or not item["label"]
            or len(item["label"].encode("utf-8")) > 512
        ):
            return False
        tokens.add(item["token"])
    return default in tokens


def _validate_animation(
    value: Any,
    node_uids: set[str],
    uids: set[str],
    targets: set[tuple[str, str]],
    spares: dict[tuple[str, str], dict[str, Any]],
    bindings: dict[tuple[Any, Any], dict[str, Any]],
) -> None:
    if not isinstance(value, dict) or set(value) != _ANIMATION_FIELDS:
        _fail("Numeric animation has an invalid closed shape.")
    uid = _entity_id(value["uid"], "animation uid")
    node_uid = _node_uid(value["nodeUid"], node_uids)
    parm_name = _identifier(value["parmName"], "animation parmName")
    value_type = value["valueType"]
    if value_type not in {"float", "int"}:
        _fail("Only scalar float and integral int components may be animated.")
    _numeric(value["value"], value_type, "animation snapshot value")
    for field in ("authoredFps", "displayFps"):
        fps = value[field]
        if not _finite(fps) or not 0 < float(fps) <= MAX_FPS:
            _fail(f"{field} must be finite and in (0, {MAX_FPS}].")
    extrapolation = value["extrapolation"]
    if (
        not isinstance(extrapolation, dict)
        or set(extrapolation) != {"before", "after"}
        or any(item not in _EXTRAPOLATIONS for item in extrapolation.values())
    ):
        _fail("Animation extrapolation is unsupported.")
    _validate_keys(value["keys"], value_type)
    if not isinstance(value["metadata"], dict):
        _fail("Animation metadata must be an object.")
    target = (node_uid, parm_name)
    if uid in uids or target in targets:
        _fail("Animation ids and node/parameter targets must be unique.")
    uids.add(uid)
    targets.add(target)
    spare = spares.get(target)
    if spare is not None and (
        spare["type"] != value_type or spare["tupleSize"] != 1
    ):
        _fail("Animation and managed spare declaration types conflict.")
    binding = bindings.get(target)
    if binding is not None:
        _validate_animation_binding(binding, value_type)


def _validate_animation_binding(
    binding: dict[str, Any], value_type: str,
) -> None:
    if binding.get("valueMode") != "literal":
        _fail("Animation cannot be combined with a parameter value adapter.")
    value = binding.get("value")
    _numeric(value, value_type, "animated literal binding")


def _validate_keys(value: Any, value_type: str) -> None:
    if (
        not isinstance(value, list)
        or not 1 <= len(value) <= MAX_KEYS_PER_ANIMATION
    ):
        _fail("Animation key count is outside the closed carrier bound.")
    previous = -math.inf
    for key in value:
        if (
            not isinstance(key, dict)
            or not _KEY_REQUIRED <= set(key) <= _KEY_REQUIRED | _KEY_TANGENTS
        ):
            _fail("Animation key has an invalid closed shape.")
        seconds = key["timeSeconds"]
        if (
            not _finite(seconds)
            or abs(float(seconds)) > MAX_ABS_TIME_SECONDS
            or float(seconds) <= previous
        ):
            _fail("Animation key times must be finite, unique, and increasing.")
        previous = float(seconds)
        _numeric(key["value"], value_type, "animation key value")
        interpolation = key["interpolation"]
        if interpolation not in _INTERPOLATIONS:
            _fail("Animation interpolation is unsupported.")
        tangents = set(key) - _KEY_REQUIRED
        if tangents and interpolation != "bezier":
            _fail("Animation tangents require bezier interpolation.")
        if tangents not in (
            set(),
            {"slope", "accel"},
            _KEY_TANGENTS,
        ):
            _fail("Animation tangent fields must form a complete tuple.")
        for field in ("slope", "accel"):
            if field in key and not _finite(key[field]):
                _fail(f"Animation key {field} must be finite.")
        for field in _KEY_TANGENTS - {"slope", "accel"}:
            if field in key and type(key[field]) is not bool:
                _fail(f"Animation key {field} must be boolean.")


def _node_uids(document: dict[str, Any]) -> set[str]:
    return {
        item["uid"]
        for item in document.get("nodes", [])
        if isinstance(item, dict) and isinstance(item.get("uid"), str)
    }


def validate_runtime_json_envelope(
    value: Any,
    *,
    label: str,
    max_items: int = MAX_RUNTIME_ENVELOPE_ITEMS,
    max_text_bytes: int = MAX_RUNTIME_ENVELOPE_TEXT_BYTES,
    max_depth: int = 32,
) -> None:
    """Iteratively enforce one bounded finite JSON trust boundary."""

    stack: list[tuple[Any, int]] = [(value, 0)]
    items = 0
    text_bytes = 0
    while stack:
        current, depth = stack.pop()
        items += 1
        if items > max_items or depth > max_depth:
            _fail(f"{label} exceeds its item/depth bound.")
        if current is None or type(current) in {bool, int}:
            continue
        if type(current) is float:
            if not math.isfinite(current):
                _fail(f"{label} contains a non-finite number.")
            continue
        if isinstance(current, str):
            text_bytes += len(current.encode("utf-8"))
        elif isinstance(current, list):
            stack.extend((item, depth + 1) for item in current)
        elif isinstance(current, dict):
            for key, child in current.items():
                if not isinstance(key, str):
                    _fail(f"{label} contains a non-string object key.")
                text_bytes += len(key.encode("utf-8"))
                stack.append((child, depth + 1))
        else:
            _fail(f"{label} contains a non-JSON value.")
        if text_bytes > max_text_bytes:
            _fail(f"{label} exceeds its aggregate text-byte bound.")


def _node_uid(value: Any, node_uids: set[str]) -> str:
    uid = _entity_id(value, "nodeUid")
    if uid not in node_uids:
        _fail("Runtime entity nodeUid is dangling.")
    return uid


def _entity_id(value: Any, label: str) -> str:
    if not isinstance(value, str) or _ENTITY_ID.fullmatch(value) is None:
        _fail(f"{label} is invalid.")
    return value


def _identifier(value: Any, label: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        _fail(f"{label} is invalid.")
    return value


def _text(value: Any, label: str, maximum: int) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value.encode("utf-8")) > maximum
    ):
        _fail(f"{label} is invalid.")
    return value


def _numeric(value: Any, value_type: str, label: str) -> None:
    if value_type == "int":
        if type(value) is not int:
            _fail(f"{label} must be an integral int.")
    elif not _finite(value):
        _fail(f"{label} must be finite.")


def _finite(value: Any) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(value)
    )


def _fail(message: str) -> None:
    raise DocumentRuntimeContractError(message)

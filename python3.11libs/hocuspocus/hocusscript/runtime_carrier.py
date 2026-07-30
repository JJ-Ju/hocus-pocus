"""Closed GraphSpec-0.5 carrier for managed spares and numeric animation."""

from __future__ import annotations

import math
import re
import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

from .diagnostics import SourceSpan
from .expander import ModuleExpansionError
from .runtime_syntax import AnimationDecl, RuntimeProperty, SpareParameterDecl
from .syntax import ArrayExpr, LiteralExpr, NodeDecl, ParmStmt


MAX_RUNTIME_ENTITIES = 16_384
MAX_KEYS = 4_096
MAX_ABS_TANGENT = 1_000_000_000_000.0
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
_SPARE_TYPES = {"float", "int", "string", "toggle", "menu"}
_INTERPOLATIONS = {"constant", "linear", "bezier"}
_EXTRAPOLATIONS = {"constant", "linear", "cycle", "cycle_offset", "oscillate"}
_SPARE_FIELDS = {
    "explicitId", "nodeSymbol", "name", "label", "type", "tupleSize",
    "default", "menuItems", "span", "fieldSpans",
}
_ANIMATION_FIELDS = {
    "explicitId", "nodeSymbol", "parmName", "valueType", "value",
    "authoredFps", "displayFps", "extrapolation", "keys", "span",
    "fieldSpans",
}


def encode_node_runtime(
    node: NodeDecl,
    *,
    node_symbol: str,
    ownership: str | None,
    compose_identity: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Encode and validate one expanded node's runtime declarations."""

    declarations = [
        item for item in node.statements
        if isinstance(item, (SpareParameterDecl, AnimationDecl))
    ]
    if declarations and not ownership:
        _source_error(
            "Authored spares and animation require graph ownership.",
            declarations[0].span,
        )
    ordinary = {
        item.name for item in node.statements if isinstance(item, ParmStmt)
    }
    spares, animations = [], []
    for declaration in declarations:
        if declaration.explicit_id in {
            item["explicitId"] for item in (*spares, *animations)
        }:
            _source_error(
                "Runtime entity IDs must be unique on an authored node.",
                declaration.explicit_id_span,
            )
        if isinstance(declaration, SpareParameterDecl):
            encoded = _encode_spare(declaration, node_symbol)
            spares.append(_composed(encoded, node_symbol) if compose_identity else encoded)
        else:
            if declaration.parm_name in ordinary:
                _source_error(
                    "Animation snapshot conflicts with an ordinary parameter assignment.",
                    declaration.parm_name_span,
                )
            encoded = _encode_animation(declaration, node_symbol)
            animations.append(_composed(encoded, node_symbol) if compose_identity else encoded)
    try:
        validate_runtime_carrier(spares, animations, ownership=ownership)
    except ValueError as exc:
        _source_error(
            str(exc), declarations[0].span if declarations else node.span,
        )
    return spares, animations


def validate_node_runtime_source(node: NodeDecl, language_version: str) -> None:
    declarations = [
        item for item in node.statements
        if isinstance(item, (SpareParameterDecl, AnimationDecl))
    ]
    if declarations and language_version != "0.4":
        _source_error(
            "Managed spares and animation require HocusScript 0.4.",
            declarations[0].span,
        )
    encode_node_runtime(node, node_symbol=node.symbol, ownership="deferred")


def is_runtime_declaration(value: Any) -> bool:
    return isinstance(value, (SpareParameterDecl, AnimationDecl))


def _composed(value: dict[str, Any], node_symbol: str) -> dict[str, Any]:
    authored = str(value["explicitId"])
    digest = hashlib.sha256(json.dumps(
        {
            "domain": "hocus-runtime-entity-v1",
            "nodeSymbol": node_symbol,
            "authoredId": authored,
        },
        sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()
    return {**value, "explicitId": f"hocus.{digest}"}


def validate_runtime_carrier(
    spares: Any,
    animations: Any,
    *,
    ownership: str | None,
    node_symbols: set[str] | None = None,
    forbidden_ids: set[str] | None = None,
) -> None:
    """Strict-decode the two GraphSpec tables without trusting source ASTs."""

    if (
        not isinstance(spares, list)
        or not isinstance(animations, list)
        or len(spares) > MAX_RUNTIME_ENTITIES
        or len(animations) > MAX_RUNTIME_ENTITIES
    ):
        raise ValueError("runtime entity tables exceed their closed bounds")
    if (spares or animations) and not isinstance(ownership, str):
        raise ValueError("runtime entities require graph ownership")
    ids: set[str] = set(forbidden_ids or ())
    targets: set[tuple[str, str, str]] = set()
    spare_targets: dict[tuple[str, str], Mapping[str, Any]] = {}
    for index, item in enumerate(spares):
        _validate_spare(item, index, ids, targets, node_symbols)
        spare_targets[(item["nodeSymbol"], item["name"])] = item
    for index, item in enumerate(animations):
        _validate_animation(
            item, index, ids, targets, spare_targets, node_symbols,
        )


def _encode_spare(
    declaration: SpareParameterDecl, node_symbol: str,
) -> dict[str, Any]:
    properties = _properties(declaration.properties)
    required = {"label", "type", "tuple_size", "default", "menu_items"}
    _require_properties(properties, required, "spare", declaration.span)
    return {
        "explicitId": declaration.explicit_id,
        "nodeSymbol": node_symbol,
        "name": declaration.name,
        "label": _property_literal(properties["label"]),
        "type": _property_literal(properties["type"]),
        "tupleSize": _property_literal(properties["tuple_size"]),
        "default": _property_literal(properties["default"]),
        "menuItems": _menu_items(properties["menu_items"], declaration.span),
        "span": declaration.span.to_dict(),
        "fieldSpans": _field_spans(
            declaration.name_span, declaration.explicit_id_span, properties,
        ),
    }


def _encode_animation(
    declaration: AnimationDecl, node_symbol: str,
) -> dict[str, Any]:
    properties = _properties(declaration.properties)
    required = {
        "value_type", "value", "authored_fps", "display_fps",
        "extrapolation", "keys",
    }
    _require_properties(properties, required, "animate", declaration.span)
    extrapolation = _property_literal(properties["extrapolation"])
    if not isinstance(extrapolation, list) or len(extrapolation) != 2:
        _source_error(
            "Animation extrapolation must be [before, after].",
            properties["extrapolation"].span,
        )
    return {
        "explicitId": declaration.explicit_id,
        "nodeSymbol": node_symbol,
        "parmName": declaration.parm_name,
        "valueType": _property_literal(properties["value_type"]),
        "value": _property_literal(properties["value"]),
        "authoredFps": _property_literal(properties["authored_fps"]),
        "displayFps": _property_literal(properties["display_fps"]),
        "extrapolation": {
            "before": extrapolation[0], "after": extrapolation[1],
        },
        "keys": _keys(properties["keys"], declaration.span),
        "span": declaration.span.to_dict(),
        "fieldSpans": _field_spans(
            declaration.parm_name_span, declaration.explicit_id_span,
            properties,
        ),
    }


def _properties(
    values: Sequence[RuntimeProperty],
) -> dict[str, RuntimeProperty]:
    return {item.name: item for item in values}


def _require_properties(
    properties: Mapping[str, RuntimeProperty],
    required: set[str],
    kind: str,
    span: SourceSpan,
) -> None:
    if set(properties) != required:
        _source_error(
            f"{kind} requires exactly {', '.join(sorted(required))}.", span,
        )


def _field_spans(
    name_span: SourceSpan,
    id_span: SourceSpan,
    properties: Mapping[str, RuntimeProperty],
) -> dict[str, Any]:
    result = {
        "name": name_span.to_dict(), "explicitId": id_span.to_dict(),
    }
    aliases = {
        "tuple_size": "tupleSize", "menu_items": "menuItems",
        "value_type": "valueType", "authored_fps": "authoredFps",
        "display_fps": "displayFps",
    }
    result.update({
        aliases.get(name, name): item.span.to_dict()
        for name, item in properties.items()
    })
    return result


def _literal(value: Any) -> Any:
    if isinstance(value, LiteralExpr):
        return value.value
    if isinstance(value, ArrayExpr):
        return [_literal(item) for item in value.items]
    raise ValueError("runtime properties accept only literal values and arrays")


def _property_literal(value: RuntimeProperty) -> Any:
    try:
        return _literal(value.value)
    except ValueError as exc:
        _source_error(str(exc), value.span)


def _menu_items(
    property_value: RuntimeProperty, span: SourceSpan,
) -> list[dict[str, str]]:
    value = _property_literal(property_value)
    if not isinstance(value, list):
        _source_error("menu_items must be an array of [token, label].", span)
    result = []
    for item in value:
        if (
            not isinstance(item, list) or len(item) != 2
            or not all(isinstance(part, str) for part in item)
        ):
            _source_error("menu_items entries must be [token, label].", span)
        result.append({"token": item[0], "label": item[1]})
    return result


def _keys(property_value: RuntimeProperty, span: SourceSpan) -> list[dict[str, Any]]:
    value = _property_literal(property_value)
    if not isinstance(value, list):
        _source_error("Animation keys must be an array.", span)
    result = []
    for item in value:
        if not isinstance(item, list) or len(item) not in {3, 5, 11}:
            _source_error(
                "Animation keys use [seconds, value, interpolation] or "
                "[seconds, value, interpolation, slope, accel] with optional "
                "six exact tangent flags.",
                span,
            )
        key = {
            "timeSeconds": item[0], "value": item[1],
            "interpolation": item[2],
        }
        if len(item) == 5:
            key.update({"slope": item[3], "accel": item[4]})
        elif len(item) == 11:
            key.update(dict(zip(
                (
                    "slope", "accel", "slopeAuto", "accelAuto",
                    "slopeTied", "accelTied", "slopeUsed", "accelUsed",
                ),
                item[3:],
            )))
        result.append(key)
    return result


def _validate_spare(
    item: Any,
    index: int,
    ids: set[str],
    targets: set[tuple[str, str, str]],
    node_symbols: set[str] | None,
) -> None:
    label = f"spareParameters[{index}]"
    _closed(item, _SPARE_FIELDS, label)
    _identity(item["explicitId"], label, ids)
    node = _node(item["nodeSymbol"], node_symbols, label)
    name = _identifier(item["name"], f"{label}.name")
    target = ("spare", node, name)
    if target in targets:
        raise ValueError("managed spare targets must be unique")
    targets.add(target)
    if not isinstance(item["label"], str) or not item["label"]:
        raise ValueError(f"{label}.label is invalid")
    kind, size = item["type"], item["tupleSize"]
    if kind not in _SPARE_TYPES or type(size) is not int or not 1 <= size <= 16:
        raise ValueError(f"{label} type/tupleSize is invalid")
    _validate_spare_default(item, label)
    _span(item["span"], f"{label}.span")
    _spans(item["fieldSpans"], label)


def _validate_spare_default(item: Mapping[str, Any], label: str) -> None:
    kind, size, default = item["type"], item["tupleSize"], item["default"]
    menu = item["menuItems"]
    if not isinstance(menu, list) or len(menu) > 256:
        raise ValueError(f"{label}.menuItems is invalid")
    if kind == "float":
        valid = (
            isinstance(default, list) and len(default) == size and not menu
            and all(_finite(value) for value in default)
        )
    elif size != 1:
        valid = False
    elif kind == "int":
        valid = type(default) is int and not menu
    elif kind == "string":
        valid = isinstance(default, str) and not menu
    elif kind == "toggle":
        valid = type(default) is bool and not menu
    else:
        valid = _valid_menu(default, menu)
    if not valid:
        raise ValueError(f"{label} default/menu contract is invalid")


def _valid_menu(default: Any, menu: list[Any]) -> bool:
    tokens = set()
    for item in menu:
        if (
            not isinstance(item, dict) or set(item) != {"token", "label"}
            or not isinstance(item["token"], str) or not item["token"]
            or not isinstance(item["label"], str) or not item["label"]
            or item["token"] in tokens
        ):
            return False
        tokens.add(item["token"])
    return isinstance(default, str) and default in tokens


def _validate_animation(
    item: Any,
    index: int,
    ids: set[str],
    targets: set[tuple[str, str, str]],
    spares: Mapping[tuple[str, str], Mapping[str, Any]],
    node_symbols: set[str] | None,
) -> None:
    label = f"animations[{index}]"
    _closed(item, _ANIMATION_FIELDS, label)
    _identity(item["explicitId"], label, ids)
    node = _node(item["nodeSymbol"], node_symbols, label)
    parm = _identifier(item["parmName"], f"{label}.parmName")
    target = ("animation", node, parm)
    if target in targets:
        raise ValueError("animation targets must be unique")
    targets.add(target)
    value_type = item["valueType"]
    if value_type not in {"float", "int"}:
        raise ValueError(f"{label} supports only float or int")
    _numeric(item["value"], value_type, f"{label}.value")
    for field in ("authoredFps", "displayFps"):
        if not _finite(item[field]) or not 0 < float(item[field]) <= 1_000:
            raise ValueError(f"{label}.{field} is invalid")
    extrapolation = item["extrapolation"]
    if (
        not isinstance(extrapolation, dict)
        or set(extrapolation) != {"before", "after"}
        or any(value not in _EXTRAPOLATIONS for value in extrapolation.values())
    ):
        raise ValueError(f"{label}.extrapolation is invalid")
    _validate_keys(item["keys"], value_type, label)
    spare = spares.get((node, parm))
    if spare is not None and (
        spare["type"] != value_type or spare["tupleSize"] != 1
    ):
        raise ValueError(f"{label} conflicts with its managed spare")
    _span(item["span"], f"{label}.span")
    _spans(item["fieldSpans"], label)


def _validate_keys(keys: Any, value_type: str, label: str) -> None:
    if not isinstance(keys, list) or not 1 <= len(keys) <= MAX_KEYS:
        raise ValueError(f"{label}.keys is invalid")
    previous = -math.inf
    for key in keys:
        tangent_bools = {
            "slopeAuto", "accelAuto", "slopeTied", "accelTied",
            "slopeUsed", "accelUsed",
        }
        allowed = {
            "timeSeconds", "value", "interpolation", "slope", "accel",
            *tangent_bools,
        }
        if (
            not isinstance(key, dict)
            or not {"timeSeconds", "value", "interpolation"} <= set(key) <= allowed
        ):
            raise ValueError(f"{label}.keys has an invalid closed shape")
        seconds = key["timeSeconds"]
        if not _finite(seconds) or float(seconds) <= previous:
            raise ValueError(f"{label}.keys must have increasing finite seconds")
        previous = float(seconds)
        _numeric(key["value"], value_type, f"{label}.keys.value")
        if key["interpolation"] not in _INTERPOLATIONS:
            raise ValueError(f"{label}.keys interpolation is unsupported")
        tangent_fields = {"slope", "accel", *tangent_bools}
        tangents = set(key) & tangent_fields
        if tangents and key["interpolation"] != "bezier":
            raise ValueError("Only bezier keys may carry tangents")
        if tangents not in (
            set(),
            {"slope", "accel"},
            tangent_fields,
        ):
            raise ValueError(
                f"{label}.keys tangent fields must form a complete tuple"
            )
        for field in ("slope", "accel"):
            if field in key and (
                not _finite(key[field])
                or abs(float(key[field])) > MAX_ABS_TANGENT
            ):
                raise ValueError(f"{label}.keys {field} exceeds its bound")
        if any(field in key and type(key[field]) is not bool for field in tangent_bools):
            raise ValueError(f"{label}.keys tangent flags must be boolean")


def _closed(item: Any, fields: set[str], label: str) -> None:
    if not isinstance(item, dict) or set(item) != fields:
        raise ValueError(f"{label} has missing or unknown fields")


def _identity(value: Any, label: str, ids: set[str]) -> None:
    if not isinstance(value, str) or _ID.fullmatch(value) is None or value in ids:
        raise ValueError(f"{label}.explicitId is invalid or duplicated")
    ids.add(value)


def _node(value: Any, nodes: set[str] | None, label: str) -> str:
    result = _identifier(value, f"{label}.nodeSymbol")
    if nodes is not None and result not in nodes:
        raise ValueError(f"{label}.nodeSymbol is dangling")
    return result


def _identifier(value: Any, label: str) -> str:
    if not isinstance(value, str) or _IDENT.fullmatch(value) is None:
        raise ValueError(f"{label} is invalid")
    return value


def _spans(value: Any, label: str) -> None:
    if not isinstance(value, dict) or not {"name", "explicitId"} <= set(value):
        raise ValueError(f"{label}.fieldSpans is invalid")
    for name, span in value.items():
        _span(span, f"{label}.fieldSpans.{name}")


def _span(value: Any, label: str) -> None:
    if (
        not isinstance(value, dict)
        or set(value) != {"sourceUri", "start", "end"}
        or not isinstance(value["sourceUri"], str)
    ):
        raise ValueError(f"{label} is invalid")
    for point in ("start", "end"):
        child = value[point]
        if (
            not isinstance(child, dict)
            or set(child) != {"offset", "line", "column"}
            or type(child["offset"]) is not int or child["offset"] < 0
            or any(
                type(child[name]) is not int or child[name] < 1
                for name in ("line", "column")
            )
        ):
            raise ValueError(f"{label}.{point} is invalid")


def _numeric(value: Any, value_type: str, label: str) -> None:
    if value_type == "int":
        if type(value) is not int:
            raise ValueError(f"{label} must be an int")
    elif not _finite(value):
        raise ValueError(f"{label} must be finite")


def _finite(value: Any) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(value)
    )


def _source_error(message: str, span: SourceSpan) -> None:
    raise ModuleExpansionError("HOCUS946", message, span)

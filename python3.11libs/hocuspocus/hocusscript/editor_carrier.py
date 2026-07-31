"""Strict source and GraphSpec semantics for HS7 editor entities."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from typing import Any

from .diagnostics import SourceSpan
from .editor_syntax import (
    EditorConnectionRef,
    EditorDestinationRefs,
    EditorEntityDecl,
    EditorItemRef,
    EditorItemRefs,
)
from .expander import ModuleExpansionError
from .syntax import ArrayExpr, LiteralExpr


_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_KINDS = {
    "network_box", "sticky_note", "node_comment", "network_dot",
    "layout_constraint",
}
_REF_KINDS = {"node", "dot", "box", "sticky"}
_LAYOUT_KINDS = {
    "align_x", "align_y", "offset", "distribute_x", "distribute_y",
    "contain",
}
_MAX_ENTITIES = 16_384
_MAX_ITEMS = 4_096
_MAX_CONSTRAINT_ITEMS = 256
_MAX_TEXT_BYTES = 65_536
_MAX_COORDINATE = 1_000_000.0
_MAX_SIZE = 100_000.0
_BASE_KEYS = {"kind", "explicitId", "span", "fieldSpans"}
_FIELDS = {
    "network_box": {
        "label", "position", "size", "color", "itemRefs",
    },
    "sticky_note": {
        "text", "position", "size", "color", "textSize",
        "drawBackground", "minimized",
    },
    "node_comment": {"nodeRef", "text", "visible"},
    "network_dot": {"position", "pinned", "input", "outputs"},
    "layout_constraint": {
        "constraintKind", "itemRefs", "anchorRef", "offset", "spacing",
        "padding", "priority",
    },
}


def encode_editor_declarations(
    declarations: Sequence[EditorEntityDecl],
    *,
    known_nodes: set[str],
    mutable_nodes: set[str],
    ownership: str | None,
    node_symbols: Mapping[str, str] | None = None,
    node_explicit_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Validate source declarations and return the strict carrier shape."""

    if len(declarations) > _MAX_ENTITIES:
        _error("Editor entity count exceeds its bounded limit.", declarations[0].span)
    if declarations and not ownership:
        _error(
            "Authored editor entities require a graph ownership namespace.",
            declarations[0].span,
        )
    symbol_map = dict(node_symbols or {})
    encoded_known = {symbol_map.get(item, item) for item in known_nodes}
    encoded_mutable = {symbol_map.get(item, item) for item in mutable_nodes}
    encoded: list[dict[str, Any]] = []
    identities: dict[str, str] = {}
    node_ids = set(node_explicit_ids or ())
    for declaration in declarations:
        if declaration.entity_kind not in _KINDS:
            _error("Unsupported editor entity kind.", declaration.span)
        if _ID.fullmatch(declaration.explicit_id) is None:
            _error(
                "Editor entity IDs must match "
                "[A-Za-z0-9][A-Za-z0-9._:-]{0,127}.",
                declaration.explicit_id_span,
            )
        if declaration.explicit_id in identities:
            _error("Editor entity IDs must be unique.", declaration.explicit_id_span)
        if declaration.explicit_id in node_ids:
            _error(
                "Editor entity ID collides with an authored node ID.",
                declaration.explicit_id_span,
            )
        identities[declaration.explicit_id] = declaration.entity_kind
        encoded.append(
            _encode_declaration(
                declaration,
                known_nodes,
                mutable_nodes,
                symbol_map,
            )
        )
    _validate_editor_references(
        encoded, encoded_known, encoded_mutable, identities
    )
    validate_editor_carrier(encoded)
    return encoded


def validate_editor_carrier(value: Any) -> list[dict[str, Any]]:
    """Reject forged GraphSpec editor-entity tables with a closed shape."""

    if not isinstance(value, list) or len(value) > _MAX_ENTITIES:
        raise ValueError("editorEntities must be a bounded array")
    seen: set[str] = set()
    for index, entity in enumerate(value):
        label = f"editorEntities[{index}]"
        if not isinstance(entity, dict) or entity.get("kind") not in _KINDS:
            raise ValueError(f"{label} has an invalid kind")
        expected = _BASE_KEYS | _FIELDS[entity["kind"]]
        if set(entity) != expected:
            raise ValueError(f"{label} has missing or unknown fields")
        identity = entity["explicitId"]
        if not isinstance(identity, str) or _ID.fullmatch(identity) is None:
            raise ValueError(f"{label}.explicitId is invalid")
        if identity in seen:
            raise ValueError("editor entity explicit IDs must be unique")
        seen.add(identity)
        _validate_span_shape(entity["span"], f"{label}.span")
        field_spans = entity["fieldSpans"]
        if (
            not isinstance(field_spans, dict)
            or "explicitId" not in field_spans
            or set(field_spans) - ({"explicitId"} | _source_field_names(entity["kind"]))
        ):
            raise ValueError(f"{label}.fieldSpans is invalid")
        for name, span in field_spans.items():
            _validate_span_shape(span, f"{label}.fieldSpans.{name}")
        _validate_carrier_entity(entity, label)
    return value


def validate_editor_carrier_references(
    entities: Sequence[Mapping[str, Any]],
    *,
    node_symbols: set[str],
    mutable_node_symbols: set[str],
) -> None:
    identities = {
        str(item["explicitId"]): str(item["kind"]) for item in entities
    }
    edges: dict[str, list[str]] = {}
    destinations: set[tuple[str, int]] = set()
    for entity in entities:
        identity = str(entity["explicitId"])
        refs = list(entity.get("itemRefs", []))
        for name in ("nodeRef", "anchorRef"):
            if entity.get(name) is not None:
                refs.append(entity[name])
        connection = entity.get("input")
        if connection is not None:
            refs.append(connection["item"])
        refs.extend(
            destination["nodeRef"]
            for destination in entity.get("outputs", [])
        )
        for ref in refs:
            _require_carrier_target(
                entity, ref, identities, node_symbols, mutable_node_symbols
            )
        if any(
            destination["nodeRef"]["identity"] not in mutable_node_symbols
            for destination in entity.get("outputs", [])
        ):
            raise ValueError("dot destination targets a read-only node symbol")
        for destination in entity.get("outputs", []):
            coordinate = (
                destination["nodeRef"]["identity"],
                destination["inputIndex"],
            )
            if coordinate in destinations:
                raise ValueError("dot destination is claimed by multiple dots")
            destinations.add(coordinate)
        if entity["kind"] == "network_dot" and connection is not None:
            ref = connection["item"]
            if ref["kind"] == "dot":
                edges.setdefault(identity, []).append(ref["identity"])
        if entity["kind"] == "network_box":
            edges[identity] = [
                ref["identity"] for ref in entity["itemRefs"]
                if ref["kind"] == "box"
            ]
    _reject_reference_cycles(edges)


def validate_dot_route_conflicts(
    entities: Sequence[Mapping[str, Any]],
    graph: Mapping[str, Any],
    connection_selections: Sequence[Mapping[str, Any]] | None = None,
) -> None:
    routes = {
        (output["nodeRef"]["identity"], output["inputIndex"])
        for entity in entities
        if entity["kind"] == "network_dot"
        for output in entity["outputs"]
    }
    direct = set()
    if connection_selections is not None:
        direct.update(
            (item["nodeSymbol"], item["inputIndex"])
            for item in connection_selections
        )
    else:
        direct.update(
            (node["symbol"], input_spec["index"])
            for node in graph["nodes"]
            for input_spec in node["inputs"]
            if "index" in input_spec
        )
    overlap = sorted(routes & direct)
    if overlap:
        raise ValueError(
            "dot-routed destination also has a direct authored data edge"
        )


def _require_carrier_target(
    entity: Mapping[str, Any],
    ref: Mapping[str, Any],
    identities: Mapping[str, str],
    node_symbols: set[str],
    mutable_node_symbols: set[str],
) -> None:
    kind, identity = str(ref["kind"]), str(ref["identity"])
    if kind == "node":
        if identity not in node_symbols:
            raise ValueError("editor entity references an unknown node symbol")
        if (
            entity["kind"] in {"node_comment", "layout_constraint"}
            and identity not in mutable_node_symbols
        ):
            raise ValueError("editor mutation references a read-only node symbol")
        return
    expected = {
        "dot": "network_dot", "box": "network_box",
        "sticky": "sticky_note",
    }[kind]
    if identities.get(identity) != expected:
        raise ValueError("editor entity reference kind or identity is invalid")
    if entity["kind"] == "network_box" and identity == entity["explicitId"]:
        raise ValueError("network box cannot contain itself")


def _reject_reference_cycles(edges: Mapping[str, list[str]]) -> None:
    for root in edges:
        stack = [(root, False)]
        active: set[str] = set()
        complete: set[str] = set()
        while stack:
            current, leaving = stack.pop()
            if leaving:
                active.discard(current)
                complete.add(current)
                continue
            if current in active:
                raise ValueError("editor topology contains a reference cycle")
            if current in complete:
                continue
            active.add(current)
            stack.append((current, True))
            stack.extend((child, False) for child in edges.get(current, ()))


def _encode_declaration(
    declaration: EditorEntityDecl,
    known_nodes: set[str],
    mutable_nodes: set[str],
    symbol_map: Mapping[str, str],
) -> dict[str, Any]:
    properties = {item.name: item for item in declaration.properties}
    values = {name: item.value for name, item in properties.items()}
    kind = declaration.entity_kind
    required = {
        "network_box": {"position", "size"},
        "sticky_note": {"text", "position", "size"},
        "node_comment": {"node", "text"},
        "network_dot": {"position"},
        "layout_constraint": {"kind", "items"},
    }[kind]
    if not required <= set(values):
        _error(
            f"{kind} is missing required properties: "
            f"{', '.join(sorted(required - set(values)))}.",
            declaration.span,
        )
    base = {
        "kind": kind,
        "explicitId": declaration.explicit_id,
        "span": declaration.span.to_dict(),
        "fieldSpans": {
            "explicitId": declaration.explicit_id_span.to_dict(),
            **{
                name: item.name_span.to_dict()
                for name, item in properties.items()
            },
        },
    }
    if kind == "network_box":
        base.update({
            "label": _text(values.get("label"), "", 4_096, declaration.span),
            "position": _vector(values["position"], True, False),
            "size": _vector(values["size"], False, True),
            "color": _color(values.get("color")),
            "itemRefs": _refs(values.get("items"), symbol_map),
        })
    elif kind == "sticky_note":
        base.update({
            "text": _text(values["text"], "", _MAX_TEXT_BYTES, declaration.span),
            "position": _vector(values["position"], True, False),
            "size": _vector(values["size"], False, True),
            "color": _color(values.get("color")),
            "textSize": _number(values.get("text_size"), 1.0, 0.1, 10.0),
            "drawBackground": _bool(values.get("background"), True),
            "minimized": _bool(values.get("minimized"), False),
        })
    elif kind == "node_comment":
        node_ref = _ref(values["node"], symbol_map)
        if node_ref["kind"] != "node":
            _error("Node comments must reference a node symbol.", declaration.span)
        if _authored_identity(values["node"]) not in mutable_nodes:
            _error("Node comments may target only authored or adopted nodes.", declaration.span)
        base.update({
            "nodeRef": node_ref,
            "text": _text(values["text"], "", _MAX_TEXT_BYTES, declaration.span),
            "visible": _bool(values.get("visible"), True),
        })
    elif kind == "network_dot":
        base.update({
            "position": _vector(values["position"], True, False),
            "pinned": _bool(values.get("pinned"), False),
            "input": _connection(values.get("input"), symbol_map),
            "outputs": _destinations(values.get("outputs"), symbol_map),
        })
    else:
        base.update(_constraint(values, declaration.span, symbol_map))
    return base


def _constraint(
    values: Mapping[str, Any],
    span: SourceSpan,
    symbol_map: Mapping[str, str],
) -> dict[str, Any]:
    kind = _literal(values["kind"], str, span)
    if kind not in _LAYOUT_KINDS:
        _error("Unsupported layout constraint kind.", span)
    refs = _refs(values["items"], symbol_map)
    anchor = _ref(values["anchor"], symbol_map) if "anchor" in values else None
    if kind in {"align_x", "align_y", "offset", "contain"} and anchor is None:
        _error(f"{kind} requires an anchor property.", span)
    if kind in {"distribute_x", "distribute_y"} and len(refs) < 3:
        _error("Distribute constraints require at least three items.", span)
    if kind == "offset" and "offset" not in values:
        _error("Offset constraints require an offset property.", span)
    return {
        "constraintKind": kind,
        "itemRefs": refs,
        "anchorRef": anchor,
        "offset": (
            _vector(values["offset"], True, False)
            if "offset" in values else None
        ),
        "spacing": (
            _number(values["spacing"], 0.0, 0.0, _MAX_SIZE)
            if "spacing" in values else None
        ),
        "padding": (
            _vector(values["padding"], False, False, allow_zero=True)
            if "padding" in values else [0.0, 0.0]
        ),
        "priority": _integer(values.get("priority"), 50, 0, 100),
    }


def _validate_editor_references(
    entities: list[dict[str, Any]],
    known_nodes: set[str],
    mutable_nodes: set[str],
    identities: Mapping[str, str],
) -> None:
    for entity in entities:
        refs = list(entity.get("itemRefs", []))
        for name in ("nodeRef", "anchorRef"):
            if entity.get(name) is not None:
                refs.append(entity[name])
        if entity.get("input") is not None:
            refs.append(entity["input"]["item"])
        refs.extend(
            destination["nodeRef"]
            for destination in entity.get("outputs", [])
        )
        for ref in refs:
            kind, identity = ref["kind"], ref["identity"]
            if kind == "node":
                if identity not in known_nodes:
                    # Generated symbol maps are already substituted; callers pass
                    # the generated known set when encoding the carrier.
                    _error("Editor entity references an unknown node.", _span(entity))
                if entity["kind"] == "layout_constraint" and identity not in mutable_nodes:
                    _error(
                        "Layout constraints may move only authored or adopted nodes.",
                        _span(entity),
                    )
                continue
            expected = {
                "dot": "network_dot", "box": "network_box",
                "sticky": "sticky_note",
            }[kind]
            if identities.get(identity) != expected:
                _error("Editor entity reference has the wrong or missing kind.", _span(entity))
        if any(
            destination["nodeRef"]["identity"] not in mutable_nodes
            for destination in entity.get("outputs", [])
        ):
            _error("Dot destinations may target only authored or adopted nodes.", _span(entity))


def _validate_carrier_entity(entity: dict[str, Any], label: str) -> None:
    kind = entity["kind"]
    if kind == "network_box":
        _carrier_text(entity["label"], 4_096, label)
        _carrier_vec(entity["position"], True, False, label)
        _carrier_vec(entity["size"], False, True, label)
        _carrier_color(entity["color"], label)
        _carrier_refs(entity["itemRefs"], _MAX_ITEMS, label)
    elif kind == "sticky_note":
        _carrier_text(entity["text"], _MAX_TEXT_BYTES, label)
        _carrier_vec(entity["position"], True, False, label)
        _carrier_vec(entity["size"], False, True, label)
        _carrier_color(entity["color"], label)
        _carrier_number(entity["textSize"], 0.1, 10.0, label)
        _carrier_bool(entity["drawBackground"], label)
        _carrier_bool(entity["minimized"], label)
    elif kind == "node_comment":
        _carrier_ref(entity["nodeRef"], label)
        _carrier_text(entity["text"], _MAX_TEXT_BYTES, label)
        _carrier_bool(entity["visible"], label)
    elif kind == "network_dot":
        _carrier_vec(entity["position"], True, False, label)
        _carrier_bool(entity["pinned"], label)
        if entity["input"] is not None:
            if not isinstance(entity["input"], dict) or set(entity["input"]) != {
                "item", "outputIndex",
            }:
                raise ValueError(f"{label}.input is invalid")
            _carrier_ref(entity["input"]["item"], label)
            _carrier_int(entity["input"]["outputIndex"], 0, 65_535, label)
        _carrier_destinations(entity["outputs"], label)
    else:
        _carrier_constraint(entity, label)


def _carrier_constraint(entity: dict[str, Any], label: str) -> None:
    if entity["constraintKind"] not in _LAYOUT_KINDS:
        raise ValueError(f"{label}.constraintKind is invalid")
    _carrier_refs(entity["itemRefs"], _MAX_CONSTRAINT_ITEMS, label)
    if entity["anchorRef"] is not None:
        _carrier_ref(entity["anchorRef"], label)
    if entity["offset"] is not None:
        _carrier_vec(entity["offset"], True, False, label)
    if entity["spacing"] is not None:
        _carrier_number(entity["spacing"], 0.0, _MAX_SIZE, label)
    _carrier_vec(entity["padding"], False, False, label, allow_zero=True)
    _carrier_int(entity["priority"], 0, 100, label)


def _source_field_names(kind: str) -> set[str]:
    return {
        "network_box": {"label", "position", "size", "color", "items"},
        "sticky_note": {
            "text", "position", "size", "color", "text_size",
            "background", "minimized",
        },
        "node_comment": {"node", "text", "visible"},
        "network_dot": {"position", "pinned", "input", "outputs"},
        "layout_constraint": {
            "kind", "items", "anchor", "offset", "spacing", "padding",
            "priority",
        },
    }[kind]


def _refs(value: Any, symbol_map: Mapping[str, str]) -> list[dict[str, str]]:
    if value is None:
        return []
    if not isinstance(value, EditorItemRefs):
        _error("Editor items must be a typed item-reference array.", value.span)
    limit = _MAX_CONSTRAINT_ITEMS if len(value.items) <= _MAX_CONSTRAINT_ITEMS else _MAX_ITEMS
    if len(value.items) > limit:
        _error("Editor item reference list exceeds its bounded limit.", value.span)
    result = [_ref(item, symbol_map) for item in value.items]
    if len({(item["kind"], item["identity"]) for item in result}) != len(result):
        _error("Editor item references must be unique.", value.span)
    return result


def _ref(value: Any, symbol_map: Mapping[str, str]) -> dict[str, str]:
    if not isinstance(value, EditorItemRef):
        _error("Expected a typed editor item reference.", value.span)
    identity = symbol_map.get(value.identity, value.identity) if value.item_kind == "node" else value.identity
    return {"kind": value.item_kind, "identity": identity}


def _connection(
    value: Any, symbol_map: Mapping[str, str],
) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, EditorConnectionRef):
        _error("Expected a typed editor connection.", value.span)
    if value.item.item_kind not in {"node", "dot"}:
        _error("Network dot inputs may reference only nodes or dots.", value.span)
    if not 0 <= value.output_index <= 65_535:
        _error("Editor connection output index is out of range.", value.output_index_span)
    return {"item": _ref(value.item, symbol_map), "outputIndex": value.output_index}


def _destinations(
    value: Any, symbol_map: Mapping[str, str],
) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, EditorDestinationRefs):
        _error("Expected a typed dot destination array.", value.span)
    if len(value.items) > _MAX_CONSTRAINT_ITEMS:
        _error("Dot destinations exceed their bounded limit.", value.span)
    result = []
    seen = set()
    for item in value.items:
        if item.node.item_kind != "node" or not 0 <= item.input_index <= 65_535:
            _error("Dot destination must select one node input.", item.span)
        record = {
            "nodeRef": _ref(item.node, symbol_map),
            "inputIndex": item.input_index,
        }
        coordinate = (record["nodeRef"]["identity"], item.input_index)
        if coordinate in seen:
            _error("Dot destinations must be unique.", item.span)
        seen.add(coordinate)
        result.append(record)
    return result


def _authored_identity(value: Any) -> str:
    return value.identity if isinstance(value, EditorItemRef) else ""


def _text(value: Any, default: str, limit: int, span: SourceSpan) -> str:
    result = default if value is None else _literal(value, str, span)
    try:
        size = len(result.encode("utf-8"))
    except UnicodeEncodeError:
        _error("Editor text must be valid UTF-8.", span)
    if size > limit:
        _error("Editor text exceeds its UTF-8 byte limit.", span)
    return result


def _bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    return _literal(value, bool, value.span)


def _integer(value: Any, default: int, minimum: int, maximum: int) -> int:
    result = default if value is None else _literal(value, int, value.span)
    if type(result) is not int or not minimum <= result <= maximum:
        _error("Editor integer is outside its bounded range.", value.span)
    return result


def _number(
    value: Any, default: float, minimum: float, maximum: float,
) -> float:
    raw = default if value is None else _literal_number(value)
    result = float(raw)
    if not math.isfinite(result) or not minimum <= result <= maximum:
        _error("Editor number is outside its bounded range.", value.span)
    return result


def _vector(
    value: Any, signed: bool, positive: bool, *, allow_zero: bool = False,
) -> list[float]:
    if not isinstance(value, ArrayExpr) or len(value.items) != 2:
        _error("Editor vectors require exactly two numbers.", value.span)
    minimum = -_MAX_COORDINATE if signed else (0.0 if allow_zero else 0.000001)
    maximum = _MAX_COORDINATE if signed else _MAX_SIZE
    result = [
        float(_literal_number(item))
        for item in value.items
    ]
    if (
        any(not math.isfinite(item) or not minimum <= item <= maximum for item in result)
        or positive and any(item <= 0.0 for item in result)
    ):
        _error("Editor vector is outside its bounded range.", value.span)
    return result


def _color(value: Any) -> list[float] | None:
    if value is None:
        return None
    if not isinstance(value, ArrayExpr) or len(value.items) != 3:
        _error("Editor colors require exactly three channels.", value.span)
    result = [float(_literal_number(item)) for item in value.items]
    if any(not math.isfinite(item) or not 0.0 <= item <= 1.0 for item in result):
        _error("Editor color channels must be between zero and one.", value.span)
    return result


def _literal(value: Any, expected: type, span: SourceSpan) -> Any:
    if not isinstance(value, LiteralExpr) or type(value.value) is not expected:
        _error(f"Editor property requires {expected.__name__}.", span)
    return value.value


def _literal_number(value: Any) -> int | float:
    if (
        not isinstance(value, LiteralExpr)
        or isinstance(value.value, bool)
        or not isinstance(value.value, (int, float))
    ):
        _error("Editor property requires a finite number.", value.span)
    return value.value


def _carrier_refs(value: Any, limit: int, label: str) -> None:
    if not isinstance(value, list) or len(value) > limit:
        raise ValueError(f"{label} references exceed their bounded limit")
    identities = []
    for ref in value:
        _carrier_ref(ref, label)
        identities.append((ref["kind"], ref["identity"]))
    if len(identities) != len(set(identities)):
        raise ValueError(f"{label} references are duplicated")


def _carrier_destinations(value: Any, label: str) -> None:
    if not isinstance(value, list) or len(value) > _MAX_CONSTRAINT_ITEMS:
        raise ValueError(f"{label}.outputs is invalid")
    coordinates = set()
    for item in value:
        if not isinstance(item, dict) or set(item) != {"nodeRef", "inputIndex"}:
            raise ValueError(f"{label}.outputs is invalid")
        _carrier_ref(item["nodeRef"], label)
        if item["nodeRef"]["kind"] != "node":
            raise ValueError(f"{label}.outputs must target nodes")
        _carrier_int(item["inputIndex"], 0, 65_535, label)
        coordinate = (item["nodeRef"]["identity"], item["inputIndex"])
        if coordinate in coordinates:
            raise ValueError(f"{label}.outputs contains duplicate destinations")
        coordinates.add(coordinate)


def _carrier_ref(value: Any, label: str) -> None:
    if (
        not isinstance(value, dict)
        or set(value) != {"kind", "identity"}
        or value["kind"] not in _REF_KINDS
        or not isinstance(value["identity"], str)
        or not value["identity"]
        or len(value["identity"]) > 512
    ):
        raise ValueError(f"{label} contains an invalid editor reference")


def _carrier_vec(
    value: Any, signed: bool, positive: bool, label: str,
    *, allow_zero: bool = False,
) -> None:
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError(f"{label} contains an invalid vector")
    minimum = -_MAX_COORDINATE if signed else (0.0 if allow_zero else 0.000001)
    maximum = _MAX_COORDINATE if signed else _MAX_SIZE
    for item in value:
        _carrier_number(item, minimum, maximum, label)
        if positive and float(item) <= 0.0:
            raise ValueError(f"{label} contains a nonpositive size")


def _carrier_color(value: Any, label: str) -> None:
    if value is None:
        return
    if not isinstance(value, list) or len(value) != 3:
        raise ValueError(f"{label} contains an invalid color")
    for item in value:
        _carrier_number(item, 0.0, 1.0, label)


def _carrier_number(value: Any, minimum: float, maximum: float, label: str) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or not minimum <= float(value) <= maximum
    ):
        raise ValueError(f"{label} contains an invalid finite number")


def _carrier_int(value: Any, minimum: int, maximum: int, label: str) -> None:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{label} contains an invalid integer")


def _carrier_bool(value: Any, label: str) -> None:
    if type(value) is not bool:
        raise ValueError(f"{label} contains an invalid boolean")


def _carrier_text(value: Any, limit: int, label: str) -> None:
    if not isinstance(value, str):
        raise ValueError(f"{label} contains invalid text")
    try:
        size = len(value.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise ValueError(f"{label} contains invalid UTF-8 text") from exc
    if size > limit:
        raise ValueError(f"{label} text exceeds its UTF-8 byte limit")


def _validate_span_shape(value: Any, label: str) -> None:
    if not isinstance(value, dict) or set(value) != {"sourceUri", "start", "end"}:
        raise ValueError(f"{label} is malformed")
    if not isinstance(value["sourceUri"], str) or not value["sourceUri"]:
        raise ValueError(f"{label}.sourceUri is malformed")
    for key in ("start", "end"):
        point = value[key]
        if (
            not isinstance(point, dict)
            or set(point) != {"offset", "line", "column"}
            or type(point["offset"]) is not int
            or type(point["line"]) is not int
            or type(point["column"]) is not int
            or point["offset"] < 0
            or point["line"] < 1
            or point["column"] < 1
        ):
            raise ValueError(f"{label}.{key} is malformed")


def _span(entity: Mapping[str, Any]) -> SourceSpan:
    raw = entity["span"]
    from .diagnostics import SourcePosition

    return SourceSpan(
        raw["sourceUri"],
        SourcePosition(**raw["start"]),
        SourcePosition(**raw["end"]),
    )


def _error(message: str, span: SourceSpan) -> None:
    raise ModuleExpansionError("HOCUS940", message, span)

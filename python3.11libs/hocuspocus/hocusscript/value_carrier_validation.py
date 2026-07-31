"""Strict GraphSpec-0.5 tagged-value carrier validation."""

from __future__ import annotations

import math
import re
from typing import Any, Callable

from .bundle import BundleValidationError


_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
_INSTANCE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_TAGGED_KINDS = {
    "reset", "expression", "channel_reference", "raw_path", "quantity",
    "ramp", "multiparm",
}
_BASIS = {
    "constant", "linear", "catmullrom", "monotonecubic", "bezier",
    "bspline", "hermite",
}


def _fail(message: str) -> None:
    raise BundleValidationError("HOCUS520", message)


def validate_tagged_graph_value(
    value: dict[str, Any],
    label: str,
    *,
    validate_span: Callable[[Any, str], None],
    validate_value: Callable[[Any, str], None],
) -> bool:
    """Validate one tagged value; return false for non-tagged discriminants."""

    kind = value.get("kind")
    if kind not in _TAGGED_KINDS:
        return False
    if kind == "reset":
        _exact(value, {"kind", "span"}, label)
    elif kind == "expression":
        _validate_expression(value, label, validate_span)
    elif kind == "channel_reference":
        _validate_channel(value, label)
    elif kind == "raw_path":
        _validate_raw_path(value, label)
    elif kind == "quantity":
        _validate_quantity(value, label)
    elif kind == "ramp":
        _validate_ramp(value, label, validate_value)
    else:
        _validate_multiparm(value, label, validate_value)
    validate_span(value["span"], f"{label}.span")
    return True


def _exact(value: dict[str, Any], keys: set[str], label: str) -> None:
    if set(value) != keys:
        _fail(f"{label} has an invalid tagged-value shape.")


def _validate_expression(
    value: dict[str, Any],
    label: str,
    validate_span: Callable[[Any, str], None],
) -> None:
    _exact(
        value,
        {"kind", "language", "body", "bodySpan", "offsetMap", "span"},
        label,
    )
    body = value["body"]
    if (
        value["language"] not in {"hscript", "python"}
        or not isinstance(body, str)
        or not body
        or len(body.encode("utf-8")) > 1024 * 1024
    ):
        _fail(f"{label} expression language/body is invalid.")
    validate_span(value["bodySpan"], f"{label}.bodySpan")
    _validate_offset_map(value["offsetMap"], body, value["bodySpan"], label)


def _validate_offset_map(
    value: Any, body: str, body_span: dict[str, Any], label: str,
) -> None:
    if (
        not isinstance(value, dict)
        or set(value) != {"bodyLength", "checkpoints"}
        or type(value["bodyLength"]) is not int
        or value["bodyLength"] != len(body)
        or not isinstance(value["checkpoints"], list)
        or not value["checkpoints"]
    ):
        _fail(f"{label}.offsetMap is malformed.")
    points: list[tuple[int, int]] = []
    for point in value["checkpoints"]:
        if (
            not isinstance(point, dict)
            or set(point) != {"bodyOffset", "sourceOffset"}
            or type(point["bodyOffset"]) is not int
            or type(point["sourceOffset"]) is not int
        ):
            _fail(f"{label}.offsetMap checkpoint is malformed.")
        points.append((point["bodyOffset"], point["sourceOffset"]))
    if (
        points != sorted(set(points))
        or points[0] != (0, body_span["start"]["offset"])
        or points[-1] != (len(body), body_span["end"]["offset"])
    ):
        _fail(f"{label}.offsetMap is inconsistent with expression text.")


def _validate_channel(value: dict[str, Any], label: str) -> None:
    _exact(value, {"kind", "nodeSymbol", "parmName", "span"}, label)
    if (
        not isinstance(value["nodeSymbol"], str)
        or _IDENTIFIER.fullmatch(value["nodeSymbol"]) is None
        or not isinstance(value["parmName"], str)
        or _IDENTIFIER.fullmatch(value["parmName"]) is None
    ):
        _fail(f"{label} structural channel identity is invalid.")


def _validate_raw_path(value: dict[str, Any], label: str) -> None:
    _exact(value, {"kind", "pathKind", "raw", "span"}, label)
    raw = value["raw"]
    if (
        value["pathKind"] not in {"node", "parm", "file", "usd_prim", "asset"}
        or not isinstance(raw, str)
        or len(raw.encode("utf-8")) > 8192
    ):
        _fail(f"{label} raw-path value is invalid.")


def _validate_quantity(value: dict[str, Any], label: str) -> None:
    _exact(value, {"kind", "magnitude", "unit", "span"}, label)
    magnitude = value["magnitude"]
    unit = value["unit"]
    if (
        isinstance(magnitude, bool)
        or not isinstance(magnitude, (int, float))
        or not math.isfinite(magnitude)
        or not isinstance(unit, str)
        or not unit
        or len(unit) > 128
    ):
        _fail(f"{label} quantity value is invalid.")


def _validate_ramp(
    value: dict[str, Any],
    label: str,
    validate_value: Callable[[Any, str], None],
) -> None:
    _exact(value, {"kind", "points", "basis", "span"}, label)
    points = value["points"]
    basis = value["basis"]
    if (
        not isinstance(points, list)
        or not 2 <= len(points) <= 4096
        or not isinstance(basis, list)
        or len(basis) != len(points)
        or any(item not in _BASIS for item in basis)
    ):
        _fail(f"{label} ramp has an invalid bounded shape.")
    previous = -math.inf
    for index, point in enumerate(points):
        if not isinstance(point, dict) or set(point) != {"position", "value"}:
            _fail(f"{label}.points[{index}] has an invalid shape.")
        position = point["position"]
        if (
            isinstance(position, bool)
            or not isinstance(position, (int, float))
            or not math.isfinite(position)
            or not 0 <= position <= 1
            or position <= previous
        ):
            _fail(f"{label} ramp positions must be finite and strictly increasing.")
        previous = position
        item = point["value"]
        if not isinstance(item, dict) or item.get("kind") not in {"literal", "array"}:
            _fail(f"{label} ramp point values must be scalar or tuple literals.")
        validate_value(item, f"{label}.points[{index}].value")


def _validate_multiparm(
    value: dict[str, Any],
    label: str,
    validate_value: Callable[[Any, str], None],
) -> None:
    _exact(value, {"kind", "instances", "span"}, label)
    instances = value["instances"]
    if not isinstance(instances, list) or len(instances) > 4096:
        _fail(f"{label} multiparm exceeds its instance bound.")
    identities: set[str] = set()
    for index, instance in enumerate(instances):
        current = f"{label}.instances[{index}]"
        if (
            not isinstance(instance, dict)
            or set(instance) != {"instanceId", "fields"}
            or not isinstance(instance["instanceId"], str)
            or _INSTANCE_ID.fullmatch(instance["instanceId"]) is None
            or instance["instanceId"] in identities
            or not isinstance(instance["fields"], list)
            or len(instance["fields"]) > 256
        ):
            _fail(f"{current} is malformed.")
        identities.add(instance["instanceId"])
        names: set[str] = set()
        for field_index, field in enumerate(instance["fields"]):
            field_label = f"{current}.fields[{field_index}]"
            if (
                not isinstance(field, dict)
                or set(field) != {"name", "value"}
                or not isinstance(field["name"], str)
                or _IDENTIFIER.fullmatch(field["name"]) is None
                or field["name"] in names
            ):
                _fail(f"{field_label} is malformed.")
            names.add(field["name"])
            child = field["value"]
            if (
                isinstance(child, dict)
                and child.get("kind") in {"reset", "ramp", "multiparm"}
            ):
                _fail(f"{field_label} uses an unsupported nested compound value.")
            validate_value(child, f"{field_label}.value")


def validate_value_adapter(
    value: Any, authored: dict[str, Any], label: str,
) -> None:
    if not isinstance(value, dict) or not isinstance(value.get("kind"), str):
        _fail(f"{label} valueAdapter is malformed.")
    kind = value["kind"]
    authored_kind = authored.get("kind")
    expected = authored_kind
    if authored_kind == "channel_reference":
        expected = "channel_reference"
    if kind != expected:
        _fail(f"{label} valueAdapter conflicts with the authored value.")
    shapes = {
        "reset": {"kind"},
        "expression": {"kind", "language"},
        "channel_reference": {"kind", "valueType"},
        "raw_path": {"kind", "pathKind"},
        "quantity": {
            "kind", "dimension", "authoredUnit", "canonicalUnit", "scale",
            "offset", "canonicalMagnitude",
        },
        "ramp": {"kind", "rampKind"},
        "multiparm": {
            "kind", "instanceStart", "minInstances", "maxInstances", "fields",
        },
    }
    if kind not in shapes or set(value) != shapes[kind]:
        _fail(f"{label} valueAdapter has an invalid shape.")
    if kind == "expression" and value["language"] != authored.get("language"):
        _fail(f"{label} expression adapter language conflicts with source.")
    if kind == "raw_path" and value["pathKind"] != authored.get("pathKind"):
        _fail(f"{label} raw-path adapter conflicts with source.")
    if kind == "quantity":
        _validate_quantity_adapter(value, authored, label)
    if kind == "ramp" and value["rampKind"] not in {"float", "color"}:
        _fail(f"{label} ramp adapter kind is invalid.")
    if kind == "multiparm":
        _validate_multiparm_adapter(value, label)


def _validate_quantity_adapter(
    value: dict[str, Any], authored: dict[str, Any], label: str,
) -> None:
    numbers = (
        value["scale"], value["offset"], value["canonicalMagnitude"],
    )
    if (
        value["authoredUnit"] != authored.get("unit")
        or any(
            isinstance(item, bool)
            or not isinstance(item, (int, float))
            or not math.isfinite(item)
            for item in numbers
        )
        or not all(
            isinstance(value[field], str) and value[field]
            for field in ("dimension", "authoredUnit", "canonicalUnit")
        )
    ):
        _fail(f"{label} quantity adapter is invalid.")


def _validate_multiparm_adapter(value: dict[str, Any], label: str) -> None:
    instance_start = value["instanceStart"]
    minimum = value["minInstances"]
    maximum = value["maxInstances"]
    fields = value["fields"]
    if (
        type(instance_start) is not int
        or not 0 <= instance_start <= 4096
        or type(minimum) is not int
        or type(maximum) is not int
        or not 0 <= minimum <= maximum <= 4096
        or not isinstance(fields, list)
        or len(fields) > 256
    ):
        _fail(f"{label} multiparm adapter bounds are invalid.")
    names: set[str] = set()
    for item in fields:
        if (
            not isinstance(item, dict)
            or set(item) != {
                "name", "tokenTemplate", "valueType", "tupleSize",
                "elementType",
            }
            or not isinstance(item["name"], str)
            or _IDENTIFIER.fullmatch(item["name"]) is None
            or item["name"] in names
            or not isinstance(item["tokenTemplate"], str)
            or item["tokenTemplate"].count("#") != 1
            or type(item["tupleSize"]) is not int
            or not 1 <= item["tupleSize"] <= 1024
        ):
            _fail(f"{label} multiparm field adapter is invalid.")
        names.add(item["name"])

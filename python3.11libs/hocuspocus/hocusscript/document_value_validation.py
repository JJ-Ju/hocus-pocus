"""Closed network-document-v2 parameter-binding validation."""

from __future__ import annotations

import math
import re
from typing import Any


_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
_INSTANCE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_BASES = {
    "constant", "linear", "catmullrom", "monotonecubic", "bezier",
    "bspline", "hermite",
}
_PATH_KINDS = {"node", "parm", "file", "usd_prim", "asset"}
_VALUE_TYPES = {
    "bool", "int", "float", "string", "tuple", "menu", "code",
    "node_path", "parm_path", "file_path", "usd_prim_path",
    "asset_reference",
}
_ELEMENT_TYPES = {"bool", "int", "float", "string"}
_COMMON = {"uid", "nodeUid", "parmName", "valueMode", "metadata"}
_MODE_FIELDS = {
    "literal": {"value"},
    "menu_token": {"menuToken"},
    "reset": set(),
    "expression": {"expression", "expressionLanguage"},
    "channel_reference": {"channelReference"},
    "raw_path": {"pathKind", "raw"},
    "quantity": {
        "magnitude", "unit", "dimension", "canonicalMagnitude",
        "canonicalUnit",
    },
    "ramp": {"rampKind", "points", "basis"},
    "multiparm": {"instanceStart", "instances", "fieldContract"},
    "code_reference": {"codeBlobUid"},
}


class DocumentValueValidationError(ValueError):
    """Typed internal rejection for malformed v2 binding content."""


def validate_v2_binding(binding: Any, node_uids: set[str]) -> None:
    if not isinstance(binding, dict):
        _fail("Binding must be an object.")
    mode = binding.get("valueMode")
    fields = _MODE_FIELDS.get(mode)
    if fields is None or set(binding) != _COMMON | fields:
        _fail("Binding has an invalid closed value-mode shape.")
    for field in ("uid", "nodeUid", "parmName"):
        if not isinstance(binding[field], str) or not binding[field]:
            _fail(f"Binding {field} must be non-empty.")
    if binding["nodeUid"] not in node_uids:
        _fail("Binding nodeUid is dangling.")
    if _IDENTIFIER.fullmatch(binding["parmName"]) is None:
        _fail("Binding parmName is invalid.")
    if not isinstance(binding["metadata"], dict):
        _fail("Binding metadata must be an object.")
    _parameter_selection(binding)
    _validate_mode(binding, mode, node_uids)


def validate_v1_receipt_binding(
    binding: Any, node_uids: set[str],
) -> None:
    """Validate the frozen v1 binding shape retained in a durable receipt."""

    allowed = _COMMON | {
        "value", "expression", "expressionLanguage",
        "channelReference", "codeBlobUid",
    }
    if (
        not isinstance(binding, dict)
        or not _COMMON <= set(binding) <= allowed
        or binding.get("valueMode") not in {
            "literal", "expression", "channel_reference", "code_reference",
        }
    ):
        _fail("Frozen v1 receipt binding has an invalid closed shape.")
    for field in ("uid", "nodeUid", "parmName"):
        _string(binding[field], field, maximum=512)
    if binding["nodeUid"] not in node_uids:
        _fail("Frozen v1 receipt binding nodeUid is dangling.")
    if not isinstance(binding["metadata"], dict):
        _fail("Frozen v1 receipt binding metadata must be an object.")
    _parameter_selection(binding, require_adapter=False)
    _validate_v1_receipt_mode(binding)


def _validate_v1_receipt_mode(binding: dict[str, Any]) -> None:
    mode = binding["valueMode"]
    if mode == "literal":
        if "value" not in binding or isinstance(binding["value"], (list, dict)):
            _fail("Frozen v1 literal receipt must contain one scalar.")
        _json_value(binding["value"], depth=0, budget=[0])
    elif mode == "expression":
        _string(
            binding.get("expression"), "expression", maximum=1_048_576,
        )
    elif mode == "channel_reference":
        reference = binding.get("channelReference")
        expression = binding.get("expression")
        if not (
            isinstance(reference, str) and reference
            or isinstance(expression, str) and expression
        ):
            _fail("Frozen v1 channel receipt lacks a reference.")
        for value in (reference, expression):
            if value is not None:
                _string(value, "channel reference", maximum=1_048_576)
    else:
        _string(binding.get("codeBlobUid"), "codeBlobUid", maximum=512)
    language = binding.get("expressionLanguage")
    if language is not None:
        _string(language, "expressionLanguage", maximum=64)


def _validate_mode(
    binding: dict[str, Any], mode: str, node_uids: set[str],
) -> None:
    if mode == "literal":
        _json_value(binding["value"], depth=0, budget=[0])
    elif mode == "menu_token":
        _string(binding["menuToken"], "menuToken", maximum=8192)
    elif mode == "expression":
        _string(binding["expression"], "expression", maximum=1_048_576)
        if binding["expressionLanguage"] not in {"hscript", "python"}:
            _fail("expressionLanguage is invalid.")
    elif mode == "channel_reference":
        _channel(binding["channelReference"], node_uids)
    elif mode == "raw_path":
        _raw_path(binding)
    elif mode == "quantity":
        _quantity(binding)
    elif mode == "ramp":
        _ramp(binding)
    elif mode == "multiparm":
        _multiparm(binding, node_uids)
    elif mode == "code_reference":
        _string(binding["codeBlobUid"], "codeBlobUid", maximum=512)


def _parameter_selection(
    binding: dict[str, Any], *, require_adapter: bool = True,
) -> None:
    selection = binding["metadata"].get("parameterSelection")
    if selection is None:
        return
    if not isinstance(selection, dict):
        _fail("parameterSelection must be an object.")
    tuple_fields = {
        "authoredToken", "parameterToken", "componentIndex",
        "componentToken", "tupleSize", "elementType", "conversion",
        "menuToken",
    }
    scalar_fields = {
        "authoredToken", "parameterToken", "componentIndex", "valueType",
        "conversion", "menuToken",
    }
    fields = set(selection)
    if fields == tuple_fields:
        _tuple_parameter_selection(binding, selection)
        return
    if fields not in (scalar_fields, scalar_fields | {"valueAdapter"}):
        _fail("parameterSelection has an invalid closed shape.")
    for field in ("authoredToken", "parameterToken"):
        if (
            not isinstance(selection[field], str)
            or _IDENTIFIER.fullmatch(selection[field]) is None
        ):
            _fail(f"parameterSelection {field} is invalid.")
    component = selection["componentIndex"]
    if component is not None and (
        type(component) is not int or component < 0
    ):
        _fail("parameterSelection componentIndex is invalid.")
    if selection["valueType"] not in _VALUE_TYPES | {"ramp", "multiparm"}:
        _fail("parameterSelection valueType is invalid.")
    _selection_nullable_fields(selection)
    _selection_adapter(
        binding, selection.get("valueAdapter"), required=require_adapter
    )


def _tuple_parameter_selection(
    binding: dict[str, Any], selection: dict[str, Any],
) -> None:
    for field in ("authoredToken", "parameterToken", "componentToken"):
        if (
            not isinstance(selection[field], str)
            or _IDENTIFIER.fullmatch(selection[field]) is None
        ):
            _fail(f"tuple parameterSelection {field} is invalid.")
    index, size = selection["componentIndex"], selection["tupleSize"]
    if (
        type(index) is not int
        or type(size) is not int
        or not 0 <= index < size <= 1024
        or selection["componentToken"] != binding["parmName"]
        or selection["elementType"] not in _ELEMENT_TYPES
    ):
        _fail("tuple parameterSelection component evidence is invalid.")
    _selection_nullable_fields(selection)


def _selection_nullable_fields(selection: dict[str, Any]) -> None:
    if selection["conversion"] not in {None, "int_to_float"}:
        _fail("parameterSelection conversion is invalid.")
    menu = selection["menuToken"]
    if menu is not None and (
        not isinstance(menu, str) or len(menu.encode("utf-8")) > 8192
    ):
        _fail("parameterSelection menuToken is invalid.")


def _selection_adapter(
    binding: dict[str, Any], adapter: Any, *, required: bool,
) -> None:
    mode = binding["valueMode"]
    expected = {
        "reset": "reset", "expression": "expression",
        "channel_reference": "channel_reference", "raw_path": "raw_path",
        "quantity": "quantity", "ramp": "ramp", "multiparm": "multiparm",
    }.get(mode)
    if not required:
        if adapter is not None:
            _fail("Frozen v1 parameterSelection cannot carry a valueAdapter.")
        return
    if expected is None:
        if adapter is not None:
            _fail("This binding mode cannot carry a valueAdapter.")
        return
    if not isinstance(adapter, dict) or adapter.get("kind") != expected:
        _fail(f"{mode} binding lacks exact valueAdapter evidence.")
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
    if set(adapter) != shapes[expected]:
        _fail(f"{mode} valueAdapter has an invalid closed shape.")
    if mode == "expression" and adapter["language"] != binding["expressionLanguage"]:
        _fail("Expression valueAdapter language conflicts with its binding.")
    if mode == "channel_reference" and adapter["valueType"] not in _VALUE_TYPES:
        _fail("Channel valueAdapter type is invalid.")
    if mode == "raw_path" and adapter["pathKind"] != binding["pathKind"]:
        _fail("Raw-path valueAdapter conflicts with its binding.")


def _channel(value: Any, node_uids: set[str]) -> None:
    if not isinstance(value, dict) or set(value) != {"nodeUid", "parmName"}:
        _fail("channelReference must be an exact structural object.")
    if value["nodeUid"] not in node_uids:
        _fail("channelReference nodeUid is dangling.")
    if (
        not isinstance(value["parmName"], str)
        or _IDENTIFIER.fullmatch(value["parmName"]) is None
    ):
        _fail("channelReference parmName is invalid.")


def _raw_path(value: dict[str, Any]) -> None:
    if value["pathKind"] not in _PATH_KINDS:
        _fail("pathKind is invalid.")
    _string(value["raw"], "raw", maximum=8192, allow_empty=True)


def _quantity(value: dict[str, Any]) -> None:
    for field in ("magnitude", "canonicalMagnitude"):
        _finite(value[field], field)
    for field in ("unit", "dimension", "canonicalUnit"):
        _string(value[field], field, maximum=128)
    adapter = _binding_adapter(value, "quantity")
    if (
        adapter.get("authoredUnit") != value["unit"]
        or adapter.get("dimension") != value["dimension"]
        or adapter.get("canonicalUnit") != value["canonicalUnit"]
        or not _is_finite(adapter.get("scale"))
        or not _is_finite(adapter.get("offset"))
    ):
        _fail("Quantity binding conflicts with its authenticated adapter.")
    expected = (
        value["magnitude"] * adapter["scale"] + adapter["offset"]
    )
    if not math.isclose(
        float(expected), float(value["canonicalMagnitude"]),
        rel_tol=0.0, abs_tol=0.0,
    ):
        _fail("Quantity canonical magnitude conflicts with its adapter.")


def _ramp(value: dict[str, Any]) -> None:
    ramp_kind = value["rampKind"]
    points = value["points"]
    basis = value["basis"]
    if (
        ramp_kind not in {"float", "color"}
        or not isinstance(points, list)
        or not 2 <= len(points) <= 4096
        or not isinstance(basis, list)
        or len(basis) != len(points)
        or any(item not in _BASES for item in basis)
    ):
        _fail("Ramp shape is invalid.")
    previous = -1.0
    for point in points:
        if not isinstance(point, dict) or set(point) != {"position", "value"}:
            _fail("Ramp point shape is invalid.")
        position = _finite(point["position"], "ramp position")
        if not 0 <= position <= 1 or position <= previous:
            _fail("Ramp positions must be strictly increasing in [0, 1].")
        previous = position
        item = point["value"]
        if ramp_kind == "float":
            _finite(item, "ramp value")
        elif (
            not isinstance(item, list)
            or len(item) != 3
            or any(not _is_finite(child) for child in item)
        ):
            _fail("Color ramp values must be finite triples.")


def _multiparm(value: dict[str, Any], node_uids: set[str]) -> None:
    instance_start = value["instanceStart"]
    contracts = value["fieldContract"]
    instances = value["instances"]
    if (
        type(instance_start) is not int
        or not 0 <= instance_start <= 4096
        or not isinstance(contracts, list)
        or len(contracts) > 256
        or not isinstance(instances, list)
        or len(instances) > 4096
    ):
        _fail("Multiparm bounds are invalid.")
    contract_names: set[str] = set()
    for contract in contracts:
        _field_contract(contract, contract_names)
    adapter = _binding_adapter(value, "multiparm")
    if (
        adapter.get("instanceStart") != instance_start
        or adapter.get("fields") != contracts
    ):
        _fail("Multiparm field contract conflicts with its authenticated adapter.")
    identities: set[str] = set()
    for instance in instances:
        if (
            not isinstance(instance, dict)
            or set(instance) != {"instanceId", "fields"}
            or not isinstance(instance["instanceId"], str)
            or _INSTANCE_ID.fullmatch(instance["instanceId"]) is None
            or instance["instanceId"] in identities
            or not isinstance(instance["fields"], list)
            or len(instance["fields"]) != len(contracts)
        ):
            _fail("Multiparm instance shape is invalid.")
        identities.add(instance["instanceId"])
        names: set[str] = set()
        for field in instance["fields"]:
            if (
                not isinstance(field, dict)
                or set(field) != {"name", "value"}
                or field["name"] not in contract_names
                or field["name"] in names
            ):
                _fail("Multiparm field identity is invalid.")
            names.add(field["name"])
            _nested_value(field["value"], node_uids)


def _field_contract(value: Any, names: set[str]) -> None:
    keys = {"name", "tokenTemplate", "valueType", "tupleSize", "elementType"}
    if (
        not isinstance(value, dict)
        or set(value) != keys
        or not isinstance(value["name"], str)
        or _IDENTIFIER.fullmatch(value["name"]) is None
        or value["name"] in names
        or not isinstance(value["tokenTemplate"], str)
        or value["tokenTemplate"].count("#") != 1
        or len(value["tokenTemplate"].encode("utf-8")) > 512
        or value["valueType"] not in _VALUE_TYPES
        or type(value["tupleSize"]) is not int
        or value["tupleSize"] != 1
        or value["elementType"] is not None
    ):
        _fail("Multiparm field contract is invalid.")
    names.add(value["name"])


def _binding_adapter(value: dict[str, Any], kind: str) -> dict[str, Any]:
    metadata = value.get("metadata")
    selection = (
        metadata.get("parameterSelection")
        if isinstance(metadata, dict) else None
    )
    adapter = (
        selection.get("valueAdapter")
        if isinstance(selection, dict) else None
    )
    if not isinstance(adapter, dict) or adapter.get("kind") != kind:
        _fail(f"{kind} binding lacks authenticated adapter evidence.")
    return adapter


def _nested_value(value: Any, node_uids: set[str]) -> None:
    if not isinstance(value, dict) or not isinstance(value.get("kind"), str):
        _fail("Nested multiparm value is malformed.")
    handler = _NESTED_VALIDATORS.get(value["kind"])
    if handler is None:
        _fail("Nested multiparm value kind is unsupported.")
    handler(value, node_uids)


def _nested_literal(value: dict[str, Any], _node_uids: set[str]) -> None:
    if set(value) != {"kind", "value"}:
        _fail("Nested literal shape is invalid.")
    _json_value(value["value"], depth=0, budget=[0])


def _nested_expression(value: dict[str, Any], _node_uids: set[str]) -> None:
    if set(value) != {"kind", "language", "body"}:
        _fail("Nested expression shape is invalid.")
    _string(value["body"], "nested expression", maximum=1_048_576)
    if value["language"] not in {"hscript", "python"}:
        _fail("Nested expression language is invalid.")


def _nested_channel(value: dict[str, Any], node_uids: set[str]) -> None:
    if set(value) != {"kind", "nodeUid", "parmName"}:
        _fail("Nested channel shape is invalid.")
    _channel(
        {"nodeUid": value["nodeUid"], "parmName": value["parmName"]},
        node_uids,
    )


def _nested_raw_path(value: dict[str, Any], _node_uids: set[str]) -> None:
    if set(value) != {"kind", "pathKind", "raw"}:
        _fail("Nested raw-path shape is invalid.")
    _raw_path(value)


def _nested_quantity(value: dict[str, Any], _node_uids: set[str]) -> None:
    if set(value) != {"kind", "magnitude", "unit"}:
        _fail("Nested quantity shape is invalid.")
    _finite(value["magnitude"], "nested quantity")
    _string(value["unit"], "nested unit", maximum=128)


_NESTED_VALIDATORS = {
    "literal": _nested_literal,
    "expression": _nested_expression,
    "channel_reference": _nested_channel,
    "raw_path": _nested_raw_path,
}


def _json_value(value: Any, *, depth: int, budget: list[int]) -> None:
    budget[0] += 1
    if depth > 64 or budget[0] > 100_000:
        _fail("Literal value exceeds structural bounds.")
    if value is None or type(value) in {bool, int, str}:
        return
    if type(value) is float:
        _finite(value, "literal")
        return
    if isinstance(value, list):
        for item in value:
            _json_value(item, depth=depth + 1, budget=budget)
        return
    _fail("Literal value must be JSON data without objects.")


def _string(
    value: Any, label: str, *, maximum: int, allow_empty: bool = False,
) -> str:
    if (
        not isinstance(value, str)
        or (not allow_empty and not value)
        or len(value.encode("utf-8")) > maximum
    ):
        _fail(f"{label} is invalid.")
    return value


def _is_finite(value: Any) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(value)
    )


def _finite(value: Any, label: str) -> float:
    if not _is_finite(value):
        _fail(f"{label} must be finite.")
    return float(value)


def _fail(message: str) -> None:
    raise DocumentValueValidationError(message)

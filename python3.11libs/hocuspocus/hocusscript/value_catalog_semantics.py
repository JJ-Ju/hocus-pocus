"""Catalog-v2 semantic adapters for GraphSpec-0.5 tagged values."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping

from .catalog import OperatorDefinition, ParameterDefinition
from .model import ArrayValue, GraphSpec, LiteralValue, TaggedValue


_RAW_PATH_VALUE_TYPES = {
    "node": "node_path",
    "parm": "parm_path",
    "file": "file_path",
    "usd_prim": "usd_prim_path",
    "asset": "asset_reference",
}


@dataclass(frozen=True, slots=True)
class TypedValueSemanticError(ValueError):
    message: str

    def __str__(self) -> str:
        return self.message


def invalid_channel_targets(
    graph: GraphSpec,
    selected: Mapping[str, OperatorDefinition],
) -> list[tuple[TaggedValue, str]]:
    """Return structural channel references lacking one exact catalog target."""

    result: list[tuple[TaggedValue, str]] = []
    for node_index, node in enumerate(graph.nodes):
        for parm_index, parm in enumerate(node.parms):
            for ordinal, reference in enumerate(_channel_references(parm.value)):
                operator = selected.get(reference.payload["nodeSymbol"])
                if operator is None or not _catalog_parm_token_is_exact(
                    operator, reference.payload["parmName"]
                ):
                    result.append((
                        reference,
                        f"/nodes/{node_index}/parms/{parm_index}/value"
                        f"/channelReferences/{ordinal}",
                    ))
    return result


def _channel_references(value: Any) -> list[TaggedValue]:
    pending = [value]
    result: list[TaggedValue] = []
    while pending:
        current = pending.pop()
        if isinstance(current, TaggedValue):
            if current.tag == "channel_reference":
                result.append(current)
            elif current.tag == "multiparm":
                pending.extend(
                    field["value"]
                    for instance in current.payload["instances"]
                    for field in instance["fields"]
                )
        elif isinstance(current, ArrayValue):
            pending.extend(current.items)
    return result


def _catalog_parm_token_is_exact(
    operator: OperatorDefinition, token: str,
) -> bool:
    return sum(
        int(parameter.token == token)
        + sum(component == token for component in parameter.tuple_names)
        for parameter in operator.parameters
    ) == 1


def typed_value_adapter(
    value: TaggedValue,
    definition: ParameterDefinition,
    component_index: int | None = None,
) -> dict[str, Any]:
    kind = value.tag
    if kind == "reset":
        _reject_action(definition)
        return {"kind": "reset"}
    if kind == "expression":
        _reject_compound_or_action(definition)
        return {"kind": "expression", "language": value.payload["language"]}
    if kind == "channel_reference":
        _reject_compound_or_action(definition)
        return {"kind": "channel_reference", "valueType": definition.value_type}
    if kind == "raw_path":
        return _raw_path_adapter(value, definition)
    if kind == "quantity":
        return _quantity_adapter(value, definition, component_index)
    if kind == "ramp":
        return _ramp_adapter(value, definition)
    if kind == "multiparm":
        return _multiparm_adapter(value, definition)
    raise TypedValueSemanticError("Unsupported tagged-value discriminant.")


def _reject_action(definition: ParameterDefinition) -> None:
    if definition.value_type == "button":
        raise TypedValueSemanticError(
            "Buttons and callbacks are actions and cannot be authored as values."
        )


def _reject_compound_or_action(definition: ParameterDefinition) -> None:
    _reject_action(definition)
    if definition.value_type in {"ramp", "multiparm", "code"}:
        raise TypedValueSemanticError(
            "This typed value is not valid for a compound or code parameter."
        )


def _raw_path_adapter(
    value: TaggedValue, definition: ParameterDefinition,
) -> dict[str, Any]:
    expected = _RAW_PATH_VALUE_TYPES[value.payload["pathKind"]]
    if definition.value_type != expected:
        raise TypedValueSemanticError(
            f"raw_path({value.payload['pathKind']}) requires {expected}."
        )
    return {"kind": "raw_path", "pathKind": value.payload["pathKind"]}


def _quantity_adapter(
    value: TaggedValue,
    definition: ParameterDefinition,
    component_index: int | None,
) -> dict[str, Any]:
    if definition.value_type == "tuple" and component_index is None:
        raise TypedValueSemanticError(
            "Quantity assignment to a tuple requires an explicit component."
        )
    contract = _contract(definition, "quantity")
    authored = value.payload["unit"]
    unit = next(
        (item for item in contract["units"] if item["unit"] == authored),
        None,
    )
    if unit is None:
        raise TypedValueSemanticError(
            f"Unit {authored!r} is not declared for this parameter."
        )
    magnitude = value.payload["magnitude"]
    canonical = magnitude * unit["scale"] + unit["offset"]
    if not math.isfinite(canonical):
        raise TypedValueSemanticError("Quantity conversion is not finite.")
    target_type = (
        _element_type(definition)
        if definition.value_type == "tuple" else definition.value_type
    )
    if target_type not in {"int", "float"}:
        raise TypedValueSemanticError(
            "Quantity assignment requires a numeric scalar component."
        )
    if target_type == "int" and type(canonical) is not int:
        if not float(canonical).is_integer():
            raise TypedValueSemanticError(
                "Quantity conversion is not exact for an integer parameter."
            )
        canonical = int(canonical)
    return {
        "kind": "quantity",
        "dimension": contract["dimension"],
        "authoredUnit": authored,
        "canonicalUnit": contract["canonicalUnit"],
        "scale": unit["scale"],
        "offset": unit["offset"],
        "canonicalMagnitude": canonical,
    }


def _element_type(definition: ParameterDefinition) -> str | None:
    value = definition.tags.get("elementType")
    return value if isinstance(value, str) else None


def _ramp_adapter(
    value: TaggedValue, definition: ParameterDefinition,
) -> dict[str, Any]:
    contract = _contract(definition, "ramp")
    points = value.payload["points"]
    bases = value.payload["basis"]
    if any(item not in contract["allowedBases"] for item in bases):
        raise TypedValueSemanticError("Ramp uses a basis not declared by the catalog.")
    expected_size = 1 if contract["rampKind"] == "float" else 3
    for point in points:
        item = point["value"]
        if expected_size == 1 and not _numeric_literal(item):
            raise TypedValueSemanticError("Float ramp values must be numeric scalars.")
        if expected_size == 3 and not _numeric_tuple(item, 3):
            raise TypedValueSemanticError("Color ramp values must be numeric triples.")
    return {"kind": "ramp", "rampKind": contract["rampKind"]}


def _multiparm_adapter(
    value: TaggedValue, definition: ParameterDefinition,
) -> dict[str, Any]:
    contract = _contract(definition, "multiparm")
    instances = value.payload["instances"]
    if not contract["minInstances"] <= len(instances) <= contract["maxInstances"]:
        raise TypedValueSemanticError("Multiparm instance count is outside catalog bounds.")
    fields = {item["name"]: item for item in contract["fields"]}
    if any(item["tupleSize"] != 1 for item in fields.values()):
        raise TypedValueSemanticError(
            "HS7 multiparm fields must resolve to scalar Houdini parameters."
        )
    for instance in instances:
        authored = {item["name"]: item["value"] for item in instance["fields"]}
        if set(authored) != set(fields):
            raise TypedValueSemanticError(
                "Each multiparm instance must author the exact catalog field set."
            )
        for name, item in authored.items():
            if not _field_value_matches(item, fields[name]):
                raise TypedValueSemanticError(
                    f"Multiparm field {name!r} has the wrong value type."
                )
    return {
        "kind": "multiparm",
        "instanceStart": contract["instanceStart"],
        "minInstances": contract["minInstances"],
        "maxInstances": contract["maxInstances"],
        "fields": [dict(item) for item in contract["fields"]],
    }


def _contract(
    definition: ParameterDefinition, expected: str,
) -> Mapping[str, Any]:
    contract = definition.value_contract
    if contract is None or contract.get("kind") != expected:
        raise TypedValueSemanticError(
            f"Catalog v2 lacks the required {expected} value contract."
        )
    return contract


def _numeric_literal(value: Any) -> bool:
    return (
        isinstance(value, LiteralValue)
        and not isinstance(value.value, bool)
        and isinstance(value.value, (int, float))
    )


def _numeric_tuple(value: Any, size: int) -> bool:
    return (
        isinstance(value, ArrayValue)
        and len(value.items) == size
        and all(_numeric_literal(item) for item in value.items)
    )


def _field_value_matches(value: Any, field: Mapping[str, Any]) -> bool:
    value_type = field["valueType"]
    if isinstance(value, TaggedValue):
        return (
            value.tag == "raw_path"
            and _RAW_PATH_VALUE_TYPES.get(value.payload.get("pathKind"))
            == value_type
        ) or (
            value.tag in {"expression", "channel_reference"}
            and value_type not in {"ramp", "multiparm", "button", "code"}
        )
    if field["tupleSize"] != 1:
        return False
    if not isinstance(value, LiteralValue):
        return False
    raw = value.value
    return {
        "bool": type(raw) is bool,
        "int": type(raw) is int,
        "float": not isinstance(raw, bool) and isinstance(raw, (int, float)),
        "string": isinstance(raw, str),
        "menu": isinstance(raw, str),
        "node_path": isinstance(raw, str),
        "parm_path": isinstance(raw, str),
        "file_path": isinstance(raw, str),
        "usd_prim_path": isinstance(raw, str),
        "asset_reference": isinstance(raw, str),
    }.get(value_type, False)

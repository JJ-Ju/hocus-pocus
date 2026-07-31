"""Catalog-backed semantic evidence for HS7 runtime declarations."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .catalog import OperatorDefinition, ParameterDefinition
from .model import GraphSpec


def resolve_runtime_entities(
    graph: GraphSpec,
    selected: Mapping[str, OperatorDefinition],
    parameter_selections: Sequence[Any],
) -> tuple[list[dict[str, Any]], list[tuple[str, str]]]:
    """Return authenticated evidence plus pointer-addressed semantic errors."""

    if graph.graph_spec_version != "0.5":
        return [], []
    evidence: list[dict[str, Any]] = []
    errors: list[tuple[str, str]] = []
    selections = {
        (item.node_symbol, item.authored_token): item
        for item in parameter_selections
    }
    spares = {
        (item["nodeSymbol"], item["name"]): item
        for item in graph.spare_parameters
    }
    for index, spare in enumerate(graph.spare_parameters):
        pointer = f"/spareParameters/{index}"
        operator = selected.get(spare["nodeSymbol"])
        if operator is None:
            continue
        if (
            operator.spare_parameter_policy not in {"declared_only", "allowed"}
            or operator.locked or not operator.editable
        ):
            errors.append((
                pointer,
                "Managed instance spares require an editable unlocked operator "
                "whose catalog policy permits declared spares.",
            ))
            continue
        evidence.append({
            "kind": "spare", "explicitId": spare["explicitId"],
            "nodeSymbol": spare["nodeSymbol"], "jsonPointer": pointer,
            "spareParameterPolicy": operator.spare_parameter_policy,
            "instanceEditable": True,
        })
    for index, animation in enumerate(graph.animations):
        pointer = f"/animations/{index}"
        operator = selected.get(animation["nodeSymbol"])
        if operator is None:
            continue
        if operator.locked or not operator.editable:
            errors.append((
                pointer, "Animation requires an editable unlocked node instance.",
            ))
            continue
        spare = spares.get((animation["nodeSymbol"], animation["parmName"]))
        if spare is not None:
            if (
                spare["type"] != animation["valueType"]
                or spare["tupleSize"] != 1
            ):
                errors.append((pointer, "Animation conflicts with its managed spare type."))
                continue
            evidence.append({
                "kind": "animation", "explicitId": animation["explicitId"],
                "nodeSymbol": animation["nodeSymbol"], "jsonPointer": pointer,
                "parameterToken": animation["parmName"],
                "componentIndex": None, "valueType": animation["valueType"],
                "targetKind": "managed_spare",
                "spareExplicitId": spare["explicitId"],
            })
            continue
        selection = selections.get(
            (animation["nodeSymbol"], animation["parmName"])
        )
        definition, component = _parameter(
            operator, animation["parmName"],
        )
        expected = _numeric_type(definition, component)
        if (
            selection is None
            or definition is None
            or expected != animation["valueType"]
            or selection.value_adapter is not None
            or definition.value_type in {"code", "button", "ramp", "multiparm"}
        ):
            errors.append((
                pointer,
                "Animation target must be one exact ordinary numeric "
                "parameter/component with a literal snapshot.",
            ))
            continue
        evidence.append({
            "kind": "animation", "explicitId": animation["explicitId"],
            "nodeSymbol": animation["nodeSymbol"], "jsonPointer": pointer,
            "parameterToken": definition.token,
            "componentIndex": component,
            "valueType": expected, "targetKind": "catalog_parameter",
            "spareExplicitId": None,
        })
    return evidence, errors


def append_runtime_semantics(
    graph: GraphSpec,
    selected: Mapping[str, OperatorDefinition],
    parameter_selections: Sequence[Any],
    diagnostics: list[Any],
    diagnostic_factory: Any,
) -> list[dict[str, Any]]:
    evidence, errors = resolve_runtime_entities(
        graph, selected, parameter_selections,
    )
    diagnostics.extend(
        diagnostic_factory(
            "HOCUS947", message, graph.span, pointer=pointer,
        )
        for pointer, message in errors
    )
    return evidence


def validate_runtime_evidence(
    graph: Mapping[str, Any],
    evidence: Any,
    parameter_selections: Sequence[Mapping[str, Any]] = (),
) -> None:
    """Cross-check bundle semantic evidence against exact GraphSpec content."""

    if not isinstance(evidence, list):
        raise ValueError("runtimeSelections must be an array")
    expected = {
        ("spare", item["explicitId"], item["nodeSymbol"])
        for item in graph.get("spareParameters", [])
    } | {
        ("animation", item["explicitId"], item["nodeSymbol"])
        for item in graph.get("animations", [])
    }
    actual: set[tuple[str, str, str]] = set()
    for item in evidence:
        if not isinstance(item, dict):
            raise ValueError("runtime selection must be an object")
        kind = item.get("kind")
        keys = (
            {
                "kind", "explicitId", "nodeSymbol", "jsonPointer",
                "spareParameterPolicy", "instanceEditable",
            }
            if kind == "spare" else {
                "kind", "explicitId", "nodeSymbol", "jsonPointer",
                "parameterToken", "componentIndex", "valueType",
                "targetKind", "spareExplicitId",
            }
        )
        if kind not in {"spare", "animation"} or set(item) != keys:
            raise ValueError("runtime selection has an invalid closed shape")
        key = (kind, item["explicitId"], item["nodeSymbol"])
        if key in actual or key not in expected:
            raise ValueError("runtime selection is duplicated or unexpected")
        actual.add(key)
        table = "spareParameters" if kind == "spare" else "animations"
        source = next(
            candidate for candidate in graph[table]
            if candidate["explicitId"] == item["explicitId"]
            and candidate["nodeSymbol"] == item["nodeSymbol"]
        )
        expected_pointer = f"/{table}/{graph[table].index(source)}"
        if item["jsonPointer"] != expected_pointer:
            raise ValueError("runtime selection pointer conflicts with GraphSpec")
        if kind == "spare":
            if (
                item["spareParameterPolicy"] not in {"declared_only", "allowed"}
                or item["instanceEditable"] is not True
            ):
                raise ValueError("spare semantic evidence is not editable")
        else:
            _validate_animation_evidence(
                graph, source, item, parameter_selections,
            )
    if actual != expected:
        raise ValueError("runtime selections do not exactly cover GraphSpec entities")


def _validate_animation_evidence(
    graph: Mapping[str, Any],
    source: Mapping[str, Any],
    evidence: Mapping[str, Any],
    parameter_selections: Sequence[Mapping[str, Any]],
) -> None:
    if (
        evidence["valueType"] != source["valueType"]
    ):
        raise ValueError("animation semantic evidence conflicts with GraphSpec")
    if evidence["targetKind"] == "managed_spare":
        matching = [
            item for item in graph["spareParameters"]
            if item["nodeSymbol"] == source["nodeSymbol"]
            and item["name"] == source["parmName"]
        ]
        if (
            len(matching) != 1
            or evidence["spareExplicitId"] != matching[0]["explicitId"]
            or evidence["parameterToken"] != source["parmName"]
            or evidence["componentIndex"] is not None
        ):
            raise ValueError("managed-spare animation evidence is inconsistent")
        return
    if evidence["targetKind"] != "catalog_parameter":
        raise ValueError("animation target kind is invalid")
    matching = [
        item for item in parameter_selections
        if item.get("nodeSymbol") == source["nodeSymbol"]
        and item.get("authoredToken") == source["parmName"]
    ]
    if (
        len(matching) != 1
        or evidence["spareExplicitId"] is not None
        or matching[0].get("valueAdapter") is not None
        or evidence["parameterToken"] != matching[0].get("parameterToken")
        or evidence["componentIndex"] != matching[0].get("componentIndex")
    ):
        raise ValueError("catalog animation evidence is inconsistent")


def _parameter(
    operator: OperatorDefinition, token: str,
) -> tuple[ParameterDefinition | None, int | None]:
    roots = [item for item in operator.parameters if item.token == token]
    components = [
        (item, index)
        for item in operator.parameters
        for index, name in enumerate(item.tuple_names)
        if name == token
    ]
    if len(roots) + len(components) != 1:
        return None, None
    return (roots[0], None) if roots else components[0]


def _numeric_type(
    definition: ParameterDefinition | None, component: int | None,
) -> str | None:
    if definition is None:
        return None
    if component is None:
        return (
            definition.value_type
            if definition.tuple_size == 1
            and definition.value_type in {"float", "int"} else None
        )
    tagged = definition.tags.get("elementType")
    if tagged in {"float", "int"}:
        return tagged
    default = definition.default
    if isinstance(default, tuple) and component < len(default):
        value = default[component]
        if type(value) is int:
            return "int"
        if type(value) is float:
            return "float"
    return None

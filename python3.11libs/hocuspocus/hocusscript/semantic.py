"""Pure catalog-backed semantic resolution for HocusScript GraphSpec v0.1."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Mapping

from .catalog import CatalogProvider, CatalogSnapshot, ConnectorDefinition, OperatorDefinition, ParameterDefinition
from .diagnostics import Diagnostic, SourceSpan, sort_diagnostics
from .model import ArrayValue, CodeValue, GraphSpec, LiteralValue, NodeSpec, ParmSpec

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True, slots=True)
class CatalogConstraint:
    fingerprint: str


@dataclass(frozen=True, slots=True)
class ExternalNodeBinding:
    operator_qualified_name: str
    catalog_fingerprint: str
    category: str | None = None


@dataclass(frozen=True, slots=True)
class OperatorSelection:
    node_symbol: str
    node_index: int
    json_pointer: str
    category: str
    qualified_name: str
    namespace: str | None
    version: str | None
    source_kind: str
    definition_digest: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodeSymbol": self.node_symbol, "nodeIndex": self.node_index, "jsonPointer": self.json_pointer,
            "category": self.category, "qualifiedName": self.qualified_name, "namespace": self.namespace,
            "version": self.version, "sourceKind": self.source_kind, "definitionDigest": self.definition_digest,
        }


@dataclass(frozen=True, slots=True)
class ParameterSelection:
    node_symbol: str
    node_index: int
    parm_index: int
    json_pointer: str
    authored_token: str
    parameter_token: str
    component_index: int | None
    value_type: str
    conversion: str | None = None
    menu_token: str | None = None
    code_surface: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodeSymbol": self.node_symbol, "nodeIndex": self.node_index, "parmIndex": self.parm_index,
            "jsonPointer": self.json_pointer, "authoredToken": self.authored_token,
            "parameterToken": self.parameter_token, "componentIndex": self.component_index,
            "valueType": self.value_type, "conversion": self.conversion, "menuToken": self.menu_token,
            "codeSurface": self.code_surface,
        }


@dataclass(frozen=True, slots=True)
class ConnectionSelection:
    node_symbol: str
    node_index: int
    input_index: int
    input_name: str | None
    source_symbol: str
    output_index: int
    output_name: str | None
    json_pointer: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodeSymbol": self.node_symbol, "nodeIndex": self.node_index, "inputIndex": self.input_index,
            "inputName": self.input_name, "sourceSymbol": self.source_symbol, "outputIndex": self.output_index,
            "outputName": self.output_name, "jsonPointer": self.json_pointer,
        }


@dataclass(frozen=True, slots=True)
class DeferredCheck:
    kind: str
    json_pointer: str
    symbol: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"kind": self.kind, "jsonPointer": self.json_pointer, "symbol": self.symbol, "message": self.message}


@dataclass(frozen=True, slots=True)
class SemanticResult:
    valid: bool
    ready_for_document_lowering: bool
    catalog_fingerprint: str
    diagnostics: tuple[Diagnostic, ...]
    operator_selections: tuple[OperatorSelection, ...]
    parameter_selections: tuple[ParameterSelection, ...]
    connection_selections: tuple[ConnectionSelection, ...]
    deferred_checks: tuple[DeferredCheck, ...]
    required_capabilities: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": "semantic", "valid": self.valid,
            "readyForDocumentLowering": self.ready_for_document_lowering,
            "catalogFingerprint": self.catalog_fingerprint,
            "diagnostics": [item.to_dict() for item in self.diagnostics],
            "operatorSelections": [item.to_dict() for item in self.operator_selections],
            "parameterSelections": [item.to_dict() for item in self.parameter_selections],
            "connectionSelections": [item.to_dict() for item in self.connection_selections],
            "deferredChecks": [item.to_dict() for item in self.deferred_checks],
            "requiredCapabilities": list(self.required_capabilities),
        }


def resolve_graph(
    graph: GraphSpec,
    catalog_or_provider: CatalogSnapshot | CatalogProvider,
    *,
    constraint: CatalogConstraint | None = None,
    external_bindings: Mapping[str, ExternalNodeBinding] | None = None,
) -> SemanticResult:
    """Resolve a structurally valid graph without consulting Houdini or mutating inputs."""

    catalog = (
        catalog_or_provider
        if isinstance(catalog_or_provider, CatalogSnapshot)
        else catalog_or_provider.get_catalog()
    )
    bindings = external_bindings or {}
    diagnostics: list[Diagnostic] = []
    deferred: list[DeferredCheck] = []
    operator_selections: list[OperatorSelection] = []
    parameter_selections: list[ParameterSelection] = []
    connection_selections: list[ConnectionSelection] = []
    capabilities = {"edit_scene"}
    if any(isinstance(parm.value, CodeValue) for node in graph.nodes for parm in node.parms):
        capabilities.add("run_code")
    category_names = _validate_catalog_constraint(
        graph, catalog, constraint, diagnostics,
    )
    selected = _select_operators(
        graph, catalog, category_names, diagnostics,
        operator_selections, parameter_selections, capabilities,
    )
    _resolve_connections(
        graph, catalog, bindings, selected, diagnostics, deferred,
        connection_selections,
    )
    ordered = tuple(sort_diagnostics(diagnostics))
    valid = not any(item.severity == "error" for item in ordered)
    return SemanticResult(
        valid, valid and not deferred, catalog.fingerprint, ordered, tuple(operator_selections),
        tuple(parameter_selections), tuple(connection_selections), tuple(deferred), tuple(sorted(capabilities)),
    )


def _validate_catalog_constraint(
    graph: GraphSpec,
    catalog: CatalogSnapshot,
    constraint: CatalogConstraint | None,
    diagnostics: list[Diagnostic],
) -> set[str]:
    if constraint is not None and constraint.fingerprint != catalog.fingerprint:
        diagnostics.append(_diagnostic(
            "HOCUS605", "Catalog fingerprint differs from the locked semantic input.", graph.span,
            phase="catalog", pointer="", details={"expected": constraint.fingerprint, "actual": catalog.fingerprint},
        ))
    category_names = {item.name for item in catalog.categories}
    if graph.category is not None and graph.category not in category_names:
        span = graph.field_spans.get("category", graph.span)
        diagnostics.append(_unknown_with_fixes(
            "HOCUS620", f"Unknown catalog category '{graph.category}'.", graph.category,
            sorted(category_names), span, "/category", quote=False,
        ))
    return category_names


def _select_operators(
    graph: GraphSpec,
    catalog: CatalogSnapshot,
    category_names: set[str],
    diagnostics: list[Diagnostic],
    operator_selections: list[OperatorSelection],
    parameter_selections: list[ParameterSelection],
    capabilities: set[str],
) -> dict[str, OperatorDefinition]:
    selected: dict[str, OperatorDefinition] = {}
    for node_index, node in enumerate(graph.nodes):
        if graph.category is not None and graph.category not in category_names:
            continue
        operator = _resolve_operator(node, node_index, graph.category, catalog, diagnostics)
        if operator is None:
            continue
        selected[node.symbol] = operator
        operator_selections.append(_operator_selection(node, node_index, operator))
        _resolve_parameters(node, node_index, operator, diagnostics, parameter_selections, capabilities)
    return selected


def _resolve_connections(
    graph: GraphSpec,
    catalog: CatalogSnapshot,
    bindings: Mapping[str, ExternalNodeBinding],
    selected: dict[str, OperatorDefinition],
    diagnostics: list[Diagnostic],
    deferred: list[DeferredCheck],
    selections: list[ConnectionSelection],
) -> None:
    external_symbols = {item.symbol for item in graph.external_nodes}
    for node_index, node in enumerate(graph.nodes):
        destination = selected.get(node.symbol)
        if destination is None:
            continue
        for input_ordinal, input_spec in enumerate(node.inputs):
            _resolve_connection(
                node, node_index, input_ordinal, input_spec, destination, catalog,
                bindings, external_symbols, selected, diagnostics, deferred, selections,
            )


def _resolve_connection(
    node: NodeSpec,
    node_index: int,
    input_ordinal: int,
    input_spec: Any,
    destination: OperatorDefinition,
    catalog: CatalogSnapshot,
    bindings: Mapping[str, ExternalNodeBinding],
    external_symbols: set[str],
    selected: dict[str, OperatorDefinition],
    diagnostics: list[Diagnostic],
    deferred: list[DeferredCheck],
    selections: list[ConnectionSelection],
) -> None:
    pointer = f"/nodes/{node_index}/inputs/{input_ordinal}"
    input_port = _connector_for_index(destination.inputs, input_spec.index)
    if input_port is None:
        diagnostics.append(_diagnostic(
            "HOCUS640", f"Operator '{destination.qualified_name}' has no input {input_spec.index}.",
            input_spec.field_spans.get("index", input_spec.span), pointer=pointer + "/index",
            details={"availableIndexes": _connector_indexes(destination.inputs)},
        ))
    source_operator = selected.get(input_spec.source.symbol)
    if source_operator is None and input_spec.source.symbol in external_symbols:
        source_operator = _resolve_external_operator(
            input_spec, pointer, catalog, bindings, diagnostics, deferred,
        )
    if source_operator is None:
        return
    output_port = _connector_for_index(source_operator.outputs, input_spec.source.output_index)
    if output_port is None:
        diagnostics.append(_diagnostic(
            "HOCUS641", f"Operator '{source_operator.qualified_name}' has no output {input_spec.source.output_index}.",
            input_spec.source.field_spans.get("outputIndex", input_spec.source.span),
            pointer=pointer + "/source/outputIndex",
            details={"availableIndexes": _connector_indexes(source_operator.outputs)},
        ))
        return
    if input_port is None:
        return
    if not _ports_compatible(source_operator, output_port, destination, input_port):
        diagnostics.append(_diagnostic(
            "HOCUS642", "Source output and destination input catalog types are incompatible.",
            input_spec.span, pointer=pointer, details={
                "sourceOperator": source_operator.qualified_name,
                "sourceTypes": list(output_port.data_types),
                "destinationOperator": destination.qualified_name,
                "destinationTypes": list(input_port.data_types),
            },
        ))
        return
    selections.append(ConnectionSelection(
        node.symbol, node_index, input_spec.index, input_port.name, input_spec.source.symbol,
        input_spec.source.output_index, output_port.name, pointer,
    ))


def _resolve_external_operator(
    input_spec: Any,
    pointer: str,
    catalog: CatalogSnapshot,
    bindings: Mapping[str, ExternalNodeBinding],
    diagnostics: list[Diagnostic],
    deferred: list[DeferredCheck],
) -> OperatorDefinition | None:
    symbol = input_spec.source.symbol
    binding = bindings.get(symbol)
    if binding is None:
        message = f"Output validation for external symbol '{symbol}' requires a live baseline binding."
        deferred.append(DeferredCheck("external_output", pointer + "/source", symbol, message))
        diagnostics.append(Diagnostic(
            "info", "HOCUS643", "semantic", message, input_spec.source.span,
            details={"symbol": symbol}, json_pointer=pointer + "/source",
        ))
        return None
    if binding.catalog_fingerprint != catalog.fingerprint:
        diagnostics.append(_diagnostic(
            "HOCUS605", f"External binding for '{symbol}' uses a different catalog.",
            input_spec.source.span, phase="catalog", pointer=pointer + "/source",
            details={"expected": catalog.fingerprint, "actual": binding.catalog_fingerprint},
        ))
        return None
    matches = [
        item for item in catalog.operators
        if item.qualified_name == binding.operator_qualified_name
        and (binding.category is None or item.category == binding.category)
    ]
    if len(matches) == 1:
        return matches[0]
    diagnostics.append(_diagnostic(
        "HOCUS626",
        f"External binding operator '{binding.operator_qualified_name}' does not identify exactly one catalog definition.",
        input_spec.source.span, pointer=pointer + "/source",
        details={
            "category": binding.category,
            "candidateCategories": sorted(item.category for item in matches),
        },
    ))
    return None


def _resolve_operator(
    node: NodeSpec, node_index: int, category: str | None, catalog: CatalogSnapshot,
    diagnostics: list[Diagnostic],
) -> OperatorDefinition | None:
    selector = node.type_name
    selector_category: str | None = None
    if "/" in selector:
        possible_category, possible_name = selector.split("/", 1)
        if possible_category in {item.name for item in catalog.categories} and possible_name:
            selector_category, selector = possible_category, possible_name
    if category is not None and selector_category is not None and selector_category != category:
        span = node.field_spans.get("typeName", node.span)
        diagnostics.append(_diagnostic(
            "HOCUS625",
            f"Operator selector category '{selector_category}' conflicts with graph category '{category}'.",
            span,
            pointer=f"/nodes/{node_index}/typeName",
            details={"graphCategory": category, "selectorCategory": selector_category},
        ))
        return None
    effective_category = category or selector_category
    candidates = [item for item in catalog.operators if effective_category is None or item.category == effective_category]
    exact = [item for item in candidates if item.qualified_name == selector]
    if len(exact) == 1:
        return exact[0]
    aliases = [item for item in candidates if selector in item.aliases]
    if len(aliases) == 1:
        return aliases[0]
    if "::" not in selector:
        unqualified = [item for item in candidates if item.name == selector]
        if len(unqualified) == 1:
            return unqualified[0]
        if len(unqualified) > 1:
            aliases = unqualified
    if len(aliases) > 1:
        _ambiguous_operator(node, node_index, aliases, diagnostics)
        return None
    span = node.field_spans.get("typeName", node.span)
    pointer = f"/nodes/{node_index}/typeName"
    names = sorted(
        item.qualified_name if effective_category is not None else f"{item.category}/{item.qualified_name}"
        for item in candidates
    )
    code = "HOCUS624" if "::" in selector else "HOCUS622"
    message = (
        f"Exact operator '{node.type_name}' is unavailable; version or namespace fallback is forbidden."
        if code == "HOCUS624" else f"Unknown operator '{node.type_name}'."
    )
    diagnostics.append(_unknown_with_fixes(code, message, node.type_name, names, span, pointer, quote=True))
    return None


def _ambiguous_operator(
    node: NodeSpec, node_index: int, candidates: list[OperatorDefinition], diagnostics: list[Diagnostic],
) -> None:
    cross_category = len({item.category for item in candidates}) > 1
    ordered = sorted({
        f"{item.category}/{item.qualified_name}" if cross_category else item.qualified_name
        for item in candidates
    })
    span = node.field_spans.get("typeName", node.span)
    diagnostics.append(Diagnostic(
        "error", "HOCUS623", "semantic", f"Operator '{node.type_name}' is ambiguous.", span,
        related=[{"message": name} for name in ordered],
        fixes=[_replacement_fix(f"Use {name}", span, json.dumps(name)) for name in ordered[:5]],
        details={"candidates": ordered}, json_pointer=f"/nodes/{node_index}/typeName",
    ))


def _operator_selection(node: NodeSpec, index: int, operator: OperatorDefinition) -> OperatorSelection:
    hda = operator.source.hda_library
    return OperatorSelection(
        node.symbol, index, f"/nodes/{index}/typeName", operator.category, operator.qualified_name,
        operator.namespace, operator.version, operator.source.kind, hda.content_digest if hda else None,
    )


def _resolve_parameters(
    node: NodeSpec, node_index: int, operator: OperatorDefinition, diagnostics: list[Diagnostic],
    selections: list[ParameterSelection], capabilities: set[str],
) -> None:
    roots = {item.token: item for item in operator.parameters}
    components: dict[str, list[tuple[ParameterDefinition, int]]] = {}
    for definition in operator.parameters:
        for index, token in enumerate(definition.tuple_names):
            components.setdefault(token, []).append((definition, index))
    writes: dict[str, set[int] | None] = {}
    for parm_index, parm in enumerate(node.parms):
        pointer = f"/nodes/{node_index}/parms/{parm_index}"
        definition = roots.get(parm.name)
        component_index: int | None = None
        component_candidates = components.get(parm.name, [])
        if definition is not None and component_candidates:
            diagnostics.append(_diagnostic(
                "HOCUS630", f"Parameter token '{parm.name}' collides with a tuple component in the catalog.",
                parm.field_spans.get("name", parm.span), pointer=pointer + "/name",
                details={"rootToken": definition.token,
                         "componentOwners": sorted(item.token for item, _ in component_candidates)},
            ))
            continue
        if definition is None and len(component_candidates) == 1:
            definition, component_index = component_candidates[0]
        elif definition is None and len(component_candidates) > 1:
            diagnostics.append(_diagnostic(
                "HOCUS630", f"Parameter component token '{parm.name}' is ambiguous in the catalog.",
                parm.field_spans.get("name", parm.span), pointer=pointer + "/name",
            ))
            continue
        if definition is None:
            names = sorted(set(roots) | set(components))
            diagnostics.append(_unknown_with_fixes(
                "HOCUS630", f"Unknown parameter token '{parm.name}' on '{operator.qualified_name}'.",
                parm.name, names, parm.field_spans.get("name", parm.span), pointer + "/name", quote=False,
            ))
            continue
        previous = writes.get(definition.token)
        current = None if component_index is None else {component_index}
        if definition.token in writes and (previous is None or current is None or not previous.isdisjoint(current)):
            diagnostics.append(_diagnostic(
                "HOCUS631", f"Parameter write '{parm.name}' overlaps another write to tuple '{definition.token}'.",
                parm.field_spans.get("name", parm.span), pointer=pointer + "/name",
            ))
            continue
        writes[definition.token] = current if previous is None else previous | current  # type: ignore[operator]
        selection = _validate_parameter(parm, node, node_index, parm_index, definition, component_index, pointer, diagnostics)
        if selection is not None:
            selections.append(selection)
            if isinstance(parm.value, CodeValue) or definition.code_surface != "none":
                capabilities.add("run_code")


def _validate_parameter(
    parm: ParmSpec, node: NodeSpec, node_index: int, parm_index: int, definition: ParameterDefinition,
    component_index: int | None, pointer: str, diagnostics: list[Diagnostic],
) -> ParameterSelection | None:
    if not definition.assignable or definition.value_type in {"button", "ramp", "multiparm"}:
        diagnostics.append(_diagnostic(
            "HOCUS632", f"Parameter '{definition.token}' is not an ordinary assignable HocusScript 0.1 value.",
            parm.field_spans.get("name", parm.span), pointer=pointer + "/name",
        ))
        return None
    if definition.value_type == "code":
        return _validate_code_parameter(
            parm, node, node_index, parm_index, definition, component_index, pointer, diagnostics,
        )
    if isinstance(parm.value, CodeValue):
        diagnostics.append(_diagnostic("HOCUS638", f"Parameter '{definition.token}' is not a code surface.", parm.value.span, pointer=pointer + "/value"))
        return None
    if definition.value_type == "menu":
        return _validate_menu_parameter(
            parm, node, node_index, parm_index, definition, component_index, pointer, diagnostics,
        )

    tuple_assignment = component_index is None and definition.tuple_size > 1
    if tuple_assignment:
        return _validate_tuple_parameter(
            parm, node, node_index, parm_index, definition, component_index, pointer, diagnostics,
        )
    return _validate_scalar_parameter(
        parm, node, node_index, parm_index, definition, component_index, pointer, diagnostics,
    )


def _validate_code_parameter(
    parm: ParmSpec,
    node: NodeSpec,
    node_index: int,
    parm_index: int,
    definition: ParameterDefinition,
    component_index: int | None,
    pointer: str,
    diagnostics: list[Diagnostic],
) -> ParameterSelection | None:
    if not isinstance(parm.value, CodeValue):
        diagnostics.append(_diagnostic(
            "HOCUS638",
            f"Code parameter '{definition.token}' requires tagged code.",
            parm.value.span,
            pointer=pointer + "/value",
        ))
        return None
    if definition.code_surface == "none" or parm.value.language != definition.code_surface:
        diagnostics.append(_diagnostic(
            "HOCUS639",
            f"Code language '{parm.value.language}' is not valid for the '{definition.code_surface}' surface.",
            parm.value.span,
            pointer=pointer + "/value",
            details={"actual": parm.value.language, "expected": definition.code_surface},
        ))
        return None
    return _parm_selection(
        node, node_index, parm_index, parm, definition, component_index, pointer,
        code_surface=definition.code_surface,
    )


def _validate_menu_parameter(
    parm: ParmSpec,
    node: NodeSpec,
    node_index: int,
    parm_index: int,
    definition: ParameterDefinition,
    component_index: int | None,
    pointer: str,
    diagnostics: list[Diagnostic],
) -> ParameterSelection | None:
    if definition.tuple_size != 1:
        diagnostics.append(_diagnostic(
            "HOCUS632",
            f"Tuple menu parameter '{definition.token}' is unsupported in HocusScript 0.1.",
            parm.span,
            pointer=pointer,
            details={"tupleSize": definition.tuple_size},
        ))
        return None
    raw = _literal(parm.value)
    if not isinstance(raw, str):
        diagnostics.append(_type_error(definition, parm, pointer, "a stable string menu token"))
        return None
    tokens = [item.token for item in definition.menu]
    if raw not in tokens:
        _append_invalid_menu_diagnostic(parm, definition, pointer, raw, tokens, diagnostics)
        return None
    return _parm_selection(
        node, node_index, parm_index, parm, definition, component_index, pointer,
        menu_token=raw,
    )


def _append_invalid_menu_diagnostic(
    parm: ParmSpec,
    definition: ParameterDefinition,
    pointer: str,
    raw: str,
    tokens: list[str],
    diagnostics: list[Diagnostic],
) -> None:
    labels = {item.label: item.token for item in definition.menu}
    if raw in labels:
        token = labels[raw]
        diagnostics.append(Diagnostic(
            "error",
            "HOCUS636",
            "semantic",
            f"Menu label '{raw}' is not stable; use token '{token}'.",
            parm.value.span,
            fixes=[_replacement_fix(
                f"Use menu token {token}", parm.value.span, json.dumps(token),
            )],
            details={"label": raw, "token": token},
            json_pointer=pointer + "/value",
        ))
        return
    diagnostics.append(_unknown_with_fixes(
        "HOCUS635",
        f"Unknown menu token '{raw}' for '{definition.token}'.",
        raw,
        tokens,
        parm.value.span,
        pointer + "/value",
        quote=True,
    ))


def _validate_tuple_parameter(
    parm: ParmSpec,
    node: NodeSpec,
    node_index: int,
    parm_index: int,
    definition: ParameterDefinition,
    component_index: int | None,
    pointer: str,
    diagnostics: list[Diagnostic],
) -> ParameterSelection | None:
    if not isinstance(parm.value, ArrayValue) or len(parm.value.items) != definition.tuple_size:
        diagnostics.append(_diagnostic(
            "HOCUS634",
            f"Parameter '{definition.token}' requires a {definition.tuple_size}-element tuple.",
            parm.value.span,
            pointer=pointer + "/value",
            details={"tupleSize": definition.tuple_size},
        ))
        return None
    conversions: list[str] = []
    for item in parm.value.items:
        conversion = _scalar_conversion(item, _element_type(definition))
        if conversion is False:
            diagnostics.append(_type_error(
                definition, parm, pointer, f"a tuple of {_element_type(definition)} values",
            ))
            return None
        if isinstance(conversion, str):
            conversions.append(conversion)
    if not _range_valid(definition, [_literal(item) for item in parm.value.items]):
        diagnostics.append(_range_error(definition, parm, pointer))
        return None
    return _parm_selection(
        node, node_index, parm_index, parm, definition, component_index, pointer,
        conversion="int_to_float" if conversions else None,
    )


def _validate_scalar_parameter(
    parm: ParmSpec,
    node: NodeSpec,
    node_index: int,
    parm_index: int,
    definition: ParameterDefinition,
    component_index: int | None,
    pointer: str,
    diagnostics: list[Diagnostic],
) -> ParameterSelection | None:
    if isinstance(parm.value, ArrayValue):
        diagnostics.append(_type_error(
            definition, parm, pointer, f"a scalar {_element_type(definition)} value",
        ))
        return None
    conversion = _scalar_conversion(parm.value, _element_type(definition))
    if conversion is False:
        diagnostics.append(_type_error(
            definition, parm, pointer, f"a scalar {_element_type(definition)} value",
        ))
        return None
    if not _range_valid(definition, [_literal(parm.value)]):
        diagnostics.append(_range_error(definition, parm, pointer))
        return None
    return _parm_selection(
        node, node_index, parm_index, parm, definition, component_index, pointer,
        conversion=conversion if isinstance(conversion, str) else None,
    )


def _parm_selection(
    node: NodeSpec, node_index: int, parm_index: int, parm: ParmSpec, definition: ParameterDefinition,
    component_index: int | None, pointer: str, *, conversion: str | None = None,
    menu_token: str | None = None, code_surface: str | None = None,
) -> ParameterSelection:
    return ParameterSelection(node.symbol, node_index, parm_index, pointer, parm.name, definition.token,
                              component_index, definition.value_type, conversion, menu_token, code_surface)


def _element_type(definition: ParameterDefinition) -> str:
    if definition.value_type != "tuple":
        return definition.value_type
    tagged = definition.tags.get("elementType")
    if tagged in {"bool", "int", "float", "string"}:
        return tagged
    default = definition.default
    if isinstance(default, tuple) and default:
        value = default[0]
        if isinstance(value, bool): return "bool"
        if isinstance(value, int): return "int"
        if isinstance(value, float): return "float"
        if isinstance(value, str): return "string"
    return "unknown"


def _scalar_conversion(value: Any, expected: str) -> bool | str:
    raw = _literal(value)
    if raw is _NOT_LITERAL:
        return False
    if expected == "bool": return isinstance(raw, bool)
    if expected == "int": return isinstance(raw, int) and not isinstance(raw, bool)
    if expected == "float":
        if isinstance(raw, bool) or not isinstance(raw, (int, float)): return False
        return "int_to_float" if isinstance(raw, int) else True
    if expected in {"string", "node_path", "parm_path", "file_path", "usd_prim_path", "asset_reference"}:
        return isinstance(raw, str)
    return False


_NOT_LITERAL = object()


def _literal(value: Any) -> Any:
    return value.value if isinstance(value, LiteralValue) else _NOT_LITERAL


def _range_valid(definition: ParameterDefinition, values: list[Any]) -> bool:
    constraint = definition.range
    if constraint is None:
        return True
    for value in values:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        if constraint.minimum is not None and (value < constraint.minimum or (value == constraint.minimum and not constraint.minimum_inclusive)):
            return False
        if constraint.maximum is not None and (value > constraint.maximum or (value == constraint.maximum and not constraint.maximum_inclusive)):
            return False
    return True


def _range_error(definition: ParameterDefinition, parm: ParmSpec, pointer: str) -> Diagnostic:
    assert definition.range is not None
    return _diagnostic("HOCUS637", f"Value for '{definition.token}' is outside its hard catalog range.",
                       parm.value.span, pointer=pointer + "/value", details=definition.range.to_dict())


def _type_error(definition: ParameterDefinition, parm: ParmSpec, pointer: str, expected: str) -> Diagnostic:
    return _diagnostic("HOCUS633", f"Parameter '{definition.token}' requires {expected}.", parm.value.span,
                       pointer=pointer + "/value", details={"expectedType": definition.value_type})


def _connector_for_index(connectors: tuple[ConnectorDefinition, ...], index: int) -> ConnectorDefinition | None:
    for connector in connectors:
        if connector.index == index:
            return connector
    variadic = [item for item in connectors if item.index is not None and item.index <= index and item.cardinality == "many"]
    if variadic:
        return max(variadic, key=lambda item: item.index or 0)
    return next(
        (item for item in connectors if item.index is None and item.cardinality == "many"),
        None,
    )


def _connector_indexes(connectors: tuple[ConnectorDefinition, ...]) -> list[int]:
    return sorted(item.index for item in connectors if item.index is not None)


def _ports_compatible(
    source_operator: OperatorDefinition, output: ConnectorDefinition,
    destination_operator: OperatorDefinition, destination: ConnectorDefinition,
) -> bool:
    if output.data_types and destination.data_types and not set(output.data_types).intersection(destination.data_types):
        return False
    if destination.categories and source_operator.category not in destination.categories:
        return False
    if output.categories and destination_operator.category not in output.categories:
        return False
    return True


def _unknown_with_fixes(
    code: str, message: str, authored: str, candidates: list[str], span: SourceSpan,
    pointer: str, *, quote: bool,
) -> Diagnostic:
    suggestions = _suggest(authored, candidates)
    fixes = []
    for candidate in suggestions:
        if quote or _IDENTIFIER.fullmatch(candidate):
            fixes.append(_replacement_fix(f"Replace with {candidate}", span, json.dumps(candidate) if quote else candidate))
    return Diagnostic("error", code, "semantic", message, span, fixes=fixes,
                      details={"authored": authored, "suggestions": suggestions}, json_pointer=pointer)


def _replacement_fix(title: str, span: SourceSpan, replacement: str) -> dict[str, Any]:
    serialized = span.to_dict()
    return {"title": title, "kind": "replace", "edits": [{
        "sourceUri": span.source_name,
        "span": {"start": serialized["start"], "end": serialized["end"]},
        "newText": replacement,
    }]}


def _suggest(authored: str, candidates: list[str], limit: int = 5) -> list[str]:
    if not authored or len(authored) > 256:
        return []
    normalized = authored.casefold()
    threshold = 1 if len(normalized) <= 4 else 2 if len(normalized) <= 12 else 3
    shortlist: list[tuple[int, int, int, str]] = []
    for candidate in set(candidates):
        if not candidate or len(candidate) > 256:
            continue
        current = candidate.casefold()
        case_match = current == normalized
        prefix_match = current.startswith(normalized) or normalized.startswith(current)
        if not case_match and abs(len(current) - len(normalized)) > threshold:
            continue
        if not case_match and not prefix_match and current[:1] != normalized[:1]:
            continue
        distance = _edit_distance_bounded(normalized, current, threshold)
        if distance is None:
            continue
        shortlist.append((0 if case_match else 1, 0 if prefix_match else 1, distance, candidate))
        if len(shortlist) > 512:
            shortlist = sorted(shortlist)[:256]
    return [item[3] for item in sorted(shortlist)[:limit]]


def _edit_distance_bounded(left: str, right: str, maximum: int) -> int | None:
    if abs(len(left) - len(right)) > maximum:
        return None
    previous = list(range(len(right) + 1))
    for left_index, left_char in enumerate(left, 1):
        current = [left_index]
        for right_index, right_char in enumerate(right, 1):
            current.append(min(current[-1] + 1, previous[right_index] + 1,
                               previous[right_index - 1] + (left_char != right_char)))
        if min(current) > maximum:
            return None
        previous = current
    return previous[-1] if previous[-1] <= maximum else None


def _diagnostic(
    code: str, message: str, span: SourceSpan, *, phase: str = "semantic", pointer: str,
    details: dict[str, Any] | None = None,
) -> Diagnostic:
    return Diagnostic("error", code, phase, message, span, details=details or {}, json_pointer=pointer)

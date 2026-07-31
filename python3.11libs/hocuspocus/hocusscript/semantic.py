"""Pure catalog-backed semantic resolution for HocusScript GraphSpec v0.1."""

from __future__ import annotations

import json
import re
from bisect import insort
from dataclasses import dataclass, replace
from typing import Any, Callable, Mapping

from .catalog import (
    VALUE_CATALOG_VERSION,
    CatalogProvider,
    CatalogSnapshot,
    ConnectorDefinition,
    OperatorDefinition,
    ParameterDefinition,
)
from .diagnostics import Diagnostic, SourceSpan, sort_diagnostics
from .model import (
    ArrayValue, CodeValue, GraphSpec, LiteralValue, NodeSpec, ParmSpec,
    TaggedValue,
)
from .value_catalog_semantics import (
    TypedValueSemanticError,
    invalid_channel_targets,
    typed_value_adapter,
)
from .port_selectors import (
    connector_evidence_name,
    connector_for_index,
    connector_indexes,
    fixed_named_connector,
    resolved_connector_index,
)
from .runtime_semantic import append_runtime_semantics
from .semantic_carrier import semantic_result_dict

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
    instance_network: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "nodeSymbol": self.node_symbol, "nodeIndex": self.node_index, "jsonPointer": self.json_pointer,
            "category": self.category, "qualifiedName": self.qualified_name, "namespace": self.namespace,
            "version": self.version, "sourceKind": self.source_kind, "definitionDigest": self.definition_digest,
        }
        if self.instance_network is not None:
            payload["instanceNetwork"] = self.instance_network
        return payload


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
    component_tokens: tuple[str, ...] | None = None
    tuple_size: int | None = None
    element_type: str | None = None
    value_adapter: Mapping[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "nodeSymbol": self.node_symbol, "nodeIndex": self.node_index, "parmIndex": self.parm_index,
            "jsonPointer": self.json_pointer, "authoredToken": self.authored_token,
            "parameterToken": self.parameter_token, "componentIndex": self.component_index,
            "valueType": self.value_type, "conversion": self.conversion, "menuToken": self.menu_token,
            "codeSurface": self.code_surface,
        }
        if self.component_tokens is not None:
            payload.update({
                "componentTokens": list(self.component_tokens),
                "tupleSize": self.tuple_size,
                "elementType": self.element_type,
            })
        if self.value_adapter is not None:
            payload["valueAdapter"] = dict(self.value_adapter)
        return payload


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
    runtime_selections: tuple[Mapping[str, Any], ...] | None
    required_capabilities: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return semantic_result_dict(self)


@dataclass(frozen=True, slots=True)
class _ConnectionResolutionState:
    catalog: CatalogSnapshot
    bindings: Mapping[str, ExternalNodeBinding]
    external_symbols: set[str]
    selected: dict[str, OperatorDefinition]
    diagnostics: list[Diagnostic]
    deferred: list[DeferredCheck]
    selections: list[ConnectionSelection]
    checkpoint: Callable[[], None] | None


def resolve_graph(
    graph: GraphSpec,
    catalog_or_provider: CatalogSnapshot | CatalogProvider,
    *,
    constraint: CatalogConstraint | None = None,
    external_bindings: Mapping[str, ExternalNodeBinding] | None = None,
    checkpoint: Callable[[], None] | None = None,
) -> SemanticResult:
    """Resolve a structurally valid graph without consulting Houdini or mutating inputs."""

    if checkpoint is not None:
        checkpoint()
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
    for node_index, node in enumerate(graph.nodes):
        _periodic_checkpoint(checkpoint, node_index)
        for parm_index, parm in enumerate(node.parms):
            _periodic_checkpoint(checkpoint, parm_index)
            if isinstance(parm.value, CodeValue):
                capabilities.add("run_code")
    category_names = _validate_catalog_constraint(
        graph, catalog, constraint, diagnostics, checkpoint,
    )
    selected = _select_operators(
        graph, catalog, category_names, diagnostics,
        operator_selections, parameter_selections, capabilities, checkpoint,
    )
    _validate_channel_targets(graph, selected, diagnostics, checkpoint)
    _resolve_connections(
        graph, catalog, bindings, selected, diagnostics, deferred,
        connection_selections, checkpoint,
    )
    runtime_selections = append_runtime_semantics(
        graph, selected, parameter_selections, diagnostics, _diagnostic,
    )
    if checkpoint is not None:
        checkpoint()
    ordered = tuple(sort_diagnostics(diagnostics))
    valid = not any(item.severity == "error" for item in ordered)
    return SemanticResult(
        valid, valid and not deferred, catalog.fingerprint, ordered, tuple(operator_selections),
        tuple(parameter_selections), tuple(connection_selections), tuple(deferred),
        (
            tuple(runtime_selections)
            if graph.graph_spec_version == "0.5" else None
        ),
        tuple(sorted(capabilities)),
    )


def _validate_channel_targets(
    graph: GraphSpec,
    selected: Mapping[str, OperatorDefinition],
    diagnostics: list[Diagnostic],
    checkpoint: Callable[[], None] | None,
) -> None:
    if graph.graph_spec_version != "0.5":
        return
    if checkpoint is not None:
        checkpoint()
    for reference, pointer in invalid_channel_targets(graph, selected):
        diagnostics.append(_diagnostic(
            "HOCUS932",
            "Structural channel reference does not identify one exact catalog parameter.",
            reference.span,
            pointer=pointer,
            details={
                "nodeSymbol": reference.payload["nodeSymbol"],
                "parmName": reference.payload["parmName"],
            },
        ))


def _validate_catalog_constraint(
    graph: GraphSpec,
    catalog: CatalogSnapshot,
    constraint: CatalogConstraint | None,
    diagnostics: list[Diagnostic],
    checkpoint: Callable[[], None] | None,
) -> set[str]:
    if constraint is not None and constraint.fingerprint != catalog.fingerprint:
        diagnostics.append(_diagnostic(
            "HOCUS605", "Catalog fingerprint differs from the locked semantic input.", graph.span,
            phase="catalog", pointer="", details={"expected": constraint.fingerprint, "actual": catalog.fingerprint},
        ))
    if (
        graph.graph_spec_version == "0.5"
        and catalog.catalog_version != VALUE_CATALOG_VERSION
    ):
        diagnostics.append(_diagnostic(
            "HOCUS932",
            "GraphSpec 0.5 typed values require an exact catalog v2 snapshot.",
            graph.span,
            phase="catalog",
            pointer="",
            details={"actual": catalog.catalog_version, "expected": 2},
        ))
    category_names = _catalog_category_names(catalog, checkpoint)
    if graph.category is not None and graph.category not in category_names:
        span = graph.field_spans.get("category", graph.span)
        diagnostics.append(_unknown_with_fixes(
            "HOCUS620", f"Unknown catalog category '{graph.category}'.", graph.category,
            sorted(category_names), span, "/category", quote=False,
            checkpoint=checkpoint,
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
    checkpoint: Callable[[], None] | None,
) -> dict[str, OperatorDefinition]:
    selected: dict[str, OperatorDefinition] = {}
    for node_index, node in enumerate(graph.nodes):
        _periodic_checkpoint(checkpoint, node_index)
        if graph.category is not None and graph.category not in category_names:
            continue
        operator = _resolve_operator(
            node, node_index, graph.category, catalog, diagnostics, checkpoint,
        )
        if operator is None:
            continue
        selected[node.symbol] = operator
        operator_selections.append(_operator_selection(
            node, node_index, operator,
            rich_values=graph.graph_spec_version == "0.5",
        ))
        _resolve_parameters(
            node, node_index, operator, diagnostics, parameter_selections,
            capabilities, checkpoint, rich_values=graph.language_version == "0.4",
        )
    return selected


def _resolve_connections(
    graph: GraphSpec,
    catalog: CatalogSnapshot,
    bindings: Mapping[str, ExternalNodeBinding],
    selected: dict[str, OperatorDefinition],
    diagnostics: list[Diagnostic],
    deferred: list[DeferredCheck],
    selections: list[ConnectionSelection],
    checkpoint: Callable[[], None] | None,
) -> None:
    external_symbols = {item.symbol for item in graph.external_nodes}
    state = _ConnectionResolutionState(
        catalog, bindings, external_symbols, selected, diagnostics, deferred,
        selections, checkpoint,
    )
    for node_index, node in enumerate(graph.nodes):
        _periodic_checkpoint(checkpoint, node_index)
        destination = selected.get(node.symbol)
        if destination is None:
            continue
        claimed_inputs: set[int] = set()
        for input_ordinal, input_spec in enumerate(node.inputs):
            _periodic_checkpoint(checkpoint, input_ordinal)
            _resolve_connection(
                node, node_index, input_ordinal, input_spec, destination, state,
                claimed_inputs,
            )


def _resolve_connection(
    node: NodeSpec,
    node_index: int,
    input_ordinal: int,
    input_spec: Any,
    destination: OperatorDefinition,
    state: _ConnectionResolutionState,
    claimed_inputs: set[int],
) -> None:
    pointer = f"/nodes/{node_index}/inputs/{input_ordinal}"
    input_port = (
        fixed_named_connector(destination.inputs, input_spec.name)
        if input_spec.name is not None
        else connector_for_index(destination.inputs, input_spec.index)
    )
    if input_port is None:
        selector = input_spec.name if input_spec.name is not None else input_spec.index
        field = "name" if input_spec.name is not None else "index"
        state.diagnostics.append(_diagnostic(
            "HOCUS640", f"Operator '{destination.qualified_name}' has no fixed input {selector!r}.",
            input_spec.field_spans.get(field, input_spec.span), pointer=f"{pointer}/{field}",
            details={"availableIndexes": connector_indexes(destination.inputs)},
        ))
    source_operator = state.selected.get(input_spec.source.symbol)
    if source_operator is None and input_spec.source.symbol in state.external_symbols:
        source_operator = _resolve_external_operator(
            input_spec, pointer, state,
        )
    if source_operator is None:
        return
    output_port = (
        fixed_named_connector(source_operator.outputs, input_spec.source.output_name)
        if input_spec.source.output_name is not None
        else connector_for_index(source_operator.outputs, input_spec.source.output_index)
    )
    if output_port is None:
        selector = (
            input_spec.source.output_name
            if input_spec.source.output_name is not None
            else input_spec.source.output_index
        )
        field = "outputName" if input_spec.source.output_name is not None else "outputIndex"
        state.diagnostics.append(_diagnostic(
            "HOCUS641", f"Operator '{source_operator.qualified_name}' has no fixed output {selector!r}.",
            input_spec.source.field_spans.get(field, input_spec.source.span),
            pointer=f"{pointer}/source/{field}",
            details={"availableIndexes": connector_indexes(source_operator.outputs)},
        ))
        return
    if input_port is None:
        return
    resolved_input = resolved_connector_index(input_spec.index, input_port)
    resolved_output = resolved_connector_index(
        input_spec.source.output_index, output_port)
    if resolved_input in claimed_inputs:
        state.diagnostics.append(_diagnostic(
            "HOCUS640", "Multiple authored selectors resolve to the same destination input.",
            input_spec.span, pointer=pointer, details={"resolvedIndex": resolved_input},
        ))
        return
    if not _ports_compatible(source_operator, output_port, destination, input_port):
        state.diagnostics.append(_diagnostic(
            "HOCUS642", "Source output and destination input catalog types are incompatible.",
            input_spec.span, pointer=pointer, details={
                "sourceOperator": source_operator.qualified_name,
                "sourceTypes": list(output_port.data_types),
                "destinationOperator": destination.qualified_name,
                "destinationTypes": list(input_port.data_types),
            },
        ))
        return
    state.selections.append(ConnectionSelection(
        node.symbol,
        node_index,
        resolved_input,
        connector_evidence_name(input_port, resolved_input),
        input_spec.source.symbol,
        resolved_output,
        connector_evidence_name(output_port, resolved_output),
        pointer,
    ))
    claimed_inputs.add(resolved_input)


def _resolve_external_operator(
    input_spec: Any,
    pointer: str,
    state: _ConnectionResolutionState,
) -> OperatorDefinition | None:
    symbol = input_spec.source.symbol
    binding = state.bindings.get(symbol)
    if binding is None:
        message = f"Output validation for external symbol '{symbol}' requires a live baseline binding."
        state.deferred.append(DeferredCheck("external_output", pointer + "/source", symbol, message))
        state.diagnostics.append(Diagnostic(
            "info", "HOCUS643", "semantic", message, input_spec.source.span,
            details={"symbol": symbol}, json_pointer=pointer + "/source",
        ))
        return None
    if binding.catalog_fingerprint != state.catalog.fingerprint:
        state.diagnostics.append(_diagnostic(
            "HOCUS605", f"External binding for '{symbol}' uses a different catalog.",
            input_spec.source.span, phase="catalog", pointer=pointer + "/source",
            details={"expected": state.catalog.fingerprint, "actual": binding.catalog_fingerprint},
        ))
        return None
    matches = []
    for index, item in enumerate(state.catalog.operators):
        _periodic_checkpoint(state.checkpoint, index)
        if (
            item.qualified_name == binding.operator_qualified_name
            and (binding.category is None or item.category == binding.category)
        ):
            matches.append(item)
    if len(matches) == 1:
        return matches[0]
    state.diagnostics.append(_diagnostic(
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
    diagnostics: list[Diagnostic], checkpoint: Callable[[], None] | None = None,
) -> OperatorDefinition | None:
    selector = node.type_name
    selector_category: str | None = None
    if "/" in selector:
        possible_category, possible_name = selector.split("/", 1)
        if possible_category in _catalog_category_names(catalog, checkpoint) and possible_name:
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
    candidates, exact, aliases, unqualified = _operator_matches(
        catalog, effective_category, selector, checkpoint,
    )
    if len(exact) == 1:
        return exact[0]
    if len(aliases) == 1:
        return aliases[0]
    if "::" not in selector:
        if len(unqualified) == 1:
            return unqualified[0]
        if len(unqualified) > 1:
            aliases = unqualified
    if len(aliases) > 1:
        _ambiguous_operator(
            node, node_index, aliases, diagnostics, checkpoint=checkpoint,
        )
        return None
    span = node.field_spans.get("typeName", node.span)
    pointer = f"/nodes/{node_index}/typeName"
    names = _operator_candidate_names(candidates, effective_category, checkpoint)
    code = "HOCUS624" if "::" in selector else "HOCUS622"
    message = (
        f"Exact operator '{node.type_name}' is unavailable; version or namespace fallback is forbidden."
        if code == "HOCUS624" else f"Unknown operator '{node.type_name}'."
    )
    diagnostics.append(_unknown_with_fixes(
        code, message, node.type_name, names, span, pointer,
        quote=True, checkpoint=checkpoint,
    ))
    return None


def _catalog_category_names(
    catalog: CatalogSnapshot,
    checkpoint: Callable[[], None] | None,
) -> set[str]:
    names: set[str] = set()
    for index, category in enumerate(catalog.categories):
        _periodic_checkpoint(checkpoint, index)
        names.add(category.name)
    return names


def _operator_matches(
    catalog: CatalogSnapshot,
    effective_category: str | None,
    selector: str,
    checkpoint: Callable[[], None] | None,
) -> tuple[
    list[OperatorDefinition],
    list[OperatorDefinition],
    list[OperatorDefinition],
    list[OperatorDefinition],
]:
    candidates, exact, aliases, unqualified = [], [], [], []
    for index, operator in enumerate(catalog.operators):
        _periodic_checkpoint(checkpoint, index)
        if effective_category is not None and operator.category != effective_category:
            continue
        candidates.append(operator)
        if operator.qualified_name == selector:
            exact.append(operator)
        if selector in operator.aliases:
            aliases.append(operator)
        if "::" not in selector and operator.name == selector:
            unqualified.append(operator)
    return candidates, exact, aliases, unqualified


def _operator_candidate_names(
    candidates: list[OperatorDefinition],
    effective_category: str | None,
    checkpoint: Callable[[], None] | None,
) -> list[str]:
    names: list[str] = []
    for index, operator in enumerate(candidates):
        _periodic_checkpoint(checkpoint, index)
        names.append(
            operator.qualified_name
            if effective_category is not None
            else f"{operator.category}/{operator.qualified_name}"
        )
    return sorted(names)


def _ambiguous_operator(
    node: NodeSpec,
    node_index: int,
    candidates: list[OperatorDefinition],
    diagnostics: list[Diagnostic],
    *,
    checkpoint: Callable[[], None] | None = None,
) -> None:
    span = node.field_spans.get("typeName", node.span)
    if checkpoint is None:
        cross_category = len({item.category for item in candidates}) > 1
        ordered = sorted({
            f"{item.category}/{item.qualified_name}"
            if cross_category
            else item.qualified_name
            for item in candidates
        })
        details = {"candidates": ordered}
    else:
        ordered, candidate_count = _bounded_ambiguous_names(candidates, checkpoint)
        details = {
            "candidateCount": candidate_count,
            "candidates": ordered,
            "truncated": candidate_count > len(ordered),
        }
    diagnostics.append(Diagnostic(
        "error", "HOCUS623", "semantic", f"Operator '{node.type_name}' is ambiguous.", span,
        related=[{"message": name} for name in ordered],
        fixes=[_replacement_fix(f"Use {name}", span, json.dumps(name)) for name in ordered[:5]],
        details=details,
        json_pointer=f"/nodes/{node_index}/typeName",
    ))


def _bounded_ambiguous_names(
    candidates: list[OperatorDefinition],
    checkpoint: Callable[[], None] | None,
    *,
    limit: int = 256,
) -> tuple[list[str], int]:
    identities: set[tuple[str, str]] = set()
    categories: set[str] = set()
    for index, operator in enumerate(candidates):
        _periodic_checkpoint(checkpoint, index)
        identities.add((operator.category, operator.qualified_name))
        categories.add(operator.category)
    cross_category = len(categories) > 1
    ordered: list[str] = []
    for index, (category, name) in enumerate(identities):
        _periodic_checkpoint(checkpoint, index)
        rendered = f"{category}/{name}" if cross_category else name
        insort(ordered, rendered)
        if len(ordered) > limit:
            ordered.pop()
    return ordered, len(identities)


def _operator_selection(
    node: NodeSpec, index: int, operator: OperatorDefinition, *,
    rich_values: bool,
) -> OperatorSelection:
    hda = operator.source.hda_library
    return OperatorSelection(
        node.symbol, index, f"/nodes/{index}/typeName", operator.category, operator.qualified_name,
        operator.namespace, operator.version, operator.source.kind, hda.content_digest if hda else None,
        operator.instance_network if rich_values else None,
    )


def _resolve_parameters(
    node: NodeSpec, node_index: int, operator: OperatorDefinition, diagnostics: list[Diagnostic],
    selections: list[ParameterSelection], capabilities: set[str],
    checkpoint: Callable[[], None] | None, *, rich_values: bool = False,
) -> None:
    complete_tokens = [
        token
        for parameter in operator.parameters
        for token in (parameter.token, *parameter.tuple_names)
    ]
    tuple_namespace_unambiguous = len(complete_tokens) == len(set(complete_tokens))
    roots: dict[str, ParameterDefinition] = {}
    components: dict[str, list[tuple[ParameterDefinition, int]]] = {}
    for definition_index, definition in enumerate(operator.parameters):
        _periodic_checkpoint(checkpoint, definition_index)
        roots[definition.token] = definition
        for index, token in enumerate(definition.tuple_names):
            _periodic_checkpoint(checkpoint, index)
            components.setdefault(token, []).append((definition, index))
    writes: dict[str, set[int] | None] = {}
    for parm_index, parm in enumerate(node.parms):
        _periodic_checkpoint(checkpoint, parm_index)
        pointer = f"/nodes/{node_index}/parms/{parm_index}"
        definition = roots.get(parm.name)
        component_index: int | None = None
        component_candidates = components.get(parm.name, [])
        whole_tuple = (
            rich_values
            and definition is not None
            and definition.tuple_size > 1
            and isinstance(parm.value, ArrayValue)
        )
        if definition is not None and component_candidates and not whole_tuple:
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
                checkpoint=checkpoint,
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
            selection = _attach_tuple_evidence(
                selection,
                parm,
                definition,
                component_index,
                pointer,
                diagnostics,
                rich_values=rich_values,
                namespace_unambiguous=tuple_namespace_unambiguous,
            )
            if selection is None:
                continue
            selections.append(selection)
            if isinstance(parm.value, CodeValue) or definition.code_surface != "none":
                capabilities.add("run_code")


def _attach_tuple_evidence(
    selection: ParameterSelection,
    parm: ParmSpec,
    definition: ParameterDefinition,
    component_index: int | None,
    pointer: str,
    diagnostics: list[Diagnostic],
    *,
    rich_values: bool,
    namespace_unambiguous: bool,
) -> ParameterSelection | None:
    if not (
        rich_values
        and component_index is None
        and definition.tuple_size > 1
        and isinstance(parm.value, ArrayValue)
    ):
        return selection
    element_type = _explicit_tuple_element_type(definition)
    if (
        len(definition.tuple_names) != definition.tuple_size
        or len(set(definition.tuple_names)) != definition.tuple_size
        or not namespace_unambiguous
        or element_type not in {"bool", "int", "float", "string"}
        or not _tuple_default_matches(
            definition.default,
            element_type,
            definition.tuple_size,
        )
    ):
        diagnostics.append(_diagnostic(
            "HOCUS931",
            f"Tuple parameter '{definition.token}' lacks an exact component-token map.",
            parm.span,
            pointer=pointer,
        ))
        return None
    return replace(
        selection,
        component_tokens=definition.tuple_names,
        tuple_size=definition.tuple_size,
        element_type=element_type,
    )


def _validate_parameter(
    parm: ParmSpec, node: NodeSpec, node_index: int, parm_index: int, definition: ParameterDefinition,
    component_index: int | None, pointer: str, diagnostics: list[Diagnostic],
) -> ParameterSelection | None:
    if isinstance(parm.value, TaggedValue):
        try:
            adapter = typed_value_adapter(
                parm.value, definition, component_index
            )
        except TypedValueSemanticError as exc:
            diagnostics.append(_diagnostic(
                "HOCUS932",
                str(exc),
                parm.value.span,
                pointer=pointer + "/value",
            ))
            return None
        return _parm_selection(
            node, node_index, parm_index, parm, definition, component_index,
            pointer, value_adapter=adapter,
        )
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
    value_adapter: Mapping[str, Any] | None = None,
) -> ParameterSelection:
    return ParameterSelection(node.symbol, node_index, parm_index, pointer, parm.name, definition.token,
                              component_index, definition.value_type, conversion, menu_token, code_surface,
                              value_adapter=value_adapter)


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


def _explicit_tuple_element_type(definition: ParameterDefinition) -> str | None:
    tagged = definition.tags.get("elementType")
    return tagged if tagged in {"bool", "int", "float", "string"} else None


def _tuple_default_matches(
    value: Any,
    element_type: str | None,
    tuple_size: int,
) -> bool:
    if not isinstance(value, tuple) or len(value) != tuple_size:
        return False
    expected = {
        "bool": bool,
        "int": int,
        "float": float,
        "string": str,
    }.get(element_type)
    if expected is None:
        return False
    return all(type(item) is expected for item in value)


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
    pointer: str, *, quote: bool, checkpoint: Callable[[], None] | None = None,
) -> Diagnostic:
    suggestions = _suggest(authored, candidates, checkpoint=checkpoint)
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


def _suggest(
    authored: str,
    candidates: list[str],
    limit: int = 5,
    *,
    checkpoint: Callable[[], None] | None = None,
) -> list[str]:
    if not authored or len(authored) > 256:
        return []
    normalized = authored.casefold()
    threshold = 1 if len(normalized) <= 4 else 2 if len(normalized) <= 12 else 3
    shortlist: list[tuple[int, int, int, str]] = []
    seen: set[str] = set()
    for index, candidate in enumerate(candidates):
        _periodic_checkpoint(checkpoint, index)
        if candidate in seen:
            continue
        seen.add(candidate)
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


def _periodic_checkpoint(
    checkpoint: Callable[[], None] | None,
    index: int,
) -> None:
    if checkpoint is not None and index % 64 == 0:
        checkpoint()


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

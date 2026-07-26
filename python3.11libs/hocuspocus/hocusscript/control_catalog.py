"""Pinned whole-program catalog admission for HocusScript 0.3 controls."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from .catalog import CatalogSnapshot, OperatorDefinition, ParameterDefinition
from .control_semantic import (
    ControlExpansionLimits,
    validate_control_program,
)
from .control_expander import _snapshot_program_inputs
from .diagnostics import Diagnostic, SourceSpan
from .expander import ModuleExpansionError, ResolvedModuleUnit, _check_cancel
from .model import ArrayValue, CodeValue, LiteralValue, NodeSpec, ParmSpec
from .semantic import _element_type, _resolve_operator, _validate_parameter
from .syntax import (
    ArrayExpr,
    CategoryStmt,
    CodeExpr,
    ForDecl,
    IfDecl,
    LiteralExpr,
    NodeDecl,
    ParamRefExpr,
    ParmStmt,
    SymbolRefExpr,
    SyntaxSource,
)


@dataclass(frozen=True, slots=True)
class ControlCatalogDiagnostic:
    """One immutable catalog diagnostic anchored to authored source."""

    code: str
    message: str
    span: SourceSpan
    json_pointer: str | None = None
    details: tuple[tuple[str, Any], ...] = ()
    related: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "severity": "error",
            "code": self.code,
            "phase": "catalog",
            "message": self.message,
            "sourceUri": self.span.source_name,
            "span": {
                "start": self.span.start.to_dict(),
                "end": self.span.end.to_dict(),
            },
            "details": {key: _thaw(value) for key, value in self.details},
            "related": [{"message": value} for value in self.related],
            "jsonPointer": self.json_pointer,
        }
        return payload


@dataclass(frozen=True, slots=True)
class ControlCatalogSelection:
    """One authored node's exact pinned operator selection."""

    source_uri: str
    symbol: str
    authored_type: str
    operator_category: str
    operator_qualified_name: str
    type_span: SourceSpan

    def to_dict(self) -> dict[str, Any]:
        return {
            "sourceUri": self.source_uri,
            "symbol": self.symbol,
            "authoredType": self.authored_type,
            "operatorCategory": self.operator_category,
            "operatorQualifiedName": self.operator_qualified_name,
            "typeSpan": self.type_span.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class ControlCatalogValidationResult:
    """Immutable result of pinned whole-AST catalog admission."""

    valid: bool
    catalog_fingerprint: str
    required_capabilities: tuple[str, ...]
    selections: tuple[ControlCatalogSelection, ...]
    diagnostics: tuple[ControlCatalogDiagnostic, ...]
    checked_source_uris: tuple[str, ...]
    checked_node_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "catalogFingerprint": self.catalog_fingerprint,
            "requiredCapabilities": list(self.required_capabilities),
            "checkedSourceUris": list(self.checked_source_uris),
            "checkedNodeCount": self.checked_node_count,
            "selections": [item.to_dict() for item in self.selections],
            "diagnostics": [item.to_dict() for item in self.diagnostics],
        }


@dataclass(slots=True)
class _State:
    catalog: CatalogSnapshot
    limits: ControlExpansionLimits
    cancellation: Callable[[], bool] | None
    diagnostics: list[ControlCatalogDiagnostic] = field(default_factory=list)
    selections: list[ControlCatalogSelection] = field(default_factory=list)
    capabilities: set[str] = field(default_factory=lambda: {"edit_scene"})
    checked_sources: set[str] = field(default_factory=set)
    parameter_types: dict[int, str] = field(default_factory=dict)
    checked_nodes: int = 0
    omitted_diagnostics: int = 0

    def checkpoint(self, span: SourceSpan) -> None:
        _check_cancel(self.cancellation, span)

    def claim_node(self, node: NodeDecl) -> int:
        self.checkpoint(node.span)
        self.checked_nodes += 1
        if self.checked_nodes > self.limits.source_map_entries:
            raise ModuleExpansionError(
                "HOCUS464",
                "Whole-AST catalog validation exceeded the authored-node limit.",
                node.span,
            )
        return self.checked_nodes - 1

    def add(self, diagnostic: ControlCatalogDiagnostic) -> None:
        if len(self.diagnostics) < self.limits.diagnostics - 1:
            self.diagnostics.append(diagnostic)
        else:
            self.omitted_diagnostics += 1

    def finish_diagnostics(self, fallback: SourceSpan) -> tuple[ControlCatalogDiagnostic, ...]:
        if self.omitted_diagnostics:
            self.diagnostics.append(ControlCatalogDiagnostic(
                "HOCUS019",
                f"Catalog diagnostics truncated; {self.omitted_diagnostics} additional diagnostic(s) omitted.",
                fallback,
                details=(("limit", self.limits.diagnostics), ("omittedCount", self.omitted_diagnostics)),
            ))
        return tuple(self.diagnostics)


def validate_control_catalog_program(
    entry: SyntaxSource,
    entry_imports: Mapping[str, Any],
    modules: Mapping[str, ResolvedModuleUnit],
    catalog: CatalogSnapshot,
    *,
    expected_catalog_fingerprint: str,
    limits: ControlExpansionLimits = ControlExpansionLimits(),
    cancellation: Callable[[], bool] | None = None,
) -> ControlCatalogValidationResult:
    """Validate every authored 0.3 node against one exact catalog snapshot.

    Structural whole-body validation runs first. Catalog admission then visits
    the entry and complete resolved module closure, including both conditional
    branches and every fold body regardless of selected values or counts.
    """

    _validate_inputs(catalog, expected_catalog_fingerprint, limits)
    entry_imports, modules = _snapshot_program_inputs(
        entry_imports,
        modules,
        entry.span,
        cancellation,
    )

    def record_parameter_types(
        node: NodeDecl,
        inferred: tuple[str, ...],
    ) -> None:
        parms = [
            item for item in node.statements if isinstance(item, ParmStmt)
        ]
        if len(parms) != len(inferred):
            raise RuntimeError("H2 parameter type observation is inconsistent")
        parameter_types.update({
            id(parm): type_name
            for parm, type_name in zip(parms, inferred, strict=True)
        })

    parameter_types: dict[int, str] = {}
    validate_control_program(
        entry,
        entry_imports,
        modules,
        limits=limits,
        cancellation=cancellation,
        _node_parameter_observer=record_parameter_types,
    )
    if catalog.fingerprint != expected_catalog_fingerprint:
        raise ModuleExpansionError(
            "HOCUS605",
            "Catalog fingerprint differs from the pinned semantic input.",
            entry.span,
            details={
                "expected": expected_catalog_fingerprint,
                "actual": catalog.fingerprint,
            },
        )

    state = _State(
        catalog,
        limits,
        cancellation,
        parameter_types=parameter_types,
    )
    state.checked_sources.add(entry.span.source_name)
    category = _graph_category(entry, state)
    if entry.graph is not None:
        _visit_statements(entry.graph.statements, category, state)
    for uri in sorted(modules):
        unit = modules[uri]
        state.checkpoint(unit.syntax.span)
        state.checked_sources.add(unit.syntax.span.source_name)
        if unit.syntax.module is not None:
            _visit_statements(unit.syntax.module.statements, category, state)
    state.checkpoint(entry.span)
    if catalog.fingerprint != expected_catalog_fingerprint:
        raise ModuleExpansionError(
            "HOCUS605",
            "Catalog changed during whole-AST capability validation.",
            entry.span,
            details={
                "expected": expected_catalog_fingerprint,
                "actual": catalog.fingerprint,
            },
        )
    diagnostics = state.finish_diagnostics(entry.span)
    return ControlCatalogValidationResult(
        not diagnostics,
        catalog.fingerprint,
        tuple(sorted(state.capabilities)),
        tuple(state.selections),
        diagnostics,
        tuple(sorted(state.checked_sources)),
        state.checked_nodes,
    )


def _validate_inputs(
    catalog: CatalogSnapshot,
    expected_fingerprint: str,
    limits: ControlExpansionLimits,
) -> None:
    if not isinstance(catalog, CatalogSnapshot):
        raise TypeError("catalog must be a CatalogSnapshot")
    if (
        type(expected_fingerprint) is not str
        or re.fullmatch(r"sha256:[0-9a-f]{64}", expected_fingerprint) is None
    ):
        raise TypeError("expected_catalog_fingerprint must be a SHA-256 fingerprint")
    if not isinstance(limits, ControlExpansionLimits):
        raise TypeError("limits must be ControlExpansionLimits")


def _graph_category(entry: SyntaxSource, state: _State) -> str | None:
    assert entry.graph is not None
    declarations = [
        statement
        for statement in entry.graph.statements
        if isinstance(statement, CategoryStmt)
    ]
    category = declarations[0].value if declarations else None
    if category is None:
        return None
    known = {item.name for item in state.catalog.categories}
    if category not in known:
        state.add(ControlCatalogDiagnostic(
            "HOCUS620",
            f"Unknown catalog category '{category}'.",
            declarations[0].span,
            details=(("availableCategories", tuple(sorted(known))),),
        ))
        return _InvalidCategory(category)
    return category


class _InvalidCategory(str):
    pass


def _visit_statements(
    statements: tuple[Any, ...],
    category: str | None,
    state: _State,
) -> None:
    for statement in statements:
        state.checkpoint(statement.span)
        if isinstance(statement, NodeDecl):
            _visit_node(statement, category, state)
        elif isinstance(statement, IfDecl):
            _visit_statements(statement.then_body, category, state)
            _visit_statements(statement.else_body, category, state)
        elif isinstance(statement, ForDecl):
            _visit_statements(statement.body, category, state)


def _visit_node(node: NodeDecl, category: str | None, state: _State) -> None:
    node_index = state.claim_node(node)
    if any(
        isinstance(statement, ParmStmt)
        and isinstance(statement.value, CodeExpr)
        for statement in node.statements
    ):
        state.capabilities.add("run_code")
    if isinstance(category, _InvalidCategory):
        return
    semantic_diagnostics: list[Diagnostic] = []
    model_node = NodeSpec(
        node.symbol,
        node.type_name,
        [],
        [],
        node.span,
        {"typeName": node.type_span},
        node.explicit_id,
    )
    operator = _resolve_operator(
        model_node,
        node_index,
        category,
        state.catalog,
        semantic_diagnostics,
    )
    for diagnostic in semantic_diagnostics:
        state.add(_freeze_semantic_diagnostic(diagnostic))
    if operator is None:
        return
    state.selections.append(ControlCatalogSelection(
        node.span.source_name,
        node.symbol,
        node.type_name,
        operator.category,
        operator.qualified_name,
        node.type_span,
    ))
    _validate_parameters(node, model_node, node_index, operator, state)


def _validate_parameters(
    node: NodeDecl,
    model_node: NodeSpec,
    node_index: int,
    operator: OperatorDefinition,
    state: _State,
) -> None:
    roots = {item.token: item for item in operator.parameters}
    components = _parameter_components(operator)
    writes: dict[str, set[int] | None] = {}
    parms = [item for item in node.statements if isinstance(item, ParmStmt)]
    for parm_index, parm in enumerate(parms):
        state.checkpoint(parm.span)
        definition, component_index = _parameter_target(
            parm, operator, roots, components, state,
        )
        if definition is None:
            continue
        if _overlapping_write(parm, definition, component_index, writes, state):
            continue
        _validate_parameter_value(
            parm,
            model_node,
            node_index,
            parm_index,
            definition,
            component_index,
            state,
        )


def _parameter_components(
    operator: OperatorDefinition,
) -> dict[str, list[tuple[ParameterDefinition, int]]]:
    components: dict[str, list[tuple[ParameterDefinition, int]]] = {}
    for definition in operator.parameters:
        for index, token in enumerate(definition.tuple_names):
            components.setdefault(token, []).append((definition, index))
    return components


def _parameter_target(
    parm: ParmStmt,
    operator: OperatorDefinition,
    roots: Mapping[str, ParameterDefinition],
    components: Mapping[str, list[tuple[ParameterDefinition, int]]],
    state: _State,
) -> tuple[ParameterDefinition | None, int | None]:
    definition = roots.get(parm.name)
    candidates = components.get(parm.name, [])
    if definition is not None and candidates:
        state.add(_parameter_diagnostic(
            "HOCUS630",
            f"Parameter token '{parm.name}' collides with a tuple component in the catalog.",
            parm,
        ))
        return None, None
    if definition is None and len(candidates) == 1:
        return candidates[0]
    if definition is None and len(candidates) > 1:
        state.add(_parameter_diagnostic(
            "HOCUS630",
            f"Parameter component token '{parm.name}' is ambiguous in the catalog.",
            parm,
        ))
        return None, None
    if definition is None:
        names = tuple(sorted(set(roots) | set(components)))
        state.add(_parameter_diagnostic(
            "HOCUS630",
            f"Unknown parameter token '{parm.name}' on '{operator.qualified_name}'.",
            parm,
            details=(("availableParameters", names),),
        ))
        return None, None
    return definition, None


def _overlapping_write(
    parm: ParmStmt,
    definition: ParameterDefinition,
    component_index: int | None,
    writes: dict[str, set[int] | None],
    state: _State,
) -> bool:
    previous = writes.get(definition.token)
    current = None if component_index is None else {component_index}
    if definition.token in writes and (
        previous is None
        or current is None
        or not previous.isdisjoint(current)
    ):
        state.add(_parameter_diagnostic(
            "HOCUS631",
            f"Parameter write '{parm.name}' overlaps another write to tuple '{definition.token}'.",
            parm,
        ))
        return True
    writes[definition.token] = (
        current
        if previous is None
        else previous | current  # type: ignore[operator]
    )
    return False


def _validate_parameter_value(
    parm: ParmStmt,
    model_node: NodeSpec,
    node_index: int,
    parm_index: int,
    definition: ParameterDefinition,
    component_index: int | None,
    state: _State,
) -> None:
    if isinstance(parm.value, (ParamRefExpr, SymbolRefExpr)):
        _validate_dynamic_parameter(
            parm, definition, component_index, state,
        )
        return
    model_parm = ParmSpec(
        parm.name,
        _model_value(parm.value),
        parm.span,
        {"name": parm.name_span},
    )
    diagnostics: list[Diagnostic] = []
    _validate_parameter(
        model_parm,
        model_node,
        node_index,
        parm_index,
        definition,
        component_index,
        f"/nodes/{node_index}/parms/{parm_index}",
        diagnostics,
    )
    if (
        isinstance(parm.value, CodeExpr)
        or definition.code_surface != "none"
    ):
        state.capabilities.add("run_code")
    for diagnostic in diagnostics:
        state.add(_freeze_semantic_diagnostic(diagnostic))


def _validate_dynamic_parameter(
    parm: ParmStmt,
    definition: ParameterDefinition,
    component_index: int | None,
    state: _State,
) -> None:
    if not definition.assignable or definition.value_type in {
        "button", "ramp", "multiparm",
    }:
        state.add(_parameter_diagnostic(
            "HOCUS632",
            f"Parameter '{definition.token}' is not an ordinary assignable HocusScript 0.1 value.",
            parm,
        ))
        return
    if definition.value_type == "code":
        state.capabilities.add("run_code")
        state.add(ControlCatalogDiagnostic(
            "HOCUS638",
            f"Code parameter '{definition.token}' requires tagged code.",
            parm.value.span,
        ))
        return
    if component_index is None and definition.tuple_size > 1:
        state.add(ControlCatalogDiagnostic(
            "HOCUS634",
            f"Parameter '{definition.token}' requires a {definition.tuple_size}-element tuple.",
            parm.value.span,
            details=(("tupleSize", definition.tuple_size),),
        ))
        return
    actual = state.parameter_types[id(parm)]
    expected = (
        "string"
        if definition.value_type == "menu"
        else _element_type(definition)
    )
    if not _static_type_compatible(actual, expected):
        state.add(ControlCatalogDiagnostic(
            "HOCUS633",
            f"Parameter '{definition.token}' requires a scalar {expected} value.",
            parm.value.span,
            details=(
                ("actualType", actual),
                ("expectedType", definition.value_type),
            ),
        ))
    if definition.code_surface != "none":
        state.capabilities.add("run_code")


def _static_type_compatible(actual: str, expected: str) -> bool:
    if actual == expected:
        return True
    return actual == "int" and expected == "float"


def _model_value(value: Any) -> Any:
    if isinstance(value, LiteralExpr):
        return LiteralValue(value.value, value.span)
    if isinstance(value, ArrayExpr):
        return ArrayValue(
            [_model_value(item) for item in value.items],
            value.span,
        )
    if isinstance(value, CodeExpr):
        return CodeValue(
            value.language,
            value.body,
            value.span,
            value.body_span,
            value.offset_map,
        )
    raise TypeError("Catalog value conversion requires a literal, array, or code expression")


def _parameter_diagnostic(
    code: str,
    message: str,
    parm: ParmStmt,
    *,
    details: tuple[tuple[str, Any], ...] = (),
) -> ControlCatalogDiagnostic:
    return ControlCatalogDiagnostic(
        code,
        message,
        parm.name_span,
        details=details,
    )


def _freeze_semantic_diagnostic(
    diagnostic: Diagnostic,
) -> ControlCatalogDiagnostic:
    if diagnostic.span is None:
        raise RuntimeError("Catalog operator diagnostics must retain a source span")
    return ControlCatalogDiagnostic(
        diagnostic.code,
        diagnostic.message,
        diagnostic.span,
        diagnostic.json_pointer,
        tuple(
            (key, _freeze(value))
            for key, value in sorted(diagnostic.details.items())
        ),
        tuple(
            item["message"]
            for item in diagnostic.related
            if isinstance(item, dict) and isinstance(item.get("message"), str)
        ),
    )


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return tuple(
            (key, _freeze(item))
            for key, item in sorted(value.items())
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, tuple):
        if all(
            isinstance(item, tuple)
            and len(item) == 2
            and isinstance(item[0], str)
            for item in value
        ):
            return {key: _thaw(item) for key, item in value}
        return [_thaw(item) for item in value]
    return value


__all__ = [
    "ControlCatalogDiagnostic",
    "ControlCatalogSelection",
    "ControlCatalogValidationResult",
    "validate_control_catalog_program",
]

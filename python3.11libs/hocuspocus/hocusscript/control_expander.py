"""Pure deterministic expansion for HocusScript 0.3 compile-time controls.

This module is intentionally parallel to :mod:`expander`.  It consumes only
caller-supplied bytes and resolved in-memory module units and produces the
language-0.3/GraphSpec-0.4 carrier as a plain JSON-compatible object.  Project
resolution and native compiler dispatch remain later integration concerns.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Mapping

from .contracts import CarrierContractError, decode_control_graph_spec_envelope
from .control_semantic import ControlExpansionLimits, validate_control_program
from .diagnostics import SourceSpan
from .expander import ModuleExpansionError, ResolvedModuleUnit
from .model import (
    ArrayValue, CodeValue, ExpansionFrame, ExternalNodeSpec, InputSpec,
    LiteralValue, NodeReference, NodeSpec, ParmSpec,
)
from .resolved_modules import ResolvedImport, canonical_module_uri
from .syntax import (
    ArrayExpr, CategoryStmt, CodeExpr, ExportStmt, ExternalDecl, FlagStmt,
    ForDecl, IfDecl, InputStmt, LayoutStmt, LiteralExpr, ModeStmt, NodeDecl,
    OwnershipStmt, ParamRefExpr, ParmStmt, RevisionStmt, SymbolRefExpr,
    SyntaxSource, TargetStmt, UseDecl, YieldStmt,
)


_RESERVED_PREFIX = "__hocus_"
_MODULE_IDENTITY_DOMAIN = "hocus-module-instance-v1"
_IF_IDENTITY_DOMAIN = "hocus-control-if-branch-v1"
_FOR_IDENTITY_DOMAIN = "hocus-control-for-index-v1"
_MODULE_STACK_DOMAIN = "hocus-expansion-stack-v1"
_CONTROL_STACK_DOMAIN = "hocus-control-stack-v1"


@dataclass(frozen=True, slots=True)
class _Bound:
    type_name: str
    value: Any
    span: SourceSpan
    parameter_spans: tuple[SourceSpan, ...] = ()
    related: tuple[tuple[str, SourceSpan], ...] = ()
    producer_modules: tuple[ExpansionFrame, ...] = ()
    producer_controls: tuple[dict[str, Any], ...] = ()


@dataclass(slots=True)
class _Scope:
    parameters: dict[str, _Bound] = field(default_factory=dict)
    nodes: dict[str, _Bound] = field(default_factory=dict)
    uses: dict[str, dict[str, _Bound]] = field(default_factory=dict)
    controls: dict[str, dict[str, _Bound]] = field(default_factory=dict)
    iterators: dict[str, _Bound] = field(default_factory=dict)
    carries: dict[str, _Bound] = field(default_factory=dict)

    def child(self) -> "_Scope":
        return _Scope(
            dict(self.parameters), dict(self.nodes), dict(self.uses),
            dict(self.controls), dict(self.iterators), dict(self.carries),
        )


@dataclass(frozen=True, slots=True)
class _Origin:
    span: SourceSpan
    module_frames: tuple[ExpansionFrame, ...] = ()
    control_frames: tuple[dict[str, Any], ...] = ()
    kind: str = "definition"
    related: tuple[tuple[str, SourceSpan], ...] = ()


@dataclass(slots=True)
class _State:
    limits: ControlExpansionLimits
    cancellation: Callable[[], bool] | None
    nodes: list[NodeSpec] = field(default_factory=list)
    node_origins: list[tuple[_Origin, list[_Origin], list[_Origin]]] = field(default_factory=list)
    instance_count: int = 0
    iteration_count: int = 0
    code_bytes: int = 0
    root_symbols: dict[str, str] = field(default_factory=dict)

    def checkpoint(self, span: SourceSpan) -> None:
        _check_cancel(self.cancellation, span)


def expand_control_graph(
    entry_source: bytes,
    entry_uri: str,
    entry_imports: Mapping[str, Any],
    modules: Mapping[str, ResolvedModuleUnit],
    *,
    limits: ControlExpansionLimits = ControlExpansionLimits(),
    cancellation: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """Validate and expand an exact HocusScript 0.3 graph without I/O.

    Both branches and every fold body are statically validated by
    ``validate_control_program``.  This stage then evaluates only the selected
    branch and the admitted half-open fold iterations.
    """

    if not isinstance(entry_imports, Mapping) or not isinstance(modules, Mapping):
        raise TypeError("entry_imports and modules must be mappings")
    if not isinstance(limits, ControlExpansionLimits):
        raise TypeError("limits must be ControlExpansionLimits")
    entry = _parse_entry(entry_source, entry_uri)
    entry_imports, modules = _snapshot_program_inputs(
        entry_imports, modules, entry.span, cancellation,
    )
    validate_control_program(
        entry, entry_imports, modules, limits=limits, cancellation=cancellation,
    )
    assert entry.graph is not None

    state = _State(limits, cancellation)
    graph = entry.graph
    graph_identity = _digest({"entryUri": entry_uri, "graphName": graph.name})
    scope = _Scope()
    _predeclare_nodes(
        graph.statements, scope, entry_uri, (), (), graph_identity,
    )
    for statement in graph.statements:
        if isinstance(statement, ExternalDecl):
            scope.nodes[statement.symbol] = _Bound(
                "node_output", (statement.symbol, 0), statement.span,
            )
    state.root_symbols.update({
        name: bound.value[0]
        for name, bound in scope.nodes.items()
        if bound.type_name == "node_output"
    })

    directives: list[Any] = []
    for statement in graph.statements:
        state.checkpoint(statement.span)
        if isinstance(statement, NodeDecl):
            scope.nodes[statement.symbol] = _emit_node(
                statement, entry_uri, (), (), (), graph_identity, scope, state,
            )
        elif isinstance(statement, UseDecl):
            value = _expand_use(
                statement, entry_imports, modules, (), (), (), graph_identity,
                scope, state, active=(),
            )
            _bind_use(scope, statement.symbol, value)
        elif isinstance(statement, IfDecl):
            value = _evaluate_if(
                statement, entry_uri, entry_imports, modules, (), (), (),
                graph_identity, scope, state, active=(),
            )
            _bind_control(scope, statement.symbol, value)
        elif isinstance(statement, ForDecl):
            value = _evaluate_for(
                statement, entry_uri, entry_imports, modules, (), (), (),
                graph_identity, scope, state, active=(),
            )
            _bind_control(scope, statement.symbol, value)
        else:
            directives.append(statement)

    result = _build_graph(entry, directives, graph_identity, entry_uri, state)
    projection = {
        "expandedNodes": limits.expanded_nodes,
        "sourceMapEntries": limits.source_map_entries,
        "instances": limits.instances,
        "instanceDepth": limits.instance_depth,
        "aggregateCodeBytes": limits.aggregate_code_bytes,
        "perFoldIterations": limits.per_fold_iterations,
        "aggregateIterations": limits.aggregate_iterations,
    }
    try:
        return decode_control_graph_spec_envelope(result, resolved_limits=projection)
    except CarrierContractError as exc:
        raise ModuleExpansionError(
            "HOCUS478", "Expanded graph failed strict GraphSpec 0.4 validation.",
            graph.span, details={"validatorCode": exc.code},
        ) from exc


def _parse_entry(source: bytes, uri: str) -> SyntaxSource:
    if type(source) is not bytes:
        raise TypeError("entry_source must be exact bytes")
    if len(source) > 1_048_576:
        raise ModuleExpansionError(
            "HOCUS464", "Entry source exceeds the 1 MiB limit.", _synthetic_span(),
        )
    if canonical_module_uri(uri) is None:
        raise ModuleExpansionError("HOCUS460", "Entry URI is not canonical.", _synthetic_span())
    try:
        text = source.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ModuleExpansionError(
            "HOCUS460", "Entry source must be valid UTF-8.", _synthetic_span(),
        ) from exc
    from .parser import parse_syntax
    try:
        syntax = parse_syntax(text, uri)
    except Exception as exc:
        raise ModuleExpansionError(
            "HOCUS460", "Entry source failed strict parsing.", _synthetic_span(),
        ) from exc
    if (
        syntax.version is None or syntax.version.value != "0.3"
        or syntax.graph is None or syntax.module is not None
        or syntax.span.source_name != uri
    ):
        raise ModuleExpansionError(
            "HOCUS460", "Expansion requires one HocusScript 0.3 graph entry source.",
            syntax.span,
        )
    return syntax


def _snapshot_program_inputs(
    entry_imports: Mapping[str, Any],
    modules: Mapping[str, ResolvedModuleUnit],
    span: SourceSpan,
    cancellation: Callable[[], bool] | None,
) -> tuple[dict[str, ResolvedImport], dict[str, ResolvedModuleUnit]]:
    """Freeze caller evidence once for both validation and evaluation.

    Mapping implementations and import-like objects are untrusted public input.
    Reading their evidence twice would permit validation/runtime target swaps.
    """

    frozen_modules: dict[str, ResolvedModuleUnit] = {}
    _check_cancel(cancellation, span)
    for key, unit in _bounded_mapping_items(
        modules, 4_096, "modules", span, cancellation,
    ):
        if not isinstance(key, str) or key in frozen_modules:
            raise ModuleExpansionError(
                "HOCUS460", "Module mapping keys must be unique strings.", span,
            )
        if not isinstance(unit, ResolvedModuleUnit):
            raise ModuleExpansionError(
                "HOCUS460", "Module mapping values must be ResolvedModuleUnit.", span,
            )
        try:
            uri = unit.uri
            source_digest = unit.source_digest
            syntax = unit.syntax
            imports = unit.imports
        except Exception as exc:
            raise ModuleExpansionError(
                "HOCUS460", "Resolved module evidence could not be read.", span,
            ) from exc
        if not isinstance(syntax, SyntaxSource) or not isinstance(syntax.span, SourceSpan):
            raise ModuleExpansionError(
                "HOCUS460", "Resolved module syntax evidence is invalid.", span,
            )
        frozen_modules[key] = ResolvedModuleUnit(
            uri, source_digest, syntax,
            _snapshot_import_mapping(imports, syntax.span, cancellation),
        )
    return (
        _snapshot_import_mapping(entry_imports, span, cancellation),
        frozen_modules,
    )


def _snapshot_import_mapping(
    value: Mapping[str, Any], span: SourceSpan,
    cancellation: Callable[[], bool] | None,
) -> dict[str, ResolvedImport]:
    if not isinstance(value, Mapping):
        raise ModuleExpansionError("HOCUS460", "Import map must be a mapping.", span)
    result: dict[str, ResolvedImport] = {}
    for key, item in _bounded_mapping_items(
        value, 4_096, "imports", span, cancellation,
    ):
        if not isinstance(key, str) or key in result:
            raise ModuleExpansionError(
                "HOCUS460", "Import mapping keys must be unique strings.", span,
            )
        try:
            # Each potentially stateful property is read exactly once.
            specifier = item.specifier
            imported_name = item.imported_name
            local_name = item.local_name
            target_uri = item.target_uri
            import_span = item.span
        except Exception as exc:
            raise ModuleExpansionError(
                "HOCUS460", "Resolved import evidence could not be read.", span,
            ) from exc
        result[key] = ResolvedImport(
            specifier, imported_name, local_name, target_uri, import_span,
        )
    return result


def _bounded_mapping_items(
    value: Mapping[Any, Any], maximum: int, label: str, span: SourceSpan,
    cancellation: Callable[[], bool] | None,
) -> tuple[tuple[Any, Any], ...]:
    if not isinstance(value, Mapping):
        raise ModuleExpansionError("HOCUS460", f"{label} must be a mapping.", span)
    items: list[tuple[Any, Any]] = []
    try:
        _check_cancel(cancellation, span)
        iterator = iter(value.items())
        for index, pair in enumerate(iterator):
            _check_cancel(cancellation, span)
            if index >= maximum:
                raise ModuleExpansionError(
                    "HOCUS464", f"{label} exceeds its fixed item limit.", span,
                )
            if not isinstance(pair, tuple) or len(pair) != 2:
                raise ModuleExpansionError(
                    "HOCUS460", f"{label} yielded malformed items.", span,
                )
            items.append(pair)
    except ModuleExpansionError:
        raise
    except Exception as exc:
        raise ModuleExpansionError(
            "HOCUS460", f"{label} could not be snapshotted.", span,
        ) from exc
    return tuple(items)


def _predeclare_nodes(
    statements: tuple[Any, ...], scope: _Scope, module_uri: str,
    seed_path: tuple[str, ...], control_path: tuple[dict[str, Any], ...],
    graph_identity: str,
) -> None:
    for statement in statements:
        if isinstance(statement, NodeDecl):
            scope.uses.pop(statement.symbol, None)
            scope.controls.pop(statement.symbol, None)
            scope.nodes[statement.symbol] = _node_bound(
                statement, module_uri, seed_path, control_path, graph_identity,
            )


def _bind_use(scope: _Scope, symbol: str, value: dict[str, _Bound]) -> None:
    scope.nodes.pop(symbol, None)
    scope.controls.pop(symbol, None)
    scope.uses[symbol] = value


def _bind_control(scope: _Scope, symbol: str, value: dict[str, _Bound]) -> None:
    scope.nodes.pop(symbol, None)
    scope.uses.pop(symbol, None)
    scope.controls[symbol] = value


def _expand_use(
    use: UseDecl, imports: Mapping[str, Any], modules: Mapping[str, ResolvedModuleUnit],
    seed_path: tuple[str, ...], module_frames: tuple[ExpansionFrame, ...],
    control_frames: tuple[dict[str, Any], ...], graph_identity: str,
    caller_scope: _Scope, state: _State, *, active: tuple[str, ...],
    control_path: tuple[dict[str, Any], ...] = (),
) -> dict[str, _Bound]:
    state.checkpoint(use.span)
    resolved_import = imports.get(use.module_name)
    target_uri = getattr(resolved_import, "target_uri", None)
    if not isinstance(target_uri, str) or target_uri not in modules:
        raise ModuleExpansionError(
            "HOCUS466", f"Unknown imported module: {use.module_name}.", use.module_name_span,
        )
    if target_uri in active:
        raise ModuleExpansionError("HOCUS467", "Module instantiation cycle detected.", use.span)
    next_path = (*seed_path, use.explicit_id)
    if len(next_path) > state.limits.instance_depth:
        raise ModuleExpansionError("HOCUS464", "Module instance depth exceeds its limit.", use.span)
    state.instance_count += 1
    if state.instance_count > state.limits.instances:
        raise ModuleExpansionError("HOCUS464", "Module instance count exceeds its limit.", use.span)

    unit = modules[target_uri]
    module = unit.declaration
    frame = ExpansionFrame(
        target_uri, unit.source_digest, module.name, use.symbol, next_path,
        getattr(resolved_import, "span", None), use.span,
    )
    next_module_frames = (*module_frames, frame)
    module_identity_path = (*control_path, {
        "domain": _MODULE_IDENTITY_DOMAIN,
        "durableSeed": use.explicit_id,
        "moduleUri": target_uri,
    })
    parameters = _bind_arguments(
        use, module.parameters, caller_scope, control_frames,
    )
    scope = _Scope(parameters=parameters)
    _predeclare_nodes(
        module.statements, scope, target_uri, next_path,
        module_identity_path, graph_identity,
    )
    exports: dict[str, _Bound] = {}
    export_statements: dict[str, ExportStmt] = {}
    for statement in module.statements:
        state.checkpoint(statement.span)
        if isinstance(statement, NodeDecl):
            scope.nodes[statement.symbol] = _emit_node(
                statement, target_uri, next_path, next_module_frames,
                control_frames, graph_identity, scope, state,
                control_path=module_identity_path,
            )
        elif isinstance(statement, UseDecl):
            value = _expand_use(
                statement, unit.imports, modules, next_path, next_module_frames,
                control_frames, graph_identity, scope, state,
                active=(*active, target_uri), control_path=module_identity_path,
            )
            _bind_use(scope, statement.symbol, value)
        elif isinstance(statement, IfDecl):
            value = _evaluate_if(
                statement, target_uri, unit.imports, modules, next_path,
                next_module_frames, control_frames, graph_identity, scope, state,
                active=(*active, target_uri), control_path=module_identity_path,
            )
            _bind_control(scope, statement.symbol, value)
        elif isinstance(statement, ForDecl):
            value = _evaluate_for(
                statement, target_uri, unit.imports, modules, next_path,
                next_module_frames, control_frames, graph_identity, scope, state,
                active=(*active, target_uri), control_path=module_identity_path,
            )
            _bind_control(scope, statement.symbol, value)
        elif isinstance(statement, ExportStmt):
            export_statements[statement.name] = statement
    for declaration in module.exports:
        statement = export_statements[declaration.name]
        bound = _resolve_expr(statement.value, scope)
        exports[declaration.name] = replace(
            bound,
            producer_modules=bound.producer_modules or next_module_frames,
            producer_controls=_selected_producer_controls(
                bound.producer_controls, control_frames,
            ),
        )
    return exports


def _bind_arguments(
    use: UseDecl, declarations: tuple[Any, ...], scope: _Scope,
    control_frames: tuple[dict[str, Any], ...],
) -> dict[str, _Bound]:
    authored = {item.name: item for item in use.arguments}
    result: dict[str, _Bound] = {}
    for declaration in declarations:
        argument = authored.get(declaration.name)
        if argument is None:
            assert declaration.default is not None
            bound = _literal_bound(declaration.default)
        else:
            bound = _resolve_expr(argument.value, scope)
        bound = replace(
            bound,
            producer_controls=_selected_producer_controls(
                bound.producer_controls, control_frames,
            ),
        )
        spans = (*bound.parameter_spans, declaration.span)
        if len(spans) > 16:
            raise ModuleExpansionError(
                "HOCUS464", "Forwarded parameter provenance exceeds 16 origins.",
                use.span,
            )
        result[declaration.name] = replace(bound, parameter_spans=spans)
    return result


def _evaluate_if(
    control: IfDecl, module_uri: str, imports: Mapping[str, Any],
    modules: Mapping[str, ResolvedModuleUnit], seed_path: tuple[str, ...],
    module_frames: tuple[ExpansionFrame, ...],
    control_frames: tuple[dict[str, Any], ...], graph_identity: str,
    scope: _Scope, state: _State, *, active: tuple[str, ...],
    control_path: tuple[dict[str, Any], ...] = (),
) -> dict[str, _Bound]:
    state.checkpoint(control.condition_span)
    condition = _resolve_expr(control.condition, scope)
    if condition.type_name != "bool" or type(condition.value) is not bool:
        raise ModuleExpansionError(
            "HOCUS475", "If condition must evaluate to an exact bool.", control.condition_span,
        )
    branch = "then" if condition.value else "else"
    body = control.then_body if condition.value else control.else_body
    yields = tuple(item for item in body if isinstance(item, YieldStmt))
    frame = {
        "kind": "if",
        "controlSymbol": control.symbol,
        "durableSeed": control.explicit_id,
        "branch": branch,
        "declarationSpan": control.span.to_dict(),
        "selectionSpan": control.condition_span.to_dict(),
        "yieldSpans": [item.span.to_dict() for item in yields],
    }
    next_frames = (*control_frames, frame)
    _check_control_depth(next_frames, control.span, state)
    step = {
        "domain": _IF_IDENTITY_DOMAIN,
        "durableSeed": control.explicit_id,
        "branch": branch,
    }
    next_path = (*control_path, step)
    values = _execute_control_body(
        body, module_uri, imports, modules, seed_path, module_frames, next_frames,
        next_path, graph_identity, scope, state, active=active,
    )
    result: dict[str, _Bound] = {}
    for declaration in control.outputs:
        bound, yield_statement = values[declaration.name]
        state.checkpoint(yield_statement.span)
        result[declaration.name] = replace(
            bound,
            related=_bounded_related((
                ("control_declaration", control.span),
                ("condition", control.condition_span),
                ("yield", yield_statement.span),
            ), (), yield_statement.span),
            producer_controls=_selected_producer_controls(
                bound.producer_controls, next_frames,
            ),
        )
    return result


def _evaluate_for(
    control: ForDecl, module_uri: str, imports: Mapping[str, Any],
    modules: Mapping[str, ResolvedModuleUnit], seed_path: tuple[str, ...],
    module_frames: tuple[ExpansionFrame, ...],
    control_frames: tuple[dict[str, Any], ...], graph_identity: str,
    scope: _Scope, state: _State, *, active: tuple[str, ...],
    control_path: tuple[dict[str, Any], ...] = (),
) -> dict[str, _Bound]:
    state.checkpoint(control.count_span)
    count = _resolve_expr(control.count, scope)
    if count.type_name != "int" or type(count.value) is not int or count.value < 0:
        raise ModuleExpansionError(
            "HOCUS475", "Fold count must evaluate to an exact nonnegative int.",
            control.count_span,
        )
    if count.value > state.limits.per_fold_iterations:
        raise ModuleExpansionError("HOCUS464", "Fold exceeds perFoldIterations.", control.count_span)
    remaining = state.limits.aggregate_iterations - state.iteration_count
    if count.value > remaining:
        raise ModuleExpansionError("HOCUS464", "Fold exceeds aggregateIterations.", control.count_span)

    carries: dict[str, _Bound] = {}
    for declaration in control.carries:
        state.checkpoint(declaration.initial_span)
        bound = _resolve_expr(declaration.initial, scope)
        carries[declaration.name] = replace(
            bound,
            related=_bounded_related((
                ("control_declaration", control.span),
                ("fold_count", control.count_span),
                ("carry_initializer", declaration.initial_span),
            ), (), declaration.initial_span),
        )
    if count.value == 0:
        return carries

    yields = tuple(item for item in control.body if isinstance(item, YieldStmt))
    for index in range(count.value):
        state.checkpoint(control.span)
        if state.iteration_count >= state.limits.aggregate_iterations:
            raise ModuleExpansionError(
                "HOCUS464", "Fold exceeds aggregateIterations.", control.count_span,
            )
        state.iteration_count += 1
        frame = {
            "kind": "for",
            "controlSymbol": control.symbol,
            "durableSeed": control.explicit_id,
            "iterator": control.iterator,
            "iterationIndex": index,
            "declarationSpan": control.span.to_dict(),
            "selectionSpan": control.count_span.to_dict(),
            "yieldSpans": [item.span.to_dict() for item in yields],
        }
        next_frames = (*control_frames, frame)
        _check_control_depth(next_frames, control.span, state)
        step = {
            "domain": _FOR_IDENTITY_DOMAIN,
            "durableSeed": control.explicit_id,
            "iterationIndex": index,
        }
        next_path = (*control_path, step)
        iteration_scope = scope.child()
        iteration_scope.iterators[control.iterator] = _Bound(
            "int", index, control.iterator_span,
        )
        iteration_scope.carries.update(carries)
        values = _execute_control_body(
            control.body, module_uri, imports, modules, seed_path, module_frames,
            next_frames, next_path, graph_identity, iteration_scope, state,
            active=active,
        )
        committed: dict[str, _Bound] = {}
        for declaration in control.carries:
            state.checkpoint(values[declaration.name][1].span)
            bound, yield_statement = values[declaration.name]
            committed[declaration.name] = replace(
                bound,
                related=_bounded_related((
                    ("control_declaration", control.span),
                    ("fold_count", control.count_span),
                    ("yield", yield_statement.span),
                ), (), yield_statement.span),
                producer_controls=_selected_producer_controls(
                    bound.producer_controls, next_frames,
                ),
            )
        carries = committed
    return carries


def _execute_control_body(
    statements: tuple[Any, ...], module_uri: str, imports: Mapping[str, Any],
    modules: Mapping[str, ResolvedModuleUnit], seed_path: tuple[str, ...],
    module_frames: tuple[ExpansionFrame, ...],
    control_frames: tuple[dict[str, Any], ...],
    control_path: tuple[dict[str, Any], ...], graph_identity: str,
    parent_scope: _Scope, state: _State, *, active: tuple[str, ...],
) -> dict[str, tuple[_Bound, YieldStmt]]:
    scope = parent_scope.child()
    _predeclare_nodes(statements, scope, module_uri, seed_path, control_path, graph_identity)
    yields: dict[str, tuple[_Bound, YieldStmt]] = {}
    for statement in statements:
        state.checkpoint(statement.span)
        if isinstance(statement, NodeDecl):
            scope.nodes[statement.symbol] = _emit_node(
                statement, module_uri, seed_path, module_frames, control_frames,
                graph_identity, scope, state, control_path=control_path,
            )
        elif isinstance(statement, UseDecl):
            value = _expand_use(
                statement, imports, modules, seed_path, module_frames,
                control_frames, graph_identity, scope, state, active=active,
                control_path=control_path,
            )
            _bind_use(scope, statement.symbol, value)
        elif isinstance(statement, IfDecl):
            value = _evaluate_if(
                statement, module_uri, imports, modules, seed_path, module_frames,
                control_frames, graph_identity, scope, state, active=active,
                control_path=control_path,
            )
            _bind_control(scope, statement.symbol, value)
        elif isinstance(statement, ForDecl):
            value = _evaluate_for(
                statement, module_uri, imports, modules, seed_path, module_frames,
                control_frames, graph_identity, scope, state, active=active,
                control_path=control_path,
            )
            _bind_control(scope, statement.symbol, value)
        elif isinstance(statement, YieldStmt):
            state.checkpoint(statement.span)
            yields[statement.name] = (_resolve_expr(statement.value, scope), statement)
    return yields


def _emit_node(
    node: NodeDecl, module_uri: str, seed_path: tuple[str, ...],
    module_frames: tuple[ExpansionFrame, ...],
    control_frames: tuple[dict[str, Any], ...], graph_identity: str,
    scope: _Scope, state: _State, *,
    control_path: tuple[dict[str, Any], ...] = (),
) -> _Bound:
    state.checkpoint(node.span)
    if len(state.nodes) >= state.limits.expanded_nodes:
        raise ModuleExpansionError("HOCUS464", "Expanded graph exceeds the node limit.", node.span)
    identity_bound = _node_bound(node, module_uri, seed_path, control_path, graph_identity)
    symbol, _ = identity_bound.value
    identity = "sha256:" + symbol.removeprefix(_RESERVED_PREFIX)
    inputs: list[InputSpec] = []
    parms: list[ParmSpec] = []
    input_origins: list[_Origin] = []
    parm_origins: list[_Origin] = []
    for statement in node.statements:
        state.checkpoint(statement.span)
        if isinstance(statement, InputStmt):
            bound = _resolve_expr(statement.source, scope)
            ref_symbol, output_index = bound.value
            inputs.append(InputSpec(
                statement.index,
                NodeReference(
                    ref_symbol, output_index, bound.span,
                    {"symbol": bound.span, "outputIndex": bound.span},
                ),
                statement.span, {"index": statement.index_span},
            ))
            input_origins.append(_value_origin(bound, module_frames, control_frames))
        elif isinstance(statement, ParmStmt):
            bound = _resolve_expr(statement.value, scope)
            graph_value = (
                bound.value
                if isinstance(bound.value, (LiteralValue, ArrayValue, CodeValue))
                else LiteralValue(bound.value, bound.span)
            )
            state.code_bytes += _graph_value_code_bytes(graph_value)
            if state.code_bytes > state.limits.aggregate_code_bytes:
                raise ModuleExpansionError(
                    "HOCUS464", "Expanded graph exceeds aggregateCodeBytes.",
                    statement.value.span,
                )
            parms.append(ParmSpec(
                statement.name, graph_value,
                statement.span, {"name": statement.name_span},
            ))
            parm_origins.append(_value_origin(bound, module_frames, control_frames))
    explicit_id = "hocus." + identity.removeprefix("sha256:")
    state.nodes.append(NodeSpec(
        symbol, node.type_name, inputs, parms, node.span,
        {
            "symbol": node.symbol_span, "typeName": node.type_span,
            "explicitId": node.explicit_id_span or node.symbol_span,
        },
        explicit_id,
    ))
    state.node_origins.append((
        _Origin(node.span, module_frames, control_frames), input_origins, parm_origins,
    ))
    return _Bound(
        "node_output", (symbol, 0), node.span,
        producer_modules=module_frames,
        producer_controls=control_frames,
    )


def _value_origin(
    bound: _Bound, module_frames: tuple[ExpansionFrame, ...],
    execution_controls: tuple[dict[str, Any], ...],
) -> _Origin:
    modules = bound.producer_modules or module_frames
    controls = _selected_producer_controls(
        bound.producer_controls, execution_controls,
    )
    related = [*bound.related]
    related.extend(("parameter_declaration", span) for span in bound.parameter_spans)
    return _Origin(
        bound.span, modules, controls,
        "argument" if bound.parameter_spans else "definition",
        _bounded_related((), tuple(related), bound.span),
    )


def _node_bound(
    node: NodeDecl, module_uri: str, seed_path: tuple[str, ...],
    control_path: tuple[dict[str, Any], ...], graph_identity: str,
) -> _Bound:
    payload: dict[str, Any] = {
        "graphIdentity": graph_identity,
        "moduleUri": module_uri,
        "localSeed": node.explicit_id or node.symbol,
    }
    if control_path:
        payload["durableIdentityPath"] = list(control_path)
    identity = _digest(payload)
    return _Bound(
        "node_output", (_RESERVED_PREFIX + identity.removeprefix("sha256:"), 0),
        node.span,
    )


def _resolve_expr(expr: Any, scope: _Scope) -> _Bound:
    if isinstance(expr, LiteralExpr):
        return _literal_bound(expr)
    if isinstance(expr, ArrayExpr):
        return _Bound("array", _array_value(expr), expr.span)
    if isinstance(expr, CodeExpr):
        return _Bound(
            "code",
            CodeValue(
                expr.language, expr.body, expr.span, expr.body_span, expr.offset_map,
            ),
            expr.span,
        )
    if isinstance(expr, ParamRefExpr):
        bound = scope.parameters.get(expr.name)
        if bound is None:
            raise ModuleExpansionError("HOCUS471", f"Unknown module parameter: {expr.name}.", expr.span)
        # The generated use is in the receiving module.  Keep upstream value
        # and control provenance, but let its current module execution stack
        # own the mapping whose primary span is this receiving ParamRef.
        return replace(bound, span=expr.span, producer_modules=())
    if isinstance(expr, SymbolRefExpr):
        return _resolve_symbol_expr(expr, scope)
    raise ModuleExpansionError("HOCUS471", "Unsupported module expression.", expr.span)


def _resolve_symbol_expr(expr: SymbolRefExpr, scope: _Scope) -> _Bound:
    table = {"iter": scope.iterators, "carry": scope.carries}.get(expr.symbol)
    if table is not None and expr.output_index is None:
        bound = table.get(expr.member)
        if bound is not None:
            return replace(bound, span=expr.span)
    node = scope.nodes.get(expr.symbol)
    if node is not None:
        symbol, _ = node.value
        return _Bound(
            "node_output",
            (symbol, 0 if expr.output_index is None else expr.output_index),
            expr.span,
            producer_modules=node.producer_modules,
            producer_controls=node.producer_controls,
        )
    for members in (scope.uses.get(expr.symbol), scope.controls.get(expr.symbol)):
        if members is not None and expr.output_index is None and expr.member in members:
            return replace(members[expr.member], span=expr.span)
    raise ModuleExpansionError("HOCUS471", "Unknown module/control symbol or member.", expr.span)


def _literal_bound(expr: Any) -> _Bound:
    if not isinstance(expr, LiteralExpr):
        raise ModuleExpansionError("HOCUS471", "Expected a literal expression.", expr.span)
    value = expr.value
    if type(value) is bool:
        type_name = "bool"
    elif type(value) is int:
        type_name = "int"
    elif type(value) is float:
        type_name = "float"
    elif type(value) is str:
        type_name = "string"
    else:
        raise ModuleExpansionError("HOCUS474", "Unsupported literal type.", expr.span)
    return _Bound(type_name, value, expr.span)


def _array_value(expr: ArrayExpr) -> ArrayValue:
    items: list[Any] = []
    for item in expr.items:
        if isinstance(item, LiteralExpr):
            items.append(LiteralValue(item.value, item.span))
        elif isinstance(item, ArrayExpr):
            items.append(_array_value(item))
        elif isinstance(item, CodeExpr):
            items.append(CodeValue(
                item.language, item.body, item.span, item.body_span, item.offset_map,
            ))
        else:
            raise ModuleExpansionError(
                "HOCUS471", "Array values may contain only literal value expressions.",
                item.span,
            )
    return ArrayValue(items, expr.span)


def _graph_value_code_bytes(value: Any) -> int:
    if isinstance(value, CodeValue):
        try:
            return len(value.body.encode("utf-8"))
        except UnicodeEncodeError as exc:
            raise ModuleExpansionError(
                "HOCUS474", "Embedded code must be valid Unicode text.", value.span,
            ) from exc
    if isinstance(value, ArrayValue):
        return sum(_graph_value_code_bytes(item) for item in value.items)
    return 0


def _build_graph(
    entry: SyntaxSource, directives: list[Any], graph_identity: str,
    entry_uri: str, state: _State,
) -> dict[str, Any]:
    graph = entry.graph
    assert graph is not None and entry.version is not None
    fields, field_spans, external_nodes, external_origins = _collect_graph_fields(
        directives, state.root_symbols, graph.name_span, entry.version.value_span
    )
    if not isinstance(fields["target"], str):
        raise ModuleExpansionError(
            "HOCUS478", "GraphSpec 0.4 requires an absolute target.", graph.span,
        )
    result = _graph_envelope(graph, fields, field_spans, external_nodes, state.nodes)
    result["expansionMap"] = _build_control_expansion_map(
        entry_uri, graph.span, result, field_spans, external_origins, state
    )
    return result


def _collect_graph_fields(
    directives: list[Any],
    root_symbols: Mapping[str, str],
    name_span: SourceSpan,
    version_span: SourceSpan,
) -> tuple[dict[str, Any], dict[str, SourceSpan], list[ExternalNodeSpec], list[_Origin]]:
    fields: dict[str, Any] = {
        "target": None, "category": None, "ownership": None, "display": None,
        "render": None, "output": None, "layout": None, "mode": "merge", "revision": None,
    }
    field_spans = {"name": name_span, "languageVersion": version_span}
    external_nodes: list[ExternalNodeSpec] = []
    external_origins: list[_Origin] = []
    for statement in directives:
        if isinstance(statement, TargetStmt):
            fields["target"], field_spans["target"] = statement.value, statement.value_span
        elif isinstance(statement, CategoryStmt):
            fields["category"], field_spans["category"] = statement.value, statement.value_span
        elif isinstance(statement, ModeStmt):
            fields["mode"], field_spans["mode"] = statement.value, statement.value_span
        elif isinstance(statement, RevisionStmt):
            fields["revision"], field_spans["expectedRevision"] = statement.value, statement.value_span
        elif isinstance(statement, OwnershipStmt):
            fields["ownership"], field_spans["ownership"] = statement.value, statement.value_span
        elif isinstance(statement, ExternalDecl):
            external_nodes.append(ExternalNodeSpec(
                statement.symbol, statement.path, statement.adopted, statement.span,
                {"symbol": statement.symbol_span, "path": statement.path_span},
            ))
            external_origins.append(_Origin(statement.span))
        elif isinstance(statement, FlagStmt):
            value = root_symbols.get(statement.symbol, statement.symbol)
            field_spans[statement.name] = statement.value_span
            fields[statement.name] = value
        elif isinstance(statement, LayoutStmt):
            fields["layout"], field_spans["layout"] = statement.value, statement.value_span
    return fields, field_spans, external_nodes, external_origins


def _graph_envelope(
    graph: Any,
    fields: Mapping[str, Any],
    field_spans: Mapping[str, SourceSpan],
    external_nodes: list[ExternalNodeSpec],
    nodes: list[NodeSpec],
) -> dict[str, Any]:
    return {
        "$schema": "hocuspocus://schemas/graph-spec/v0.4",
        "kind": "graph_spec",
        "graphSpecVersion": "0.4",
        "languageVersion": "0.3",
        "name": graph.name,
        "target": fields["target"],
        "category": fields["category"],
        "mode": fields["mode"],
        "expectedRevision": fields["revision"],
        "ownership": fields["ownership"],
        "externalNodes": [item.to_dict() for item in external_nodes],
        "nodes": [item.to_dict() for item in nodes],
        "display": fields["display"],
        "render": fields["render"],
        "output": fields["output"],
        "layout": fields["layout"],
        "span": graph.span.to_dict(),
        "fieldSpans": {
            key: value.to_dict() for key, value in sorted(field_spans.items())
        },
    }


def _build_control_expansion_map(
    entry_uri: str,
    graph_span: SourceSpan,
    graph: Mapping[str, Any],
    field_spans: Mapping[str, SourceSpan],
    external_origins: list[_Origin],
    state: _State,
) -> dict[str, Any]:
    mappings: list[dict[str, Any]] = []
    module_stacks: dict[str, dict[str, Any]] = {}
    control_stacks: dict[str, dict[str, Any]] = {}

    def add(pointer: str, origin: _Origin) -> None:
        state.checkpoint(origin.span)
        if len(mappings) >= state.limits.source_map_entries:
            raise ModuleExpansionError(
                "HOCUS464", "Expanded graph exceeds the source-map limit.", origin.span,
            )
        stack_id = None
        if origin.module_frames:
            frames = [item.to_dict() for item in origin.module_frames]
            stack_id = _digest({"domain": _MODULE_STACK_DOMAIN, "frames": frames})
            module_stacks.setdefault(stack_id, {"stackId": stack_id, "frames": frames})
        control_stack_id = None
        if origin.control_frames:
            frames = list(origin.control_frames)
            control_stack_id = _digest({"domain": _CONTROL_STACK_DOMAIN, "frames": frames})
            control_stacks.setdefault(
                control_stack_id,
                {"controlStackId": control_stack_id, "frames": frames},
            )
        payload = {
            "generatedPointer": pointer,
            "originKind": origin.kind,
            "primarySpan": origin.span.to_dict(),
            "relatedOrigins": [
                {"role": role, "span": span.to_dict()}
                for role, span in origin.related
            ],
            "stackId": stack_id,
            "controlStackId": control_stack_id,
        }
        mappings.append({"originId": _digest(payload), **payload})

    add("", _Origin(graph_span))
    for index, origin in enumerate(external_origins):
        add(f"/externalNodes/{index}", origin)
    for index, (node_origin, input_origins, parm_origins) in enumerate(state.node_origins):
        add(f"/nodes/{index}", node_origin)
        for child, origin in enumerate(input_origins):
            add(f"/nodes/{index}/inputs/{child}", origin)
        for child, origin in enumerate(parm_origins):
            add(f"/nodes/{index}/parms/{child}", origin)
    for name in ("display", "render", "output", "layout"):
        if graph[name] is not None:
            add(f"/{name}", _Origin(field_spans[name]))
    mappings.sort(key=lambda item: item["generatedPointer"])
    return {
        "$schema": "hocuspocus://schemas/expansion-map/v2",
        "kind": "hocus_expansion_map",
        "schemaVersion": 2,
        "graphSpecVersion": "0.4",
        "entrySourceUri": entry_uri,
        "stacks": [module_stacks[key] for key in sorted(module_stacks)],
        "controlStacks": [control_stacks[key] for key in sorted(control_stacks)],
        "mappings": mappings,
    }


def _check_control_depth(
    frames: tuple[dict[str, Any], ...], span: SourceSpan, state: _State,
) -> None:
    if len(frames) > state.limits.instance_depth:
        raise ModuleExpansionError("HOCUS464", "Control stack exceeds its depth limit.", span)


def _selected_producer_controls(
    producer: tuple[dict[str, Any], ...],
    selected: tuple[dict[str, Any], ...],
) -> tuple[dict[str, Any], ...]:
    """Keep only a genuinely nested producer under the current selection."""

    if len(producer) > len(selected) and producer[:len(selected)] == selected:
        return producer
    return selected


def _bounded_related(
    prefix: tuple[tuple[str, SourceSpan], ...],
    existing: tuple[tuple[str, SourceSpan], ...], span: SourceSpan,
) -> tuple[tuple[str, SourceSpan], ...]:
    result: list[tuple[str, SourceSpan]] = []
    seen: set[tuple[str, str]] = set()
    for role, item_span in (*prefix, *existing):
        key = (role, json.dumps(item_span.to_dict(), sort_keys=True, separators=(",", ":")))
        if key not in seen:
            seen.add(key)
            result.append((role, item_span))
    if len(result) > 16:
        raise ModuleExpansionError(
            "HOCUS464", "Control value provenance exceeds 16 related origins.", span,
        )
    return tuple(result)


def _check_cancel(callback: Callable[[], bool] | None, span: SourceSpan) -> None:
    if callback is None:
        return
    try:
        result = callback()
    except Exception as exc:
        raise ModuleExpansionError("HOCUS499", "Cancellation callback failed.", span) from exc
    if type(result) is not bool:
        raise ModuleExpansionError("HOCUS499", "Cancellation callback must return a boolean.", span)
    if result:
        raise ModuleExpansionError("HOCUS499", "Control expansion was cancelled.", span)


def _digest(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=True,
        allow_nan=False,
    )
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _synthetic_span() -> SourceSpan:
    from .diagnostics import SourcePosition
    position = SourcePosition(0, 1, 1)
    return SourceSpan("<control-expansion>", position, position)

"""Pure, bounded HocusScript 0.2 module interface checking and expansion."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from .diagnostics import SourceSpan
from .model import (
    ExpansionFrame, ExpansionMap, ExpansionOrigin, ExpansionStack, ExternalNodeSpec, GraphSpec,
    InputSpec, LiteralValue, MODULE_GRAPH_SPEC_VERSION, NodeReference, NodeSpec,
    ParmSpec, RelatedOrigin,
)
from .syntax import (
    CategoryStmt, ExportStmt, ExternalDecl, FlagStmt, GraphDecl, InputStmt,
    LayoutStmt, LiteralExpr, ModeStmt, ModuleDecl, ModuleExportDecl,
    ModuleParamDecl, NodeDecl, OwnershipStmt, ParamRefExpr, ParmStmt,
    RevisionStmt, SymbolRefExpr, SyntaxSource, TargetStmt, UseDecl,
)

MODULE_TYPES = frozenset({"bool", "int", "float", "string", "node_output"})
RESERVED_SYMBOL_PREFIX = "__hocus_"
_DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


class ModuleExpansionError(ValueError):
    def __init__(self, code: str, message: str, span: SourceSpan, *, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.span = span
        self.details = dict(details or {})


@dataclass(frozen=True, slots=True)
class ExpansionLimits:
    import_depth: int = 64
    instance_depth: int = 64
    instances: int = 4096
    parameters_per_module: int = 256
    exports_per_module: int = 256
    expanded_nodes: int = 10_000
    aggregate_code_bytes: int = 4 * 1024 * 1024
    source_map_entries: int = 100_000
    diagnostics: int = 500

    def __post_init__(self) -> None:
        maxima = {
            "import_depth": 64, "instance_depth": 64, "instances": 4096,
            "parameters_per_module": 256, "exports_per_module": 256,
            "expanded_nodes": 10_000, "aggregate_code_bytes": 4_194_304,
            "source_map_entries": 100_000, "diagnostics": 500,
        }
        for name, maximum in maxima.items():
            value = getattr(self, name)
            if type(value) is not int or not 1 <= value <= maximum:
                raise ValueError(f"ExpansionLimits.{name} must be an integer from 1 to {maximum}.")

    @classmethod
    def from_resolved(cls, value: Any) -> "ExpansionLimits":
        return cls(
            import_depth=value.import_depth, instance_depth=value.instance_depth,
            instances=value.instances, parameters_per_module=value.parameters_per_module,
            exports_per_module=value.exports_per_module, expanded_nodes=value.expanded_nodes,
            aggregate_code_bytes=value.aggregate_code_bytes,
            source_map_entries=value.source_map_entries, diagnostics=value.diagnostics,
        )


@dataclass(frozen=True, slots=True)
class ResolvedModuleUnit:
    uri: str
    source_digest: str
    syntax: SyntaxSource
    imports: Mapping[str, Any] = field(default_factory=dict)

    @property
    def declaration(self) -> ModuleDecl:
        if self.syntax.module is None or self.syntax.graph is not None:
            raise ModuleExpansionError("HOCUS460", "Resolved module source must contain exactly one module.", self.syntax.span)
        return self.syntax.module


def resolved_units_from_dag(dag: Any) -> dict[str, ResolvedModuleUnit]:
    """Adapt a validated ResolvedModuleDag using only its immutable in-memory bytes."""

    from .parser import parse_syntax

    units: dict[str, ResolvedModuleUnit] = {}
    for record in dag.ordered_modules:
        dependency = record.dependency
        from .resolved_modules import module_source_digest
        if module_source_digest(record.source) != dependency.source_digest:
            raise ModuleExpansionError("HOCUS460", "Resolved DAG module bytes conflict with their digest.", _synthetic_span())
        try:
            source = record.source.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise ModuleExpansionError("HOCUS460", "Resolved module source is not UTF-8.", _synthetic_span()) from exc
        syntax = parse_syntax(source, dependency.uri)
        if len(syntax.imports) != len(record.imports):
            raise ModuleExpansionError("HOCUS463", "Resolved DAG module imports conflict with exact source.", syntax.span)
        for declaration, resolved_import in zip(syntax.imports, record.imports):
            _validate_resolved_import(declaration, resolved_import)
        if tuple(sorted(item.target_uri for item in record.imports)) != dependency.dependencies:
            raise ModuleExpansionError("HOCUS463", "Resolved DAG module import targets conflict with locked dependencies.", syntax.span)
        units[dependency.uri] = ResolvedModuleUnit(
            dependency.uri, dependency.source_digest, syntax,
            {item.local_name: item for item in record.imports},
        )
    return units


def resolved_import_map(imports: Any) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for item in imports:
        if item.local_name in result:
            raise ModuleExpansionError("HOCUS463", "Duplicate local import aliases are forbidden.", item.span)
        result[item.local_name] = item
    return result


@dataclass(frozen=True, slots=True)
class _Bound:
    type_name: str
    value: Any
    span: SourceSpan
    parameter_spans: tuple[SourceSpan, ...] = ()


@dataclass(slots=True)
class _Origin:
    span: SourceSpan
    frames: tuple[ExpansionFrame, ...]
    kind: str = "definition"
    related: tuple[RelatedOrigin, ...] = ()


@dataclass(slots=True)
class _State:
    limits: ExpansionLimits
    cancel: Callable[[], bool] | None
    nodes: list[NodeSpec] = field(default_factory=list)
    node_origins: list[tuple[_Origin, list[_Origin], list[_Origin]]] = field(default_factory=list)
    instance_count: int = 0
    root_symbols: dict[str, str] = field(default_factory=dict)
    code_bytes: int = 0

    def checkpoint(self) -> None:
        _check_cancel(self.cancel, _synthetic_span())


def validate_module_interfaces(
    modules: Mapping[str, ResolvedModuleUnit], *, limits: ExpansionLimits = ExpansionLimits(),
    cancellation: Callable[[], bool] | None = None,
) -> None:
    """Validate typed interfaces and the caller-supplied import graph without I/O."""

    for uri in sorted(modules):
        _check_cancel(cancellation, modules[uri].syntax.span)
        unit = modules[uri]
        _validate_unit_provenance(uri, unit)
        module = unit.declaration
        _reject_reserved(module.name, module.name_span)
        if len(module.parameters) > limits.parameters_per_module or len(module.exports) > limits.exports_per_module:
            raise ModuleExpansionError("HOCUS461", "Module interface exceeds declared limits.", module.span)
        _unique_named(module.parameters, "parameter")
        _unique_named(module.exports, "export")
        for parameter in module.parameters:
            _reject_reserved(parameter.name, parameter.name_span)
            _require_type(parameter.type_name, parameter.type_span)
            if parameter.default is not None:
                if not isinstance(parameter.default, LiteralExpr):
                    raise ModuleExpansionError("HOCUS462", "Module parameter defaults must be literals.", parameter.default.span)
                actual = _literal_type(parameter.default.value, parameter.default.span)
                if actual != parameter.type_name:
                    _type_mismatch(parameter.type_name, actual, parameter.default.span)
        for export in module.exports:
            _reject_reserved(export.name, export.name_span)
            _require_type(export.type_name, export.type_span)
        _validate_local_symbols(module)
        declared_imports = {item.local_name: item for item in unit.syntax.imports}
        if len(declared_imports) != len(unit.syntax.imports):
            raise ModuleExpansionError("HOCUS463", "Duplicate local import aliases are forbidden.", unit.syntax.span)
        if set(declared_imports) != set(unit.imports):
            raise ModuleExpansionError("HOCUS463", "Resolved imports do not exactly match source imports.", unit.syntax.span)
        for local_name, resolved_import in sorted(unit.imports.items()):
            target_uri = _target_uri(resolved_import)
            _validate_resolved_import(declared_imports[local_name], resolved_import)
            _reject_reserved(local_name, declared_imports[local_name].local_name_span)
            target = modules.get(target_uri)
            if target is None:
                raise ModuleExpansionError("HOCUS463", "Resolved import targets an unknown module URI.", declared_imports[local_name].span)
            if declared_imports[local_name].imported_name != target.declaration.name:
                raise ModuleExpansionError("HOCUS463", "Imported name does not match the target module declaration.", declared_imports[local_name].span)
        _validate_module_body(unit, modules)
    _validate_import_dag(modules, limits.import_depth)


def expand_module_graph(
    *,
    entry_source: bytes,
    entry_uri: str,
    entry_imports: Mapping[str, Any],
    modules: Mapping[str, ResolvedModuleUnit],
    limits: ExpansionLimits = ExpansionLimits(),
    cancellation: Callable[[], bool] | None = None,
) -> GraphSpec:
    """Expand a parsed graph and validated in-memory module DAG into GraphSpec 0.3.

    Module file-count and source-byte budgets belong to ``validate_resolved_module_dag``;
    this pure stage independently revalidates provenance, interfaces, and expansion budgets.
    """

    entry = _parse_entry_source(entry_source, entry_uri)
    entry_source_digest = "sha256:" + hashlib.sha256(entry_source).hexdigest()
    if entry.graph is None or entry.module is not None or entry.version is None or entry.version.value != "0.2":
        raise ModuleExpansionError("HOCUS460", "Expansion requires one HocusScript 0.2 graph entry source.", entry.span)
    entry_identity = _canonical_uri(entry_uri)
    if (
        entry_identity is None or entry_identity[0] != "project"
        or _DIGEST_PATTERN.fullmatch(entry_source_digest) is None
        or entry.span.source_name != entry_uri
    ):
        raise ModuleExpansionError("HOCUS460", "Entry URI or source digest is not canonical.", entry.span)
    validate_module_interfaces(modules, limits=limits, cancellation=cancellation)
    declared_entry_imports = {item.local_name: item for item in entry.imports}
    if len(declared_entry_imports) != len(entry.imports):
        raise ModuleExpansionError("HOCUS463", "Duplicate local import aliases are forbidden.", entry.span)
    if set(declared_entry_imports) != set(entry_imports):
        raise ModuleExpansionError("HOCUS463", "Resolved entry imports do not exactly match source imports.", entry.span)
    for local_name, resolved_import in entry_imports.items():
        uri = _target_uri(resolved_import)
        _validate_resolved_import(declared_entry_imports[local_name], resolved_import)
        if uri not in modules or declared_entry_imports[local_name].imported_name != modules[uri].declaration.name:
            raise ModuleExpansionError("HOCUS463", "Entry import does not match a resolved module.", declared_entry_imports[local_name].span)

    state = _State(limits, cancellation)
    graph = entry.graph
    _validate_graph_symbols(graph)
    graph_identity = _digest({"entryUri": entry_uri, "graphName": graph.name})
    root_scope: dict[str, _Bound] = {
        statement.symbol: _node_bound(statement, entry_uri, (), graph_identity)
        for statement in graph.statements if isinstance(statement, NodeDecl)
    }
    root_scope.update({
        statement.symbol: _Bound("node_output", (statement.symbol, 0), statement.span)
        for statement in graph.statements if isinstance(statement, ExternalDecl)
    })
    state.root_symbols.update({name: bound.value[0] for name, bound in root_scope.items()})
    root_use_exports: dict[str, dict[str, _Bound]] = {}
    directives: list[Any] = []
    for statement in graph.statements:
        state.checkpoint()
        if isinstance(statement, NodeDecl):
            bound = _emit_node(
                statement, entry_uri, (), (), graph_identity, {}, root_scope, root_use_exports, state
            )
            root_scope[statement.symbol] = bound
        elif isinstance(statement, UseDecl):
            exports = _expand_use(
                statement, entry_imports, modules, (), (),
                graph_identity, {}, root_scope, root_use_exports, state, active=(),
            )
            root_use_exports[statement.symbol] = exports
        else:
            directives.append(statement)

    spec = _build_graph_spec(entry, directives, state.nodes, graph_identity, entry_uri, state)
    if len(state.nodes) > limits.expanded_nodes:
        raise ModuleExpansionError("HOCUS464", "Expanded graph exceeds the node limit.", graph.span)
    if len(spec.expansion_map.mappings) > limits.source_map_entries:
        raise ModuleExpansionError("HOCUS464", "Expanded graph exceeds the source-map limit.", graph.span)
    _validate_expanded_graph(spec, modules, limits)
    return spec


def expand_resolved_module_dag(
    dag: Any, *, limits: ExpansionLimits | None = None,
    cancellation: Callable[[], bool] | None = None,
) -> GraphSpec:
    """Expand only the exact entry bytes retained by a validated ResolvedModuleDag."""

    from .resolved_modules import ResolvedModuleDag, _resolved_dag_handoff_digest, module_source_digest
    if not isinstance(dag, ResolvedModuleDag):
        raise TypeError("dag must be a validated ResolvedModuleDag")
    if module_source_digest(dag.entry_source) != dag.entry_source_digest:
        raise ModuleExpansionError("HOCUS460", "Resolved DAG entry bytes conflict with their digest.", dag.entry_syntax.span)
    reparsed = _parse_entry_source(dag.entry_source, dag.entry_source_uri)
    if reparsed != dag.entry_syntax:
        raise ModuleExpansionError("HOCUS460", "Resolved DAG entry AST conflicts with its exact bytes.", dag.entry_syntax.span)
    resolved_set = _validate_retained_resolved_set(dag)
    expected_handoff_digest = _resolved_dag_handoff_digest(
        entry_source_uri=dag.entry_source_uri,
        entry_source_digest=dag.entry_source_digest,
        entry_imports=dag.entry_imports,
        ordered_modules=dag.ordered_modules,
        resolved_module_set_json=dag.resolved_module_set_json,
        catalog_content_digest=dag.catalog_content_digest,
        catalog_fingerprint=dag.catalog_fingerprint,
    )
    if (
        not isinstance(dag.handoff_digest, str)
        or _DIGEST_PATTERN.fullmatch(dag.handoff_digest) is None
        or not hmac.compare_digest(dag.handoff_digest, expected_handoff_digest)
    ):
        raise ModuleExpansionError("HOCUS460", "Resolved DAG handoff seal is invalid.", dag.entry_syntax.span)
    resolved_limits = _limits_from_contract(resolved_set["limits"])
    selected = limits or resolved_limits
    if limits is not None:
        for field_name in (
            "import_depth", "instance_depth", "instances", "parameters_per_module",
            "exports_per_module", "expanded_nodes", "aggregate_code_bytes",
            "source_map_entries", "diagnostics",
        ):
            if getattr(limits, field_name) > getattr(resolved_limits, field_name):
                raise ModuleExpansionError("HOCUS464", "Expansion limits exceed the resolved DAG contract.", dag.entry_syntax.span)
    return expand_module_graph(
        entry_source=dag.entry_source,
        entry_uri=dag.entry_source_uri,
        entry_imports=resolved_import_map(dag.entry_imports),
        modules=resolved_units_from_dag(dag),
        limits=selected,
        cancellation=cancellation,
    )


def _expand_use(
    use: UseDecl, imports: Mapping[str, Any],
    modules: Mapping[str, ResolvedModuleUnit], seed_path: tuple[str, ...],
    frames: tuple[ExpansionFrame, ...], graph_identity: str, parameters: Mapping[str, _Bound],
    local_nodes: Mapping[str, _Bound], local_uses: Mapping[str, dict[str, _Bound]], state: _State,
    *, active: tuple[str, ...],
) -> dict[str, _Bound]:
    state.checkpoint()
    if not use.explicit_id:
        raise ModuleExpansionError("HOCUS465", "Every module use requires a durable @id seed.", use.span)
    _reject_reserved(use.symbol, use.symbol_span)
    resolved_import = imports.get(use.module_name)
    target_uri = _target_uri(resolved_import) if resolved_import is not None else None
    if target_uri is None or target_uri not in modules:
        raise ModuleExpansionError("HOCUS466", f"Unknown imported module: {use.module_name}.", use.module_name_span)
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
    import_span = _resolved_import_span(resolved_import)
    frame = ExpansionFrame(
        target_uri, unit.source_digest, module.name, use.symbol, next_path,
        import_span, use.span,
    )
    next_frames = (*frames, frame)
    arguments = _bind_arguments(use, module.parameters, parameters, local_nodes, local_uses)
    nested_nodes: dict[str, _Bound] = {
        statement.symbol: _node_bound(statement, target_uri, next_path, graph_identity)
        for statement in module.statements if isinstance(statement, NodeDecl)
    }
    nested_uses: dict[str, dict[str, _Bound]] = {}
    export_statements: dict[str, ExportStmt] = {}
    for statement in module.statements:
        state.checkpoint()
        if isinstance(statement, NodeDecl):
            nested_nodes[statement.symbol] = _emit_node(
                statement, target_uri, next_path, next_frames, graph_identity,
                arguments, nested_nodes, nested_uses, state,
            )
        elif isinstance(statement, UseDecl):
            nested_uses[statement.symbol] = _expand_use(
                statement, unit.imports, modules, next_path,
                next_frames, graph_identity, arguments, nested_nodes, nested_uses, state,
                active=(*active, target_uri),
            )
        elif isinstance(statement, ExportStmt):
            if statement.name in export_statements:
                raise ModuleExpansionError("HOCUS468", f"Duplicate export definition: {statement.name}.", statement.span)
            export_statements[statement.name] = statement
    declarations = {item.name: item for item in module.exports}
    if set(export_statements) != set(declarations):
        raise ModuleExpansionError("HOCUS468", "Module export definitions do not exactly match its interface.", module.span)
    result: dict[str, _Bound] = {}
    for name, declaration in declarations.items():
        statement = export_statements[name]
        bound = _resolve_expr(statement.value, arguments, nested_nodes, nested_uses)
        if bound.type_name != declaration.type_name:
            _type_mismatch(declaration.type_name, bound.type_name, statement.value.span)
        result[name] = bound
    return result


def _bind_arguments(
    use: UseDecl, declarations: tuple[ModuleParamDecl, ...], parameters: Mapping[str, _Bound],
    nodes: Mapping[str, _Bound], uses: Mapping[str, dict[str, _Bound]],
) -> dict[str, _Bound]:
    authored: dict[str, Any] = {}
    for argument in use.arguments:
        if argument.name in authored:
            raise ModuleExpansionError("HOCUS469", f"Duplicate named argument: {argument.name}.", argument.span)
        authored[argument.name] = argument
    expected = {item.name for item in declarations}
    unknown = set(authored) - expected
    if unknown:
        argument = authored[sorted(unknown)[0]]
        raise ModuleExpansionError("HOCUS469", f"Unknown named argument: {argument.name}.", argument.span)
    bound: dict[str, _Bound] = {}
    for declaration in declarations:
        argument = authored.get(declaration.name)
        if argument is None:
            if declaration.default is None:
                raise ModuleExpansionError("HOCUS469", f"Missing required argument: {declaration.name}.", use.span)
            value = _Bound(declaration.type_name, declaration.default, declaration.default.span, (declaration.span,))
        else:
            resolved = _resolve_expr(argument.value, parameters, nodes, uses)
            if resolved.type_name != declaration.type_name:
                _type_mismatch(declaration.type_name, resolved.type_name, argument.value.span)
            related_spans = (*resolved.parameter_spans, declaration.span)
            if len(related_spans) > 16:
                raise ModuleExpansionError("HOCUS464", "Forwarded parameter provenance exceeds 16 origins.", argument.value.span)
            value = _Bound(
                resolved.type_name, resolved.value, resolved.span,
                related_spans,
            )
        bound[declaration.name] = value
    return bound


def _emit_node(
    node: NodeDecl, module_uri: str, seed_path: tuple[str, ...], frames: tuple[ExpansionFrame, ...],
    graph_identity: str, parameters: Mapping[str, _Bound], nodes: Mapping[str, _Bound],
    uses: Mapping[str, dict[str, _Bound]], state: _State,
) -> _Bound:
    state.checkpoint()
    if len(state.nodes) >= state.limits.expanded_nodes:
        raise ModuleExpansionError("HOCUS464", "Expanded graph exceeds the node limit.", node.span)
    _reject_reserved(node.symbol, node.symbol_span)
    identity_bound = _node_bound(node, module_uri, seed_path, graph_identity)
    symbol, _ = identity_bound.value
    identity = "sha256:" + symbol.removeprefix(RESERVED_SYMBOL_PREFIX)
    inputs: list[InputSpec] = []
    parms: list[ParmSpec] = []
    input_origins: list[_Origin] = []
    parm_origins: list[_Origin] = []
    for statement in node.statements:
        if isinstance(statement, InputStmt):
            if statement.index < 0:
                raise ModuleExpansionError("HOCUS474", "Node input index must be nonnegative.", statement.index_span)
            bound = _resolve_expr(statement.source, parameters, nodes, uses)
            if bound.type_name != "node_output":
                _type_mismatch("node_output", bound.type_name, statement.source.span)
            ref_symbol, output_index = bound.value
            if type(output_index) is not int or output_index < 0:
                raise ModuleExpansionError("HOCUS474", "Node output index must be nonnegative.", statement.source.span)
            inputs.append(InputSpec(
                statement.index,
                NodeReference(ref_symbol, output_index, bound.span, {"symbol": bound.span, "outputIndex": bound.span}),
                statement.span, {"index": statement.index_span},
            ))
            related = tuple(RelatedOrigin("parameter_declaration", span) for span in bound.parameter_spans)
            input_origins.append(_Origin(bound.span, frames, "argument" if related else "definition", related))
        elif isinstance(statement, ParmStmt):
            bound = _resolve_expr(statement.value, parameters, nodes, uses)
            if bound.type_name == "node_output":
                raise ModuleExpansionError("HOCUS470", "node_output cannot be assigned to a scalar parameter.", statement.value.span)
            literal = bound.value if isinstance(bound.value, LiteralExpr) else LiteralExpr(bound.value, bound.span)
            parms.append(ParmSpec(statement.name, LiteralValue(literal.value, bound.span), statement.span, {"name": statement.name_span}))
            related = tuple(RelatedOrigin("parameter_declaration", span) for span in bound.parameter_spans)
            parm_origins.append(_Origin(bound.span, frames, "argument" if related else "definition", related))
    explicit_id = "hocus." + identity.removeprefix("sha256:")
    spec = NodeSpec(
        symbol, node.type_name, inputs, parms, node.span,
        {"symbol": node.symbol_span, "typeName": node.type_span, "explicitId": node.explicit_id_span or node.symbol_span},
        explicit_id,
    )
    state.nodes.append(spec)
    state.node_origins.append((_Origin(node.span, frames), input_origins, parm_origins))
    return _Bound("node_output", (symbol, 0), node.span)


def _node_bound(node: NodeDecl, module_uri: str, seed_path: tuple[str, ...], graph_identity: str) -> _Bound:
    seed = node.explicit_id or node.symbol
    identity = _digest({
        "graphIdentity": graph_identity, "instanceIdPath": list(seed_path),
        "moduleUri": module_uri, "localSeed": seed,
    })
    return _Bound("node_output", (RESERVED_SYMBOL_PREFIX + identity.removeprefix("sha256:"), 0), node.span)


def _resolve_expr(
    expr: Any, parameters: Mapping[str, _Bound], nodes: Mapping[str, _Bound],
    uses: Mapping[str, dict[str, _Bound]],
) -> _Bound:
    if isinstance(expr, LiteralExpr):
        return _Bound(_literal_type(expr.value, expr.span), expr, expr.span)
    if isinstance(expr, ParamRefExpr):
        if expr.name not in parameters:
            raise ModuleExpansionError("HOCUS471", f"Unknown module parameter: {expr.name}.", expr.span)
        return parameters[expr.name]
    if isinstance(expr, SymbolRefExpr):
        if expr.symbol in nodes:
            if expr.member != "output" or expr.output_index is None:
                raise ModuleExpansionError("HOCUS471", "Node references must select output[index].", expr.span)
            symbol, _ = nodes[expr.symbol].value
            return _Bound("node_output", (symbol, expr.output_index), expr.span)
        if expr.symbol in uses:
            if expr.output_index is not None or expr.member not in uses[expr.symbol]:
                raise ModuleExpansionError("HOCUS471", "Unknown nested module export.", expr.span)
            return uses[expr.symbol][expr.member]
        raise ModuleExpansionError("HOCUS471", f"Unknown module symbol: {expr.symbol}.", expr.span)
    # Entry graph input references retain the 0.1 ReferenceExpr shape.
    if hasattr(expr, "symbol") and hasattr(expr, "output_index") and expr.symbol in nodes:
        symbol, _ = nodes[expr.symbol].value
        return _Bound("node_output", (symbol, expr.output_index), expr.span)
    raise ModuleExpansionError("HOCUS471", "Unsupported module expression.", expr.span)


def _build_graph_spec(
    entry: SyntaxSource, directives: list[Any], nodes: list[NodeSpec], graph_identity: str,
    entry_uri: str, state: _State,
) -> GraphSpec:
    graph = entry.graph
    target = category = ownership = display = render = output = layout = None
    mode = "merge"
    revision = None
    field_spans = {"name": graph.name_span, "languageVersion": entry.version.value_span}
    external_nodes: list[ExternalNodeSpec] = []
    external_origins: list[_Origin] = []
    # Entry directives do not currently select instance exports; node names are remapped by source span.
    authored_to_generated = state.root_symbols
    for statement in directives:
        if isinstance(statement, TargetStmt): target, field_spans["target"] = statement.value, statement.value_span
        elif isinstance(statement, CategoryStmt): category, field_spans["category"] = statement.value, statement.value_span
        elif isinstance(statement, ModeStmt): mode, field_spans["mode"] = statement.value, statement.value_span
        elif isinstance(statement, RevisionStmt): revision, field_spans["expectedRevision"] = statement.value, statement.value_span
        elif isinstance(statement, OwnershipStmt): ownership, field_spans["ownership"] = statement.value, statement.value_span
        elif isinstance(statement, ExternalDecl):
            external_nodes.append(ExternalNodeSpec(
                statement.symbol, statement.path, statement.adopted, statement.span,
                {"symbol": statement.symbol_span, "path": statement.path_span},
            ))
            external_origins.append(_Origin(statement.span, ()))
        elif isinstance(statement, FlagStmt):
            value = authored_to_generated.get(statement.symbol, statement.symbol)
            field_spans[statement.name] = statement.value_span
            if statement.name == "display": display = value
            elif statement.name == "render": render = value
            else: output = value
        elif isinstance(statement, LayoutStmt): layout, field_spans["layout"] = statement.value, statement.value_span
    placeholder = ExpansionMap(entry_uri)
    spec = GraphSpec(
        "0.2", graph.name, target, category, mode, revision, ownership, external_nodes,
        nodes, display, render, output, layout, graph.span, field_spans,
        MODULE_GRAPH_SPEC_VERSION, placeholder,
    )
    mappings: list[ExpansionOrigin] = []
    stacks: dict[str, ExpansionStack] = {}

    def add(pointer: str, origin: _Origin) -> None:
        stack_id = None
        if origin.frames:
            frames = [frame.to_dict() for frame in origin.frames]
            stack_id = _digest({"domain": "hocus-expansion-stack-v1", "frames": frames})
            stacks.setdefault(stack_id, ExpansionStack(stack_id, origin.frames))
        payload = {
            "generatedPointer": pointer, "originKind": origin.kind,
            "primarySpan": origin.span.to_dict(),
            "relatedOrigins": [item.to_dict() for item in origin.related], "stackId": stack_id,
        }
        mappings.append(ExpansionOrigin(
            _digest(payload), pointer, origin.kind, origin.span, origin.related, stack_id,
        ))

    add("", _Origin(graph.span, ()))
    for index, origin in enumerate(external_origins):
        add(f"/externalNodes/{index}", origin)
    for index, (node_origin, input_origins, parm_origins) in enumerate(state.node_origins):
        add(f"/nodes/{index}", node_origin)
        for child, origin in enumerate(input_origins): add(f"/nodes/{index}/inputs/{child}", origin)
        for child, origin in enumerate(parm_origins): add(f"/nodes/{index}/parms/{child}", origin)
    for name in ("display", "render", "output", "layout"):
        if getattr(spec, name) is not None:
            add(f"/{name}", _Origin(field_spans[name], ()))
    mappings.sort(key=lambda item: item.generated_pointer)
    spec.expansion_map = ExpansionMap(entry_uri, tuple(stacks[key] for key in sorted(stacks)), tuple(mappings))
    return spec


def _validate_module_body(unit: ResolvedModuleUnit, modules: Mapping[str, ResolvedModuleUnit]) -> None:
    module = unit.declaration
    parameters = {item.name: item.type_name for item in module.parameters}
    nodes: dict[str, str] = {
        statement.symbol: "node_output" for statement in module.statements if isinstance(statement, NodeDecl)
    }
    uses: dict[str, dict[str, str]] = {}
    for statement in module.statements:
        if isinstance(statement, UseDecl):
            resolved_import = unit.imports.get(statement.module_name)
            if resolved_import is None or _target_uri(resolved_import) not in modules:
                raise ModuleExpansionError("HOCUS466", f"Unknown imported module: {statement.module_name}.", statement.module_name_span)
            target = modules[_target_uri(resolved_import)].declaration
            uses[statement.symbol] = {item.name: item.type_name for item in target.exports}
    exports: dict[str, ExportStmt] = {}
    for statement in module.statements:
        if isinstance(statement, NodeDecl):
            for child in statement.statements:
                if isinstance(child, InputStmt):
                    actual = _infer_expr_type(child.source, parameters, nodes, uses)
                    if actual != "node_output":
                        _type_mismatch("node_output", actual, child.source.span)
                    if child.index < 0 or getattr(child.source, "output_index", 0) is not None and getattr(child.source, "output_index", 0) < 0:
                        raise ModuleExpansionError("HOCUS474", "Node input/output indices must be nonnegative.", child.span)
                elif isinstance(child, ParmStmt) and isinstance(child.value, (ParamRefExpr, SymbolRefExpr, LiteralExpr)):
                    actual = _infer_expr_type(child.value, parameters, nodes, uses)
                    if actual == "node_output":
                        raise ModuleExpansionError("HOCUS470", "node_output cannot be assigned to a scalar parameter.", child.value.span)
        elif isinstance(statement, UseDecl):
            resolved_import = unit.imports.get(statement.module_name)
            if resolved_import is None:
                raise ModuleExpansionError("HOCUS466", f"Unknown imported module: {statement.module_name}.", statement.module_name_span)
            target = modules[_target_uri(resolved_import)].declaration
            authored: dict[str, Any] = {}
            for argument in statement.arguments:
                if argument.name in authored:
                    raise ModuleExpansionError("HOCUS469", f"Duplicate named argument: {argument.name}.", argument.span)
                authored[argument.name] = argument
            declared = {item.name: item for item in target.parameters}
            if set(authored) - set(declared):
                argument = authored[sorted(set(authored) - set(declared))[0]]
                raise ModuleExpansionError("HOCUS469", f"Unknown named argument: {argument.name}.", argument.span)
            for name, declaration in declared.items():
                if name not in authored:
                    if declaration.default is None:
                        raise ModuleExpansionError("HOCUS469", f"Missing required argument: {name}.", statement.span)
                    continue
                actual = _infer_expr_type(authored[name].value, parameters, nodes, uses)
                if actual != declaration.type_name:
                    _type_mismatch(declaration.type_name, actual, authored[name].value.span)
        elif isinstance(statement, ExportStmt):
            if statement.name in exports:
                raise ModuleExpansionError("HOCUS468", f"Duplicate export definition: {statement.name}.", statement.span)
            exports[statement.name] = statement
    declarations = {item.name: item for item in module.exports}
    if set(exports) != set(declarations):
        raise ModuleExpansionError("HOCUS468", "Module export definitions do not exactly match its interface.", module.span)
    for name, declaration in declarations.items():
        actual = _infer_expr_type(exports[name].value, parameters, nodes, uses)
        if actual != declaration.type_name:
            _type_mismatch(declaration.type_name, actual, exports[name].value.span)


def _infer_expr_type(
    expr: Any, parameters: Mapping[str, str], nodes: Mapping[str, str],
    uses: Mapping[str, Mapping[str, str]],
) -> str:
    if isinstance(expr, LiteralExpr):
        return _literal_type(expr.value, expr.span)
    if isinstance(expr, ParamRefExpr):
        if expr.name not in parameters:
            raise ModuleExpansionError("HOCUS471", f"Unknown module parameter: {expr.name}.", expr.span)
        return parameters[expr.name]
    if isinstance(expr, SymbolRefExpr):
        if expr.symbol in nodes:
            if expr.member != "output" or expr.output_index is None or expr.output_index < 0:
                raise ModuleExpansionError("HOCUS471", "Node references must select output[index].", expr.span)
            return "node_output"
        if expr.symbol in uses and expr.output_index is None and expr.member in uses[expr.symbol]:
            return uses[expr.symbol][expr.member]
        raise ModuleExpansionError("HOCUS471", "Unknown module symbol or export.", expr.span)
    if hasattr(expr, "symbol") and hasattr(expr, "output_index") and expr.symbol in nodes:
        if expr.output_index < 0:
            raise ModuleExpansionError("HOCUS471", "Node output index must be nonnegative.", expr.span)
        return "node_output"
    raise ModuleExpansionError("HOCUS471", "Unsupported module expression.", expr.span)


def _validate_expanded_graph(
    spec: GraphSpec, modules: Mapping[str, ResolvedModuleUnit], limits: ExpansionLimits,
) -> None:
    from .bundle import BundleValidationError, _validate_graph_spec

    records = {
        uri: {
            "uri": uri,
            "moduleName": unit.declaration.name,
            "sourceDigest": unit.source_digest,
        }
        for uri, unit in modules.items()
    }
    try:
        _validate_graph_spec(
            spec.to_dict(), graph_spec_version=MODULE_GRAPH_SPEC_VERSION,
            module_dependencies=records, entry_source_uri=spec.expansion_map.entry_source_uri,
            module_limits={
                "expandedNodes": limits.expanded_nodes,
                "sourceMapEntries": limits.source_map_entries,
                "instances": limits.instances,
                "instanceDepth": limits.instance_depth,
                "aggregateCodeBytes": limits.aggregate_code_bytes,
            },
        )
    except BundleValidationError as exc:
        raise ModuleExpansionError(
            "HOCUS478", "Expanded graph failed strict GraphSpec 0.3 validation.", spec.span,
            details={"validatorCode": exc.code},
        ) from exc


def _validate_import_dag(modules: Mapping[str, ResolvedModuleUnit], max_depth: int) -> None:
    state: dict[str, int] = {}
    depth: dict[str, int] = {}
    for start in sorted(modules):
        if state.get(start) == 2:
            continue
        stack: list[tuple[str, bool]] = [(start, False)]
        while stack:
            uri, exiting = stack.pop()
            if exiting:
                depth[uri] = 1 + max((depth[_target_uri(child)] for child in modules[uri].imports.values()), default=0)
                if depth[uri] > max_depth:
                    raise ModuleExpansionError("HOCUS464", "Module import depth exceeds its limit.", modules[uri].syntax.span)
                state[uri] = 2
                continue
            if state.get(uri) == 1:
                raise ModuleExpansionError("HOCUS467", "Module import cycle detected.", modules[uri].syntax.span)
            if state.get(uri) == 2:
                continue
            state[uri] = 1
            stack.append((uri, True))
            for child in sorted((_target_uri(item) for item in modules[uri].imports.values()), reverse=True):
                if state.get(child) == 1:
                    raise ModuleExpansionError("HOCUS467", "Module import cycle detected.", modules[uri].syntax.span)
                stack.append((child, False))


def _validate_local_symbols(module: ModuleDecl) -> None:
    seen: set[str] = set()
    use_ids: set[str] = set()
    node_seeds: set[str] = set()
    for statement in module.statements:
        if isinstance(statement, (NodeDecl, UseDecl)):
            _reject_reserved(statement.symbol, statement.symbol_span)
            if statement.symbol in seen:
                raise ModuleExpansionError("HOCUS473", f"Duplicate local symbol: {statement.symbol}.", statement.span)
            seen.add(statement.symbol)
        if isinstance(statement, UseDecl):
            if not statement.explicit_id:
                raise ModuleExpansionError("HOCUS465", "Every module use requires a durable @id seed.", statement.span)
            if statement.explicit_id in use_ids:
                raise ModuleExpansionError("HOCUS473", f"Duplicate module use @id: {statement.explicit_id}.", statement.span)
            use_ids.add(statement.explicit_id)
        elif isinstance(statement, NodeDecl):
            _validate_node_shape(statement)
            seed = statement.explicit_id or statement.symbol
            if seed in node_seeds:
                raise ModuleExpansionError("HOCUS473", f"Duplicate effective node identity seed: {seed}.", statement.span)
            node_seeds.add(seed)


def _validate_graph_symbols(graph: GraphDecl) -> None:
    seen: set[str] = set()
    ids: set[str] = set()
    node_seeds: set[str] = set()
    for statement in graph.statements:
        if isinstance(statement, (NodeDecl, UseDecl, ExternalDecl)):
            _reject_reserved(statement.symbol, statement.symbol_span)
            if statement.symbol in seen:
                raise ModuleExpansionError("HOCUS473", f"Duplicate graph symbol: {statement.symbol}.", statement.span)
            seen.add(statement.symbol)
        if isinstance(statement, UseDecl):
            if statement.explicit_id in ids:
                raise ModuleExpansionError("HOCUS473", f"Duplicate module use @id: {statement.explicit_id}.", statement.span)
            ids.add(statement.explicit_id)
        elif isinstance(statement, NodeDecl):
            _validate_node_shape(statement)
            seed = statement.explicit_id or statement.symbol
            if seed in node_seeds:
                raise ModuleExpansionError("HOCUS473", f"Duplicate effective node identity seed: {seed}.", statement.span)
            node_seeds.add(seed)


def _validate_node_shape(node: NodeDecl) -> None:
    if not node.type_name.strip() or len(node.type_name) > 4096:
        raise ModuleExpansionError("HOCUS477", "Node operator type must not be empty.", node.type_span)
    inputs: set[int] = set()
    parms: set[str] = set()
    for statement in node.statements:
        if isinstance(statement, InputStmt):
            if statement.index < 0:
                raise ModuleExpansionError("HOCUS474", "Node input index must be nonnegative.", statement.index_span)
            if statement.index in inputs:
                raise ModuleExpansionError("HOCUS477", f"Duplicate node input index: {statement.index}.", statement.span)
            inputs.add(statement.index)
            output_index = getattr(statement.source, "output_index", None)
            if output_index is not None and (type(output_index) is not int or output_index < 0):
                raise ModuleExpansionError("HOCUS474", "Node output index must be nonnegative.", statement.source.span)
        elif isinstance(statement, ParmStmt):
            if statement.name in parms:
                raise ModuleExpansionError("HOCUS477", f"Duplicate node parameter assignment: {statement.name}.", statement.span)
            parms.add(statement.name)


def _unique_named(items: tuple[Any, ...], label: str) -> None:
    seen: set[str] = set()
    for item in items:
        if item.name in seen:
            raise ModuleExpansionError("HOCUS473", f"Duplicate module {label}: {item.name}.", item.span)
        seen.add(item.name)


def _literal_type(value: Any, span: SourceSpan) -> str:
    if type(value) is bool: return "bool"
    if type(value) is int: return "int"
    if type(value) is float: return "float"
    if type(value) is str: return "string"
    raise ModuleExpansionError("HOCUS474", "Module literals must be bool, int, float, or string.", span)


def _require_type(type_name: str, span: SourceSpan) -> None:
    if type_name not in MODULE_TYPES:
        raise ModuleExpansionError("HOCUS474", f"Unsupported module type: {type_name}.", span)


def _type_mismatch(expected: str, actual: str, span: SourceSpan) -> None:
    raise ModuleExpansionError(
        "HOCUS475", f"Module type mismatch: expected {expected}, received {actual}.", span,
        details={"expected": expected, "actual": actual},
    )


def _reject_reserved(symbol: str, span: SourceSpan) -> None:
    if symbol.startswith(RESERVED_SYMBOL_PREFIX):
        raise ModuleExpansionError("HOCUS476", f"Authored symbol uses reserved prefix {RESERVED_SYMBOL_PREFIX}.", span)


def _target_uri(resolved_import: Any) -> str:
    target_uri = getattr(resolved_import, "target_uri", None)
    if isinstance(target_uri, str):
        return target_uri
    raise TypeError("Resolved imports must expose canonical target_uri provenance")


def _parse_entry_source(source: bytes, uri: str) -> SyntaxSource:
    if type(source) is not bytes:
        raise TypeError("entry_source must be exact bytes")
    if len(source) > 1_048_576:
        raise ModuleExpansionError("HOCUS464", "Entry source exceeds the 1 MiB limit.", _synthetic_span())
    try:
        text = source.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ModuleExpansionError("HOCUS460", "Entry source must be valid UTF-8.", _synthetic_span()) from exc
    from .parser import parse_syntax
    try:
        return parse_syntax(text, uri)
    except Exception as exc:
        raise ModuleExpansionError("HOCUS460", "Entry source failed strict parsing.", _synthetic_span()) from exc


def _limits_from_contract(value: Mapping[str, Any]) -> ExpansionLimits:
    return ExpansionLimits(
        import_depth=value["importDepth"], instance_depth=value["instanceDepth"],
        instances=value["instances"], parameters_per_module=value["parametersPerModule"],
        exports_per_module=value["exportsPerModule"], expanded_nodes=value["expandedNodes"],
        aggregate_code_bytes=value["aggregateCodeBytes"],
        source_map_entries=value["sourceMapEntries"], diagnostics=value["diagnostics"],
    )


def _validate_retained_resolved_set(dag: Any) -> dict[str, Any]:
    try:
        value = json.loads(dag.resolved_module_set_json)
        canonical = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ModuleExpansionError("HOCUS460", "Resolved DAG module set is not canonical JSON.", dag.entry_syntax.span) from exc
    if canonical != dag.resolved_module_set_json:
        raise ModuleExpansionError("HOCUS460", "Resolved DAG module set is not canonical JSON.", dag.entry_syntax.span)
    keys = {
        "$schema", "kind", "schemaVersion", "languageVersion", "projectUid",
        "entrySourceUri", "projectManifestDigest", "projectLockDigest",
        "resolverPolicyDigest", "limits", "modules",
    }
    entry_identity = _canonical_uri(dag.entry_source_uri)
    if (
        not isinstance(value, dict) or set(value) != keys
        or value["$schema"] != "hocuspocus://schemas/resolved-module-set/v1"
        or value["kind"] != "hocus_resolved_module_set"
        or value["schemaVersion"] != 1
        or value["languageVersion"] != "0.2"
        or value["entrySourceUri"] != dag.entry_source_uri
        or entry_identity is None or value["projectUid"] != entry_identity[1]
        or any(
            not isinstance(value[field], str) or _DIGEST_PATTERN.fullmatch(value[field]) is None
            for field in ("projectManifestDigest", "projectLockDigest", "resolverPolicyDigest")
        )
    ):
        raise ModuleExpansionError("HOCUS460", "Resolved DAG module-set envelope is inconsistent.", dag.entry_syntax.span)
    limit_maxima = {
        "sourceBytesPerFile": 1_048_576, "aggregateSourceBytes": 8_388_608,
        "moduleFiles": 4096, "importDepth": 64, "instanceDepth": 64,
        "instances": 4096, "parametersPerModule": 256, "exportsPerModule": 256,
        "expandedNodes": 10_000, "aggregateCodeBytes": 4_194_304,
        "sourceMapEntries": 100_000, "diagnostics": 500,
    }
    limits = value["limits"]
    if (
        not isinstance(limits, dict) or set(limits) != set(limit_maxima)
        or any(type(limits[key]) is not int or not 1 <= limits[key] <= maximum
               for key, maximum in limit_maxima.items())
    ):
        raise ModuleExpansionError("HOCUS460", "Resolved DAG module-set limits are invalid.", dag.entry_syntax.span)
    expected_modules = sorted(
        (record.dependency.to_dict() for record in dag.ordered_modules),
        key=lambda item: item["uri"],
    )
    if value["modules"] != expected_modules or len(expected_modules) > limits["moduleFiles"]:
        raise ModuleExpansionError("HOCUS460", "Resolved DAG module projection conflicts with retained records.", dag.entry_syntax.span)
    return value


def _validate_resolved_import(declaration: Any, resolved_import: Any) -> None:
    if (
        getattr(resolved_import, "specifier", None) != declaration.specifier
        or getattr(resolved_import, "imported_name", None) != declaration.imported_name
        or getattr(resolved_import, "local_name", None) != declaration.local_name
        or getattr(resolved_import, "span", None) != declaration.span
    ):
        raise ModuleExpansionError("HOCUS463", "Resolved import provenance conflicts with its declaration.", declaration.span)


def _validate_unit_provenance(mapping_uri: str, unit: ResolvedModuleUnit) -> None:
    if (
        mapping_uri != unit.uri
        or _canonical_uri(unit.uri) is None
        or _DIGEST_PATTERN.fullmatch(unit.source_digest) is None
        or unit.syntax.span.source_name != unit.uri
    ):
        raise ModuleExpansionError("HOCUS460", "Resolved module URI/digest provenance is not canonical.", unit.syntax.span)


def _canonical_uri(value: Any) -> tuple[str, str, str] | None:
    # Kept behind one adapter so the resolver remains the URI authority.
    from .resolved_modules import canonical_module_uri
    return canonical_module_uri(value)


def _resolved_import_span(resolved_import: Any) -> SourceSpan | None:
    span = getattr(resolved_import, "span", None)
    return span if isinstance(span, SourceSpan) else None


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
        raise ModuleExpansionError("HOCUS499", "Module expansion was cancelled.", span)


def _digest(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _synthetic_span() -> SourceSpan:
    from .diagnostics import SourcePosition
    position = SourcePosition(0, 1, 1)
    return SourceSpan("<expansion>", position, position)

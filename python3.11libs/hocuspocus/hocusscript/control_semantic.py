from __future__ import annotations
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping
from ._control_ast_validation import _ControlAstAdmissionBudget, validate_control_syntax_ast
from .control_limits import ControlExpansionLimits
from .diagnostics import CodeOffsetMap, SourceSpan
from .expander import (
    MODULE_TYPES,
    ModuleExpansionError,
    ResolvedModuleUnit,
    _check_cancel,
    _canonical_uri,
    _literal_type,
    _validate_node_shape,
    _validate_resolved_import,
    _validate_unit_provenance,
)
from .syntax import (
    ArrayExpr,
    CategoryStmt,
    CodeExpr,
    ExportStmt,
    ExternalDecl,
    FlagStmt,
    ForDecl,
    GraphDecl,
    IfDecl,
    InputStmt,
    LayoutStmt,
    LiteralExpr,
    ModuleDecl,
    ModeStmt,
    NodeDecl,
    ParamRefExpr,
    ParmStmt,
    RevisionStmt,
    OwnershipStmt,
    SymbolRefExpr,
    SyntaxSource,
    TaggedValueExpr,
    TargetStmt,
    UseDecl,
    YieldStmt,
)
from .editor_syntax import EditorEntityDecl
from .editor_semantic import validate_graph_editor_declarations
from .runtime_carrier import is_runtime_declaration, validate_node_runtime_source
from .value_semantic_validation import validate_tagged_value
from .port_selectors import require_selector, selector_is_valid
_SPECIAL_REFERENCE_ROOTS = frozenset({"param", "iter", "carry"})
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_IDENTITY_SEED = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")

@dataclass(slots=True)
class _Scope:
    parameters: dict[str, str] = field(default_factory=dict)
    nodes: dict[str, str] = field(default_factory=dict)
    uses: dict[str, dict[str, str]] = field(default_factory=dict)
    controls: dict[str, dict[str, str]] = field(default_factory=dict)
    iterators: dict[str, str] = field(default_factory=dict)
    carries: dict[str, str] = field(default_factory=dict)

    def child(self) -> "_Scope":
        return _Scope(
            dict(self.parameters),
            dict(self.nodes),
            dict(self.uses),
            dict(self.controls),
            dict(self.iterators),
            dict(self.carries),
        )

@dataclass(slots=True)
class _ValidationState:
    modules: Mapping[str, ResolvedModuleUnit]
    limits: ControlExpansionLimits
    cancellation: Callable[[], bool] | None
    language_version: str = "0.3"
    node_parameter_observer: Callable[[NodeDecl, tuple[str, ...]], None] | None = None
    declarations: int = 0
    code_bytes: int = 0
    value_nodes: int = 0

    def checkpoint(self, span: Any) -> None:
        _check_cancel(self.cancellation, span)

    def claim_declaration(self, span: Any) -> None:
        self.checkpoint(span)
        self.declarations += 1
        if self.declarations > self.limits.source_map_entries:
            raise ModuleExpansionError(
                "HOCUS464", "Static declarations exceed the source-map limit.", span
            )

    def claim_value(self, span: Any) -> None:
        self.checkpoint(span)
        self.value_nodes += 1
        if self.value_nodes > 100_000:
            raise ModuleExpansionError(
                "HOCUS464", "Aggregate parameter values exceed 100000 nodes.", span
            )

def validate_control_program(
    entry: SyntaxSource,
    entry_imports: Mapping[str, Any],
    modules: Mapping[str, ResolvedModuleUnit],
    *,
    limits: ControlExpansionLimits = ControlExpansionLimits(),
    cancellation: Callable[[], bool] | None = None,
    _node_parameter_observer: Callable[[NodeDecl, tuple[str, ...]], None] | None = None,
) -> None:
    """Validate one exact control graph plus its complete immutable closure.

    Validation visits all branches and folds without evaluating or doing I/O.
    """

    if not isinstance(entry, SyntaxSource):
        raise TypeError("entry must be a SyntaxSource")
    if not isinstance(entry_imports, Mapping):
        raise TypeError("entry_imports must be a mapping")
    if not isinstance(modules, Mapping):
        raise TypeError("modules must be a mapping")
    if not isinstance(limits, ControlExpansionLimits):
        raise TypeError("limits must be a ControlExpansionLimits")
    ast_budget = _ControlAstAdmissionBudget()
    validate_control_syntax_ast(entry, cancellation=cancellation, budget=ast_budget)
    if (
        entry.version is None
        or entry.version.value not in {"0.3", "0.4"}
        or entry.graph is None
        or entry.module is not None
    ):
        raise ModuleExpansionError(
            "HOCUS460", "Control validation requires one HocusScript 0.3 or 0.4 graph entry.", entry.span
        )

    try:
        state = _ValidationState(
            modules, limits, cancellation, entry.version.value,
            _node_parameter_observer,
        )
        state.checkpoint(entry.span)
        _validate_module_mapping(modules, entry.span)
        _validate_module_syntax_trees(modules, cancellation, ast_budget)
        _validate_modules(modules, state)
        _validate_import_dag(modules, limits.import_depth, state)
        _validate_entry_imports(entry, entry_imports, modules, state)
        _require_complete_closure(entry_imports, modules, entry.span, state)

        graph = entry.graph
        _validate_graph_directives(graph, state)
        scope = _Scope()
        _validate_graph_body(graph, entry_imports, scope, state)
    except ModuleExpansionError:
        raise
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise ModuleExpansionError(
            "HOCUS479", "Control syntax tree contains malformed field values.", entry.span
        ) from exc


def _validate_module_syntax_trees(
    modules: Mapping[str, ResolvedModuleUnit],
    cancellation: Callable[[], bool] | None,
    budget: _ControlAstAdmissionBudget,
) -> None:
    for uri in sorted(modules):
        validate_control_syntax_ast(modules[uri].syntax, cancellation=cancellation, budget=budget)


def _validate_module_mapping(modules: Mapping[str, ResolvedModuleUnit], span: Any) -> None:
    try:
        items = tuple(modules.items())
    except Exception as exc:
        raise ModuleExpansionError(
            "HOCUS460", "Resolved control module mapping is malformed.", span
        ) from exc
    if any(type(uri) is not str or not isinstance(unit, ResolvedModuleUnit) for uri, unit in items):
        raise ModuleExpansionError(
            "HOCUS460", "Resolved control modules require canonical string keys and exact units.", span
        )


def _validate_graph_directives(graph: GraphDecl, state: _ValidationState) -> None:
    _require_authored_name(graph.name, graph.name_span)
    _validate_graph_statement_shape(graph, state)
    directives, flags = _collect_graph_directives(graph)
    target = _validate_graph_options(graph, directives)
    known, mutable = _validate_graph_externals(graph, target, state)
    _validate_graph_flags(flags, known, mutable, state)
    validate_graph_editor_declarations(graph, directives, known, mutable)


def _collect_graph_directives(
    graph: GraphDecl,
) -> tuple[dict[str, list[Any]], dict[str, list[FlagStmt]]]:
    directive_types = {
        "target": TargetStmt,
        "category": CategoryStmt,
        "mode": ModeStmt,
        "revision": RevisionStmt,
        "ownership": OwnershipStmt,
        "layout": LayoutStmt,
    }
    directives = {
        name: [item for item in graph.statements if isinstance(item, item_type)]
        for name, item_type in directive_types.items()
    }
    flags = {
        name: [item for item in graph.statements if isinstance(item, FlagStmt) and item.name == name]
        for name in ("display", "render", "output")
    }
    for items in (*directives.values(), *flags.values()):
        if len(items) > 1:
            raise ModuleExpansionError(
                "HOCUS473", "Duplicate graph directive in a forged control AST.", items[1].span
            )
    return directives, flags


def _validate_graph_options(graph: GraphDecl, directives: Mapping[str, list[Any]]) -> str:
    targets = directives["target"]
    categories = directives["category"]
    modes = directives["mode"]
    revisions = directives["revision"]
    ownerships = directives["ownership"]
    layouts = directives["layout"]
    if len(targets) != 1 or not _is_canonical_houdini_path(targets[0].value):
        raise ModuleExpansionError(
            "HOCUS302", "Graph target must be one canonical absolute Houdini path.",
            targets[0].span if targets else graph.span,
        )
    target = targets[0].value
    if categories and (
        type(categories[0].value) is not str
        or _IDENTIFIER.fullmatch(categories[0].value) is None
    ):
        raise ModuleExpansionError(
            "HOCUS479", "Graph category must be a bounded identifier.", categories[0].span
        )
    mode = modes[0].value if modes else "merge"
    if mode not in {"merge", "reconcile"}:
        raise ModuleExpansionError(
            "HOCUS303", "Graph mode must be merge or reconcile.", modes[0].span
        )
    if revisions:
        revision = revisions[0].value
        if type(revision) is not int or revision < 0:
            raise ModuleExpansionError(
                "HOCUS304", "Expected revision must be a nonnegative integer.", revisions[0].span
            )
    ownership = ownerships[0].value if ownerships else None
    if ownership is not None and (type(ownership) is not str or not ownership.strip()):
        raise ModuleExpansionError(
            "HOCUS319", "Ownership namespace must not be blank.", ownerships[0].span
        )
    if mode == "reconcile" and ownership is None:
        raise ModuleExpansionError(
            "HOCUS305", "Reconcile mode requires an ownership namespace.",
            modes[0].span if modes else graph.span,
        )
    if layouts and layouts[0].value != "auto":
        raise ModuleExpansionError(
            "HOCUS316", "Language 0.3 supports only layout = auto.", layouts[0].span
        )
    return target


def _validate_graph_statement_shape(
    graph: GraphDecl,
    state: _ValidationState,
) -> None:
    allowed = (
        TargetStmt,
        CategoryStmt,
        ModeStmt,
        RevisionStmt,
        OwnershipStmt,
        LayoutStmt,
        ExternalDecl,
        FlagStmt,
        NodeDecl,
        UseDecl,
        IfDecl,
        ForDecl,
        EditorEntityDecl,
    )
    for statement in graph.statements:
        state.checkpoint(statement.span)
        if not isinstance(statement, allowed) or (
            isinstance(statement, FlagStmt)
            and statement.name not in {"display", "render", "output"}
        ):
            raise ModuleExpansionError(
                "HOCUS479", "Unsupported statement in a control graph.", statement.span
            )


def _validate_graph_externals(
    graph: GraphDecl,
    target: str,
    state: _ValidationState,
) -> tuple[set[str], set[str]]:
    externals = [item for item in graph.statements if isinstance(item, ExternalDecl)]
    mutable = {
        item.symbol for item in graph.statements if isinstance(item, NodeDecl)
    }
    known = set(mutable)
    prefix = target.rstrip("/") + "/"
    for external in externals:
        state.checkpoint(external.span)
        if type(external.adopted) is not bool or not _is_canonical_houdini_path(external.path):
            raise ModuleExpansionError(
                "HOCUS310", "External node paths must be canonical absolute paths.", external.span
            )
        if external.path != target and not external.path.startswith(prefix):
            raise ModuleExpansionError(
                "HOCUS311", "External node path is outside the graph target scope.", external.span
            )
        known.add(external.symbol)
        if external.adopted:
            mutable.add(external.symbol)
    return known, mutable


def _validate_graph_flags(
    flags: Mapping[str, list[FlagStmt]],
    known: set[str],
    mutable: set[str],
    state: _ValidationState,
) -> None:
    for name, items in flags.items():
        if not items:
            continue
        state.checkpoint(items[0].span)
        symbol = items[0].symbol
        if symbol not in known:
            raise ModuleExpansionError(
                "HOCUS315", f"Unknown {name} symbol: {symbol}.", items[0].span
            )
        if symbol not in mutable:
            raise ModuleExpansionError(
                "HOCUS318", f"Read-only existing symbol cannot be selected as {name}.", items[0].span
            )


def _is_canonical_houdini_path(value: Any) -> bool:
    if type(value) is not str:
        return False
    if value == "/":
        return True
    if not value.startswith("/") or value.endswith("/"):
        return False
    return all(segment not in {"", ".", ".."} for segment in value.split("/")[1:])


def _validate_modules(
    modules: Mapping[str, ResolvedModuleUnit], state: _ValidationState
) -> None:
    for uri in sorted(modules):
        unit = modules[uri]
        state.checkpoint(unit.syntax.span)
        _validate_unit_provenance(uri, unit)
        syntax = unit.syntax
        if (
            syntax.version is None
            or syntax.version.value != state.language_version
            or syntax.module is None
            or syntax.graph is not None
        ):
            raise ModuleExpansionError(
                "HOCUS460",
                f"Resolved control modules must use HocusScript {state.language_version}.",
                syntax.span,
            )
        module = syntax.module
        _require_authored_name(module.name, module.name_span)
        if (
            len(module.parameters) > state.limits.parameters_per_module
            or len(module.exports) > state.limits.exports_per_module
        ):
            raise ModuleExpansionError(
                "HOCUS461", "Module interface exceeds declared limits.", module.span
            )
        parameter_types = _validate_interface(module.parameters, "parameter")
        export_types = _validate_interface(module.exports, "export")
        for parameter in module.parameters:
            state.checkpoint(parameter.span)
            if parameter.default is not None:
                if not isinstance(parameter.default, LiteralExpr):
                    raise ModuleExpansionError(
                        "HOCUS462", "Module parameter defaults must be literals.", parameter.default.span
                    )
                actual = _literal_type(parameter.default.value, parameter.default.span)
                if actual != parameter.type_name:
                    _type_mismatch(parameter.type_name, actual, parameter.default.span)

        declared_imports = _validate_import_envelope(syntax, unit.imports, state.modules, state)
        resolved_aliases = {
            name for name, _ in _resolved_import_items(unit.imports, syntax.span)
        }
        if set(declared_imports) != resolved_aliases:
            raise ModuleExpansionError(
                "HOCUS463", "Resolved imports do not exactly match source imports.", syntax.span
            )
        scope = _Scope(parameters=parameter_types)
        _validate_module_body(module, unit.imports, export_types, scope, state)


def _validate_interface(items: tuple[Any, ...], label: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in items:
        if item.name in result:
            raise ModuleExpansionError(
                "HOCUS473", f"Duplicate module {label}: {item.name}.", item.span
            )
        _require_type(item.type_name, item.type_span)
        _require_authored_name(item.name, item.name_span)
        result[item.name] = item.type_name
    return result


def _validate_entry_imports(
    entry: SyntaxSource,
    entry_imports: Mapping[str, Any],
    modules: Mapping[str, ResolvedModuleUnit],
    state: _ValidationState,
) -> None:
    declared = _validate_import_envelope(entry, entry_imports, modules, state)
    resolved_aliases = {
        name for name, _ in _resolved_import_items(entry_imports, entry.span)
    }
    if set(declared) != resolved_aliases:
        raise ModuleExpansionError(
            "HOCUS463", "Resolved entry imports do not exactly match source imports.", entry.span
        )


def _validate_import_envelope(
    syntax: SyntaxSource,
    imports: Mapping[str, Any],
    modules: Mapping[str, ResolvedModuleUnit],
    state: _ValidationState,
) -> dict[str, Any]:
    import_items = _resolved_import_items(imports, syntax.span)
    declared: dict[str, Any] = {}
    for declaration in syntax.imports:
        state.checkpoint(declaration.span)
        _require_authored_name(declaration.imported_name, declaration.imported_name_span)
        _require_authored_name(declaration.local_name, declaration.local_name_span)
        if declaration.local_name in declared:
            raise ModuleExpansionError(
                "HOCUS463", "Duplicate local import aliases are forbidden.", declaration.span
            )
        declared[declaration.local_name] = declaration
    for local_name, resolved_import in import_items:
        state.checkpoint(syntax.span)
        if type(local_name) is not str:
            raise ModuleExpansionError(
                "HOCUS463", "Resolved import aliases must be strings.", syntax.span
            )
        declaration = declared.get(local_name)
        if declaration is None:
            raise ModuleExpansionError(
                "HOCUS463", "Resolved imports do not exactly match source imports.", syntax.span
            )
        try:
            _validate_resolved_import(declaration, resolved_import)
        except ModuleExpansionError:
            raise
        except Exception as exc:
            raise ModuleExpansionError(
                "HOCUS463", "Resolved import provenance is malformed.", declaration.span
            ) from exc
        target_uri = _resolved_target_uri(resolved_import, declaration.span)
        target = modules.get(target_uri)
        if target is None or declaration.imported_name != target.declaration.name:
            raise ModuleExpansionError(
                "HOCUS463", "Import does not match a resolved control module.", declaration.span
            )
    return declared


def _require_complete_closure(
    entry_imports: Mapping[str, Any],
    modules: Mapping[str, ResolvedModuleUnit],
    span: Any,
    state: _ValidationState,
) -> None:
    reachable: set[str] = set()
    pending = sorted(
        (
            _resolved_target_uri(item, span)
            for _, item in _resolved_import_items(entry_imports, span)
        ),
        reverse=True,
    )
    while pending:
        state.checkpoint(span)
        uri = pending.pop()
        if uri in reachable:
            continue
        reachable.add(uri)
        pending.extend(
            sorted(
                (
                    _resolved_target_uri(item, modules[uri].syntax.span)
                    for _, item in _resolved_import_items(
                        modules[uri].imports, modules[uri].syntax.span
                    )
                ),
                reverse=True,
            )
        )
    if reachable != set(modules):
        raise ModuleExpansionError(
            "HOCUS463", "Resolved modules do not exactly match the entry closure.", span
        )


def _validate_graph_body(
    graph: GraphDecl,
    imports: Mapping[str, Any],
    scope: _Scope,
    state: _ValidationState,
) -> None:
    statements = tuple(
        statement
        for statement in graph.statements
        if isinstance(statement, (NodeDecl, UseDecl, IfDecl, ForDecl))
    )
    externals = tuple(
        statement for statement in graph.statements if isinstance(statement, ExternalDecl)
    )
    _scan_block_names((*externals, *statements), state)
    for external in externals:
        _require_unambiguous_name(external.symbol, external.symbol_span)
        scope.nodes[external.symbol] = "node_output"
    _predeclare_nodes(statements, scope, state)
    _validate_declarations(statements, imports, scope, state)


def _validate_module_body(
    module: ModuleDecl,
    imports: Mapping[str, Any],
    declared_exports: Mapping[str, str],
    scope: _Scope,
    state: _ValidationState,
) -> None:
    for statement in module.statements:
        state.checkpoint(statement.span)
        if not isinstance(statement, (NodeDecl, UseDecl, IfDecl, ForDecl, ExportStmt)):
            raise ModuleExpansionError(
                "HOCUS479", "Unsupported statement in a control module.", statement.span
            )
    declarations = tuple(
        statement
        for statement in module.statements
        if isinstance(statement, (NodeDecl, UseDecl, IfDecl, ForDecl))
    )
    _scan_block_names(declarations, state)
    _predeclare_nodes(declarations, scope, state)
    authored_exports: dict[str, ExportStmt] = {}
    for statement in module.statements:
        if isinstance(statement, (NodeDecl, UseDecl, IfDecl, ForDecl)):
            _validate_declaration(statement, imports, scope, state)
        elif isinstance(statement, ExportStmt):
            state.checkpoint(statement.span)
            if statement.name in authored_exports:
                raise ModuleExpansionError(
                    "HOCUS468", f"Duplicate export definition: {statement.name}.", statement.span
                )
            authored_exports[statement.name] = statement
            expected = declared_exports.get(statement.name)
            if expected is None:
                raise ModuleExpansionError(
                    "HOCUS468", f"Undeclared module export: {statement.name}.", statement.span
                )
            actual = _infer_expr_type(statement.value, scope, state.language_version)
            if actual != expected:
                _type_mismatch(expected, actual, statement.value.span)
    if set(authored_exports) != set(declared_exports):
        raise ModuleExpansionError(
            "HOCUS468", "Module export definitions do not exactly match its interface.", module.span
        )


def _validate_control_body(
    statements: tuple[Any, ...],
    imports: Mapping[str, Any],
    parent_scope: _Scope,
    expected_yields: Mapping[str, str],
    state: _ValidationState,
    owner_span: Any,
    control_depth: int,
) -> None:
    declarations = tuple(
        statement
        for statement in statements
        if isinstance(statement, (NodeDecl, UseDecl, IfDecl, ForDecl))
    )
    if any(not isinstance(item, (NodeDecl, UseDecl, IfDecl, ForDecl, YieldStmt)) for item in statements):
        invalid = next(
            item for item in statements
            if not isinstance(item, (NodeDecl, UseDecl, IfDecl, ForDecl, YieldStmt))
        )
        raise ModuleExpansionError(
            "HOCUS479", "Unsupported statement in a control body.", invalid.span
        )
    _scan_block_names(declarations, state)
    scope = parent_scope.child()
    _predeclare_nodes(declarations, scope, state)
    yielded: dict[str, YieldStmt] = {}
    saw_yield = False
    for statement in statements:
        if isinstance(statement, YieldStmt):
            saw_yield = True
            state.checkpoint(statement.span)
            if statement.name in yielded:
                raise ModuleExpansionError(
                    "HOCUS479", f"Duplicate control yield: {statement.name}.", statement.span
                )
            expected = expected_yields.get(statement.name)
            if expected is None:
                raise ModuleExpansionError(
                    "HOCUS479", f"Undeclared control yield: {statement.name}.", statement.span
                )
            actual = _infer_expr_type(statement.value, scope, state.language_version)
            if actual != expected:
                _type_mismatch(expected, actual, statement.value.span)
            yielded[statement.name] = statement
        else:
            if saw_yield:
                raise ModuleExpansionError(
                    "HOCUS479", "Control yields must be the trailing statements in their body.", statement.span
                )
            _validate_declaration(
                statement, imports, scope, state, control_depth=control_depth
            )
    if set(yielded) != set(expected_yields):
        raise ModuleExpansionError(
            "HOCUS479", "Control yields do not exactly match the declared interface.",
            statements[-1].span if statements else owner_span,
        )


def _validate_declarations(
    statements: tuple[Any, ...],
    imports: Mapping[str, Any],
    scope: _Scope,
    state: _ValidationState,
    *,
    control_depth: int = 0,
) -> None:
    for statement in statements:
        _validate_declaration(
            statement, imports, scope, state, control_depth=control_depth
        )


def _validate_declaration(
    statement: Any,
    imports: Mapping[str, Any],
    scope: _Scope,
    state: _ValidationState,
    *,
    control_depth: int = 0,
) -> None:
    state.claim_declaration(statement.span)
    if isinstance(statement, NodeDecl):
        _validate_node(statement, scope, state)
        return
    if isinstance(statement, UseDecl):
        scope.nodes.pop(statement.symbol, None)
        scope.controls.pop(statement.symbol, None)
        scope.uses[statement.symbol] = _validate_use(
            statement, imports, scope, state.modules, state.language_version)
        return
    if isinstance(statement, IfDecl):
        scope.nodes.pop(statement.symbol, None)
        scope.uses.pop(statement.symbol, None)
        scope.controls[statement.symbol] = _validate_if(
            statement, imports, scope, state, control_depth + 1
        )
        return
    if isinstance(statement, ForDecl):
        scope.nodes.pop(statement.symbol, None)
        scope.uses.pop(statement.symbol, None)
        scope.controls[statement.symbol] = _validate_for(
            statement, imports, scope, state, control_depth + 1
        )
        return
    raise ModuleExpansionError("HOCUS479", "Unsupported control declaration.", statement.span)


def _validate_node(node: NodeDecl, scope: _Scope, state: _ValidationState) -> None:
    _require_unambiguous_name(node.symbol, node.symbol_span)
    if node.explicit_id is not None:
        _require_identity_seed(node.explicit_id, node.explicit_id_span or node.symbol_span)
    if type(node.type_name) is not str:
        raise ModuleExpansionError(
            "HOCUS477", "Node operator type must be a string.", node.type_span
        )
    _validate_node_shape(node)
    validate_node_runtime_source(node, state.language_version)
    parameter_types: list[str] = []
    for child in (
        item for item in node.statements if not is_runtime_declaration(item)
    ):
        state.checkpoint(child.span)
        if isinstance(child, InputStmt):
            require_selector(
                child.index, child.name, state.language_version,
                ModuleExpansionError(
                    "HOCUS471", "Input must select one valid index or fixed name.", child.span))
            actual = _infer_expr_type(child.source, scope, state.language_version)
            if actual != "node_output":
                _type_mismatch("node_output", actual, child.source.span)
        elif isinstance(child, ParmStmt):
            if isinstance(child.value, ArrayExpr):
                _require_rich_value_lane(child.value, state)
                _validate_value_shape(child.value, state)
                parameter_types.append("array")
            elif isinstance(child.value, CodeExpr):
                _require_rich_value_lane(child.value, state)
                _validate_value_shape(child.value, state)
                parameter_types.append("code")
            elif isinstance(child.value, TaggedValueExpr):
                _require_rich_value_lane(child.value, state)
                validate_tagged_value(
                    child.value, scope, state, _validate_value_shape
                )
                parameter_types.append(f"tagged:{child.value.tag}")
            else:
                actual = _infer_expr_type(child.value, scope, state.language_version)
                if actual == "node_output":
                    raise ModuleExpansionError(
                        "HOCUS470", "node_output cannot be assigned to a scalar parameter.", child.value.span
                    )
                parameter_types.append(actual)
        else:
            raise ModuleExpansionError(
                "HOCUS479", "Unsupported statement in a control node.", child.span
            )
    if state.node_parameter_observer is not None:
        state.node_parameter_observer(node, tuple(parameter_types))


def _require_rich_value_lane(value: Any, state: _ValidationState) -> None:
    if state.language_version != "0.4":
        raise ModuleExpansionError(
            "HOCUS479",
            "Rich parameter values require HocusScript 0.4.",
            value.span,
        )


def _validate_value_shape(value: Any, state: _ValidationState, *, depth: int = 0) -> None:
    if depth > 64:
        raise ModuleExpansionError(
            "HOCUS464", "Value nesting exceeds the 64-level static limit.", value.span
        )
    state.claim_value(value.span)
    if isinstance(value, LiteralExpr):
        _literal_type(value.value, value.span)
        return
    if isinstance(value, ArrayExpr):
        for item in value.items:
            state.checkpoint(item.span)
            _validate_value_shape(item, state, depth=depth + 1)
        return
    if isinstance(value, CodeExpr):
        if (
            value.language not in {"vex", "python", "hscript"}
            or type(value.body) is not str
            or not isinstance(value.span, SourceSpan)
            or not isinstance(value.body_span, SourceSpan)
            or not isinstance(value.offset_map, CodeOffsetMap)
            or value.body_span.source_name != value.span.source_name
            or value.body_span.start.offset < value.span.start.offset
            or value.body_span.end.offset > value.span.end.offset
            or value.body_span.end.offset < value.body_span.start.offset
            or value.offset_map.body_length != len(value.body)
            or not value.offset_map.checkpoints
            or value.offset_map.checkpoints[0] != (0, value.body_span.start.offset)
            or value.offset_map.checkpoints[-1]
            != (value.offset_map.body_length, value.body_span.end.offset)
            or any(
                type(body_offset) is not int
                or type(source_offset) is not int
                or body_offset < 0
                or body_offset > value.offset_map.body_length
                or source_offset < value.body_span.start.offset
                or source_offset > value.body_span.end.offset
                for body_offset, source_offset in value.offset_map.checkpoints
            )
            or tuple(body for body, _ in value.offset_map.checkpoints)
            != tuple(sorted(set(body for body, _ in value.offset_map.checkpoints)))
            or tuple(source for _, source in value.offset_map.checkpoints)
            != tuple(sorted(source for _, source in value.offset_map.checkpoints))
        ):
            raise ModuleExpansionError(
                "HOCUS474", "Embedded code body/span/offset shape is invalid.", value.span
            )
        try:
            encoded_body = value.body.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise ModuleExpansionError(
                "HOCUS474", "Embedded code must be valid Unicode encodable as UTF-8.", value.span
            ) from exc
        state.code_bytes += len(encoded_body)
        if state.code_bytes > state.limits.aggregate_code_bytes:
            raise ModuleExpansionError(
                "HOCUS464", "Embedded code exceeds the aggregate code-byte limit.", value.span
            )
        return
    raise ModuleExpansionError("HOCUS474", "Unsupported parameter value shape.", value.span)


def _validate_use(
    use: UseDecl, imports: Mapping[str, Any], scope: _Scope,
    modules: Mapping[str, ResolvedModuleUnit], language_version: str,
) -> dict[str, str]:
    resolved_import = imports.get(use.module_name)
    if resolved_import is None:
        raise ModuleExpansionError(
            "HOCUS466", f"Unknown imported module: {use.module_name}.", use.module_name_span
        )
    target = modules.get(_resolved_target_uri(resolved_import, use.module_name_span))
    if target is None:
        raise ModuleExpansionError(
            "HOCUS466", f"Unknown imported module: {use.module_name}.", use.module_name_span
        )
    authored: dict[str, Any] = {}
    for argument in use.arguments:
        if argument.name in authored:
            raise ModuleExpansionError(
                "HOCUS469", f"Duplicate named argument: {argument.name}.", argument.span
            )
        authored[argument.name] = argument
    declared = {item.name: item for item in target.declaration.parameters}
    unknown = set(authored) - set(declared)
    if unknown:
        argument = authored[sorted(unknown)[0]]
        raise ModuleExpansionError(
            "HOCUS469", f"Unknown named argument: {argument.name}.", argument.span
        )
    for name, declaration in declared.items():
        argument = authored.get(name)
        if argument is None:
            if declaration.default is None:
                raise ModuleExpansionError(
                    "HOCUS469", f"Missing required argument: {name}.", use.span
                )
            continue
        actual = _infer_expr_type(argument.value, scope, language_version)
        if actual != declaration.type_name:
            _type_mismatch(declaration.type_name, actual, argument.value.span)
    return {item.name: item.type_name for item in target.declaration.exports}


def _validate_if(
    control: IfDecl,
    imports: Mapping[str, Any],
    scope: _Scope,
    state: _ValidationState,
    control_depth: int,
) -> dict[str, str]:
    _validate_control_depth(control_depth, control.span, state)
    outputs = _control_interface(
        control.outputs, "conditional output", control.span, state
    )
    state.checkpoint(control.condition_span)
    actual = _infer_expr_type(control.condition, scope, state.language_version)
    if actual != "bool":
        _type_mismatch("bool", actual, control.condition_span)
    _validate_control_body(
        control.then_body,
        imports,
        scope,
        outputs,
        state,
        control.span,
        control_depth,
    )
    _validate_control_body(
        control.else_body,
        imports,
        scope,
        outputs,
        state,
        control.span,
        control_depth,
    )
    return outputs


def _validate_for(
    control: ForDecl,
    imports: Mapping[str, Any],
    scope: _Scope,
    state: _ValidationState,
    control_depth: int,
) -> dict[str, str]:
    _validate_control_depth(control_depth, control.span, state)
    carries = _control_interface(control.carries, "fold carry", control.span, state)
    state.checkpoint(control.count_span)
    actual_count = _infer_expr_type(control.count, scope, state.language_version)
    if actual_count != "int":
        _type_mismatch("int", actual_count, control.count_span)
    if isinstance(control.count, LiteralExpr):
        if control.count.value < 0:
            raise ModuleExpansionError(
                "HOCUS475",
                "Fold count must evaluate to an exact nonnegative int.",
                control.count_span,
            )
        if control.count.value > state.limits.per_fold_iterations:
            raise ModuleExpansionError(
                "HOCUS464", "Fold exceeds perFoldIterations.", control.count_span
            )
    for declaration in control.carries:
        state.checkpoint(declaration.initial_span)
        actual = _infer_expr_type(declaration.initial, scope, state.language_version)
        if actual != declaration.type_name:
            _type_mismatch(declaration.type_name, actual, declaration.initial_span)
    body_scope = scope.child()
    body_scope.iterators[control.iterator] = "int"
    body_scope.carries.update(carries)
    _validate_control_body(
        control.body,
        imports,
        body_scope,
        carries,
        state,
        control.span,
        control_depth,
    )
    return carries


def _validate_control_depth(
    depth: int,
    span: Any,
    state: _ValidationState,
) -> None:
    if depth > min(16, state.limits.instance_depth):
        raise ModuleExpansionError(
            "HOCUS464", "Control nesting exceeds its depth limit.", span
        )


def _control_interface(
    items: tuple[Any, ...],
    label: str,
    owner_span: Any,
    state: _ValidationState,
) -> dict[str, str]:
    if not items:
        raise ModuleExpansionError(
            "HOCUS479", f"{label.capitalize()} interface must not be empty.", owner_span
        )
    if len(items) > 256:
        raise ModuleExpansionError(
            "HOCUS464", f"{label.capitalize()} interface exceeds 256 declarations.", owner_span
        )
    result: dict[str, str] = {}
    for item in items:
        state.checkpoint(item.span)
        if item.name in result:
            raise ModuleExpansionError(
                "HOCUS473", f"Duplicate {label}: {item.name}.", item.span
            )
        _require_type(item.type_name, item.type_span)
        _require_authored_name(item.name, item.name_span)
        result[item.name] = item.type_name
    return result


def _infer_expr_type(expr: Any, scope: _Scope, language_version: str) -> str:
    if isinstance(expr, LiteralExpr):
        return _literal_type(expr.value, expr.span)
    if isinstance(expr, ParamRefExpr):
        if expr.name not in scope.parameters:
            raise ModuleExpansionError(
                "HOCUS471", f"Unknown module parameter: {expr.name}.", expr.span
            )
        return scope.parameters[expr.name]
    if isinstance(expr, SymbolRefExpr):
        if expr.symbol == "iter":
            return _qualified_type(expr, scope.iterators, "fold iterator")
        if expr.symbol == "carry":
            return _qualified_type(expr, scope.carries, "fold carry")
        if expr.symbol in scope.nodes:
            valid = expr.member == "output" and selector_is_valid(
                expr.output_index, expr.output_name, language_version)
            if not valid:
                raise ModuleExpansionError(
                    "HOCUS471", "Node references must select output[index].", expr.span
                )
            return "node_output"
        members = scope.controls.get(expr.symbol)
        if members is None:
            members = scope.uses.get(expr.symbol)
        if members is not None and expr.output_index is None and expr.member in members:
            return members[expr.member]
        raise ModuleExpansionError(
            "HOCUS471", f"Unknown local symbol or typed member: {expr.symbol}.{expr.member}.", expr.span
        )
    raise ModuleExpansionError("HOCUS471", "Unsupported control expression.", expr.span)


def _qualified_type(expr: SymbolRefExpr, values: Mapping[str, str], label: str) -> str:
    if (
        expr.output_index is not None
        or expr.output_name is not None
        or expr.member not in values
    ):
        raise ModuleExpansionError(
            "HOCUS471", f"Unknown or inactive {label}: {expr.member}.", expr.span
        )
    return values[expr.member]


def _scan_block_names(
    statements: tuple[Any, ...], state: _ValidationState
) -> None:
    symbols: set[str] = set()
    seeds: set[str] = set()
    for statement in statements:
        state.checkpoint(statement.span)
        if isinstance(statement, ExternalDecl):
            symbol = statement.symbol
            symbol_span = statement.symbol_span
            seed = None
        elif isinstance(statement, (NodeDecl, UseDecl, IfDecl, ForDecl)):
            symbol = statement.symbol
            symbol_span = statement.symbol_span
            if isinstance(statement, NodeDecl):
                seed = statement.explicit_id or statement.symbol
            else:
                seed = statement.explicit_id
            if not seed:
                raise ModuleExpansionError(
                    "HOCUS465", "Every use/control requires a durable @id seed.", statement.span
                )
        else:
            continue
        _require_unambiguous_name(symbol, symbol_span)
        if symbol in symbols:
            raise ModuleExpansionError(
                "HOCUS473", f"Duplicate local symbol: {symbol}.", statement.span
            )
        symbols.add(symbol)
        if seed is not None:
            _require_identity_seed(
                seed,
                statement.explicit_id_span
                if getattr(statement, "explicit_id_span", None) is not None
                else symbol_span,
            )
            if seed in seeds:
                raise ModuleExpansionError(
                    "HOCUS473", f"Duplicate effective declaration identity seed: {seed}.", statement.span
                )
            seeds.add(seed)


def _predeclare_nodes(
    statements: tuple[Any, ...], scope: _Scope, state: _ValidationState
) -> None:
    for statement in statements:
        state.checkpoint(statement.span)
        if isinstance(statement, NodeDecl):
            scope.uses.pop(statement.symbol, None)
            scope.controls.pop(statement.symbol, None)
            scope.nodes[statement.symbol] = "node_output"


def _require_type(type_name: str, span: Any) -> None:
    if type_name not in MODULE_TYPES:
        raise ModuleExpansionError(
            "HOCUS474", f"Unsupported control type: {type_name}.", span
        )


def _require_unambiguous_name(name: str, span: Any) -> None:
    if name in _SPECIAL_REFERENCE_ROOTS:
        raise ModuleExpansionError(
            "HOCUS473", f"Authored declaration collides with reserved reference root: {name}.", span
        )
    _require_authored_name(name, span)


def _require_authored_name(name: str, span: Any) -> None:
    if type(name) is not str or _IDENTIFIER.fullmatch(name) is None:
        raise ModuleExpansionError(
            "HOCUS473", "Authored symbol must be a HocusScript identifier.", span
        )
    if name.startswith("__hocus_"):
        raise ModuleExpansionError(
            "HOCUS476", "Authored symbol uses reserved prefix __hocus_.", span
        )


def _require_identity_seed(seed: Any, span: Any) -> None:
    if type(seed) is not str or _IDENTITY_SEED.fullmatch(seed) is None:
        raise ModuleExpansionError(
            "HOCUS465", "Durable declaration identity seed is invalid.", span
        )


def _type_mismatch(expected: str, actual: str, span: Any) -> None:
    raise ModuleExpansionError(
        "HOCUS475",
        f"Control type mismatch: expected {expected}, received {actual}.",
        span,
        details={"expected": expected, "actual": actual},
    )


def _resolved_target_uri(resolved_import: Any, span: Any) -> str:
    try:
        target_uri = getattr(resolved_import, "target_uri", None)
        identity = _canonical_uri(target_uri) if type(target_uri) is str else None
    except Exception as exc:
        raise ModuleExpansionError(
            "HOCUS463", "Resolved import target URI is malformed.", span
        ) from exc
    if type(target_uri) is not str or identity is None:
        raise ModuleExpansionError(
            "HOCUS463", "Resolved import target URI is not canonical.", span
        )
    return target_uri


def _resolved_import_items(imports: Mapping[str, Any], span: Any) -> tuple[tuple[Any, Any], ...]:
    try:
        return tuple(imports.items())
    except Exception as exc:
        raise ModuleExpansionError(
            "HOCUS463", "Resolved import mapping is malformed.", span
        ) from exc


def _validate_import_dag(
    modules: Mapping[str, ResolvedModuleUnit],
    max_depth: int,
    validation: _ValidationState,
) -> None:
    state: dict[str, int] = {}
    depth: dict[str, int] = {}
    for start in sorted(modules):
        if state.get(start) == 2:
            continue
        stack: list[tuple[str, bool]] = [(start, False)]
        while stack:
            validation.checkpoint(modules[start].syntax.span)
            uri, exiting = stack.pop()
            if exiting:
                child_uris = tuple(
                    _resolved_target_uri(child, modules[uri].syntax.span)
                    for _, child in _resolved_import_items(
                        modules[uri].imports, modules[uri].syntax.span
                    )
                )
                depth[uri] = 1 + max((depth[child] for child in child_uris), default=0)
                if depth[uri] > max_depth:
                    raise ModuleExpansionError(
                        "HOCUS464", "Module import depth exceeds its limit.", modules[uri].syntax.span
                    )
                state[uri] = 2
                continue
            if state.get(uri) == 1:
                raise ModuleExpansionError(
                    "HOCUS467", "Module import cycle detected.", modules[uri].syntax.span
                )
            if state.get(uri) == 2:
                continue
            state[uri] = 1
            stack.append((uri, True))
            for child in sorted(
                (
                    _resolved_target_uri(item, modules[uri].syntax.span)
                    for _, item in _resolved_import_items(
                        modules[uri].imports, modules[uri].syntax.span
                    )
                ),
                reverse=True,
            ):
                if child not in modules:
                    raise ModuleExpansionError(
                        "HOCUS463", "Resolved import targets an unknown module URI.", modules[uri].syntax.span
                    )
                if state.get(child) == 1:
                    raise ModuleExpansionError(
                        "HOCUS467", "Module import cycle detected.", modules[uri].syntax.span
                    )
                stack.append((child, False))

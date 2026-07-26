"""Pure cursor scope and definition indexing for HocusScript 0.3."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from .diagnostics import SourceSpan
from .lexer import Lexer, Token
from .syntax import (
    ExportStmt,
    ForDecl,
    IfDecl,
    InputStmt,
    ModuleParamDecl,
    NodeDecl,
    ParamRefExpr,
    ParmStmt,
    SymbolRefExpr,
    SyntaxSource,
    UseDecl,
    YieldStmt,
)


@dataclass(frozen=True, slots=True)
class EditorScopeMember:
    name: str
    kind: str
    type_name: str
    source_uri: str
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class EditorScopeBinding:
    name: str
    kind: str
    source_uri: str
    span: SourceSpan
    members: tuple[EditorScopeMember, ...] = ()

    def member(self, name: str) -> EditorScopeMember | None:
        return next((item for item in self.members if item.name == name), None)


@dataclass(frozen=True, slots=True)
class ImportedModuleView:
    imported_name: str
    local_name: str
    source_uri: str
    source_digest: str
    name_span: SourceSpan
    parameters: tuple[EditorScopeMember, ...]
    exports: tuple[EditorScopeMember, ...]


@dataclass(frozen=True, slots=True)
class EditorScopeDefinition:
    name: str
    kind: str
    source_uri: str
    span: SourceSpan


@dataclass(slots=True)
class _Scope:
    bindings: dict[str, EditorScopeBinding] = field(default_factory=dict)
    yields: dict[str, EditorScopeMember] = field(default_factory=dict)

    def child(self) -> "_Scope":
        return _Scope(dict(self.bindings), dict(self.yields))


def scope_at(
    source: str,
    syntax: SyntaxSource,
    offset: int,
    imports: Mapping[str, ImportedModuleView],
) -> tuple[EditorScopeBinding, ...]:
    """Return the exact lexical bindings visible at one source offset."""

    scope = _root_scope(syntax)
    tokens = Lexer(source, syntax.span.source_name).tokenize()
    statements = _root_statements(syntax)
    resolved = _scope_in_block(statements, offset, scope, imports, tokens)
    return tuple(
        resolved.bindings[name]
        for name in sorted(resolved.bindings, key=lambda item: (item.casefold(), item))
    )


def yield_names_at(
    source: str,
    syntax: SyntaxSource,
    offset: int,
    imports: Mapping[str, ImportedModuleView],
) -> tuple[EditorScopeMember, ...]:
    scope = _scope_state(source, syntax, offset, imports)
    return tuple(
        scope.yields[name]
        for name in sorted(scope.yields, key=lambda item: (item.casefold(), item))
    )


def definition_at(
    source: str,
    syntax: SyntaxSource,
    offset: int,
    imports: Mapping[str, ImportedModuleView],
) -> EditorScopeDefinition | None:
    """Resolve one authored reference without expanding or executing controls."""

    imported = _import_definition(syntax, offset, imports)
    if imported is not None:
        return imported
    special = _statement_definition(source, syntax, offset, imports)
    if special is not None:
        return special
    expression = _expression_at(syntax, offset)
    if expression is None:
        return None
    scope = _scope_state(source, syntax, offset, imports)
    if isinstance(expression, ParamRefExpr):
        return _member_definition(scope.bindings.get("param"), expression.name)
    return _symbol_definition(scope, expression, offset)


def _scope_state(
    source: str,
    syntax: SyntaxSource,
    offset: int,
    imports: Mapping[str, ImportedModuleView],
) -> _Scope:
    tokens = Lexer(source, syntax.span.source_name).tokenize()
    return _scope_in_block(
        _root_statements(syntax), offset, _root_scope(syntax), imports, tokens,
    )


def _root_scope(syntax: SyntaxSource) -> _Scope:
    scope = _Scope()
    if syntax.module is None:
        return scope
    members = tuple(_parameter_member(item) for item in syntax.module.parameters)
    if members:
        scope.bindings["param"] = EditorScopeBinding(
            "param", "parameter_root", syntax.span.source_name,
            syntax.module.span, members,
        )
    return scope


def _parameter_member(item: ModuleParamDecl) -> EditorScopeMember:
    return EditorScopeMember(
        item.name, "parameter", item.type_name, item.name_span.source_name,
        item.name_span,
    )


def _root_statements(syntax: SyntaxSource) -> tuple[Any, ...]:
    if syntax.graph is not None:
        return syntax.graph.statements
    if syntax.module is not None:
        return syntax.module.statements
    return ()


def _scope_in_block(
    statements: tuple[Any, ...],
    offset: int,
    parent: _Scope,
    imports: Mapping[str, ImportedModuleView],
    tokens: list[Token],
) -> _Scope:
    scope = parent.child()
    _predeclare_nodes(statements, scope)
    for statement in statements:
        if not isinstance(statement, (NodeDecl, UseDecl, IfDecl, ForDecl, YieldStmt)):
            continue
        if statement.span.start.offset > offset:
            break
        if isinstance(statement, (IfDecl, ForDecl)) and _contains(statement.span, offset):
            nested = _nested_scope(statement, offset, scope, imports, tokens)
            if nested is not None:
                return nested
        if statement.span.end.offset <= offset:
            _bind_completed(statement, scope, imports)
            continue
        return scope
    return scope


def _predeclare_nodes(statements: tuple[Any, ...], scope: _Scope) -> None:
    for statement in statements:
        if not isinstance(statement, NodeDecl):
            continue
        output = EditorScopeMember(
            "output", "node_output", "node_output",
            statement.symbol_span.source_name, statement.symbol_span,
        )
        scope.bindings[statement.symbol] = EditorScopeBinding(
            statement.symbol, "node", statement.symbol_span.source_name,
            statement.symbol_span, (output,),
        )


def _bind_completed(
    statement: Any,
    scope: _Scope,
    imports: Mapping[str, ImportedModuleView],
) -> None:
    if isinstance(statement, UseDecl):
        imported = imports.get(statement.module_name)
        members = imported.exports if imported is not None else ()
        scope.bindings[statement.symbol] = EditorScopeBinding(
            statement.symbol, "use", statement.symbol_span.source_name,
            statement.symbol_span, members,
        )
    elif isinstance(statement, IfDecl):
        scope.bindings[statement.symbol] = _control_binding(
            statement.symbol, statement.symbol_span, statement.outputs,
        )
    elif isinstance(statement, ForDecl):
        scope.bindings[statement.symbol] = _control_binding(
            statement.symbol, statement.symbol_span, statement.carries,
        )


def _control_binding(
    symbol: str,
    symbol_span: SourceSpan,
    declarations: tuple[Any, ...],
) -> EditorScopeBinding:
    members = tuple(
        EditorScopeMember(
            item.name, "control_output", item.type_name,
            item.name_span.source_name, item.name_span,
        )
        for item in declarations
    )
    return EditorScopeBinding(
        symbol, "control", symbol_span.source_name, symbol_span, members,
    )


def _nested_scope(
    statement: IfDecl | ForDecl,
    offset: int,
    scope: _Scope,
    imports: Mapping[str, ImportedModuleView],
    tokens: list[Token],
) -> _Scope | None:
    pairs = _direct_brace_pairs(tokens, statement.span)
    if isinstance(statement, IfDecl):
        bodies = ((statement.then_body, statement.outputs), (statement.else_body, statement.outputs))
    else:
        bodies = ((statement.body, statement.carries),)
    for index, (body, yields) in enumerate(bodies):
        if index >= len(pairs) or not _inside_pair(pairs[index], offset):
            continue
        child = scope.child()
        child.yields = {
            item.name: EditorScopeMember(
                item.name, "yield_target", item.type_name,
                item.name_span.source_name, item.name_span,
            )
            for item in yields
        }
        if isinstance(statement, ForDecl):
            _bind_fold_roots(statement, child)
        return _scope_in_block(body, offset, child, imports, tokens)
    return None


def _bind_fold_roots(statement: ForDecl, scope: _Scope) -> None:
    iterator = EditorScopeMember(
        statement.iterator, "iterator", "int",
        statement.iterator_span.source_name, statement.iterator_span,
    )
    _merge_root(scope, "iter", "iterator_root", (iterator,), statement.span)
    carries = tuple(
        EditorScopeMember(
            item.name, "carry", item.type_name,
            item.name_span.source_name, item.name_span,
        )
        for item in statement.carries
    )
    _merge_root(scope, "carry", "carry_root", carries, statement.span)


def _merge_root(
    scope: _Scope,
    name: str,
    kind: str,
    members: tuple[EditorScopeMember, ...],
    span: SourceSpan,
) -> None:
    previous = scope.bindings.get(name)
    merged = {item.name: item for item in previous.members} if previous else {}
    merged.update({item.name: item for item in members})
    ordered = tuple(
        merged[key] for key in sorted(merged, key=lambda item: (item.casefold(), item))
    )
    scope.bindings[name] = EditorScopeBinding(
        name, kind, span.source_name, span, ordered,
    )


def _direct_brace_pairs(
    tokens: list[Token],
    span: SourceSpan,
) -> tuple[tuple[Token, Token], ...]:
    stack: list[Token] = []
    pairs: list[tuple[Token, Token]] = []
    for token in tokens:
        if token.span.start.offset < span.start.offset:
            continue
        if token.span.end.offset > span.end.offset:
            break
        if token.kind == "LBRACE":
            stack.append(token)
        elif token.kind == "RBRACE" and stack:
            opened = stack.pop()
            if not stack:
                pairs.append((opened, token))
    return tuple(pairs)


def _inside_pair(pair: tuple[Token, Token], offset: int) -> bool:
    return pair[0].span.end.offset <= offset <= pair[1].span.start.offset


def _contains(span: SourceSpan, offset: int) -> bool:
    return span.start.offset <= offset <= span.end.offset


def _import_definition(
    syntax: SyntaxSource,
    offset: int,
    imports: Mapping[str, ImportedModuleView],
) -> EditorScopeDefinition | None:
    for declaration in syntax.imports:
        imported = imports.get(declaration.local_name)
        if imported is None:
            continue
        if _contains(declaration.local_name_span, offset):
            return EditorScopeDefinition(
                declaration.local_name, "import_alias",
                declaration.local_name_span.source_name, declaration.local_name_span,
            )
        if (
            _contains(declaration.imported_name_span, offset)
            or _contains(declaration.specifier_span, offset)
        ):
            return EditorScopeDefinition(
                imported.imported_name, "module",
                imported.source_uri, imported.name_span,
            )
    return None


def _statement_definition(
    source: str,
    syntax: SyntaxSource,
    offset: int,
    imports: Mapping[str, ImportedModuleView],
) -> EditorScopeDefinition | None:
    for statement in _walk_statements(_root_statements(syntax)):
        if isinstance(statement, UseDecl):
            imported = imports.get(statement.module_name)
            if _contains(statement.module_name_span, offset):
                declaration = next(
                    (item for item in syntax.imports if item.local_name == statement.module_name),
                    None,
                )
                if declaration is not None:
                    return EditorScopeDefinition(
                        declaration.local_name, "import_alias",
                        declaration.local_name_span.source_name,
                        declaration.local_name_span,
                    )
            if imported is not None:
                for argument in statement.arguments:
                    if not _contains(argument.name_span, offset):
                        continue
                    target = next(
                        (item for item in imported.parameters if item.name == argument.name),
                        None,
                    )
                    return _as_definition(target)
        if isinstance(statement, YieldStmt) and _contains(statement.name_span, offset):
            scope = _scope_state(source, syntax, offset, imports)
            return _as_definition(scope.yields.get(statement.name))
    return None


def _expression_at(syntax: SyntaxSource, offset: int) -> ParamRefExpr | SymbolRefExpr | None:
    for statement in _walk_statements(_root_statements(syntax)):
        for expression in _statement_expressions(statement):
            if isinstance(expression, (ParamRefExpr, SymbolRefExpr)) and _contains(expression.span, offset):
                return expression
    return None


def _walk_statements(statements: tuple[Any, ...]):
    for statement in statements:
        yield statement
        if isinstance(statement, IfDecl):
            yield from _walk_statements(statement.then_body)
            yield from _walk_statements(statement.else_body)
        elif isinstance(statement, ForDecl):
            yield from _walk_statements(statement.body)


def _statement_expressions(statement: Any) -> tuple[Any, ...]:
    if isinstance(statement, NodeDecl):
        return tuple(
            child.source if isinstance(child, InputStmt) else child.value
            for child in statement.statements
            if isinstance(child, (InputStmt, ParmStmt))
        )
    if isinstance(statement, UseDecl):
        return tuple(item.value for item in statement.arguments)
    if isinstance(statement, IfDecl):
        return (statement.condition,)
    if isinstance(statement, ForDecl):
        return (statement.count, *(item.initial for item in statement.carries))
    if isinstance(statement, (YieldStmt, ExportStmt)):
        return (statement.value,)
    return ()


def _symbol_definition(
    scope: _Scope,
    expression: SymbolRefExpr,
    offset: int,
) -> EditorScopeDefinition | None:
    binding = scope.bindings.get(expression.symbol)
    if binding is None:
        return None
    if _contains(expression.symbol_span, offset):
        return EditorScopeDefinition(
            binding.name, binding.kind, binding.source_uri, binding.span,
        )
    if _contains(expression.member_span, offset):
        return _member_definition(binding, expression.member)
    return None


def _member_definition(
    binding: EditorScopeBinding | None,
    name: str,
) -> EditorScopeDefinition | None:
    if binding is None:
        return None
    return _as_definition(binding.member(name))


def _as_definition(
    value: EditorScopeMember | None,
) -> EditorScopeDefinition | None:
    if value is None:
        return None
    return EditorScopeDefinition(
        value.name, value.kind, value.source_uri, value.span,
    )

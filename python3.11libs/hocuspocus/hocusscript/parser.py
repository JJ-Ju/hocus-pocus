"""Recursive-descent parser for the HocusScript 0.1 source syntax."""

from __future__ import annotations

from .diagnostics import Diagnostic, HocusSourceError, SourceSpan
from .lexer import Token
from .syntax import (
    ArrayExpr,
    CategoryStmt,
    CodeExpr,
    ExternalDecl,
    FlagStmt,
    GraphDecl,
    InputStmt,
    LayoutStmt,
    LiteralExpr,
    ModeStmt,
    NodeDecl,
    OwnershipStmt,
    ParmStmt,
    ReferenceExpr,
    RevisionStmt,
    SyntaxSource,
    TargetStmt,
    ValueExpr,
    VersionDecl,
)


class Parser:
    def __init__(self, tokens: list[Token], *, max_value_depth: int = 128, max_nodes: int = 10_000):
        self._tokens = tokens
        self._index = 0
        self._max_value_depth = max_value_depth
        self._max_nodes = max_nodes
        self.diagnostics: list[Diagnostic] = []

    def parse(self) -> SyntaxSource:
        version: VersionDecl | None = None
        if self._is_ident("hocus"):
            start = self._advance()
            value = self._current()
            if value.kind not in {"NUMBER", "STRING"}:
                self._error("HOCUS201", "Expected a language version after 'hocus'.")
            self._advance()
            end = self._expect("SEMICOLON", "HOCUS202", "Expected ';' after the language version.")
            version = VersionDecl(
                value=value.lexeme if value.kind == "NUMBER" else str(value.value),
                quoted=value.kind == "STRING",
                span=self._joined_span(start, end),
                value_span=value.span,
            )
        elif self._is_ident("graph"):
            self.diagnostics.append(
                Diagnostic(
                    "warning",
                    "HOCUS101",
                    "parse",
                    "Missing 'hocus 0.1;' header; preview compilation assumes language 0.1.",
                    self._current().span,
                )
            )

        graph = self._parse_graph()
        self._expect("EOF", "HOCUS203", "Only one graph declaration is supported in language 0.1.")
        start = version.span.start if version is not None else graph.span.start
        return SyntaxSource(version, graph, SourceSpan(graph.span.source_name, start, graph.span.end))

    def _parse_graph(self) -> GraphDecl:
        start = self._expect_ident("graph", "HOCUS204", "Expected a graph declaration.")
        name = self._expect("IDENT", "HOCUS205", "Expected a graph name.")
        self._expect("LBRACE", "HOCUS206", "Expected '{' after the graph name.")
        statements = []
        seen_singletons: set[str] = set()
        node_count = 0

        while self._current().kind not in {"RBRACE", "EOF"}:
            try:
                if self._is_ident("target"):
                    self._claim_singleton("target", seen_singletons)
                    statements.append(self._parse_target())
                elif self._is_ident("category"):
                    self._claim_singleton("category", seen_singletons)
                    statements.append(self._parse_category())
                elif self._is_ident("mode"):
                    self._claim_singleton("mode", seen_singletons)
                    statements.append(self._parse_mode())
                elif self._is_ident("expect"):
                    self._claim_singleton("expect", seen_singletons)
                    statements.append(self._parse_revision())
                elif self._is_ident("ownership"):
                    self._claim_singleton("ownership", seen_singletons)
                    statements.append(self._parse_ownership())
                elif self._is_ident("existing") or self._is_ident("adopt"):
                    statements.append(self._parse_external())
                elif self._is_ident("node"):
                    if node_count >= self._max_nodes:
                        self._error("HOCUS314", f"Graph exceeds the {self._max_nodes}-node limit.")
                    statements.append(self._parse_node())
                    node_count += 1
                elif self._is_ident("display") or self._is_ident("render") or self._is_ident("output"):
                    key = str(self._current().value)
                    self._claim_singleton(key, seen_singletons)
                    statements.append(self._parse_flag())
                elif self._is_ident("layout"):
                    self._claim_singleton("layout", seen_singletons)
                    statements.append(self._parse_layout())
                else:
                    self._error(
                        "HOCUS217",
                        "Unknown graph statement. HocusScript 0.1 does not execute TypeScript or JavaScript constructs.",
                    )
            except HocusSourceError as exc:
                if exc.diagnostic.code in {"HOCUS226", "HOCUS314", "HOCUS246"}:
                    raise
                self.diagnostics.append(exc.diagnostic)
                if exc.diagnostic.code in {"HOCUS222", "HOCUS223", "HOCUS224", "HOCUS225"}:
                    self._synchronize_node_declaration()
                else:
                    self._synchronize_statement(
                        scope="graph",
                        preserve_current=exc.diagnostic.code == "HOCUS245",
                    )

        end = self._expect("RBRACE", "HOCUS218", "Expected '}' to close the graph.")
        return GraphDecl(str(name.value), tuple(statements), self._joined_span(start, end), name.span)

    def _parse_target(self) -> TargetStmt:
        start = self._advance()
        had_equal = self._match("EQUAL") is not None
        value = self._expect("STRING", "HOCUS207", "Expected a quoted target path.")
        end = self._statement_end()
        return TargetStmt(str(value.value), had_equal, self._joined_span(start, end), value.span)

    def _parse_category(self) -> CategoryStmt:
        start = self._advance()
        had_equal = self._match("EQUAL") is not None
        value = self._expect("IDENT", "HOCUS208", "Expected a category name.")
        end = self._statement_end()
        return CategoryStmt(str(value.value), had_equal, self._joined_span(start, end), value.span)

    def _parse_mode(self) -> ModeStmt:
        start = self._advance()
        had_equal = self._match("EQUAL") is not None
        value = self._expect("IDENT", "HOCUS209", "Expected merge or reconcile.")
        end = self._statement_end()
        return ModeStmt(str(value.value), had_equal, self._joined_span(start, end), value.span)

    def _parse_revision(self) -> RevisionStmt:
        start = self._advance()
        had_revision = False
        if self._is_ident("revision"):
            self._advance()
            had_revision = True
        had_equal = self._match("EQUAL") is not None
        value = self._expect("NUMBER", "HOCUS210", "Expected an integer document revision.")
        if not isinstance(value.value, int):
            self._error("HOCUS211", "Expected revision must be an integer.", token=value)
        end = self._statement_end()
        return RevisionStmt(value.value, had_revision, had_equal, self._joined_span(start, end), value.span)

    def _parse_ownership(self) -> OwnershipStmt:
        start = self._advance()
        had_equal = self._match("EQUAL") is not None
        value = self._expect("STRING", "HOCUS212", "Expected a quoted ownership namespace.")
        end = self._statement_end()
        return OwnershipStmt(str(value.value), had_equal, self._joined_span(start, end), value.span)

    def _parse_external(self) -> ExternalDecl:
        start = self._advance()
        adopted = start.value == "adopt"
        symbol = self._expect("IDENT", "HOCUS219", "Expected a symbol for the external node.")
        self._expect("EQUAL", "HOCUS220", "Expected '=' in an external node declaration.")
        path = self._expect("STRING", "HOCUS221", "Expected a quoted Houdini path.")
        end = self._statement_end()
        return ExternalDecl(
            str(symbol.value),
            str(path.value),
            adopted,
            self._joined_span(start, end),
            symbol.span,
            path.span,
        )

    def _parse_node(self) -> NodeDecl:
        start = self._advance()
        symbol = self._expect("IDENT", "HOCUS222", "Expected a node symbol.")
        explicit_id: str | None = None
        explicit_id_span: SourceSpan | None = None
        if self._match("AT") is not None:
            annotation = self._expect("IDENT", "HOCUS247", "Expected 'id' after '@'.")
            if annotation.value != "id":
                self._error("HOCUS248", "Only the @id annotation is supported on node declarations.", token=annotation)
            self._expect("LPAREN", "HOCUS249", "Expected '(' after @id.")
            value = self._expect("STRING", "HOCUS250", "Expected a quoted durable node ID.")
            explicit_id = str(value.value)
            explicit_id_span = value.span
            self._expect("RPAREN", "HOCUS251", "Expected ')' after the durable node ID.")
        self._expect("COLON", "HOCUS223", "Expected ':' after the node symbol.")
        type_token = self._current()
        if type_token.kind not in {"IDENT", "STRING"}:
            self._error("HOCUS224", "Expected a node type name.")
        self._advance()
        self._expect("LBRACE", "HOCUS225", "Expected '{' before node assignments.")
        statements = []
        while self._current().kind not in {"RBRACE", "EOF"}:
            try:
                statements.append(self._parse_input() if self._is_ident("input") else self._parse_parm())
            except HocusSourceError as exc:
                if exc.diagnostic.code == "HOCUS246":
                    raise
                self.diagnostics.append(exc.diagnostic)
                self._synchronize_statement(
                    scope="node",
                    preserve_current=exc.diagnostic.code == "HOCUS245",
                )
        end = self._expect("RBRACE", "HOCUS226", "Expected '}' to close the node.")
        return NodeDecl(
            str(symbol.value),
            explicit_id,
            str(type_token.value),
            type_token.kind == "STRING",
            tuple(statements),
            self._joined_span(start, end),
            symbol.span,
            explicit_id_span,
            type_token.span,
        )

    def _parse_input(self) -> InputStmt:
        start = self._advance()
        self._expect("LBRACKET", "HOCUS227", "Expected '[' after input.")
        index = self._expect("NUMBER", "HOCUS228", "Expected an integer input index.")
        if not isinstance(index.value, int):
            self._error("HOCUS229", "Input index must be an integer.", token=index)
        self._expect("RBRACKET", "HOCUS230", "Expected ']' after the input index.")
        self._expect("EQUAL", "HOCUS231", "Expected '=' in an input assignment.")
        reference = self._parse_reference()
        end = self._statement_end()
        return InputStmt(index.value, reference, self._joined_span(start, end), index.span)

    def _parse_reference(self) -> ReferenceExpr:
        symbol = self._expect("IDENT", "HOCUS232", "Expected a node symbol.")
        output_index = 0
        output_span = symbol.span
        end = symbol
        explicit_output = False
        port_keyword: str | None = None
        if self._match("DOT") is not None:
            explicit_output = True
            port = self._expect("IDENT", "HOCUS233", "Expected output or out after '.'.")
            if port.value not in {"output", "out"}:
                self._error("HOCUS234", "Only .output[index] and .out[index] are supported in 0.1.", token=port)
            port_keyword = str(port.value)
            self._expect("LBRACKET", "HOCUS235", "Expected '[' before the output index.")
            output = self._expect("NUMBER", "HOCUS236", "Expected an integer output index.")
            if not isinstance(output.value, int):
                self._error("HOCUS237", "Output index must be an integer.", token=output)
            output_index = output.value
            output_span = output.span
            end = self._expect("RBRACKET", "HOCUS238", "Expected ']' after the output index.")
        return ReferenceExpr(
            str(symbol.value),
            output_index,
            explicit_output,
            port_keyword,
            self._joined_span(symbol, end),
            symbol.span,
            output_span,
        )

    def _parse_parm(self) -> ParmStmt:
        name = self._expect("IDENT", "HOCUS239", "Expected a parameter name.")
        self._expect("EQUAL", "HOCUS240", "Expected '=' after the parameter name.")
        value = self._parse_value()
        end = self._statement_end()
        return ParmStmt(str(name.value), value, self._joined_span(name, end), name.span)

    def _parse_value(self, depth: int = 0) -> ValueExpr:
        if depth > self._max_value_depth:
            self._error("HOCUS246", f"Value nesting exceeds the {self._max_value_depth}-level limit.")
        token = self._current()
        if token.kind in {"STRING", "NUMBER"}:
            self._advance()
            return LiteralExpr(token.value, token.span)
        if token.kind == "IDENT" and token.value in {"true", "false", "null"}:
            self._advance()
            value = {"true": True, "false": False, "null": None}[str(token.value)]
            return LiteralExpr(value, token.span)
        if token.kind == "IDENT" and token.value in {"vex", "python", "hscript"}:
            language = self._advance()
            code = self._expect("CODE", "HOCUS241", "Expected a raw code template after the language tag.")
            if code.body_span is None or code.code_offset_map is None:
                raise RuntimeError("CODE token is missing body source-map metadata")
            return CodeExpr(
                str(language.value),
                str(code.value),
                SourceSpan(language.span.source_name, language.span.start, code.span.end),
                code.body_span,
                code.code_offset_map,
            )
        if token.kind == "LBRACKET":
            start = self._advance()
            values: list[ValueExpr] = []
            trailing_comma = False
            if self._current().kind != "RBRACKET":
                while True:
                    values.append(self._parse_value(depth + 1))
                    if self._match("COMMA") is None:
                        break
                    if self._current().kind == "RBRACKET":
                        trailing_comma = True
                        break
            end = self._expect("RBRACKET", "HOCUS242", "Expected ']' to close the array.")
            return ArrayExpr(tuple(values), trailing_comma, self._joined_span(start, end))
        self._error("HOCUS243", "Expected a scalar, array, or tagged code value; executable expressions are not supported.")
        raise AssertionError("unreachable")

    def _parse_flag(self) -> FlagStmt:
        start = self._advance()
        key = str(start.value)
        self._expect("EQUAL", "HOCUS213", f"Expected '=' after {key}.")
        symbol = self._expect("IDENT", "HOCUS214", f"Expected a symbol after {key} =.")
        end = self._statement_end()
        return FlagStmt(key, str(symbol.value), self._joined_span(start, end), symbol.span)

    def _parse_layout(self) -> LayoutStmt:
        start = self._advance()
        self._expect("EQUAL", "HOCUS215", "Expected '=' after layout.")
        value = self._expect("IDENT", "HOCUS216", "Expected auto layout mode.")
        end = self._statement_end()
        return LayoutStmt(str(value.value), self._joined_span(start, end), value.span)

    def _claim_singleton(self, name: str, seen: set[str]) -> None:
        if name in seen:
            self._error("HOCUS244", f"Duplicate graph statement: {name}.")
        seen.add(name)

    def _statement_end(self) -> Token:
        return self._expect("SEMICOLON", "HOCUS245", "Expected ';' after the statement.")

    def _synchronize_statement(self, *, scope: str, preserve_current: bool) -> None:
        if preserve_current and self._is_statement_start(scope):
            return
        start_index = self._index
        while self._current().kind not in {"SEMICOLON", "RBRACE", "EOF"}:
            self._advance()
        if self._current().kind == "SEMICOLON":
            self._advance()
        if self._index == start_index and self._current().kind not in {"RBRACE", "EOF"}:
            self._advance()

    def _synchronize_node_declaration(self) -> None:
        depth = 0
        saw_body = False
        while self._current().kind != "EOF":
            token = self._current()
            if token.kind == "LBRACE":
                saw_body = True
                depth += 1
                self._advance()
                continue
            if token.kind == "RBRACE":
                if not saw_body:
                    return
                depth -= 1
                self._advance()
                if depth == 0:
                    return
                continue
            if not saw_body and self._is_statement_start("graph"):
                return
            if not saw_body and token.kind == "SEMICOLON":
                self._advance()
                return
            self._advance()

    def _is_statement_start(self, scope: str) -> bool:
        token = self._current()
        if token.kind != "IDENT":
            return False
        if scope == "node":
            return True
        return token.value in {
            "target", "category", "mode", "expect", "ownership", "existing", "adopt", "node",
            "display", "render", "output", "layout",
        }

    def _joined_span(self, start: Token, end: Token) -> SourceSpan:
        return SourceSpan(start.span.source_name, start.span.start, end.span.end)

    def _current(self) -> Token:
        return self._tokens[self._index]

    def _advance(self) -> Token:
        token = self._current()
        if token.kind != "EOF":
            self._index += 1
        return token

    def _match(self, kind: str) -> Token | None:
        if self._current().kind != kind:
            return None
        return self._advance()

    def _is_ident(self, value: str) -> bool:
        token = self._current()
        return token.kind == "IDENT" and token.value == value

    def _expect_ident(self, value: str, code: str, message: str) -> Token:
        if not self._is_ident(value):
            self._error(code, message)
        return self._advance()

    def _expect(self, kind: str, code: str, message: str) -> Token:
        token = self._current()
        if token.kind != kind:
            self._error(code, message, token=token)
        return self._advance()

    def _error(self, code: str, message: str, *, token: Token | None = None) -> None:
        actual = token or self._current()
        raise HocusSourceError(Diagnostic("error", code, "parse", message, actual.span))

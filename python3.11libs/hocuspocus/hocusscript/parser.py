"""Recursive-descent parser for the HocusScript 0.1 preview grammar."""

from __future__ import annotations

from typing import Any

from .diagnostics import Diagnostic, HocusSourceError, SourceSpan
from .lexer import Token
from .model import (
    ArrayValue,
    CodeValue,
    ExternalNodeSpec,
    GraphSpec,
    InputSpec,
    LiteralValue,
    NodeReference,
    NodeSpec,
    ParmSpec,
)


class Parser:
    def __init__(self, tokens: list[Token], *, max_value_depth: int = 128, max_nodes: int = 10_000):
        self._tokens = tokens
        self._index = 0
        self._max_value_depth = max_value_depth
        self._max_nodes = max_nodes
        self.diagnostics: list[Diagnostic] = []

    def parse(self) -> GraphSpec:
        language_version = "0.1"
        if self._is_ident("hocus"):
            self._advance()
            version = self._current()
            if version.kind not in {"NUMBER", "STRING"}:
                self._error("HOCUS201", "Expected a language version after 'hocus'.")
            language_version = version.lexeme if version.kind == "NUMBER" else str(version.value)
            self._advance()
            self._expect("SEMICOLON", "HOCUS202", "Expected ';' after the language version.")
        else:
            self.diagnostics.append(
                Diagnostic(
                    "warning",
                    "HOCUS101",
                    "parse",
                    "Missing 'hocus 0.1;' header; preview compilation assumes language 0.1.",
                    self._current().span,
                )
            )

        graph = self._parse_graph(language_version)
        self._expect("EOF", "HOCUS203", "Only one graph declaration is supported in language 0.1.")
        return graph

    def _parse_graph(self, language_version: str) -> GraphSpec:
        start = self._expect_ident("graph", "HOCUS204", "Expected a graph declaration.")
        name = self._expect("IDENT", "HOCUS205", "Expected a graph name.")
        self._expect("LBRACE", "HOCUS206", "Expected '{' after the graph name.")

        target: str | None = None
        category: str | None = None
        mode = "merge"
        expected_revision: int | None = None
        ownership: str | None = None
        external_nodes: list[ExternalNodeSpec] = []
        nodes: list[NodeSpec] = []
        display: str | None = None
        render: str | None = None
        output: str | None = None
        layout: str | None = None
        seen_singletons: set[str] = set()

        while self._current().kind not in {"RBRACE", "EOF"}:
            if self._is_ident("target"):
                self._claim_singleton("target", seen_singletons)
                self._advance()
                self._match("EQUAL")
                target = str(self._expect("STRING", "HOCUS207", "Expected a quoted target path.").value)
                self._statement_end()
                continue
            if self._is_ident("category"):
                self._claim_singleton("category", seen_singletons)
                self._advance()
                self._match("EQUAL")
                token = self._current()
                if token.kind != "IDENT":
                    self._error("HOCUS208", "Expected a category name.")
                category = str(token.value)
                self._advance()
                self._statement_end()
                continue
            if self._is_ident("mode"):
                self._claim_singleton("mode", seen_singletons)
                self._advance()
                self._match("EQUAL")
                mode = str(self._expect("IDENT", "HOCUS209", "Expected merge or reconcile.").value)
                self._statement_end()
                continue
            if self._is_ident("expect"):
                self._claim_singleton("expect", seen_singletons)
                self._advance()
                if self._is_ident("revision"):
                    self._advance()
                self._match("EQUAL")
                token = self._expect("NUMBER", "HOCUS210", "Expected an integer document revision.")
                if not isinstance(token.value, int):
                    self._error("HOCUS211", "Expected revision must be an integer.", token=token)
                expected_revision = token.value
                self._statement_end()
                continue
            if self._is_ident("ownership"):
                self._claim_singleton("ownership", seen_singletons)
                self._advance()
                self._match("EQUAL")
                ownership = str(self._expect("STRING", "HOCUS212", "Expected a quoted ownership namespace.").value)
                self._statement_end()
                continue
            if self._is_ident("existing") or self._is_ident("adopt"):
                external_nodes.append(self._parse_external())
                continue
            if self._is_ident("node"):
                if len(nodes) >= self._max_nodes:
                    self._error(
                        "HOCUS314",
                        f"Graph exceeds the {self._max_nodes}-node limit.",
                    )
                nodes.append(self._parse_node())
                continue
            if self._is_ident("display") or self._is_ident("render") or self._is_ident("output"):
                key = str(self._current().value)
                self._claim_singleton(key, seen_singletons)
                self._advance()
                self._expect("EQUAL", "HOCUS213", f"Expected '=' after {key}.")
                symbol = str(self._expect("IDENT", "HOCUS214", f"Expected a symbol after {key} =.").value)
                self._statement_end()
                if key == "display":
                    display = symbol
                elif key == "render":
                    render = symbol
                else:
                    output = symbol
                continue
            if self._is_ident("layout"):
                self._claim_singleton("layout", seen_singletons)
                self._advance()
                self._expect("EQUAL", "HOCUS215", "Expected '=' after layout.")
                layout = str(self._expect("IDENT", "HOCUS216", "Expected auto layout mode.").value)
                self._statement_end()
                continue
            self._error(
                "HOCUS217",
                "Unknown graph statement. HocusScript 0.1 does not execute TypeScript or JavaScript constructs.",
            )

        end = self._expect("RBRACE", "HOCUS218", "Expected '}' to close the graph.")
        return GraphSpec(
            language_version=language_version,
            name=str(name.value),
            target=target,
            category=category,
            mode=mode,
            expected_revision=expected_revision,
            ownership=ownership,
            external_nodes=external_nodes,
            nodes=nodes,
            display=display,
            render=render,
            output=output,
            layout=layout,
            span=SourceSpan(start.span.source_name, start.span.start, end.span.end),
        )

    def _parse_external(self) -> ExternalNodeSpec:
        start = self._advance()
        adopted = start.value == "adopt"
        symbol = self._expect("IDENT", "HOCUS219", "Expected a symbol for the external node.")
        self._expect("EQUAL", "HOCUS220", "Expected '=' in an external node declaration.")
        path = self._expect("STRING", "HOCUS221", "Expected a quoted Houdini path.")
        end = self._statement_end()
        return ExternalNodeSpec(
            symbol=str(symbol.value),
            path=str(path.value),
            adopted=adopted,
            span=SourceSpan(start.span.source_name, start.span.start, end.span.end),
        )

    def _parse_node(self) -> NodeSpec:
        start = self._advance()
        symbol = self._expect("IDENT", "HOCUS222", "Expected a node symbol.")
        self._expect("COLON", "HOCUS223", "Expected ':' after the node symbol.")
        type_token = self._current()
        if type_token.kind not in {"IDENT", "STRING"}:
            self._error("HOCUS224", "Expected a node type name.")
        self._advance()
        self._expect("LBRACE", "HOCUS225", "Expected '{' before node assignments.")
        inputs: list[InputSpec] = []
        parms: list[ParmSpec] = []
        while self._current().kind not in {"RBRACE", "EOF"}:
            if self._is_ident("input"):
                inputs.append(self._parse_input())
            else:
                parms.append(self._parse_parm())
        end = self._expect("RBRACE", "HOCUS226", "Expected '}' to close the node.")
        return NodeSpec(
            symbol=str(symbol.value),
            type_name=str(type_token.value),
            inputs=inputs,
            parms=parms,
            span=SourceSpan(start.span.source_name, start.span.start, end.span.end),
        )

    def _parse_input(self) -> InputSpec:
        start = self._advance()
        self._expect("LBRACKET", "HOCUS227", "Expected '[' after input.")
        index = self._expect("NUMBER", "HOCUS228", "Expected an integer input index.")
        if not isinstance(index.value, int):
            self._error("HOCUS229", "Input index must be an integer.", token=index)
        self._expect("RBRACKET", "HOCUS230", "Expected ']' after the input index.")
        self._expect("EQUAL", "HOCUS231", "Expected '=' in an input assignment.")
        reference = self._parse_reference()
        end = self._statement_end()
        return InputSpec(
            index=index.value,
            source=reference,
            span=SourceSpan(start.span.source_name, start.span.start, end.span.end),
        )

    def _parse_reference(self) -> NodeReference:
        symbol = self._expect("IDENT", "HOCUS232", "Expected a node symbol.")
        output_index = 0
        end = symbol
        if self._match("DOT") is not None:
            port = self._expect("IDENT", "HOCUS233", "Expected output or out after '.'.")
            if port.value not in {"output", "out"}:
                self._error("HOCUS234", "Only .output[index] and .out[index] are supported in 0.1.", token=port)
            self._expect("LBRACKET", "HOCUS235", "Expected '[' before the output index.")
            output = self._expect("NUMBER", "HOCUS236", "Expected an integer output index.")
            if not isinstance(output.value, int):
                self._error("HOCUS237", "Output index must be an integer.", token=output)
            output_index = output.value
            end = self._expect("RBRACKET", "HOCUS238", "Expected ']' after the output index.")
        return NodeReference(
            symbol=str(symbol.value),
            output_index=output_index,
            span=SourceSpan(symbol.span.source_name, symbol.span.start, end.span.end),
        )

    def _parse_parm(self) -> ParmSpec:
        name = self._expect("IDENT", "HOCUS239", "Expected a parameter name.")
        self._expect("EQUAL", "HOCUS240", "Expected '=' after the parameter name.")
        value, value_span = self._parse_value()
        end = self._statement_end()
        return ParmSpec(
            name=str(name.value),
            value=value,
            span=SourceSpan(name.span.source_name, name.span.start, end.span.end),
        )

    def _parse_value(self, depth: int = 0) -> tuple[Any, SourceSpan]:
        if depth > self._max_value_depth:
            self._error(
                "HOCUS246",
                f"Value nesting exceeds the {self._max_value_depth}-level limit.",
            )
        token = self._current()
        if token.kind in {"STRING", "NUMBER"}:
            self._advance()
            return LiteralValue(token.value, token.span), token.span
        if token.kind == "IDENT" and token.value in {"true", "false", "null"}:
            self._advance()
            value = {"true": True, "false": False, "null": None}[str(token.value)]
            return LiteralValue(value, token.span), token.span
        if token.kind == "IDENT" and token.value in {"vex", "python", "hscript"}:
            language = self._advance()
            code = self._expect("CODE", "HOCUS241", "Expected a raw code template after the language tag.")
            span = SourceSpan(language.span.source_name, language.span.start, code.span.end)
            return CodeValue(str(language.value), str(code.value), span), span
        if token.kind == "LBRACKET":
            start = self._advance()
            values: list[Any] = []
            if self._current().kind != "RBRACKET":
                while True:
                    value, _ = self._parse_value(depth + 1)
                    values.append(value)
                    if self._match("COMMA") is None:
                        break
                    if self._current().kind == "RBRACKET":
                        break
            end = self._expect("RBRACKET", "HOCUS242", "Expected ']' to close the array.")
            span = SourceSpan(start.span.source_name, start.span.start, end.span.end)
            return ArrayValue(values, span), span
        self._error(
            "HOCUS243",
            "Expected a scalar, array, or tagged code value; executable expressions are not supported.",
        )
        raise AssertionError("unreachable")

    def _claim_singleton(self, name: str, seen: set[str]) -> None:
        if name in seen:
            self._error("HOCUS244", f"Duplicate graph statement: {name}.")
        seen.add(name)

    def _statement_end(self) -> Token:
        return self._expect("SEMICOLON", "HOCUS245", "Expected ';' after the statement.")

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

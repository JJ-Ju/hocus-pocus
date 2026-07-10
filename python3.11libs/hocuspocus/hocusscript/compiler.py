"""Offline structural compiler for HocusScript source."""

from __future__ import annotations

import hashlib
from typing import Iterable

from .diagnostics import Diagnostic, HocusSourceError, SourcePosition, SourceSpan, sort_diagnostics
from .formatter import format_graph
from .lexer import Lexer
from .model import CompileResult, GraphSpec, NodeSpec
from .parser import Parser

SUPPORTED_LANGUAGE_VERSIONS = {"0.1"}
MAX_SOURCE_BYTES = 1024 * 1024
MAX_SOURCE_NAME_CHARACTERS = 1024
MAX_DIAGNOSTICS = 500


def _diagnostic(
    code: str,
    message: str,
    span: SourceSpan,
    *,
    severity: str = "error",
    details: dict | None = None,
) -> Diagnostic:
    return Diagnostic(
        severity,
        code,
        "structural",
        message,
        span,
        details=details or {},
    )


def _duplicates(values: Iterable[tuple[str, SourceSpan]]) -> Iterable[tuple[str, SourceSpan]]:
    seen: set[str] = set()
    for value, span in values:
        if value in seen:
            yield value, span
        seen.add(value)


class _DiagnosticCollector:
    def __init__(self, limit: int, span: SourceSpan):
        self._limit = limit
        self._span = span
        self._items: list[Diagnostic] = []
        self._omitted = 0

    def add(self, diagnostic: Diagnostic) -> None:
        if len(self._items) < self._limit:
            self._items.append(diagnostic)
        else:
            self._omitted += 1

    def finish(self) -> list[Diagnostic]:
        if self._omitted:
            if self._items:
                self._items.pop()
                self._omitted += 1
            self._items.append(
                Diagnostic(
                    "error",
                    "HOCUS019",
                    "structural",
                    f"Diagnostic output truncated; {self._omitted} additional diagnostic(s) omitted.",
                    self._span,
                    details={"omittedCount": self._omitted, "limit": self._limit},
                )
            )
        return self._items


def _validate_node(node: NodeSpec, symbols: set[str], collector: _DiagnosticCollector) -> None:
    for name, span in _duplicates((item.name, item.span) for item in node.parms):
        collector.add(_diagnostic("HOCUS307", f"Duplicate parameter assignment '{name}' on node '{node.symbol}'.", span))
    for index, span in _duplicates((str(item.index), item.span) for item in node.inputs):
        collector.add(_diagnostic("HOCUS308", f"Duplicate input index {index} on node '{node.symbol}'.", span))
    for input_spec in node.inputs:
        if input_spec.index < 0:
            collector.add(_diagnostic("HOCUS312", "Input indexes must be nonnegative.", input_spec.span))
        if input_spec.source.output_index < 0:
            collector.add(_diagnostic("HOCUS313", "Output indexes must be nonnegative.", input_spec.source.span))
        if input_spec.source.symbol not in symbols:
            collector.add(
                _diagnostic(
                    "HOCUS309",
                    f"Unknown input source symbol: {input_spec.source.symbol}.",
                    input_spec.source.span,
                    details={"symbol": input_spec.source.symbol, "knownSymbolCount": len(symbols)},
                )
            )


def validate_graph(
    graph: GraphSpec,
    *,
    max_nodes: int = 10_000,
    max_diagnostics: int = MAX_DIAGNOSTICS,
) -> list[Diagnostic]:
    collector = _DiagnosticCollector(max_diagnostics, graph.span)
    if graph.language_version not in SUPPORTED_LANGUAGE_VERSIONS:
        collector.add(
            _diagnostic(
                "HOCUS102",
                f"Unsupported HocusScript language version: {graph.language_version}.",
                graph.span,
                details={"supportedVersions": sorted(SUPPORTED_LANGUAGE_VERSIONS)},
            )
        )
    if graph.target is None:
        collector.add(_diagnostic("HOCUS301", "Graph target is required.", graph.span))
    elif not _is_canonical_houdini_path(graph.target):
        collector.add(_diagnostic("HOCUS302", "Graph target must be a canonical absolute Houdini path.", graph.span))
    if graph.mode not in {"merge", "reconcile"}:
        collector.add(_diagnostic("HOCUS303", "Graph mode must be merge or reconcile.", graph.span))
    if graph.expected_revision is not None and graph.expected_revision < 0:
        collector.add(_diagnostic("HOCUS304", "Expected revision must be nonnegative.", graph.span))
    if graph.mode == "reconcile" and not graph.ownership:
        collector.add(_diagnostic("HOCUS305", "Reconcile mode requires an ownership namespace.", graph.span))
    if graph.ownership is not None and not graph.ownership.strip():
        collector.add(_diagnostic("HOCUS319", "Ownership namespace must not be empty.", graph.span))
    if len(graph.nodes) > max_nodes:
        collector.add(
            _diagnostic(
                "HOCUS314",
                f"Graph contains {len(graph.nodes)} nodes, exceeding the {max_nodes}-node limit.",
                graph.span,
            )
        )

    symbol_spans = [(item.symbol, item.span) for item in graph.external_nodes]
    symbol_spans.extend((item.symbol, item.span) for item in graph.nodes)
    for symbol, span in _duplicates(symbol_spans):
        collector.add(_diagnostic("HOCUS306", f"Duplicate graph symbol: {symbol}.", span))
    symbols = {symbol for symbol, _ in symbol_spans}

    if graph.target is not None:
        prefix = graph.target.rstrip("/") + "/"
        for external in graph.external_nodes:
            if not _is_canonical_houdini_path(external.path):
                collector.add(_diagnostic("HOCUS310", "External node paths must be canonical absolute paths.", external.span))
            elif external.path != graph.target and not external.path.startswith(prefix):
                collector.add(
                    _diagnostic(
                        "HOCUS311",
                        "External node path is outside the graph target scope.",
                        external.span,
                        details={"target": graph.target, "path": external.path},
                    )
                )

    for node in graph.nodes:
        if not node.type_name.strip():
            collector.add(_diagnostic("HOCUS320", f"Node '{node.symbol}' must declare a non-empty type name.", node.span))
        _validate_node(node, symbols, collector)

    mutable_symbols = {item.symbol for item in graph.nodes}
    mutable_symbols.update(item.symbol for item in graph.external_nodes if item.adopted)
    for field_name, symbol in (
        ("display", graph.display),
        ("render", graph.render),
        ("output", graph.output),
    ):
        if symbol is not None and symbol not in symbols:
            collector.add(
                _diagnostic(
                    "HOCUS315",
                    f"Unknown {field_name} symbol: {symbol}.",
                    graph.span,
                    details={"symbol": symbol, "knownSymbolCount": len(symbols)},
                )
            )
        elif symbol is not None and symbol not in mutable_symbols:
            collector.add(
                _diagnostic(
                    "HOCUS318",
                    f"The read-only existing symbol '{symbol}' cannot be selected as {field_name}; use adopt for managed mutation.",
                    graph.span,
                    details={"symbol": symbol, "directive": field_name},
                )
            )
    if graph.layout is not None and graph.layout != "auto":
        collector.add(_diagnostic("HOCUS316", "HocusScript 0.1 supports only layout = auto.", graph.span))
    return collector.finish()


def _is_canonical_houdini_path(path: str) -> bool:
    if path == "/":
        return True
    if not path.startswith("/") or path.endswith("/"):
        return False
    segments = path.split("/")[1:]
    return bool(segments) and all(segment not in {"", ".", ".."} for segment in segments)


def compile_source(
    source: str,
    source_name: str = "<memory>",
    *,
    strict: bool = True,
    max_diagnostics: int = MAX_DIAGNOSTICS,
) -> CompileResult:
    if not isinstance(source, str):
        raise TypeError("source must be a string")
    if not isinstance(source_name, str) or not source_name.strip():
        raise TypeError("source_name must be a non-empty string")
    if len(source_name) > MAX_SOURCE_NAME_CHARACTERS:
        raise TypeError(f"source_name must not exceed {MAX_SOURCE_NAME_CHARACTERS} characters")
    if not isinstance(strict, bool):
        raise TypeError("strict must be a boolean")
    if not isinstance(max_diagnostics, int) or max_diagnostics < 1:
        raise TypeError("max_diagnostics must be a positive integer")
    if len(source) > MAX_SOURCE_BYTES:
        position = SourcePosition(0, 1, 1)
        diagnostic = Diagnostic(
            "error",
            "HOCUS001",
            "lex",
            f"Source exceeds the {MAX_SOURCE_BYTES}-byte limit.",
            SourceSpan(source_name, position, position),
        )
        return CompileResult(
            source_name=source_name,
            source_digest="sha256:source-too-large",
            language_version=None,
            valid=False,
            diagnostics=[diagnostic],
        )
    try:
        source_bytes = source.encode("utf-8")
    except UnicodeEncodeError as exc:
        prefix = source[: exc.start]
        line = prefix.count("\n") + 1
        last_newline = prefix.rfind("\n")
        column = exc.start - last_newline
        start = SourcePosition(exc.start, line, column)
        end = SourcePosition(exc.end, line, column + max(1, exc.end - exc.start))
        diagnostic = Diagnostic(
            "error",
            "HOCUS010",
            "lex",
            "Source contains an invalid Unicode scalar value.",
            SourceSpan(source_name, start, end),
        )
        return CompileResult(
            source_name=source_name,
            source_digest="sha256:invalid-unicode",
            language_version=None,
            valid=False,
            diagnostics=[diagnostic],
        )
    if len(source_bytes) > MAX_SOURCE_BYTES:
        position = SourcePosition(0, 1, 1)
        diagnostic = Diagnostic(
            "error",
            "HOCUS001",
            "lex",
            f"Source exceeds the {MAX_SOURCE_BYTES}-byte limit.",
            SourceSpan(source_name, position, position),
        )
        return CompileResult(
            source_name=source_name,
            source_digest="sha256:source-too-large",
            language_version=None,
            valid=False,
            diagnostics=[diagnostic],
        )
    digest = hashlib.sha256(source_bytes).hexdigest()
    diagnostics: list[Diagnostic] = []
    graph: GraphSpec | None = None
    try:
        tokens = Lexer(source, source_name).tokenize()
        parser = Parser(tokens)
        graph = parser.parse()
        diagnostics.extend(parser.diagnostics)
        if strict:
            for item in diagnostics:
                if item.code == "HOCUS101":
                    item.severity = "error"
                    item.message = "Missing required 'hocus 0.1;' language header."
        remaining_diagnostics = max(1, max_diagnostics - len(diagnostics))
        diagnostics.extend(validate_graph(graph, max_diagnostics=remaining_diagnostics))
    except HocusSourceError as exc:
        diagnostics.append(exc.diagnostic)
    except RecursionError:
        position = SourcePosition(0, 1, 1)
        diagnostics.append(
            Diagnostic(
                "error",
                "HOCUS246",
                "parse",
                "Source nesting exceeded the parser safety limit.",
                SourceSpan(source_name, position, position),
            )
        )

    truncation_diagnostics = [item for item in diagnostics if item.code == "HOCUS019"]
    diagnostics = sort_diagnostics([item for item in diagnostics if item.code != "HOCUS019"])
    diagnostics.extend(truncation_diagnostics)
    if len(diagnostics) > max_diagnostics:
        omitted = len(diagnostics) - (max_diagnostics - 1)
        diagnostics = diagnostics[: max_diagnostics - 1]
        span = graph.span if graph is not None else SourceSpan(
            source_name,
            SourcePosition(0, 1, 1),
            SourcePosition(0, 1, 1),
        )
        diagnostics.append(
            Diagnostic(
                "error",
                "HOCUS019",
                "structural",
                f"Diagnostic output truncated; {omitted} additional diagnostic(s) omitted.",
                span,
                details={"omittedCount": omitted, "limit": max_diagnostics},
            )
        )
    valid = graph is not None and not any(item.severity == "error" for item in diagnostics)
    return CompileResult(
        source_name=source_name,
        source_digest=f"sha256:{digest}",
        language_version=graph.language_version if graph is not None else None,
        valid=valid,
        diagnostics=diagnostics,
        graph_spec=graph,
        formatted_source=format_graph(graph) if valid and graph is not None else None,
    )

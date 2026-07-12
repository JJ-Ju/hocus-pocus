"""Pure editor-facing check, format, and completion APIs for HocusScript."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from .catalog import CatalogProvider, CatalogSnapshot, OperatorDefinition, ParameterDefinition
from .compiler import MAX_SOURCE_BYTES, MAX_SOURCE_NAME_CHARACTERS, compile_source
from .diagnostics import Diagnostic, SourcePosition, SourceSpan, sort_diagnostics
from .model import CompileResult, GraphSpec
from .semantic import SemanticResult, resolve_graph

MAX_COMPLETION_ITEMS = 200
EDITOR_INTERFACE_VERSION = "1.0"
OFFSET_ENCODING = "unicode_code_points"


@dataclass(frozen=True, slots=True)
class EditorCheckResult:
    source_name: str
    source_uri: str
    source_digest: str
    valid: bool
    diagnostics: tuple[Diagnostic, ...]
    graph_spec: GraphSpec | None
    catalog_fingerprint: str | None = None
    semantic_result: SemanticResult | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "interfaceVersion": EDITOR_INTERFACE_VERSION,
            "offsetEncoding": OFFSET_ENCODING,
            "sourceName": self.source_name,
            "sourceUri": self.source_uri,
            "sourceDigest": self.source_digest,
            "valid": self.valid,
            "diagnosticCount": len(self.diagnostics),
            "diagnostics": [item.to_dict() for item in self.diagnostics],
            "catalogFingerprint": self.catalog_fingerprint,
            "graphSpec": self.graph_spec.to_dict() if self.graph_spec is not None else None,
            "semanticResolution": (
                self.semantic_result.to_dict() if self.semantic_result is not None else None
            ),
        }


@dataclass(frozen=True, slots=True)
class EditorFormatResult:
    source_name: str
    source_uri: str
    source_digest: str
    valid: bool
    changed: bool
    formatted_source: str | None
    diagnostics: tuple[Diagnostic, ...]
    language_version: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "interfaceVersion": EDITOR_INTERFACE_VERSION,
            "offsetEncoding": OFFSET_ENCODING,
            "languageVersion": self.language_version,
            "sourceName": self.source_name,
            "sourceUri": self.source_uri,
            "sourceDigest": self.source_digest,
            "valid": self.valid,
            "changed": self.changed,
            "formattedSource": self.formatted_source,
            "diagnosticCount": len(self.diagnostics),
            "diagnostics": [item.to_dict() for item in self.diagnostics],
        }


@dataclass(frozen=True, slots=True)
class CompletionItem:
    label: str
    kind: str
    insert_text: str
    replacement_span: SourceSpan
    detail: str | None = None
    documentation: str | None = None
    sort_text: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "kind": self.kind,
            "insertText": self.insert_text,
            "replacementSpan": self.replacement_span.to_dict(),
            "detail": self.detail,
            "documentation": self.documentation,
            "sortText": self.sort_text or self.label.casefold(),
        }


@dataclass(frozen=True, slots=True)
class CompletionResult:
    source_uri: str
    offset: int
    context: str
    items: tuple[CompletionItem, ...]
    catalog_fingerprint: str
    is_incomplete: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "interfaceVersion": EDITOR_INTERFACE_VERSION,
            "offsetEncoding": OFFSET_ENCODING,
            "sourceUri": self.source_uri,
            "offset": self.offset,
            "context": self.context,
            "catalogFingerprint": self.catalog_fingerprint,
            "isIncomplete": self.is_incomplete,
            "items": [item.to_dict() for item in self.items],
        }


def check_source(
    source: str,
    source_name: str = "<memory>",
    *,
    source_uri: str | None = None,
    catalog: CatalogSnapshot | CatalogProvider | None = None,
    strict: bool = True,
    max_diagnostics: int = 100,
) -> EditorCheckResult:
    """Return stable structural and optional catalog-semantic diagnostics."""
    compiled = compile_source(
        source,
        source_name,
        source_uri=source_uri,
        strict=strict,
        max_diagnostics=max_diagnostics,
    )
    semantic: SemanticResult | None = None
    fingerprint: str | None = None
    diagnostics = list(compiled.diagnostics)
    if catalog is not None and compiled.valid and compiled.graph_spec is not None:
        snapshot = _catalog_snapshot(catalog)
        fingerprint = snapshot.fingerprint
        semantic = resolve_graph(compiled.graph_spec, snapshot)
        diagnostics.extend(semantic.diagnostics)
    diagnostics = sort_diagnostics(diagnostics)
    if len(diagnostics) > max_diagnostics:
        omitted = len(diagnostics) - (max_diagnostics - 1)
        span = compiled.graph_spec.span if compiled.graph_spec is not None else diagnostics[0].span
        diagnostics = diagnostics[: max_diagnostics - 1]
        diagnostics.append(
            Diagnostic(
                "error",
                "HOCUS019",
                "editor",
                f"Diagnostic output truncated; {omitted} additional diagnostic(s) omitted.",
                span,
                details={"omittedCount": omitted, "limit": max_diagnostics},
            )
        )
    valid = compiled.graph_spec is not None and not any(item.severity == "error" for item in diagnostics)
    return EditorCheckResult(
        compiled.source_name,
        compiled.source_uri or compiled.source_name,
        compiled.source_digest,
        valid,
        tuple(diagnostics),
        compiled.graph_spec,
        fingerprint,
        semantic,
    )


def format_source(
    source: str,
    source_name: str = "<memory>",
    *,
    source_uri: str | None = None,
    strict: bool = True,
    max_diagnostics: int = 100,
) -> EditorFormatResult:
    """Return canonical text only when the structural source is valid."""
    compiled: CompileResult = compile_source(
        source,
        source_name,
        source_uri=source_uri,
        strict=strict,
        max_diagnostics=max_diagnostics,
    )
    formatted = compiled.formatted_source if compiled.valid else None
    return EditorFormatResult(
        compiled.source_name,
        compiled.source_uri or compiled.source_name,
        compiled.source_digest,
        compiled.valid,
        formatted is not None and formatted != source,
        formatted,
        tuple(compiled.diagnostics),
        compiled.language_version,
    )


def complete_source(
    source: str,
    offset: int,
    catalog: CatalogSnapshot | CatalogProvider,
    *,
    source_name: str = "<memory>",
    source_uri: str | None = None,
    limit: int = MAX_COMPLETION_ITEMS,
) -> CompletionResult:
    """Complete incomplete source without requiring it to parse successfully."""
    if not isinstance(source, str):
        raise TypeError("source must be a string")
    try:
        source_bytes = source.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError("source contains an invalid Unicode scalar value") from exc
    if len(source_bytes) > MAX_SOURCE_BYTES:
        raise ValueError(f"source must not exceed {MAX_SOURCE_BYTES} UTF-8 bytes")
    if isinstance(offset, bool) or not isinstance(offset, int) or not 0 <= offset <= len(source):
        raise ValueError("offset must be within source")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_COMPLETION_ITEMS:
        raise ValueError(f"limit must be between 1 and {MAX_COMPLETION_ITEMS}")
    if not isinstance(source_name, str) or not source_name.strip():
        raise TypeError("source_name must be a non-empty string")
    if len(source_name) > MAX_SOURCE_NAME_CHARACTERS:
        raise TypeError(f"source_name must not exceed {MAX_SOURCE_NAME_CHARACTERS} characters")
    if source_uri is not None and (not isinstance(source_uri, str) or not source_uri.strip()):
        raise TypeError("source_uri must be a non-empty string when provided")
    diagnostic_source = source_uri.strip() if source_uri is not None else (
        f"hocus-memory:///{quote(source_name, safe='/-._~')}"
    )
    snapshot = _catalog_snapshot(catalog)
    before = source[:offset]
    prefix, prefix_start = _completion_prefix(before)
    span = SourceSpan(
        diagnostic_source,
        _position(source, prefix_start),
        _position(source, offset),
    )

    context, candidates = _completion_candidates(before, snapshot)
    folded = prefix.casefold()
    candidates = [item for item in candidates if not folded or item[0].casefold().startswith(folded)]
    candidates.sort(key=lambda item: (item[0].casefold(), item[0], item[1]))
    incomplete = len(candidates) > limit
    items = tuple(
        CompletionItem(label, kind, insert_text, span, detail, documentation)
        for label, kind, insert_text, detail, documentation in candidates[:limit]
    )
    return CompletionResult(
        diagnostic_source, offset, context, items, snapshot.fingerprint, incomplete
    )


def _catalog_snapshot(catalog: CatalogSnapshot | CatalogProvider) -> CatalogSnapshot:
    return catalog if isinstance(catalog, CatalogSnapshot) else catalog.get_catalog()


def _position(source: str, offset: int) -> SourcePosition:
    prefix = source[:offset]
    line = prefix.count("\n") + 1
    newline = prefix.rfind("\n")
    return SourcePosition(offset, line, offset - newline)


def _completion_prefix(before: str) -> tuple[str, int]:
    match = re.search(r"[A-Za-z_][A-Za-z0-9_:.-]*$", before)
    return (match.group(0), match.start()) if match else ("", len(before))


def _category(before: str) -> str | None:
    matches = list(re.finditer(r"\bcategory\s+(?:=\s*)?([A-Za-z_][A-Za-z0-9_]*)\s*;", before))
    return matches[-1].group(1) if matches else None


def _operator_candidates(
    snapshot: CatalogSnapshot, category: str | None, *, quoted: bool
) -> list[tuple[str, str, str, str | None, str | None]]:
    operators = [item for item in snapshot.operators if category is None or item.category == category]
    return [
        (
            item.qualified_name,
            "operator",
            item.qualified_name + '"' if quoted else json.dumps(item.qualified_name, ensure_ascii=False),
            f"{item.category} node type",
            f"{item.source.kind} operator; {len(item.parameters)} parameters",
        )
        for item in operators
    ]


def _active_node(before: str, snapshot: CatalogSnapshot) -> tuple[str, OperatorDefinition] | None:
    header = re.compile(
        r"\bnode\s+([A-Za-z_][A-Za-z0-9_]*)"
        r"(?:\s*@id\s*\(\s*\"[^\"]+\"\s*\))?\s*:\s*"
        r"(?:\"([^\"]+)\"|([A-Za-z_][A-Za-z0-9_:]*))\s*\{"
    )
    category = _category(before)
    for match in reversed(list(header.finditer(before))):
        tail = _mask_literals_and_comments(before[match.end() :])
        if tail.count("}") > tail.count("{"):
            continue
        type_name = match.group(2) or match.group(3)
        definitions = [
            item
            for item in snapshot.operators
            if (category is None or item.category == category)
            and type_name in {item.qualified_name, item.name, *item.aliases}
        ]
        if len(definitions) == 1:
            return match.group(1), definitions[0]
    return None


def _mask_literals_and_comments(source: str) -> str:
    chars = list(source)
    index = 0
    quote: str | None = None
    while index < len(chars):
        if quote is not None:
            if chars[index] == "\\":
                chars[index] = " "
                if index + 1 < len(chars):
                    chars[index + 1] = " "
                    index += 2
                    continue
            if chars[index] == quote:
                quote = None
            if chars[index] != "\n":
                chars[index] = " "
            index += 1
            continue
        if source.startswith("//", index):
            end = source.find("\n", index)
            end = len(source) if end < 0 else end
            for cursor in range(index, end):
                chars[cursor] = " "
            index = end
            continue
        if chars[index] in {'"', "`"}:
            quote = chars[index]
            chars[index] = " "
        index += 1
    return "".join(chars)


def _symbols(before: str) -> list[str]:
    values = re.findall(r"\b(?:node|existing|adopt)\s+([A-Za-z_][A-Za-z0-9_]*)", before)
    return sorted(set(values), key=lambda value: (value.casefold(), value))


def _completion_candidates(
    before: str, snapshot: CatalogSnapshot
) -> tuple[str, list[tuple[str, str, str, str | None, str | None]]]:
    if re.search(r"\bhocus\s+[A-Za-z0-9.]*$", before):
        return "language_version", [("0.1", "value", "0.1", "language version", None)]
    if re.search(r"\bcategory\s+(?:=\s*)?[A-Za-z0-9_]*$", before):
        return "category", [
            (item.name, "category", item.name, item.label, item.network_family)
            for item in snapshot.categories
        ]
    if re.search(r"\bmode\s+(?:=\s*)?[A-Za-z0-9_]*$", before):
        return "mode", [(value, "value", value, "graph mode", None) for value in ("merge", "reconcile")]
    if re.search(r"\blayout\s+(?:=\s*)?[A-Za-z0-9_]*$", before):
        return "layout", [("auto", "value", "auto", "deterministic layout", None)]
    node_type = re.search(
        r"\bnode\s+[A-Za-z_][A-Za-z0-9_]*"
        r"(?:\s*@id\s*\(\s*\"[^\"]+\"\s*\))?\s*:\s*"
        r"(\")?[A-Za-z0-9_:.-]*$",
        before,
    )
    if node_type:
        return "node_type", _operator_candidates(
            snapshot, _category(before), quoted=node_type.group(1) is not None
        )

    active = _active_node(before, snapshot)
    if active is not None:
        _, operator = active
        if re.search(r"\binput\s*\[\s*\d*\s*\]\s*=\s*[A-Za-z0-9_]*$", before):
            return "node_reference", [
                (symbol, "reference", symbol, "graph node", None) for symbol in _symbols(before)
            ]
        value_match = re.search(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*=\s*\"?[A-Za-z0-9_.:-]*$", before)
        if value_match:
            parameter = next((item for item in operator.parameters if item.token == value_match.group(1)), None)
            if parameter is not None and parameter.menu:
                quoted = before[value_match.end(1) :].lstrip().startswith('= "')
                return "menu_value", [
                    (
                        item.token,
                        "enum_member",
                        item.token + '"' if quoted else json.dumps(item.token),
                        item.label,
                        parameter.label,
                    )
                    for item in parameter.menu
                ]
        return "parameter", [
            (
                item.token,
                "parameter",
                f"{item.token} = ",
                f"{item.label}: {item.value_type}",
                _parameter_documentation(item),
            )
            for item in operator.parameters
            if item.assignable
        ] + [("input", "keyword", "input[", "node input", None)]

    if re.search(r"\b(?:display|render|output)\s*=\s*[A-Za-z0-9_]*$", before):
        return "node_reference", [
            (symbol, "reference", symbol, "graph node", None) for symbol in _symbols(before)
        ]
    return "graph", [
        (label, "keyword", insert, detail, None)
        for label, insert, detail in (
            ("target", 'target "";', "target network"),
            ("category", "category ", "network category"),
            ("mode", "mode merge;", "merge policy"),
            ("ownership", 'ownership "";', "ownership namespace"),
            ("existing", 'existing name = "";', "external node"),
            ("adopt", 'adopt name = "";', "adopted external node"),
            ("node", 'node name: "" {\n  }', "authored node"),
            ("display", "display = ", "display node"),
            ("render", "render = ", "render node"),
            ("output", "output = ", "network output"),
            ("layout", "layout = auto;", "deterministic layout"),
        )
    ]


def _parameter_documentation(parameter: ParameterDefinition) -> str:
    details = [f"type={parameter.value_type}", f"tupleSize={parameter.tuple_size}"]
    if parameter.code_surface != "none":
        details.append(f"code={parameter.code_surface}")
    return ", ".join(details)

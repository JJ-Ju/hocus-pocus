"""Typed syntax and GraphSpec model for HocusScript 0.1."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .diagnostics import CodeOffsetMap, Diagnostic, SourceSpan

GRAPH_SPEC_VERSION = "0.1"
COMPILER_VERSION = "0.2.0"


def _value_to_dict(value: Any) -> Any:
    if isinstance(value, (LiteralValue, ArrayValue, CodeValue)):
        return value.to_dict()
    return value


@dataclass(slots=True)
class LiteralValue:
    value: Any
    span: SourceSpan

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "literal",
            "value": self.value,
            "span": self.span.to_dict(),
        }


@dataclass(slots=True)
class ArrayValue:
    items: list[Any]
    span: SourceSpan

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "array",
            "items": [_value_to_dict(item) for item in self.items],
            "span": self.span.to_dict(),
        }


@dataclass(slots=True)
class CodeValue:
    language: str
    body: str
    span: SourceSpan
    body_span: SourceSpan | None = None
    offset_map: CodeOffsetMap | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "kind": "code",
            "language": self.language,
            "body": self.body,
            "span": self.span.to_dict(),
        }
        if self.body_span is not None:
            payload["bodySpan"] = self.body_span.to_dict()
        if self.offset_map is not None:
            payload["offsetMap"] = self.offset_map.to_dict()
        return payload


@dataclass(slots=True)
class NodeReference:
    symbol: str
    output_index: int
    span: SourceSpan
    field_spans: dict[str, SourceSpan] = field(default_factory=dict, repr=False)

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "symbol": self.symbol,
            "outputIndex": self.output_index,
            "span": self.span.to_dict(),
        }
        if self.field_spans:
            payload["fieldSpans"] = {key: value.to_dict() for key, value in sorted(self.field_spans.items())}
        return payload


@dataclass(slots=True)
class InputSpec:
    index: int
    source: NodeReference
    span: SourceSpan
    field_spans: dict[str, SourceSpan] = field(default_factory=dict, repr=False)

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "index": self.index,
            "source": self.source.to_dict(),
            "span": self.span.to_dict(),
        }
        if self.field_spans:
            payload["fieldSpans"] = {key: value.to_dict() for key, value in sorted(self.field_spans.items())}
        return payload


@dataclass(slots=True)
class ParmSpec:
    name: str
    value: Any
    span: SourceSpan
    field_spans: dict[str, SourceSpan] = field(default_factory=dict, repr=False)

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "name": self.name,
            "value": _value_to_dict(self.value),
            "span": self.span.to_dict(),
        }
        if self.field_spans:
            payload["fieldSpans"] = {key: value.to_dict() for key, value in sorted(self.field_spans.items())}
        return payload


@dataclass(slots=True)
class NodeSpec:
    symbol: str
    type_name: str
    inputs: list[InputSpec]
    parms: list[ParmSpec]
    span: SourceSpan
    field_spans: dict[str, SourceSpan] = field(default_factory=dict, repr=False)

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "symbol": self.symbol,
            "typeName": self.type_name,
            "inputs": [item.to_dict() for item in self.inputs],
            "parms": [item.to_dict() for item in self.parms],
            "span": self.span.to_dict(),
        }
        if self.field_spans:
            payload["fieldSpans"] = {key: value.to_dict() for key, value in sorted(self.field_spans.items())}
        return payload


@dataclass(slots=True)
class ExternalNodeSpec:
    symbol: str
    path: str
    adopted: bool
    span: SourceSpan
    field_spans: dict[str, SourceSpan] = field(default_factory=dict, repr=False)

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "symbol": self.symbol,
            "path": self.path,
            "adopted": self.adopted,
            "span": self.span.to_dict(),
        }
        if self.field_spans:
            payload["fieldSpans"] = {key: value.to_dict() for key, value in sorted(self.field_spans.items())}
        return payload


@dataclass(slots=True)
class GraphSpec:
    language_version: str
    name: str
    target: str | None
    category: str | None
    mode: str
    expected_revision: int | None
    ownership: str | None
    external_nodes: list[ExternalNodeSpec]
    nodes: list[NodeSpec]
    display: str | None
    render: str | None
    output: str | None
    layout: str | None
    span: SourceSpan
    field_spans: dict[str, SourceSpan] = field(default_factory=dict, repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "$schema": "hocuspocus://schemas/graph-spec/v0.1",
            "kind": "graph_spec",
            "graphSpecVersion": GRAPH_SPEC_VERSION,
            "languageVersion": self.language_version,
            "name": self.name,
            "target": self.target,
            "category": self.category,
            "mode": self.mode,
            "expectedRevision": self.expected_revision,
            "ownership": self.ownership,
            "externalNodes": [item.to_dict() for item in self.external_nodes],
            "nodes": [item.to_dict() for item in self.nodes],
            "display": self.display,
            "render": self.render,
            "output": self.output,
            "layout": self.layout,
            "span": self.span.to_dict(),
            "fieldSpans": {
                key: value.to_dict()
                for key, value in sorted(self.field_spans.items())
            },
        }


@dataclass(slots=True)
class CompileResult:
    source_name: str
    source_digest: str
    language_version: str | None
    valid: bool
    source_uri: str | None = None
    source_kind: str = "memory"
    project_uid: str | None = None
    project_manifest_digest: str | None = None
    project_lock_digest: str | None = None
    catalog_content_digest: str | None = None
    catalog_fingerprint: str | None = None
    semantic_result: Any | None = None
    native_source_path: str | None = field(default=None, repr=False)
    diagnostics: list[Diagnostic] = field(default_factory=list)
    graph_spec: GraphSpec | None = None
    formatted_source: str | None = None

    def to_dict(self) -> dict[str, Any]:
        semantic = self.semantic_result.to_dict() if self.semantic_result is not None else None
        return {
            "stage": "semantic" if semantic is not None else "structural",
            "compilerVersion": COMPILER_VERSION,
            "graphSpecVersion": GRAPH_SPEC_VERSION,
            "sourceName": self.source_name,
            "sourceUri": self.source_uri or self.source_name,
            "sourceKind": self.source_kind,
            "sourceDigest": self.source_digest,
            "projectUid": self.project_uid,
            "projectManifestDigest": self.project_manifest_digest,
            "projectLockDigest": self.project_lock_digest,
            "catalogContentDigest": self.catalog_content_digest,
            "catalogFingerprint": self.catalog_fingerprint,
            "languageVersion": self.language_version,
            "valid": self.valid,
            "diagnosticCount": len(self.diagnostics),
            "diagnostics": [item.to_dict() for item in self.diagnostics],
            "graphSpec": self.graph_spec.to_dict() if self.graph_spec is not None else None,
            "formattedSource": self.formatted_source,
            "semanticResolution": semantic,
            "readyForDocumentLowering": bool(
                semantic is not None and semantic.get("readyForDocumentLowering", False)
            ),
            "readyForApply": False,
        }

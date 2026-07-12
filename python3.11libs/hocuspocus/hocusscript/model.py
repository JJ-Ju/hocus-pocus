"""Typed syntax and GraphSpec model for HocusScript 0.1."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any

from .diagnostics import CodeOffsetMap, Diagnostic, SourcePosition, SourceSpan

LEGACY_GRAPH_SPEC_VERSION = "0.1"
GRAPH_SPEC_VERSION = "0.2"
LEGACY_COMPILER_VERSION = "0.2.0"
COMPILER_VERSION = "0.3.0"
EXPLICIT_NODE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


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
    explicit_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "symbol": self.symbol,
            "typeName": self.type_name,
            "inputs": [item.to_dict() for item in self.inputs],
            "parms": [item.to_dict() for item in self.parms],
            "span": self.span.to_dict(),
        }
        if self.explicit_id is not None:
            payload["explicitId"] = self.explicit_id
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
            "$schema": f"hocuspocus://schemas/graph-spec/v{GRAPH_SPEC_VERSION}",
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


def graph_spec_from_dict(value: dict[str, Any]) -> GraphSpec:
    """Rehydrate a GraphSpec that already crossed the strict bundle boundary."""

    def position(item: dict[str, Any]) -> SourcePosition:
        return SourcePosition(offset=item["offset"], line=item["line"], column=item["column"])

    def span(item: dict[str, Any]) -> SourceSpan:
        return SourceSpan(item["sourceUri"], position(item["start"]), position(item["end"]))

    def field_spans(item: dict[str, Any]) -> dict[str, SourceSpan]:
        return {key: span(child) for key, child in item.get("fieldSpans", {}).items()}

    def decoded_value(item: dict[str, Any]) -> Any:
        kind = item["kind"]
        if kind == "literal":
            return LiteralValue(item["value"], span(item["span"]))
        if kind == "array":
            return ArrayValue([decoded_value(child) for child in item["items"]], span(item["span"]))
        body_span = span(item["bodySpan"]) if "bodySpan" in item else None
        offset_map = None
        if "offsetMap" in item:
            encoded = item["offsetMap"]
            offset_map = CodeOffsetMap(
                encoded["bodyLength"],
                tuple((point["bodyOffset"], point["sourceOffset"]) for point in encoded["checkpoints"]),
            )
        return CodeValue(item["language"], item["body"], span(item["span"]), body_span, offset_map)

    external_nodes = [
        ExternalNodeSpec(
            item["symbol"], item["path"], item["adopted"], span(item["span"]), field_spans(item)
        )
        for item in value["externalNodes"]
    ]
    nodes = []
    for item in value["nodes"]:
        inputs = [
            InputSpec(
                child["index"],
                NodeReference(
                    child["source"]["symbol"],
                    child["source"]["outputIndex"],
                    span(child["source"]["span"]),
                    field_spans(child["source"]),
                ),
                span(child["span"]),
                field_spans(child),
            )
            for child in item["inputs"]
        ]
        parms = [
            ParmSpec(
                child["name"], decoded_value(child["value"]), span(child["span"]), field_spans(child)
            )
            for child in item["parms"]
        ]
        nodes.append(NodeSpec(
            item["symbol"], item["typeName"], inputs, parms, span(item["span"]),
            field_spans(item), item.get("explicitId"),
        ))
    return GraphSpec(
        value["languageVersion"], value["name"], value["target"], value["category"], value["mode"],
        value["expectedRevision"], value["ownership"], external_nodes, nodes, value["display"],
        value["render"], value["output"], value["layout"], span(value["span"]), field_spans(value),
    )


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

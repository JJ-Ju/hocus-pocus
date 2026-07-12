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
MODULE_LANGUAGE_VERSION = "0.2"
MODULE_GRAPH_SPEC_VERSION = "0.3"
MODULE_COMPILER_VERSION = "0.4.0"
EXPANSION_MAP_VERSION = 1
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


@dataclass(frozen=True, slots=True)
class ExpansionFrame:
    module_uri: str
    source_digest: str
    module_name: str
    instance_symbol: str
    instance_id_path: tuple[str, ...]
    import_span: SourceSpan | None
    use_span: SourceSpan

    def to_dict(self) -> dict[str, Any]:
        return {
            "moduleUri": self.module_uri,
            "sourceDigest": self.source_digest,
            "moduleName": self.module_name,
            "instanceSymbol": self.instance_symbol,
            "instanceIdPath": list(self.instance_id_path),
            "importSpan": self.import_span.to_dict() if self.import_span is not None else None,
            "useSpan": self.use_span.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class ExpansionStack:
    stack_id: str
    frames: tuple[ExpansionFrame, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"stackId": self.stack_id, "frames": [item.to_dict() for item in self.frames]}


@dataclass(frozen=True, slots=True)
class RelatedOrigin:
    role: str
    span: SourceSpan

    def to_dict(self) -> dict[str, Any]:
        return {"role": self.role, "span": self.span.to_dict()}


@dataclass(frozen=True, slots=True)
class ExpansionOrigin:
    origin_id: str
    generated_pointer: str
    origin_kind: str
    primary_span: SourceSpan
    related_origins: tuple[RelatedOrigin, ...] = ()
    stack_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "originId": self.origin_id,
            "generatedPointer": self.generated_pointer,
            "originKind": self.origin_kind,
            "primarySpan": self.primary_span.to_dict(),
            "relatedOrigins": [item.to_dict() for item in self.related_origins],
            "stackId": self.stack_id,
        }


@dataclass(frozen=True, slots=True)
class ExpansionMap:
    entry_source_uri: str
    stacks: tuple[ExpansionStack, ...] = ()
    mappings: tuple[ExpansionOrigin, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "$schema": "hocuspocus://schemas/expansion-map/v1",
            "kind": "hocus_expansion_map",
            "schemaVersion": 1,
            "graphSpecVersion": MODULE_GRAPH_SPEC_VERSION,
            "entrySourceUri": self.entry_source_uri,
            "stacks": [item.to_dict() for item in self.stacks],
            "mappings": [item.to_dict() for item in self.mappings],
        }


@dataclass(frozen=True, slots=True)
class ModuleDependency:
    uri: str
    module_name: str
    relative_path: str
    origin: str
    owner_uid: str
    alias: str | None
    version: str | None
    module_manifest_digest: str | None
    source_digest: str
    interface_digest: str
    transitive_digest: str
    dependencies: tuple[str, ...] = ()
    language_version: str = MODULE_LANGUAGE_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "uri": self.uri,
            "moduleName": self.module_name,
            "relativePath": self.relative_path,
            "origin": self.origin,
            "ownerUid": self.owner_uid,
            "alias": self.alias,
            "version": self.version,
            "moduleManifestDigest": self.module_manifest_digest,
            "sourceDigest": self.source_digest,
            "interfaceDigest": self.interface_digest,
            "transitiveDigest": self.transitive_digest,
            "dependencies": list(self.dependencies),
            "languageVersion": self.language_version,
        }


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
    graph_spec_version: str = GRAPH_SPEC_VERSION
    expansion_map: ExpansionMap | None = None

    def __post_init__(self) -> None:
        if self.graph_spec_version in {LEGACY_GRAPH_SPEC_VERSION, GRAPH_SPEC_VERSION}:
            if self.language_version != "0.1" or self.expansion_map is not None:
                raise ValueError("GraphSpec v0.1/v0.2 requires language 0.1 without expansionMap")
            return
        if self.graph_spec_version == MODULE_GRAPH_SPEC_VERSION:
            if self.language_version != MODULE_LANGUAGE_VERSION or self.expansion_map is None:
                raise ValueError("GraphSpec v0.3 requires language 0.2 and expansionMap v1")
            return
        raise ValueError(f"Unsupported GraphSpec version: {self.graph_spec_version}")

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "$schema": f"hocuspocus://schemas/graph-spec/v{self.graph_spec_version}",
            "kind": "graph_spec",
            "graphSpecVersion": self.graph_spec_version,
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
        if self.graph_spec_version == MODULE_GRAPH_SPEC_VERSION:
            if self.expansion_map is None:
                raise ValueError("GraphSpec v0.3 requires an expansion map")
            payload["expansionMap"] = self.expansion_map.to_dict()
        return payload


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
    expansion_map = None
    if "expansionMap" in value:
        encoded_map = value["expansionMap"]
        expansion_map = ExpansionMap(
            entry_source_uri=encoded_map["entrySourceUri"],
            stacks=tuple(
                ExpansionStack(
                    stack_id=item["stackId"],
                    frames=tuple(
                        ExpansionFrame(
                            frame["moduleUri"], frame["sourceDigest"], frame["moduleName"],
                            frame["instanceSymbol"], tuple(frame["instanceIdPath"]),
                            span(frame["importSpan"]) if frame["importSpan"] is not None else None,
                            span(frame["useSpan"]),
                        )
                        for frame in item["frames"]
                    ),
                )
                for item in encoded_map["stacks"]
            ),
            mappings=tuple(
                ExpansionOrigin(
                    origin_id=item["originId"],
                    generated_pointer=item["generatedPointer"],
                    origin_kind=item["originKind"],
                    primary_span=span(item["primarySpan"]),
                    related_origins=tuple(
                        RelatedOrigin(child["role"], span(child["span"]))
                        for child in item["relatedOrigins"]
                    ),
                    stack_id=item["stackId"],
                )
                for item in encoded_map["mappings"]
            ),
        )
    return GraphSpec(
        value["languageVersion"], value["name"], value["target"], value["category"], value["mode"],
        value["expectedRevision"], value["ownership"], external_nodes, nodes, value["display"],
        value["render"], value["output"], value["layout"], span(value["span"]), field_spans(value),
        value["graphSpecVersion"], expansion_map,
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

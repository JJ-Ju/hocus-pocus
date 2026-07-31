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
CONTROL_LANGUAGE_VERSION = "0.3"
CONTROL_GRAPH_SPEC_VERSION = "0.4"
CONTROL_EXPANSION_MAP_VERSION = 2
VALUE_LANGUAGE_VERSION = "0.4"
VALUE_GRAPH_SPEC_VERSION = "0.5"
VALUE_COMPILER_VERSION = "0.6.0"
VALUE_EXPANSION_MAP_VERSION = 3
EXPLICIT_NODE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def _value_to_dict(value: Any) -> Any:
    if isinstance(value, (LiteralValue, ArrayValue, CodeValue, TaggedValue)):
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
class TaggedValue:
    tag: str
    payload: dict[str, Any]
    span: SourceSpan

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.tag,
            **{
                key: _tagged_payload_to_dict(value)
                for key, value in self.payload.items()
            },
            "span": self.span.to_dict(),
        }


def _tagged_payload_to_dict(value: Any) -> Any:
    if isinstance(value, (LiteralValue, ArrayValue, CodeValue, TaggedValue)):
        return value.to_dict()
    if isinstance(value, list):
        return [_tagged_payload_to_dict(item) for item in value]
    if isinstance(value, dict):
        return {
            key: _tagged_payload_to_dict(item)
            for key, item in value.items()
        }
    return value


@dataclass(slots=True)
class NodeReference:
    symbol: str
    output_index: int | None
    span: SourceSpan
    field_spans: dict[str, SourceSpan] = field(default_factory=dict, repr=False)
    output_name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "symbol": self.symbol,
            "span": self.span.to_dict(),
        }
        payload["outputName" if self.output_name is not None else "outputIndex"] = (
            self.output_name if self.output_name is not None else self.output_index
        )
        if self.field_spans:
            payload["fieldSpans"] = {key: value.to_dict() for key, value in sorted(self.field_spans.items())}
        return payload


@dataclass(slots=True)
class InputSpec:
    index: int | None
    source: NodeReference
    span: SourceSpan
    field_spans: dict[str, SourceSpan] = field(default_factory=dict, repr=False)
    name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "source": self.source.to_dict(),
            "span": self.span.to_dict(),
        }
        payload["name" if self.name is not None else "index"] = (
            self.name if self.name is not None else self.index
        )
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
    control_stack_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "originId": self.origin_id,
            "generatedPointer": self.generated_pointer,
            "originKind": self.origin_kind,
            "primarySpan": self.primary_span.to_dict(),
            "relatedOrigins": [item.to_dict() for item in self.related_origins],
            "stackId": self.stack_id,
        }
        if self.control_stack_id is not None:
            payload["controlStackId"] = self.control_stack_id
        return payload


@dataclass(frozen=True, slots=True)
class ExpansionMap:
    entry_source_uri: str
    stacks: tuple[ExpansionStack, ...] = ()
    mappings: tuple[ExpansionOrigin, ...] = ()
    schema_version: int = EXPANSION_MAP_VERSION
    graph_spec_version: str = MODULE_GRAPH_SPEC_VERSION
    control_stacks: tuple[dict[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        mappings = [item.to_dict() for item in self.mappings]
        if self.schema_version in {
            CONTROL_EXPANSION_MAP_VERSION,
            VALUE_EXPANSION_MAP_VERSION,
        }:
            for mapping in mappings:
                mapping.setdefault("controlStackId", None)
        payload = {
            "$schema": f"hocuspocus://schemas/expansion-map/v{self.schema_version}",
            "kind": "hocus_expansion_map",
            "schemaVersion": self.schema_version,
            "graphSpecVersion": self.graph_spec_version,
            "entrySourceUri": self.entry_source_uri,
            "stacks": [item.to_dict() for item in self.stacks],
            "mappings": mappings,
        }
        if self.schema_version in {
            CONTROL_EXPANSION_MAP_VERSION,
            VALUE_EXPANSION_MAP_VERSION,
        }:
            payload["controlStacks"] = [
                {
                    **item,
                    "frames": [dict(frame) for frame in item["frames"]],
                }
                for item in self.control_stacks
            ]
        return payload


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


def _validate_editor_lane(version: str, entities: Any) -> None:
    if version != VALUE_GRAPH_SPEC_VERSION and entities:
        raise ValueError("Editor entities require GraphSpec v0.5")
    if not isinstance(entities, list):
        raise ValueError("GraphSpec editor entities must be a list")


def _validate_runtime_lane(
    version: str, spares: Any, animations: Any, ownership: str | None,
) -> None:
    if version != VALUE_GRAPH_SPEC_VERSION and (spares or animations):
        raise ValueError("Runtime entities require GraphSpec v0.5")
    from .runtime_carrier import validate_runtime_carrier
    validate_runtime_carrier(spares, animations, ownership=ownership)


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
    editor_entities: list[dict[str, Any]] = field(default_factory=list)
    spare_parameters: list[dict[str, Any]] = field(default_factory=list)
    animations: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        _validate_editor_lane(self.graph_spec_version, self.editor_entities)
        _validate_runtime_lane(
            self.graph_spec_version, self.spare_parameters, self.animations,
            self.ownership,
        )
        if self.graph_spec_version in {LEGACY_GRAPH_SPEC_VERSION, GRAPH_SPEC_VERSION}:
            if self.language_version != "0.1" or self.expansion_map is not None:
                raise ValueError("GraphSpec v0.1/v0.2 requires language 0.1 without expansionMap")
            return
        if self.graph_spec_version == MODULE_GRAPH_SPEC_VERSION:
            if self.language_version != MODULE_LANGUAGE_VERSION or self.expansion_map is None:
                raise ValueError("GraphSpec v0.3 requires language 0.2 and expansionMap v1")
            if (
                self.expansion_map.schema_version != EXPANSION_MAP_VERSION
                or self.expansion_map.graph_spec_version != MODULE_GRAPH_SPEC_VERSION
            ):
                raise ValueError("GraphSpec v0.3 requires expansionMap v1")
            return
        if self.graph_spec_version == CONTROL_GRAPH_SPEC_VERSION:
            if self.language_version != CONTROL_LANGUAGE_VERSION or self.expansion_map is None:
                raise ValueError("GraphSpec v0.4 requires language 0.3 and expansionMap v2")
            if (
                self.expansion_map.schema_version != CONTROL_EXPANSION_MAP_VERSION
                or self.expansion_map.graph_spec_version != CONTROL_GRAPH_SPEC_VERSION
            ):
                raise ValueError("GraphSpec v0.4 requires expansionMap v2")
            return
        if self.graph_spec_version == VALUE_GRAPH_SPEC_VERSION:
            if self.language_version != VALUE_LANGUAGE_VERSION or self.expansion_map is None:
                raise ValueError("GraphSpec v0.5 requires language 0.4 and expansionMap v3")
            if (
                self.expansion_map.schema_version != VALUE_EXPANSION_MAP_VERSION
                or self.expansion_map.graph_spec_version != VALUE_GRAPH_SPEC_VERSION
            ):
                raise ValueError("GraphSpec v0.5 requires expansionMap v3")
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
        if self.graph_spec_version in {
            MODULE_GRAPH_SPEC_VERSION,
            CONTROL_GRAPH_SPEC_VERSION,
            VALUE_GRAPH_SPEC_VERSION,
        }:
            if self.expansion_map is None:
                raise ValueError("Module GraphSpec requires an expansion map")
            payload["expansionMap"] = self.expansion_map.to_dict()
        if self.graph_spec_version == VALUE_GRAPH_SPEC_VERSION:
            payload["editorEntities"] = [
                dict(item) for item in self.editor_entities
            ]
            payload["spareParameters"] = [
                dict(item) for item in self.spare_parameters
            ]
            payload["animations"] = [dict(item) for item in self.animations]
        return payload


def _decode_position(item: dict[str, Any]) -> SourcePosition:
    return SourcePosition(
        offset=item["offset"], line=item["line"], column=item["column"]
    )


def _decode_span(item: dict[str, Any]) -> SourceSpan:
    return SourceSpan(
        item["sourceUri"],
        _decode_position(item["start"]),
        _decode_position(item["end"]),
    )


def _decode_field_spans(item: dict[str, Any]) -> dict[str, SourceSpan]:
    return {
        key: _decode_span(child)
        for key, child in item.get("fieldSpans", {}).items()
    }


def _decode_graph_value(item: dict[str, Any]) -> Any:
    kind = item["kind"]
    if kind == "literal":
        return LiteralValue(item["value"], _decode_span(item["span"]))
    if kind == "array":
        return ArrayValue(
            [_decode_graph_value(child) for child in item["items"]],
            _decode_span(item["span"]),
        )
    if kind != "code":
        return TaggedValue(
            kind,
            {
                key: _decode_tagged_payload(child)
                for key, child in item.items()
                if key not in {"kind", "span"}
            },
            _decode_span(item["span"]),
        )
    body_span = _decode_span(item["bodySpan"]) if "bodySpan" in item else None
    offset_map = None
    if "offsetMap" in item:
        encoded = item["offsetMap"]
        offset_map = CodeOffsetMap(
            encoded["bodyLength"],
            tuple(
                (point["bodyOffset"], point["sourceOffset"])
                for point in encoded["checkpoints"]
            ),
        )
    return CodeValue(
        item["language"], item["body"], _decode_span(item["span"]),
        body_span, offset_map,
    )


def _decode_tagged_payload(item: Any) -> Any:
    if isinstance(item, dict) and "kind" in item and "span" in item:
        return _decode_graph_value(item)
    if isinstance(item, list):
        return [_decode_tagged_payload(child) for child in item]
    if isinstance(item, dict):
        return {
            key: _decode_tagged_payload(child) for key, child in item.items()
        }
    return item


def graph_spec_from_dict(value: dict[str, Any]) -> GraphSpec:
    """Rehydrate a GraphSpec that already crossed the strict bundle boundary."""

    span = _decode_span
    field_spans = _decode_field_spans
    decoded_value = _decode_graph_value

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
                child.get("index"),
                NodeReference(
                    child["source"]["symbol"],
                    child["source"].get("outputIndex"),
                    span(child["source"]["span"]),
                    field_spans(child["source"]),
                    child["source"].get("outputName"),
                ),
                span(child["span"]),
                field_spans(child),
                child.get("name"),
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
                    control_stack_id=item.get("controlStackId"),
                )
                for item in encoded_map["mappings"]
            ),
            schema_version=encoded_map["schemaVersion"],
            graph_spec_version=encoded_map["graphSpecVersion"],
            control_stacks=tuple(encoded_map.get("controlStacks", ())),
        )
    return GraphSpec(
        value["languageVersion"], value["name"], value["target"], value["category"], value["mode"],
        value["expectedRevision"], value["ownership"], external_nodes, nodes, value["display"],
        value["render"], value["output"], value["layout"], span(value["span"]), field_spans(value),
        value["graphSpecVersion"], expansion_map, value.get("editorEntities", []),
        value.get("spareParameters", []), value.get("animations", []),
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

"""Source-faithful language-0.4 network-editor declarations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias

from .diagnostics import SourceSpan
from .syntax import ArrayExpr, LiteralExpr


EDITOR_ENTITY_KEYWORDS = {
    "network_box",
    "sticky_note",
    "node_comment",
    "network_dot",
    "layout_constraint",
}


@dataclass(frozen=True, slots=True)
class EditorItemRef:
    item_kind: str
    identity: str
    span: SourceSpan
    identity_span: SourceSpan


@dataclass(frozen=True, slots=True)
class EditorItemRefs:
    items: tuple[EditorItemRef, ...]
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class EditorConnectionRef:
    item: EditorItemRef
    output_index: int
    span: SourceSpan
    output_index_span: SourceSpan


@dataclass(frozen=True, slots=True)
class EditorDestinationRef:
    node: EditorItemRef
    input_index: int
    span: SourceSpan
    input_index_span: SourceSpan


@dataclass(frozen=True, slots=True)
class EditorDestinationRefs:
    items: tuple[EditorDestinationRef, ...]
    span: SourceSpan


EditorPropertyValue: TypeAlias = (
    LiteralExpr
    | ArrayExpr
    | EditorItemRef
    | EditorItemRefs
    | EditorConnectionRef
    | EditorDestinationRefs
)


@dataclass(frozen=True, slots=True)
class EditorProperty:
    name: str
    value: EditorPropertyValue
    span: SourceSpan
    name_span: SourceSpan


@dataclass(frozen=True, slots=True)
class EditorEntityDecl:
    entity_kind: str
    explicit_id: str
    properties: tuple[EditorProperty, ...]
    span: SourceSpan
    explicit_id_span: SourceSpan

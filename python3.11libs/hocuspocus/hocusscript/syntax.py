"""Source-faithful syntax tree for HocusScript 0.1."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TypeAlias

from .diagnostics import CodeOffsetMap, SourceSpan


@dataclass(frozen=True, slots=True)
class VersionDecl:
    value: str
    quoted: bool
    span: SourceSpan
    value_span: SourceSpan


@dataclass(frozen=True, slots=True)
class LiteralExpr:
    value: Any
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class ArrayExpr:
    items: tuple["ValueExpr", ...]
    trailing_comma: bool
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class CodeExpr:
    language: str
    body: str
    span: SourceSpan
    body_span: SourceSpan
    offset_map: CodeOffsetMap


ValueExpr: TypeAlias = LiteralExpr | ArrayExpr | CodeExpr


@dataclass(frozen=True, slots=True)
class TargetStmt:
    value: str
    had_equal: bool
    span: SourceSpan
    value_span: SourceSpan


@dataclass(frozen=True, slots=True)
class CategoryStmt:
    value: str
    had_equal: bool
    span: SourceSpan
    value_span: SourceSpan


@dataclass(frozen=True, slots=True)
class ModeStmt:
    value: str
    had_equal: bool
    span: SourceSpan
    value_span: SourceSpan


@dataclass(frozen=True, slots=True)
class RevisionStmt:
    value: int
    had_revision_keyword: bool
    had_equal: bool
    span: SourceSpan
    value_span: SourceSpan


@dataclass(frozen=True, slots=True)
class OwnershipStmt:
    value: str
    had_equal: bool
    span: SourceSpan
    value_span: SourceSpan


@dataclass(frozen=True, slots=True)
class ExternalDecl:
    symbol: str
    path: str
    adopted: bool
    span: SourceSpan
    symbol_span: SourceSpan
    path_span: SourceSpan


@dataclass(frozen=True, slots=True)
class ReferenceExpr:
    symbol: str
    output_index: int
    explicit_output: bool
    port_keyword: str | None
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class InputStmt:
    index: int
    source: ReferenceExpr
    span: SourceSpan
    index_span: SourceSpan


@dataclass(frozen=True, slots=True)
class ParmStmt:
    name: str
    value: ValueExpr
    span: SourceSpan
    name_span: SourceSpan


NodeStmt: TypeAlias = InputStmt | ParmStmt


@dataclass(frozen=True, slots=True)
class NodeDecl:
    symbol: str
    type_name: str
    type_quoted: bool
    statements: tuple[NodeStmt, ...]
    span: SourceSpan
    symbol_span: SourceSpan
    type_span: SourceSpan


@dataclass(frozen=True, slots=True)
class FlagStmt:
    name: str
    symbol: str
    span: SourceSpan
    value_span: SourceSpan


@dataclass(frozen=True, slots=True)
class LayoutStmt:
    value: str
    span: SourceSpan
    value_span: SourceSpan


GraphStmt: TypeAlias = (
    TargetStmt
    | CategoryStmt
    | ModeStmt
    | RevisionStmt
    | OwnershipStmt
    | ExternalDecl
    | NodeDecl
    | FlagStmt
    | LayoutStmt
)


@dataclass(frozen=True, slots=True)
class GraphDecl:
    name: str
    statements: tuple[GraphStmt, ...]
    span: SourceSpan
    name_span: SourceSpan


@dataclass(frozen=True, slots=True)
class SyntaxSource:
    version: VersionDecl | None
    graph: GraphDecl
    span: SourceSpan

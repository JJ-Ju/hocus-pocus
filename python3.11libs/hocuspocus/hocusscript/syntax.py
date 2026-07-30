"""Source-faithful syntax trees for version-dispatched HocusScript source."""

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


@dataclass(frozen=True, slots=True)
class ResetValue:
    pass


@dataclass(frozen=True, slots=True)
class ExpressionValue:
    language: str
    body: str
    body_span: SourceSpan
    offset_map: CodeOffsetMap


@dataclass(frozen=True, slots=True)
class ChannelReferenceValue:
    node_symbol: str
    parm_name: str
    node_span: SourceSpan
    parm_span: SourceSpan


@dataclass(frozen=True, slots=True)
class RawPathValue:
    path_kind: str
    raw: str
    kind_span: SourceSpan
    raw_span: SourceSpan


@dataclass(frozen=True, slots=True)
class QuantityValue:
    magnitude: int | float
    unit: str
    magnitude_span: SourceSpan
    unit_span: SourceSpan


@dataclass(frozen=True, slots=True)
class RampPointExpr:
    position: int | float
    value: LiteralExpr | ArrayExpr
    span: SourceSpan
    position_span: SourceSpan


@dataclass(frozen=True, slots=True)
class RampValue:
    points: tuple[RampPointExpr, ...]
    basis: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MultiparmFieldExpr:
    name: str
    value: "ValueExpr"
    span: SourceSpan
    name_span: SourceSpan


@dataclass(frozen=True, slots=True)
class MultiparmInstanceExpr:
    instance_id: str
    fields: tuple[MultiparmFieldExpr, ...]
    span: SourceSpan
    instance_id_span: SourceSpan


@dataclass(frozen=True, slots=True)
class MultiparmValue:
    instances: tuple[MultiparmInstanceExpr, ...]


TaggedValuePayload: TypeAlias = (
    ResetValue
    | ExpressionValue
    | ChannelReferenceValue
    | RawPathValue
    | QuantityValue
    | RampValue
    | MultiparmValue
)


@dataclass(frozen=True, slots=True)
class TaggedValueExpr:
    tag: str
    payload: TaggedValuePayload
    span: SourceSpan


ValueExpr: TypeAlias = LiteralExpr | ArrayExpr | CodeExpr | TaggedValueExpr


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
    output_index: int | None
    explicit_output: bool
    port_keyword: str | None
    span: SourceSpan
    symbol_span: SourceSpan
    output_index_span: SourceSpan | None
    output_name: str | None = None
    output_name_span: SourceSpan | None = None


@dataclass(frozen=True, slots=True)
class ParamRefExpr:
    name: str
    span: SourceSpan
    name_span: SourceSpan


@dataclass(frozen=True, slots=True)
class SymbolRefExpr:
    symbol: str
    member: str
    output_index: int | None
    span: SourceSpan
    symbol_span: SourceSpan
    member_span: SourceSpan
    output_index_span: SourceSpan | None
    output_name: str | None = None
    output_name_span: SourceSpan | None = None


ModuleExpr: TypeAlias = LiteralExpr | ParamRefExpr | SymbolRefExpr


@dataclass(frozen=True, slots=True)
class InputStmt:
    index: int | None
    source: ReferenceExpr | ParamRefExpr | SymbolRefExpr
    span: SourceSpan
    index_span: SourceSpan | None
    name: str | None = None
    name_span: SourceSpan | None = None


@dataclass(frozen=True, slots=True)
class ParmStmt:
    name: str
    value: ValueExpr | ModuleExpr
    span: SourceSpan
    name_span: SourceSpan


from .runtime_syntax import AnimationDecl, SpareParameterDecl


NodeStmt: TypeAlias = InputStmt | ParmStmt | SpareParameterDecl | AnimationDecl


@dataclass(frozen=True, slots=True)
class NodeDecl:
    symbol: str
    explicit_id: str | None
    type_name: str
    type_quoted: bool
    statements: tuple[NodeStmt, ...]
    span: SourceSpan
    symbol_span: SourceSpan
    explicit_id_span: SourceSpan | None
    type_span: SourceSpan


@dataclass(frozen=True, slots=True)
class NamedArgument:
    name: str
    value: ModuleExpr
    span: SourceSpan
    name_span: SourceSpan


@dataclass(frozen=True, slots=True)
class UseDecl:
    symbol: str
    explicit_id: str
    module_name: str
    arguments: tuple[NamedArgument, ...]
    span: SourceSpan
    symbol_span: SourceSpan
    explicit_id_span: SourceSpan
    module_name_span: SourceSpan


@dataclass(frozen=True, slots=True)
class ExportStmt:
    name: str
    value: ModuleExpr
    span: SourceSpan
    name_span: SourceSpan


@dataclass(frozen=True, slots=True)
class ControlOutputDecl:
    name: str
    type_name: str
    span: SourceSpan
    name_span: SourceSpan
    type_span: SourceSpan


@dataclass(frozen=True, slots=True)
class CarryDecl:
    name: str
    type_name: str
    initial: ModuleExpr
    span: SourceSpan
    name_span: SourceSpan
    type_span: SourceSpan
    initial_span: SourceSpan


@dataclass(frozen=True, slots=True)
class YieldStmt:
    name: str
    value: ModuleExpr
    span: SourceSpan
    name_span: SourceSpan


@dataclass(frozen=True, slots=True)
class IfDecl:
    symbol: str
    explicit_id: str
    condition: ModuleExpr
    outputs: tuple[ControlOutputDecl, ...]
    then_body: tuple["ControlStmt", ...]
    else_body: tuple["ControlStmt", ...]
    span: SourceSpan
    symbol_span: SourceSpan
    explicit_id_span: SourceSpan
    condition_span: SourceSpan


@dataclass(frozen=True, slots=True)
class ForDecl:
    symbol: str
    explicit_id: str
    iterator: str
    count: ModuleExpr
    carries: tuple[CarryDecl, ...]
    body: tuple["ControlStmt", ...]
    span: SourceSpan
    symbol_span: SourceSpan
    explicit_id_span: SourceSpan
    iterator_span: SourceSpan
    count_span: SourceSpan


ControlStmt: TypeAlias = NodeDecl | UseDecl | IfDecl | ForDecl | YieldStmt


@dataclass(frozen=True, slots=True)
class ModuleParamDecl:
    name: str
    type_name: str
    default: ModuleExpr | None
    span: SourceSpan
    name_span: SourceSpan
    type_span: SourceSpan
    default_span: SourceSpan | None


@dataclass(frozen=True, slots=True)
class ModuleExportDecl:
    name: str
    type_name: str
    span: SourceSpan
    name_span: SourceSpan
    type_span: SourceSpan


ModuleStmt: TypeAlias = NodeDecl | UseDecl | IfDecl | ForDecl | ExportStmt


@dataclass(frozen=True, slots=True)
class ModuleDecl:
    name: str
    parameters: tuple[ModuleParamDecl, ...]
    exports: tuple[ModuleExportDecl, ...]
    statements: tuple[ModuleStmt, ...]
    span: SourceSpan
    name_span: SourceSpan


@dataclass(frozen=True, slots=True)
class ImportDecl:
    imported_name: str
    local_name: str
    specifier: str
    span: SourceSpan
    imported_name_span: SourceSpan
    local_name_span: SourceSpan
    specifier_span: SourceSpan


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
    | UseDecl
    | IfDecl
    | ForDecl
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
    graph: GraphDecl | None
    span: SourceSpan
    imports: tuple[ImportDecl, ...] = ()
    module: ModuleDecl | None = None

    @property
    def root(self) -> GraphDecl | ModuleDecl:
        root = self.graph if self.graph is not None else self.module
        if root is None:
            raise RuntimeError("syntax source has no root declaration")
        return root

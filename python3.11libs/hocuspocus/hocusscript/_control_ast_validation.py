"""Bounded hostile-AST admission for the isolated HocusScript 0.3 lane."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Callable

from .diagnostics import CodeOffsetMap, SourcePosition, SourceSpan
from .expander import ModuleExpansionError, _check_cancel
from .syntax import (
    ArrayExpr,
    CarryDecl,
    CategoryStmt,
    ChannelReferenceValue,
    CodeExpr,
    ControlOutputDecl,
    ExpressionValue,
    ExportStmt,
    ExternalDecl,
    FlagStmt,
    ForDecl,
    GraphDecl,
    IfDecl,
    ImportDecl,
    InputStmt,
    LayoutStmt,
    LiteralExpr,
    ModeStmt,
    ModuleDecl,
    ModuleExportDecl,
    ModuleParamDecl,
    MultiparmFieldExpr,
    MultiparmInstanceExpr,
    MultiparmValue,
    NamedArgument,
    NodeDecl,
    OwnershipStmt,
    ParamRefExpr,
    ParmStmt,
    ReferenceExpr,
    ResetValue,
    RevisionStmt,
    RampPointExpr,
    RampValue,
    RawPathValue,
    SymbolRefExpr,
    SyntaxSource,
    TaggedValueExpr,
    TargetStmt,
    QuantityValue,
    UseDecl,
    VersionDecl,
    YieldStmt,
)
from .editor_syntax import (
    EditorConnectionRef,
    EditorDestinationRef,
    EditorDestinationRefs,
    EditorEntityDecl,
    EditorItemRef,
    EditorItemRefs,
    EditorProperty,
)
from .runtime_syntax import AnimationDecl, RuntimeProperty, SpareParameterDecl


_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_MAX_AST_ITEMS = 1_600_000
_MAX_AST_DEPTH = 128
_MAX_SEQUENCE_ITEMS = 250_000
_MAX_TEXT_BYTES = 4 * 1024 * 1024
_MAX_AGGREGATE_TEXT_BYTES = 8 * 1024 * 1024
_CHECKPOINT_INTERVAL = 64

_VALUE_TYPES = (LiteralExpr, ArrayExpr, CodeExpr, TaggedValueExpr)
_MODULE_EXPR_TYPES = (LiteralExpr, ParamRefExpr, SymbolRefExpr)
_PARM_VALUE_TYPES = (*_VALUE_TYPES, ParamRefExpr, SymbolRefExpr)
_NODE_STMT_TYPES = (InputStmt, ParmStmt, SpareParameterDecl, AnimationDecl)
_CONTROL_STMT_TYPES = (NodeDecl, UseDecl, IfDecl, ForDecl, YieldStmt)
_MODULE_STMT_TYPES = (NodeDecl, UseDecl, IfDecl, ForDecl, ExportStmt)
_GRAPH_STMT_TYPES = (
    TargetStmt,
    CategoryStmt,
    ModeStmt,
    RevisionStmt,
    OwnershipStmt,
    ExternalDecl,
    NodeDecl,
    UseDecl,
    IfDecl,
    ForDecl,
    FlagStmt,
    LayoutStmt,
    EditorEntityDecl,
)


@dataclass(frozen=True, slots=True)
class _Rule:
    kind: str
    types: tuple[type[Any], ...] = ()
    span_field: str | None = None


def _identifier(span_field: str) -> _Rule:
    return _Rule("identifier", span_field=span_field)


def _child(*types: type[Any]) -> _Rule:
    return _Rule("child", types)


def _optional_child(*types: type[Any]) -> _Rule:
    return _Rule("optional_child", types)


def _items(*types: type[Any]) -> _Rule:
    return _Rule("items", types)


_STRING = _Rule("string")
_OPTIONAL_STRING = _Rule("optional_string")
_BOOL = _Rule("bool")
_INT = _Rule("int")
_OPTIONAL_INT = _Rule("optional_int")
_LITERAL = _Rule("literal")
_SPAN = _Rule("span")
_OPTIONAL_SPAN = _Rule("optional_span")
_OFFSET_MAP = _Rule("offset_map")


_SCHEMAS: dict[type[Any], tuple[tuple[str, _Rule], ...]] = {
    VersionDecl: (
        ("value", _STRING),
        ("quoted", _BOOL),
        ("value_span", _SPAN),
    ),
    LiteralExpr: (("value", _LITERAL),),
    ArrayExpr: (
        ("items", _items(*_VALUE_TYPES)),
        ("trailing_comma", _BOOL),
    ),
    CodeExpr: (
        ("language", _STRING),
        ("body", _STRING),
        ("body_span", _SPAN),
        ("offset_map", _OFFSET_MAP),
    ),
    TaggedValueExpr: (("tag", _STRING),),
    TargetStmt: (
        ("value", _STRING),
        ("had_equal", _BOOL),
        ("value_span", _SPAN),
    ),
    CategoryStmt: (
        ("value", _STRING),
        ("had_equal", _BOOL),
        ("value_span", _SPAN),
    ),
    ModeStmt: (
        ("value", _STRING),
        ("had_equal", _BOOL),
        ("value_span", _SPAN),
    ),
    RevisionStmt: (
        ("value", _INT),
        ("had_revision_keyword", _BOOL),
        ("had_equal", _BOOL),
        ("value_span", _SPAN),
    ),
    OwnershipStmt: (
        ("value", _STRING),
        ("had_equal", _BOOL),
        ("value_span", _SPAN),
    ),
    ExternalDecl: (
        ("symbol", _identifier("symbol_span")),
        ("path", _STRING),
        ("adopted", _BOOL),
        ("symbol_span", _SPAN),
        ("path_span", _SPAN),
    ),
    ReferenceExpr: (
        ("symbol", _identifier("symbol_span")),
        ("output_index", _OPTIONAL_INT),
        ("explicit_output", _BOOL),
        ("port_keyword", _OPTIONAL_STRING),
        ("symbol_span", _SPAN),
        ("output_index_span", _OPTIONAL_SPAN),
        ("output_name", _OPTIONAL_STRING),
        ("output_name_span", _OPTIONAL_SPAN),
    ),
    ParamRefExpr: (
        ("name", _identifier("name_span")),
        ("name_span", _SPAN),
    ),
    SymbolRefExpr: (
        ("symbol", _identifier("symbol_span")),
        ("member", _identifier("member_span")),
        ("output_index", _OPTIONAL_INT),
        ("symbol_span", _SPAN),
        ("member_span", _SPAN),
        ("output_index_span", _OPTIONAL_SPAN),
        ("output_name", _OPTIONAL_STRING),
        ("output_name_span", _OPTIONAL_SPAN),
    ),
    InputStmt: (
        ("index", _OPTIONAL_INT),
        ("source", _child(ReferenceExpr, ParamRefExpr, SymbolRefExpr)),
        ("index_span", _OPTIONAL_SPAN),
        ("name", _OPTIONAL_STRING),
        ("name_span", _OPTIONAL_SPAN),
    ),
    ParmStmt: (
        ("name", _identifier("name_span")),
        ("value", _child(*_PARM_VALUE_TYPES)),
        ("name_span", _SPAN),
    ),
    RuntimeProperty: (
        ("name", _identifier("name_span")),
        ("value", _child(*_VALUE_TYPES)),
        ("name_span", _SPAN),
    ),
    SpareParameterDecl: (
        ("name", _identifier("name_span")),
        ("explicit_id", _STRING),
        ("properties", _items(RuntimeProperty)),
        ("name_span", _SPAN),
        ("explicit_id_span", _SPAN),
    ),
    AnimationDecl: (
        ("parm_name", _identifier("parm_name_span")),
        ("explicit_id", _STRING),
        ("properties", _items(RuntimeProperty)),
        ("parm_name_span", _SPAN),
        ("explicit_id_span", _SPAN),
    ),
    NodeDecl: (
        ("symbol", _identifier("symbol_span")),
        ("explicit_id", _OPTIONAL_STRING),
        ("type_name", _STRING),
        ("type_quoted", _BOOL),
        ("statements", _items(*_NODE_STMT_TYPES)),
        ("symbol_span", _SPAN),
        ("explicit_id_span", _OPTIONAL_SPAN),
        ("type_span", _SPAN),
    ),
    NamedArgument: (
        ("name", _identifier("name_span")),
        ("value", _child(*_MODULE_EXPR_TYPES)),
        ("name_span", _SPAN),
    ),
    UseDecl: (
        ("symbol", _identifier("symbol_span")),
        ("explicit_id", _STRING),
        ("module_name", _identifier("module_name_span")),
        ("arguments", _items(NamedArgument)),
        ("symbol_span", _SPAN),
        ("explicit_id_span", _SPAN),
        ("module_name_span", _SPAN),
    ),
    ExportStmt: (
        ("name", _identifier("name_span")),
        ("value", _child(*_MODULE_EXPR_TYPES)),
        ("name_span", _SPAN),
    ),
    ControlOutputDecl: (
        ("name", _identifier("name_span")),
        ("type_name", _STRING),
        ("name_span", _SPAN),
        ("type_span", _SPAN),
    ),
    CarryDecl: (
        ("name", _identifier("name_span")),
        ("type_name", _STRING),
        ("initial", _child(*_MODULE_EXPR_TYPES)),
        ("name_span", _SPAN),
        ("type_span", _SPAN),
        ("initial_span", _SPAN),
    ),
    YieldStmt: (
        ("name", _identifier("name_span")),
        ("value", _child(*_MODULE_EXPR_TYPES)),
        ("name_span", _SPAN),
    ),
    IfDecl: (
        ("symbol", _identifier("symbol_span")),
        ("explicit_id", _STRING),
        ("condition", _child(*_MODULE_EXPR_TYPES)),
        ("outputs", _items(ControlOutputDecl)),
        ("then_body", _items(*_CONTROL_STMT_TYPES)),
        ("else_body", _items(*_CONTROL_STMT_TYPES)),
        ("symbol_span", _SPAN),
        ("explicit_id_span", _SPAN),
        ("condition_span", _SPAN),
    ),
    ForDecl: (
        ("symbol", _identifier("symbol_span")),
        ("explicit_id", _STRING),
        ("iterator", _identifier("iterator_span")),
        ("count", _child(*_MODULE_EXPR_TYPES)),
        ("carries", _items(CarryDecl)),
        ("body", _items(*_CONTROL_STMT_TYPES)),
        ("symbol_span", _SPAN),
        ("explicit_id_span", _SPAN),
        ("iterator_span", _SPAN),
        ("count_span", _SPAN),
    ),
    ModuleParamDecl: (
        ("name", _identifier("name_span")),
        ("type_name", _STRING),
        ("default", _optional_child(*_MODULE_EXPR_TYPES)),
        ("name_span", _SPAN),
        ("type_span", _SPAN),
        ("default_span", _OPTIONAL_SPAN),
    ),
    ModuleExportDecl: (
        ("name", _identifier("name_span")),
        ("type_name", _STRING),
        ("name_span", _SPAN),
        ("type_span", _SPAN),
    ),
    ModuleDecl: (
        ("name", _identifier("name_span")),
        ("parameters", _items(ModuleParamDecl)),
        ("exports", _items(ModuleExportDecl)),
        ("statements", _items(*_MODULE_STMT_TYPES)),
        ("name_span", _SPAN),
    ),
    ImportDecl: (
        ("imported_name", _identifier("imported_name_span")),
        ("local_name", _identifier("local_name_span")),
        ("specifier", _STRING),
        ("imported_name_span", _SPAN),
        ("local_name_span", _SPAN),
        ("specifier_span", _SPAN),
    ),
    FlagStmt: (
        ("name", _identifier("span")),
        ("symbol", _identifier("value_span")),
        ("value_span", _SPAN),
    ),
    LayoutStmt: (
        ("value", _STRING),
        ("value_span", _SPAN),
    ),
    EditorItemRef: (
        ("item_kind", _STRING),
        ("identity", _STRING),
        ("identity_span", _SPAN),
    ),
    EditorItemRefs: (("items", _items(EditorItemRef)),),
    EditorConnectionRef: (
        ("item", _child(EditorItemRef)),
        ("output_index", _INT),
        ("output_index_span", _SPAN),
    ),
    EditorDestinationRef: (
        ("node", _child(EditorItemRef)),
        ("input_index", _INT),
        ("input_index_span", _SPAN),
    ),
    EditorDestinationRefs: (("items", _items(EditorDestinationRef)),),
    EditorProperty: (
        ("name", _identifier("name_span")),
        (
            "value",
            _child(
                LiteralExpr, ArrayExpr, EditorItemRef, EditorItemRefs,
                EditorConnectionRef,
                EditorDestinationRefs,
            ),
        ),
        ("name_span", _SPAN),
    ),
    EditorEntityDecl: (
        ("entity_kind", _STRING),
        ("explicit_id", _STRING),
        ("properties", _items(EditorProperty)),
        ("explicit_id_span", _SPAN),
    ),
    GraphDecl: (
        ("name", _identifier("name_span")),
        ("statements", _items(*_GRAPH_STMT_TYPES)),
        ("name_span", _SPAN),
    ),
    SyntaxSource: (
        ("version", _optional_child(VersionDecl)),
        ("graph", _optional_child(GraphDecl)),
        ("imports", _items(ImportDecl)),
        ("module", _optional_child(ModuleDecl)),
    ),
}


@dataclass(slots=True)
class _ControlAstAdmissionBudget:
    claimed: int = 0
    text_bytes: int = 0
    source_name_ids: set[int] = field(default_factory=set)


@dataclass(slots=True)
class _Admission:
    root_span: SourceSpan
    cancellation: Callable[[], bool] | None
    stack: list[tuple[Any, SourceSpan, int]]
    budget: _ControlAstAdmissionBudget
    language_version: str | None

    def claim(self) -> None:
        self.budget.claimed += 1
        if self.budget.claimed > _MAX_AST_ITEMS:
            self.malformed("Control syntax tree exceeds its admission bound.")
        if self.budget.claimed % _CHECKPOINT_INTERVAL == 0:
            _check_cancel(self.cancellation, self.root_span)

    def charge_text(
        self,
        value: str,
        span: SourceSpan,
        *,
        source_name: bool = False,
    ) -> None:
        if source_name:
            identity = id(value)
            if identity in self.budget.source_name_ids:
                return
            self.budget.source_name_ids.add(identity)
        _check_cancel(self.cancellation, span)
        size = len(value.encode("utf-8"))
        self.budget.text_bytes += size
        if self.budget.text_bytes > _MAX_AGGREGATE_TEXT_BYTES:
            self.malformed("Control syntax text exceeds its aggregate admission bound.", span)

    def malformed(self, message: str, span: SourceSpan | None = None) -> None:
        raise ModuleExpansionError("HOCUS479", message, span or self.root_span)

    def invalid_identifier(self, span: SourceSpan) -> None:
        raise ModuleExpansionError(
            "HOCUS473",
            "Authored symbol must be a bounded HocusScript identifier.",
            span,
        )

    def queue(
        self,
        value: Any,
        expected: tuple[type[Any], ...],
        owner_span: SourceSpan,
        depth: int,
    ) -> None:
        if type(value) not in expected:
            self.malformed("Control syntax tree contains malformed field values.", owner_span)
        if depth > _MAX_AST_DEPTH:
            self.malformed("Control syntax tree exceeds its nesting bound.", owner_span)
        self.stack.append((value, owner_span, depth))


def validate_control_syntax_ast(
    source: Any,
    *,
    cancellation: Callable[[], bool] | None = None,
    budget: _ControlAstAdmissionBudget | None = None,
) -> None:
    """Admit one exact, bounded syntax tree without recursive traversal."""

    root_span = safe_control_ast_span(source)
    if type(source) is not SyntaxSource:
        raise ModuleExpansionError(
            "HOCUS479",
            "Control syntax tree root must be an exact SyntaxSource.",
            root_span,
        )
    shared_budget = budget if budget is not None else _ControlAstAdmissionBudget()
    version = source.version
    language_version = (
        version.value
        if type(version) is VersionDecl and type(version.value) is str
        else None
    )
    admission = _Admission(
        root_span,
        cancellation,
        [(source, root_span, 0)],
        shared_budget,
        language_version,
    )
    while admission.stack:
        node, parent_span, depth = admission.stack.pop()
        admission.claim()
        _validate_syntax_node(node, parent_span, depth, admission)


def safe_control_ast_span(value: Any) -> SourceSpan:
    """Return a trustworthy root span or a deterministic diagnostic fallback."""

    span = value.span if type(value) is SyntaxSource else None
    if _span_is_valid(span):
        return span
    position = SourcePosition(0, 1, 1)
    return SourceSpan("<control-ast>", position, position)


def _validate_syntax_node(
    node: Any,
    parent_span: SourceSpan,
    depth: int,
    admission: _Admission,
) -> None:
    schema = _SCHEMAS.get(type(node))
    if schema is None:
        admission.malformed("Control syntax tree contains an unsupported syntax node.")
    owner_span = _require_span(node.span, parent_span, admission)
    if (
        type(node) in {ArrayExpr, CodeExpr, TaggedValueExpr}
        and admission.language_version != "0.4"
    ):
        admission.malformed(
            "Rich parameter values require HocusScript 0.4.",
            owner_span,
        )
    _validate_cross_fields(node, owner_span, admission)
    for field_name, rule in schema:
        value = getattr(node, field_name)
        _validate_field(value, field_name, rule, node, owner_span, depth, admission)


def _validate_field(
    value: Any,
    field_name: str,
    rule: _Rule,
    node: Any,
    owner_span: SourceSpan,
    depth: int,
    admission: _Admission,
) -> None:
    if rule.kind in {"string", "optional_string", "bool", "int", "optional_int", "literal"}:
        _validate_scalar(value, rule.kind, owner_span, admission)
        return
    if rule.kind == "identifier":
        _validate_identifier(value, rule.span_field, node, owner_span, admission)
        return
    _validate_structured(value, field_name, rule, owner_span, depth, admission)


def _validate_scalar(
    value: Any,
    kind: str,
    owner_span: SourceSpan,
    admission: _Admission,
) -> None:
    if kind == "string":
        valid = _string_is_valid(value)
    elif kind == "optional_string":
        valid = value is None or _string_is_valid(value)
    elif kind == "bool":
        valid = type(value) is bool
    elif kind == "int":
        valid = type(value) is int
    elif kind == "optional_int":
        valid = value is None or type(value) is int
    else:
        valid = _literal_is_valid(value)
    if not valid:
        admission.malformed("Control syntax tree contains malformed field values.", owner_span)
    if type(value) is str:
        admission.charge_text(value, owner_span)


def _validate_identifier(
    value: Any,
    span_field: str | None,
    node: Any,
    owner_span: SourceSpan,
    admission: _Admission,
) -> None:
    if _string_is_valid(value) and _IDENTIFIER.fullmatch(value) is not None:
        admission.charge_text(value, owner_span)
        return
    candidate = getattr(node, span_field) if span_field is not None else None
    span = candidate if _span_inside(candidate, owner_span) else owner_span
    admission.invalid_identifier(span)


def _validate_structured(
    value: Any,
    field_name: str,
    rule: _Rule,
    owner_span: SourceSpan,
    depth: int,
    admission: _Admission,
) -> None:
    if rule.kind == "span":
        _require_span(value, owner_span, admission)
        return
    if rule.kind == "optional_span":
        if value is not None:
            _require_span(value, owner_span, admission)
        return
    if rule.kind == "offset_map":
        if type(value) is not CodeOffsetMap:
            admission.malformed("Embedded code offset map is malformed.", owner_span)
        return
    if rule.kind in {"child", "optional_child"}:
        if value is None and rule.kind == "optional_child":
            return
        admission.queue(value, rule.types, owner_span, depth + 1)
        return
    if rule.kind != "items" or type(value) is not tuple:
        admission.malformed(f"Control AST field {field_name} must be an exact tuple.", owner_span)
    _queue_items(value, rule.types, owner_span, depth, admission)


def _queue_items(
    values: tuple[Any, ...],
    expected: tuple[type[Any], ...],
    owner_span: SourceSpan,
    depth: int,
    admission: _Admission,
) -> None:
    if len(values) > _MAX_SEQUENCE_ITEMS:
        admission.malformed("Control syntax tuple exceeds its admission bound.", owner_span)
    for item in reversed(values):
        admission.queue(item, expected, owner_span, depth + 1)


def _validate_cross_fields(
    node: Any,
    owner_span: SourceSpan,
    admission: _Admission,
) -> None:
    node_type = type(node)
    if node_type is CodeExpr:
        _validate_code_expr(node, owner_span, admission)
    elif node_type is TaggedValueExpr:
        _validate_tagged_value_expr(node, owner_span, admission)
    elif node_type is ReferenceExpr:
        _validate_reference_expr(node, owner_span, admission)
    elif node_type is SymbolRefExpr:
        _require_optional_pair(node.output_index, node.output_index_span, owner_span, admission)
        _require_optional_pair(node.output_name, node.output_name_span, owner_span, admission)
        if node.output_index is not None and node.output_name is not None:
            admission.malformed("Output selector is ambiguous.", owner_span)
    elif node_type is InputStmt:
        _require_optional_pair(node.index, node.index_span, owner_span, admission)
        _require_optional_pair(node.name, node.name_span, owner_span, admission)
        if (node.index is None) == (node.name is None):
            admission.malformed("Input selector must use exactly one index or name.", owner_span)
    elif node_type is NodeDecl:
        _require_optional_pair(node.explicit_id, node.explicit_id_span, owner_span, admission)
    elif node_type is ModuleParamDecl:
        _require_optional_pair(node.default, node.default_span, owner_span, admission)


def _validate_tagged_value_expr(
    value: TaggedValueExpr,
    owner_span: SourceSpan,
    admission: _Admission,
) -> None:
    expected = {
        "reset": ResetValue,
        "expression": ExpressionValue,
        "channel": ChannelReferenceValue,
        "raw_path": RawPathValue,
        "quantity": QuantityValue,
        "ramp": RampValue,
        "multiparm": MultiparmValue,
    }
    payload_type = expected.get(value.tag)
    if payload_type is None or type(value.payload) is not payload_type:
        admission.malformed("Tagged value discriminant/payload is malformed.", owner_span)
    if type(value.payload) is ResetValue:
        return
    if type(value.payload) is ExpressionValue:
        _validate_expression_payload(value.payload, owner_span, admission)
    elif type(value.payload) is ChannelReferenceValue:
        _validate_channel_payload(value.payload, owner_span, admission)
    elif type(value.payload) is RawPathValue:
        _validate_raw_path_payload(value.payload, owner_span, admission)
    elif type(value.payload) is QuantityValue:
        _validate_quantity_payload(value.payload, owner_span, admission)
    elif type(value.payload) is RampValue:
        _validate_ramp_payload(value.payload, owner_span, admission)
    else:
        _validate_multiparm_payload(value.payload, owner_span, admission)


def _validate_expression_payload(
    value: ExpressionValue,
    owner_span: SourceSpan,
    admission: _Admission,
) -> None:
    body_span = value.body_span
    offset_map = value.offset_map
    if (
        value.language not in {"hscript", "python"}
        or not _string_is_valid(value.body)
        or len(value.body.encode("utf-8")) > 1024 * 1024
        or not _span_inside(body_span, owner_span)
        or type(offset_map) is not CodeOffsetMap
        or type(offset_map.body_length) is not int
        or type(offset_map.checkpoints) is not tuple
        or not offset_map.checkpoints
    ):
        admission.malformed("Expression value body/span/offset shape is invalid.", owner_span)
    admission.charge_text(value.language, owner_span)
    admission.charge_text(value.body, body_span)
    proxy = CodeExpr(
        value.language,
        value.body,
        owner_span,
        body_span,
        offset_map,
    )
    _validate_code_checkpoints(proxy, body_span, offset_map, admission)


def _validate_channel_payload(
    value: ChannelReferenceValue,
    owner_span: SourceSpan,
    admission: _Admission,
) -> None:
    for authored, span in (
        (value.node_symbol, value.node_span),
        (value.parm_name, value.parm_span),
    ):
        if (
            not _string_is_valid(authored)
            or _IDENTIFIER.fullmatch(authored) is None
            or not _span_inside(span, owner_span)
        ):
            admission.invalid_identifier(
                span if _span_inside(span, owner_span) else owner_span
            )
        admission.charge_text(authored, span)


def _validate_raw_path_payload(
    value: RawPathValue,
    owner_span: SourceSpan,
    admission: _Admission,
) -> None:
    if (
        value.path_kind not in {"node", "parm", "file", "usd_prim", "asset"}
        or not _string_is_valid(value.raw)
        or len(value.raw.encode("utf-8")) > 8192
        or not _span_inside(value.kind_span, owner_span)
        or not _span_inside(value.raw_span, owner_span)
    ):
        admission.malformed("Raw-path value is malformed.", owner_span)
    admission.charge_text(value.path_kind, value.kind_span)
    admission.charge_text(value.raw, value.raw_span)


def _validate_quantity_payload(
    value: QuantityValue,
    owner_span: SourceSpan,
    admission: _Admission,
) -> None:
    if (
        isinstance(value.magnitude, bool)
        or not isinstance(value.magnitude, (int, float))
        or not math.isfinite(value.magnitude)
        or not _string_is_valid(value.unit)
        or not _span_inside(value.magnitude_span, owner_span)
        or not _span_inside(value.unit_span, owner_span)
    ):
        admission.malformed("Quantity value is malformed.", owner_span)
    admission.charge_text(value.unit, value.unit_span)


def _validate_ramp_payload(
    value: RampValue,
    owner_span: SourceSpan,
    admission: _Admission,
) -> None:
    if (
        type(value.points) is not tuple
        or type(value.basis) is not tuple
        or not 2 <= len(value.points) <= 4096
        or len(value.basis) != len(value.points)
    ):
        admission.malformed("Ramp value has an invalid bounded shape.", owner_span)
    for basis in value.basis:
        if basis not in {
            "constant", "linear", "catmullrom", "monotonecubic", "bezier",
            "bspline", "hermite",
        }:
            admission.malformed("Ramp basis token is unsupported.", owner_span)
        admission.charge_text(basis, owner_span)
    previous = -math.inf
    for point in value.points:
        admission.claim()
        if (
            type(point) is not RampPointExpr
            or isinstance(point.position, bool)
            or not isinstance(point.position, (int, float))
            or not math.isfinite(point.position)
            or point.position < 0
            or point.position > 1
            or point.position < previous
            or not _span_inside(point.span, owner_span)
            or not _span_inside(point.position_span, point.span)
        ):
            admission.malformed("Ramp point is malformed.", owner_span)
        previous = point.position
        admission.queue(
            point.value, (LiteralExpr, ArrayExpr), point.span, 1
        )


def _validate_multiparm_payload(
    value: MultiparmValue,
    owner_span: SourceSpan,
    admission: _Admission,
) -> None:
    if type(value.instances) is not tuple or len(value.instances) > 4096:
        admission.malformed("Multiparm value exceeds its instance bound.", owner_span)
    identities: set[str] = set()
    for instance in value.instances:
        admission.claim()
        if (
            type(instance) is not MultiparmInstanceExpr
            or not _string_is_valid(instance.instance_id)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", instance.instance_id)
            or instance.instance_id in identities
            or type(instance.fields) is not tuple
            or len(instance.fields) > 256
            or not _span_inside(instance.span, owner_span)
            or not _span_inside(instance.instance_id_span, instance.span)
        ):
            admission.malformed("Multiparm instance is malformed.", owner_span)
        identities.add(instance.instance_id)
        field_names: set[str] = set()
        for item_field in instance.fields:
            admission.claim()
            if (
                type(item_field) is not MultiparmFieldExpr
                or not _string_is_valid(item_field.name)
                or _IDENTIFIER.fullmatch(item_field.name) is None
                or item_field.name in field_names
                or not _span_inside(item_field.span, instance.span)
                or not _span_inside(item_field.name_span, item_field.span)
            ):
                admission.malformed("Multiparm field is malformed.", instance.span)
            field_names.add(item_field.name)
            admission.charge_text(item_field.name, item_field.name_span)
            admission.queue(item_field.value, _VALUE_TYPES, item_field.span, 1)


def _validate_code_expr(
    value: CodeExpr,
    owner_span: SourceSpan,
    admission: _Admission,
) -> None:
    body_span = value.body_span
    offset_map = value.offset_map
    if (
        not _string_is_valid(value.body)
        or not _span_inside(body_span, owner_span)
        or type(offset_map) is not CodeOffsetMap
        or type(offset_map.body_length) is not int
        or offset_map.body_length < 0
        or type(offset_map.checkpoints) is not tuple
        or not offset_map.checkpoints
        or len(offset_map.checkpoints) > _MAX_SEQUENCE_ITEMS
    ):
        admission.malformed("Embedded code body/span/offset shape is invalid.", owner_span)
    _validate_code_checkpoints(value, body_span, offset_map, admission)


def _validate_code_checkpoints(
    value: CodeExpr,
    body_span: SourceSpan,
    offset_map: CodeOffsetMap,
    admission: _Admission,
) -> None:
    previous_body = -1
    previous_source = -1
    for checkpoint in offset_map.checkpoints:
        admission.claim()
        if type(checkpoint) is not tuple or len(checkpoint) != 2:
            admission.malformed("Embedded code offset checkpoint is malformed.", body_span)
        body_offset, source_offset = checkpoint
        if (
            type(body_offset) is not int
            or type(source_offset) is not int
            or body_offset <= previous_body
            or source_offset < previous_source
        ):
            admission.malformed("Embedded code offset checkpoint is malformed.", body_span)
        previous_body, previous_source = body_offset, source_offset
    expected_first = (0, body_span.start.offset)
    expected_last = (offset_map.body_length, body_span.end.offset)
    if (
        offset_map.body_length != len(value.body)
        or offset_map.checkpoints[0] != expected_first
        or offset_map.checkpoints[-1] != expected_last
    ):
        admission.malformed("Embedded code body/span/offset shape is invalid.", body_span)


def _validate_reference_expr(
    value: ReferenceExpr,
    owner_span: SourceSpan,
    admission: _Admission,
) -> None:
    _require_optional_pair(value.output_index, value.output_index_span, owner_span, admission)
    _require_optional_pair(value.output_name, value.output_name_span, owner_span, admission)
    one_selector = (value.output_index is None) != (value.output_name is None)
    valid_explicit = (
        value.explicit_output
        and value.port_keyword in {"output", "out"}
        and one_selector
    )
    valid_implicit = (
        not value.explicit_output
        and value.port_keyword is None
        and value.output_index == 0
        and value.output_index_span == value.symbol_span
        and value.output_name is None
        and value.output_name_span is None
    )
    if not valid_explicit and not valid_implicit:
        admission.malformed("Node output reference shape is malformed.", owner_span)


def _require_optional_pair(
    value: Any,
    span: Any,
    owner_span: SourceSpan,
    admission: _Admission,
) -> None:
    if (value is None) != (span is None):
        admission.malformed("Optional control syntax value/span pair is malformed.", owner_span)


def _require_span(
    value: Any,
    envelope: SourceSpan,
    admission: _Admission,
) -> SourceSpan:
    if not _span_inside(value, envelope):
        admission.malformed("Control syntax tree contains a malformed source span.")
    admission.charge_text(value.source_name, value, source_name=True)
    return value


def _span_inside(value: Any, envelope: SourceSpan) -> bool:
    return (
        _span_shape_is_valid(value)
        and value.source_name == envelope.source_name
        and value.start.offset >= envelope.start.offset
        and value.end.offset <= envelope.end.offset
    )


def _span_is_valid(value: Any) -> bool:
    return _span_shape_is_valid(value) and _string_is_valid(value.source_name)


def _span_shape_is_valid(value: Any) -> bool:
    if type(value) is not SourceSpan or type(value.source_name) is not str:
        return False
    if not _position_is_valid(value.start) or not _position_is_valid(value.end):
        return False
    if value.end.offset < value.start.offset or value.end.line < value.start.line:
        return False
    return value.end.line != value.start.line or value.end.column >= value.start.column


def _position_is_valid(value: Any) -> bool:
    return (
        type(value) is SourcePosition
        and type(value.offset) is int
        and type(value.line) is int
        and type(value.column) is int
        and value.offset >= 0
        and value.line >= 1
        and value.column >= 1
    )


def _string_is_valid(value: Any) -> bool:
    if type(value) is not str:
        return False
    try:
        return len(value.encode("utf-8")) <= _MAX_TEXT_BYTES
    except UnicodeEncodeError:
        return False


def _literal_is_valid(value: Any) -> bool:
    if value is None or type(value) in {bool, int}:
        return True
    if type(value) is float:
        return math.isfinite(value)
    return _string_is_valid(value)

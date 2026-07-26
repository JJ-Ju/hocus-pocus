"""Pure lowering from source-faithful syntax into normalized GraphSpec."""

from __future__ import annotations

from typing import Any

from .model import (
    ArrayValue,
    CodeValue,
    ExternalNodeSpec,
    GraphSpec,
    InputSpec,
    LiteralValue,
    NodeReference,
    NodeSpec,
    ParmSpec,
)
from .syntax import (
    ArrayExpr,
    CategoryStmt,
    CodeExpr,
    ExternalDecl,
    FlagStmt,
    InputStmt,
    LayoutStmt,
    LiteralExpr,
    ModeStmt,
    NodeDecl,
    OwnershipStmt,
    ParmStmt,
    RevisionStmt,
    SyntaxSource,
    TargetStmt,
    ValueExpr,
)


def lower_syntax(source: SyntaxSource) -> GraphSpec:
    """Normalize syntax while retaining internal source-field provenance."""

    language_version = source.version.value if source.version is not None else "0.1"
    values: dict[str, Any] = {
        "target": None, "category": None, "mode": "merge",
        "expected_revision": None, "ownership": None,
        "display": None, "render": None, "output": None, "layout": None,
    }
    external_nodes: list[ExternalNodeSpec] = []
    nodes: list[NodeSpec] = []
    field_spans = {"name": source.graph.name_span}
    if source.version is not None:
        field_spans["languageVersion"] = source.version.value_span

    for statement in source.graph.statements:
        _lower_graph_statement(statement, values, field_spans, external_nodes, nodes)

    return GraphSpec(
        language_version=language_version,
        name=source.graph.name,
        target=values["target"],
        category=values["category"],
        mode=values["mode"],
        expected_revision=values["expected_revision"],
        ownership=values["ownership"],
        external_nodes=external_nodes,
        nodes=nodes,
        display=values["display"],
        render=values["render"],
        output=values["output"],
        layout=values["layout"],
        span=source.graph.span,
        field_spans=field_spans,
    )


def _lower_graph_statement(
    statement: Any,
    values: dict[str, Any],
    field_spans: dict[str, Any],
    external_nodes: list[ExternalNodeSpec],
    nodes: list[NodeSpec],
) -> None:
    if isinstance(statement, TargetStmt):
        _set_graph_value(values, field_spans, "target", statement.value, statement.value_span)
    elif isinstance(statement, CategoryStmt):
        _set_graph_value(values, field_spans, "category", statement.value, statement.value_span)
    elif isinstance(statement, ModeStmt):
        _set_graph_value(values, field_spans, "mode", statement.value, statement.value_span)
    elif isinstance(statement, RevisionStmt):
        _set_graph_value(values, field_spans, "expected_revision", statement.value, statement.value_span, "expectedRevision")
    elif isinstance(statement, OwnershipStmt):
        _set_graph_value(values, field_spans, "ownership", statement.value, statement.value_span)
    elif isinstance(statement, ExternalDecl):
        external_nodes.append(_lower_external(statement))
    elif isinstance(statement, NodeDecl):
        nodes.append(_lower_node(statement))
    elif isinstance(statement, FlagStmt):
        _set_graph_value(values, field_spans, statement.name, statement.symbol, statement.value_span)
    elif isinstance(statement, LayoutStmt):
        _set_graph_value(values, field_spans, "layout", statement.value, statement.value_span)


def _set_graph_value(
    values: dict[str, Any],
    field_spans: dict[str, Any],
    key: str,
    value: Any,
    span: Any,
    field_name: str | None = None,
) -> None:
    values[key] = value
    field_spans[field_name or key] = span


def _lower_external(statement: ExternalDecl) -> ExternalNodeSpec:
    return ExternalNodeSpec(
        statement.symbol,
        statement.path,
        statement.adopted,
        statement.span,
        {"symbol": statement.symbol_span, "path": statement.path_span},
    )


def _lower_node(node: NodeDecl) -> NodeSpec:
    inputs: list[InputSpec] = []
    parms: list[ParmSpec] = []
    for statement in node.statements:
        if isinstance(statement, InputStmt):
            inputs.append(
                InputSpec(
                    statement.index,
                    NodeReference(
                        statement.source.symbol,
                        statement.source.output_index,
                        statement.source.span,
                        {
                            "symbol": statement.source.symbol_span,
                            "outputIndex": statement.source.output_index_span,
                        },
                    ),
                    statement.span,
                    {"index": statement.index_span},
                )
            )
        elif isinstance(statement, ParmStmt):
            parms.append(
                ParmSpec(statement.name, _lower_value(statement.value), statement.span, {"name": statement.name_span})
            )
    field_spans = {"symbol": node.symbol_span, "typeName": node.type_span}
    if node.explicit_id_span is not None:
        field_spans["explicitId"] = node.explicit_id_span
    return NodeSpec(
        node.symbol,
        node.type_name,
        inputs,
        parms,
        node.span,
        field_spans,
        node.explicit_id,
    )


def _lower_value(value: ValueExpr):
    if isinstance(value, LiteralExpr):
        return LiteralValue(value.value, value.span)
    if isinstance(value, ArrayExpr):
        return ArrayValue([_lower_value(item) for item in value.items], value.span)
    if isinstance(value, CodeExpr):
        return CodeValue(value.language, value.body, value.span, value.body_span, value.offset_map)
    raise TypeError(f"Unsupported syntax value: {type(value).__name__}")

"""Pure lowering from source-faithful syntax into normalized GraphSpec."""

from __future__ import annotations

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
    target: str | None = None
    category: str | None = None
    mode = "merge"
    expected_revision: int | None = None
    ownership: str | None = None
    external_nodes: list[ExternalNodeSpec] = []
    nodes: list[NodeSpec] = []
    display: str | None = None
    render: str | None = None
    output: str | None = None
    layout: str | None = None
    field_spans = {"name": source.graph.name_span}
    if source.version is not None:
        field_spans["languageVersion"] = source.version.value_span

    for statement in source.graph.statements:
        if isinstance(statement, TargetStmt):
            target = statement.value
            field_spans["target"] = statement.value_span
        elif isinstance(statement, CategoryStmt):
            category = statement.value
            field_spans["category"] = statement.value_span
        elif isinstance(statement, ModeStmt):
            mode = statement.value
            field_spans["mode"] = statement.value_span
        elif isinstance(statement, RevisionStmt):
            expected_revision = statement.value
            field_spans["expectedRevision"] = statement.value_span
        elif isinstance(statement, OwnershipStmt):
            ownership = statement.value
            field_spans["ownership"] = statement.value_span
        elif isinstance(statement, ExternalDecl):
            external_nodes.append(
                ExternalNodeSpec(statement.symbol, statement.path, statement.adopted, statement.span)
            )
        elif isinstance(statement, NodeDecl):
            nodes.append(_lower_node(statement))
        elif isinstance(statement, FlagStmt):
            field_spans[statement.name] = statement.value_span
            if statement.name == "display":
                display = statement.symbol
            elif statement.name == "render":
                render = statement.symbol
            else:
                output = statement.symbol
        elif isinstance(statement, LayoutStmt):
            layout = statement.value
            field_spans["layout"] = statement.value_span

    return GraphSpec(
        language_version=language_version,
        name=source.graph.name,
        target=target,
        category=category,
        mode=mode,
        expected_revision=expected_revision,
        ownership=ownership,
        external_nodes=external_nodes,
        nodes=nodes,
        display=display,
        render=render,
        output=output,
        layout=layout,
        span=source.graph.span,
        field_spans=field_spans,
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
                    ),
                    statement.span,
                )
            )
        elif isinstance(statement, ParmStmt):
            parms.append(ParmSpec(statement.name, _lower_value(statement.value), statement.span))
    return NodeSpec(node.symbol, node.type_name, inputs, parms, node.span)


def _lower_value(value: ValueExpr):
    if isinstance(value, LiteralExpr):
        return LiteralValue(value.value, value.span)
    if isinstance(value, ArrayExpr):
        return ArrayValue([_lower_value(item) for item in value.items], value.span)
    if isinstance(value, CodeExpr):
        return CodeValue(value.language, value.body, value.span, value.body_span, value.offset_map)
    raise TypeError(f"Unsupported syntax value: {type(value).__name__}")

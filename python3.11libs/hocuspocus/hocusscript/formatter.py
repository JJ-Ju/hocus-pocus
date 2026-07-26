"""Canonical formatter for parsed HocusScript 0.1 graphs."""

from __future__ import annotations

import json
from typing import Any

from .model import ArrayValue, CodeValue, GraphSpec, LiteralValue, NodeReference
from .syntax import (
    CategoryStmt,
    ExportStmt,
    ExternalDecl,
    FlagStmt,
    ForDecl,
    GraphDecl,
    InputStmt,
    LayoutStmt,
    LiteralExpr,
    ModeStmt,
    ModuleDecl,
    NodeDecl,
    OwnershipStmt,
    IfDecl,
    ParamRefExpr,
    ParmStmt,
    RevisionStmt,
    SymbolRefExpr,
    SyntaxSource,
    TargetStmt,
    UseDecl,
    YieldStmt,
)


def _format_value(value: Any) -> str:
    if isinstance(value, LiteralValue):
        return _format_value(value.value)
    if isinstance(value, ArrayValue):
        return "[" + ", ".join(_format_value(item) for item in value.items) + "]"
    if isinstance(value, CodeValue):
        body = value.body.replace("\r\n", "\n").replace("\r", "\n").replace("`", "\\`")
        return f"{value.language}`{body}`"
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def _format_reference(reference: NodeReference) -> str:
    return f"{reference.symbol}.output[{reference.output_index}]"


def format_graph(graph: GraphSpec) -> str:
    lines = [f"hocus {graph.language_version};", "", f"graph {graph.name} {{"]
    _format_graph_header(graph, lines)
    _format_graph_nodes(graph, lines)
    _format_graph_flags(graph, lines)
    lines.append("}")
    return "\n".join(lines) + "\n"


def _format_graph_header(graph: GraphSpec, lines: list[str]) -> None:
    if graph.target is not None:
        lines.append(f"  target {_format_value(graph.target)};")
    if graph.category is not None:
        lines.append(f"  category {graph.category};")
    lines.append(f"  mode {graph.mode};")
    if graph.expected_revision is not None:
        lines.append(f"  expect revision {graph.expected_revision};")
    if graph.ownership is not None:
        lines.append(f"  ownership {_format_value(graph.ownership)};")

    if graph.external_nodes:
        lines.append("")
        for external in graph.external_nodes:
            keyword = "adopt" if external.adopted else "existing"
            lines.append(f"  {keyword} {external.symbol} = {_format_value(external.path)};")


def _format_graph_nodes(graph: GraphSpec, lines: list[str]) -> None:
    for node in graph.nodes:
        lines.append("")
        identity = f" @id({_format_value(node.explicit_id)})" if node.explicit_id is not None else ""
        lines.append(f"  node {node.symbol}{identity}: {_format_value(node.type_name)} {{")
        for input_spec in node.inputs:
            lines.append(f"    input[{input_spec.index}] = {_format_reference(input_spec.source)};")
        for parm in node.parms:
            lines.append(f"    {parm.name} = {_format_value(parm.value)};")
        lines.append("  }")


def _format_graph_flags(graph: GraphSpec, lines: list[str]) -> None:
    if any(value is not None for value in (graph.display, graph.render, graph.output, graph.layout)):
        lines.append("")
    if graph.display is not None:
        lines.append(f"  display = {graph.display};")
    if graph.render is not None:
        lines.append(f"  render = {graph.render};")
    if graph.output is not None:
        lines.append(f"  output = {graph.output};")
    if graph.layout is not None:
        lines.append(f"  layout = {graph.layout};")


def _format_syntax_expr(value: Any) -> str:
    if isinstance(value, LiteralExpr):
        return _format_value(value.value)
    if isinstance(value, ParamRefExpr):
        return f"param.{value.name}"
    if isinstance(value, SymbolRefExpr):
        suffix = f"[{value.output_index}]" if value.output_index is not None else ""
        return f"{value.symbol}.{value.member}{suffix}"
    # The 0.1 syntax formatter delegates through lowering, so this is a hard
    # boundary against accidentally accepting arrays or code in language 0.2.
    raise TypeError(f"unsupported language 0.2 expression: {type(value).__name__}")


def _format_syntax_node(node: NodeDecl, indent: str) -> list[str]:
    identity = f" @id({_format_value(node.explicit_id)})" if node.explicit_id is not None else ""
    lines = [f"{indent}node {node.symbol}{identity}: {_format_value(node.type_name)} {{"]
    child = indent + "  "
    for statement in node.statements:
        if isinstance(statement, InputStmt):
            lines.append(
                f"{child}input[{statement.index}] = {_format_syntax_expr(statement.source)};"
            )
        elif isinstance(statement, ParmStmt):
            lines.append(f"{child}{statement.name} = {_format_syntax_expr(statement.value)};")
        else:  # pragma: no cover - closed syntax union
            raise TypeError(f"unsupported node statement: {type(statement).__name__}")
    lines.append(f"{indent}}}")
    return lines


def _format_use(statement: UseDecl, indent: str) -> str:
    arguments = ", ".join(
        f"{item.name} = {_format_syntax_expr(item.value)}" for item in statement.arguments
    )
    return (
        f"{indent}use {statement.symbol} @id({_format_value(statement.explicit_id)}) = "
        f"{statement.module_name}({arguments});"
    )


def _format_control_statement(statement: Any, indent: str) -> list[str]:
    if isinstance(statement, NodeDecl):
        return _format_syntax_node(statement, indent)
    if isinstance(statement, UseDecl):
        return [_format_use(statement, indent)]
    if isinstance(statement, YieldStmt):
        return [
            f"{indent}yield {statement.name} = {_format_syntax_expr(statement.value)};"
        ]
    if isinstance(statement, IfDecl):
        outputs = ", ".join(
            f"{item.name}: {item.type_name}" for item in statement.outputs
        )
        lines = [
            f"{indent}if {statement.symbol} @id({_format_value(statement.explicit_id)}) "
            f"({_format_syntax_expr(statement.condition)}) outputs ({outputs}) {{"
        ]
        for item in statement.then_body:
            lines.extend(_format_control_statement(item, indent + "  "))
        lines.append(f"{indent}}} else {{")
        for item in statement.else_body:
            lines.extend(_format_control_statement(item, indent + "  "))
        lines.append(f"{indent}}}")
        return lines
    if isinstance(statement, ForDecl):
        carries = ", ".join(
            f"{item.name}: {item.type_name} = {_format_syntax_expr(item.initial)}"
            for item in statement.carries
        )
        lines = [
            f"{indent}for {statement.symbol} @id({_format_value(statement.explicit_id)}) "
            f"({statement.iterator} in range({_format_syntax_expr(statement.count)})) "
            f"carry ({carries}) {{"
        ]
        for item in statement.body:
            lines.extend(_format_control_statement(item, indent + "  "))
        lines.append(f"{indent}}}")
        return lines
    raise TypeError(f"unsupported control statement: {type(statement).__name__}")


def _format_v02_graph(graph: GraphDecl) -> list[str]:
    lines = [f"graph {graph.name} {{"]
    for statement in graph.statements:
        lines.extend(_format_v02_graph_statement(statement))
    lines.append("}")
    return lines


def _format_v02_graph_statement(statement: Any) -> list[str]:
    if isinstance(statement, TargetStmt):
        return [f"  target {_format_value(statement.value)};"]
    if isinstance(statement, CategoryStmt):
        return [f"  category {statement.value};"]
    if isinstance(statement, ModeStmt):
        return [f"  mode {statement.value};"]
    if isinstance(statement, RevisionStmt):
        return [f"  expect revision {statement.value};"]
    if isinstance(statement, OwnershipStmt):
        return [f"  ownership {_format_value(statement.value)};"]
    if isinstance(statement, ExternalDecl):
        keyword = "adopt" if statement.adopted else "existing"
        return [f"  {keyword} {statement.symbol} = {_format_value(statement.path)};"]
    return _format_v02_graph_body_statement(statement)


def _format_v02_graph_body_statement(statement: Any) -> list[str]:
    if isinstance(statement, NodeDecl):
        return _format_syntax_node(statement, "  ")
    if isinstance(statement, UseDecl):
        return [_format_use(statement, "  ")]
    if isinstance(statement, (IfDecl, ForDecl)):
        return _format_control_statement(statement, "  ")
    if isinstance(statement, FlagStmt):
        return [f"  {statement.name} = {statement.symbol};"]
    if isinstance(statement, LayoutStmt):
        return [f"  layout = {statement.value};"]
    raise TypeError(f"unsupported graph statement: {type(statement).__name__}")


def _format_v02_module(module: ModuleDecl) -> list[str]:
    lines = [f"module {module.name}("]
    for parameter in module.parameters:
        default = (
            f" = {_format_syntax_expr(parameter.default)}"
            if parameter.default is not None else ""
        )
        lines.append(f"  {parameter.name}: {parameter.type_name}{default},")
    lines.append(") exports (")
    for export in module.exports:
        lines.append(f"  {export.name}: {export.type_name},")
    lines.append(") {")
    for statement in module.statements:
        if isinstance(statement, NodeDecl):
            lines.extend(_format_syntax_node(statement, "  "))
        elif isinstance(statement, UseDecl):
            lines.append(_format_use(statement, "  "))
        elif isinstance(statement, (IfDecl, ForDecl)):
            lines.extend(_format_control_statement(statement, "  "))
        elif isinstance(statement, ExportStmt):
            lines.append(f"  export {statement.name} = {_format_syntax_expr(statement.value)};")
        else:  # pragma: no cover - closed syntax union
            raise TypeError(f"unsupported module statement: {type(statement).__name__}")
    lines.append("}")
    return lines


def _validate_control_ast(
    statements: tuple[Any, ...], *, version: str, in_control: bool = False
) -> None:
    for statement in statements:
        if isinstance(statement, YieldStmt):
            if version != "0.3":
                raise ValueError("language 0.2 syntax cannot contain language 0.3 controls")
            if not in_control:
                raise ValueError("yield statements are valid only inside language 0.3 controls")
        elif isinstance(statement, IfDecl):
            if version != "0.3":
                raise ValueError("language 0.2 syntax cannot contain language 0.3 controls")
            _validate_control_ast(statement.then_body, version=version, in_control=True)
            _validate_control_ast(statement.else_body, version=version, in_control=True)
        elif isinstance(statement, ForDecl):
            if version != "0.3":
                raise ValueError("language 0.2 syntax cannot contain language 0.3 controls")
            _validate_control_ast(statement.body, version=version, in_control=True)


def format_syntax(source: SyntaxSource) -> str:
    """Canonical-format parsed language 0.2 or 0.3 source without compiling it."""
    version = source.version.value if source.version is not None else "0.1"
    if version not in {"0.2", "0.3"}:
        from .lowering import lower_syntax

        return format_graph(lower_syntax(source))
    root_statements = (
        source.graph.statements
        if source.graph is not None
        else source.module.statements if source.module is not None else ()
    )
    _validate_control_ast(root_statements, version=version)

    lines = [f"hocus {version};"]
    if source.imports:
        lines.append("")
        for declaration in source.imports:
            alias = (
                f" as {declaration.local_name}"
                if declaration.local_name != declaration.imported_name else ""
            )
            lines.append(
                f"import {{ {declaration.imported_name}{alias} }} from "
                f"{_format_value(declaration.specifier)};"
            )
    lines.append("")
    if source.graph is not None:
        lines.extend(_format_v02_graph(source.graph))
    elif source.module is not None:
        lines.extend(_format_v02_module(source.module))
    else:
        raise ValueError(f"language {version} source has no root declaration")
    return "\n".join(lines) + "\n"

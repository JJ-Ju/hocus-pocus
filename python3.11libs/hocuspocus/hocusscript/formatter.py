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
    GraphDecl,
    InputStmt,
    LayoutStmt,
    LiteralExpr,
    ModeStmt,
    ModuleDecl,
    NodeDecl,
    OwnershipStmt,
    ParamRefExpr,
    ParmStmt,
    RevisionStmt,
    SymbolRefExpr,
    SyntaxSource,
    TargetStmt,
    UseDecl,
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

    for node in graph.nodes:
        lines.append("")
        identity = f" @id({_format_value(node.explicit_id)})" if node.explicit_id is not None else ""
        lines.append(f"  node {node.symbol}{identity}: {_format_value(node.type_name)} {{")
        for input_spec in node.inputs:
            lines.append(f"    input[{input_spec.index}] = {_format_reference(input_spec.source)};")
        for parm in node.parms:
            lines.append(f"    {parm.name} = {_format_value(parm.value)};")
        lines.append("  }")

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
    lines.append("}")
    return "\n".join(lines) + "\n"


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


def _format_v02_graph(graph: GraphDecl) -> list[str]:
    lines = [f"graph {graph.name} {{"]
    for statement in graph.statements:
        if isinstance(statement, TargetStmt):
            lines.append(f"  target {_format_value(statement.value)};")
        elif isinstance(statement, CategoryStmt):
            lines.append(f"  category {statement.value};")
        elif isinstance(statement, ModeStmt):
            lines.append(f"  mode {statement.value};")
        elif isinstance(statement, RevisionStmt):
            lines.append(f"  expect revision {statement.value};")
        elif isinstance(statement, OwnershipStmt):
            lines.append(f"  ownership {_format_value(statement.value)};")
        elif isinstance(statement, ExternalDecl):
            keyword = "adopt" if statement.adopted else "existing"
            lines.append(f"  {keyword} {statement.symbol} = {_format_value(statement.path)};")
        elif isinstance(statement, NodeDecl):
            lines.extend(_format_syntax_node(statement, "  "))
        elif isinstance(statement, UseDecl):
            lines.append(_format_use(statement, "  "))
        elif isinstance(statement, FlagStmt):
            lines.append(f"  {statement.name} = {statement.symbol};")
        elif isinstance(statement, LayoutStmt):
            lines.append(f"  layout = {statement.value};")
        else:  # pragma: no cover - closed syntax union
            raise TypeError(f"unsupported graph statement: {type(statement).__name__}")
    lines.append("}")
    return lines


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
        elif isinstance(statement, ExportStmt):
            lines.append(f"  export {statement.name} = {_format_syntax_expr(statement.value)};")
        else:  # pragma: no cover - closed syntax union
            raise TypeError(f"unsupported module statement: {type(statement).__name__}")
    lines.append("}")
    return lines


def format_syntax(source: SyntaxSource) -> str:
    """Canonical-format a parsed source without enabling language 0.2 compilation."""
    version = source.version.value if source.version is not None else "0.1"
    if version != "0.2":
        from .lowering import lower_syntax

        return format_graph(lower_syntax(source))
    lines = ["hocus 0.2;"]
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
        raise ValueError("language 0.2 source has no root declaration")
    return "\n".join(lines) + "\n"

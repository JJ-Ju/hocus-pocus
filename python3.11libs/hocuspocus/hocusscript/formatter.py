"""Canonical formatter for parsed HocusScript 0.1 graphs."""

from __future__ import annotations

import json
from typing import Any

from .model import ArrayValue, CodeValue, GraphSpec, LiteralValue, NodeReference


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
        lines.append(f"  node {node.symbol}: {_format_value(node.type_name)} {{")
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

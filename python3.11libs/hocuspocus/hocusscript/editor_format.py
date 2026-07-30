"""Canonical formatter for language-0.4 editor declarations."""

from __future__ import annotations

import json

from .editor_syntax import (
    EditorConnectionRef,
    EditorDestinationRefs,
    EditorEntityDecl,
    EditorItemRef,
    EditorItemRefs,
)
from .syntax import ArrayExpr, LiteralExpr


def format_editor_entity(entity: EditorEntityDecl, indent: str = "  ") -> list[str]:
    lines = [
        f"{indent}{entity.entity_kind} @id({_quote(entity.explicit_id)}) {{"
    ]
    for prop in entity.properties:
        lines.append(
            f"{indent}  {prop.name} = {_format_value(prop.value)};"
        )
    lines.append(f"{indent}}}")
    return lines


def _format_value(value: object) -> str:
    if isinstance(value, LiteralExpr):
        return _scalar(value.value)
    if isinstance(value, ArrayExpr):
        return "[" + ", ".join(_format_value(item) for item in value.items) + "]"
    if isinstance(value, EditorItemRef):
        return _format_ref(value)
    if isinstance(value, EditorItemRefs):
        return "[" + ", ".join(_format_ref(item) for item in value.items) + "]"
    if isinstance(value, EditorConnectionRef):
        return f"{_format_ref(value.item)}.output[{value.output_index}]"
    if isinstance(value, EditorDestinationRefs):
        return "[" + ", ".join(
            f"{_format_ref(item.node)}.input[{item.input_index}]"
            for item in value.items
        ) + "]"
    raise TypeError(f"unsupported editor formatter value: {type(value).__name__}")


def _format_ref(value: EditorItemRef) -> str:
    identity = value.identity if value.item_kind == "node" else _quote(value.identity)
    return f"{value.item_kind} {identity}"


def _scalar(value: object) -> str:
    if value is True:
        return "true"
    if value is False:
        return "false"
    if value is None:
        return "null"
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def _quote(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)

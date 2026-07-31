"""Bounded aggregate-code accounting for expanded graph values."""

from __future__ import annotations

from typing import Any

from .expander import ModuleExpansionError
from .model import ArrayValue, CodeValue, TaggedValue


def graph_value_code_bytes(value: Any) -> int:
    if isinstance(value, CodeValue):
        try:
            return len(value.body.encode("utf-8"))
        except UnicodeEncodeError as exc:
            raise ModuleExpansionError(
                "HOCUS474",
                "Embedded code must be valid Unicode text.",
                value.span,
            ) from exc
    if isinstance(value, ArrayValue):
        return sum(graph_value_code_bytes(item) for item in value.items)
    if isinstance(value, TaggedValue):
        return _tagged_text_bytes(value)
    return 0


def _tagged_text_bytes(value: TaggedValue) -> int:
    total = 0
    stack = [value.payload]
    while stack:
        item = stack.pop()
        if isinstance(item, str):
            total += len(item.encode("utf-8"))
        elif isinstance(item, CodeValue):
            total += len(item.body.encode("utf-8"))
        elif isinstance(item, TaggedValue):
            stack.append(item.payload)
        elif isinstance(item, ArrayValue):
            stack.extend(item.items)
        elif isinstance(item, dict):
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)
    return total


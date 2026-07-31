"""Root-only editor declaration projection into GraphSpec 0.5."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .editor_carrier import encode_editor_declarations
from .editor_syntax import EditorEntityDecl
from .diagnostics import SourcePosition, SourceSpan
from .syntax import ExternalDecl, NodeDecl


def expanded_editor_entities(
    graph_statements: Sequence[Any],
    directives: Sequence[Any],
    root_symbols: Mapping[str, str],
    ownership: str | None,
) -> list[dict[str, Any]]:
    declarations = [
        item for item in directives if isinstance(item, EditorEntityDecl)
    ]
    known = {
        item.symbol
        for item in graph_statements
        if isinstance(item, (NodeDecl, ExternalDecl))
    }
    mutable = {
        item.symbol
        for item in graph_statements
        if isinstance(item, NodeDecl)
        or isinstance(item, ExternalDecl) and item.adopted
    }
    return encode_editor_declarations(
        declarations,
        known_nodes=known,
        mutable_nodes=mutable,
        ownership=ownership,
        node_symbols=root_symbols,
        node_explicit_ids={
            item.explicit_id
            for item in graph_statements
            if isinstance(item, NodeDecl) and item.explicit_id is not None
        },
    )


def attach_editor_entities(
    result: dict[str, Any],
    entry: Any,
    directives: Sequence[Any],
    root_symbols: Mapping[str, str],
    ownership: str | None,
) -> None:
    if entry.version.value == "0.4":
        result["editorEntities"] = expanded_editor_entities(
            entry.graph.statements, directives, root_symbols, ownership,
        )


def editor_origin_spans(graph: Mapping[str, Any]) -> list[SourceSpan]:
    result = []
    for item in graph.get("editorEntities", []):
        span = item["span"]
        result.append(SourceSpan(
            span["sourceUri"],
            SourcePosition(**span["start"]),
            SourcePosition(**span["end"]),
        ))
    return result

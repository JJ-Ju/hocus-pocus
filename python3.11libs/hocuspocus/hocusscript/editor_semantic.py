"""Small root-graph semantic adapter for editor declarations."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .editor_carrier import encode_editor_declarations
from .editor_syntax import EditorEntityDecl
from .syntax import NodeDecl


def validate_graph_editor_declarations(
    graph: Any,
    directives: Mapping[str, list[Any]],
    known: set[str],
    mutable: set[str],
) -> None:
    ownership = (
        directives["ownership"][0].value if directives["ownership"] else None
    )
    encode_editor_declarations(
        [
            item for item in graph.statements
            if isinstance(item, EditorEntityDecl)
        ],
        known_nodes=known,
        mutable_nodes=mutable,
        ownership=ownership,
        node_explicit_ids={
            item.explicit_id
            for item in graph.statements
            if isinstance(item, NodeDecl) and item.explicit_id is not None
        },
    )

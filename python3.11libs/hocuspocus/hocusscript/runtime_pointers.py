"""Shared GraphSpec pointer surface for HS7 runtime entity tables."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def runtime_entity_pointers(graph: Mapping[str, Any]) -> set[str]:
    return {
        f"/{table}/{index}"
        for table in ("spareParameters", "animations")
        for index, _ in enumerate(graph.get(table, []))
    } | {
        f"/editorEntities/{index}"
        for index, _ in enumerate(graph.get("editorEntities", []))
    }

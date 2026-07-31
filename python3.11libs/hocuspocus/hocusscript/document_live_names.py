"""Deterministic legal Houdini names for lowered internal graph symbols."""

from __future__ import annotations

import hashlib
from typing import Any

_INTERNAL_SYMBOL_PREFIX = "__hocus_"


def live_node_names(nodes: list[dict[str, Any]]) -> dict[str, str]:
    """Keep authored names and map reserved generated symbols injectively."""

    symbols = [str(node["symbol"]) for node in nodes]
    occupied = {
        symbol for symbol in symbols
        if not symbol.startswith(_INTERNAL_SYMBOL_PREFIX)
    }
    result = {symbol: symbol for symbol in occupied}
    for symbol in sorted(
        item for item in symbols if item.startswith(_INTERNAL_SYMBOL_PREFIX)
    ):
        digest = hashlib.sha256(symbol.encode("utf-8")).hexdigest()
        candidate = f"hocus_generated_{digest}"
        while candidate in occupied:
            candidate += "_"
        occupied.add(candidate)
        result[symbol] = candidate
    return result

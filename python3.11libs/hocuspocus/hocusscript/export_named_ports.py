"""Language-0.4 export symbol and named-port selection helpers."""

from __future__ import annotations

import re
from typing import Any

from .port_selectors import fixed_named_connector

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def use_authored_symbols(work: Any) -> None:
    if work.language_version != "0.4":
        return
    symbols = {
        str(node["uid"]): node.get("name")
        for node in work.authored_nodes
    }
    if (
        len(set(symbols.values())) != len(symbols)
        or any(
            not isinstance(value, str)
            or _IDENTIFIER.fullmatch(value) is None
            or value.startswith("__hocus_")
            for value in symbols.values()
        )
    ):
        work.block(
            "HOCUS803", "Language 0.4 export requires unique authored live names.",
            "/nodes",
        )
        return
    work.symbols_by_uid = symbols


def named_edge_selectors(work: Any, provider: Any) -> set[tuple[str, int]]:
    if work.language_version != "0.4" or provider is None:
        return set()
    snapshot = provider.get_catalog()
    selected: dict[str, Any] = {}
    for uid, node in work.nodes_by_uid.items():
        candidates = [
            item for item in snapshot.operators
            if item.category == work.child_category
            and (
                node.get("typeName") == item.qualified_name
                or node.get("typeName") == item.name
                or node.get("typeName") in item.aliases
            )
        ]
        if len(candidates) == 1:
            selected[uid] = candidates[0]
    named: set[tuple[str, int]] = set()
    for dest_uid, edges in work.inputs_by_dest.items():
        destination = selected.get(dest_uid)
        for input_index, source_uid, output_index in edges:
            source = selected.get(source_uid)
            names = work.connector_names_by_dest.get((dest_uid, input_index))
            if source is None or destination is None or names is None:
                continue
            output = (
                fixed_named_connector(source.outputs, names[0])
                if names[0] is not None else None
            )
            input_port = (
                fixed_named_connector(destination.inputs, names[1])
                if names[1] is not None else None
            )
            if (
                output is not None and output.index == output_index
                and input_port is not None and input_port.index == input_index
            ):
                named.add((dest_uid, input_index))
    return named

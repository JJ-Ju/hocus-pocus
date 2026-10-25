"""Helpers shared by the 2.0 workloads (not a test module).

The scene content the 1.4 workloads shared with these (the city's VEX and builders, the
soak's model) is in ``city_scene.py`` and ``soak_model.py``, so the 2.0 totals still
measure the work the 1.4 budgets in ``tests/workloads/budgets.json`` measured.
"""

from __future__ import annotations

import re
from typing import Any


def ident(path: str) -> str:
    """An ``edit`` op id for a node path: ``/obj/city_gen/LOT`` -> ``city_gen_LOT``."""
    return re.sub(r"[^A-Za-z0-9_]", "_", path.removeprefix("/obj/").strip("/"))


def creates(items: list[dict[str, Any]], known: set[str] | None = None) -> list[dict[str, Any]]:
    """1.4 ``node_create`` items as ``edit`` create ops chained by ``$id``.

    Every created node gets the id of its path (:func:`ident`); a ``parent`` or an input's
    ``from`` that names a node created earlier in the same ``edit`` (or listed in ``known``)
    becomes ``$<id>``, so the transaction says how its nodes relate instead of repeating
    their paths.
    """
    made = set(known or ())
    ops = []
    for item in items:
        op: dict[str, Any] = {"op": "create", **item}
        path = f"{item['parent'].rstrip('/')}/{item['name']}" if item.get("name") else None
        if item["parent"] in made:
            op["parent"] = f"${ident(item['parent'])}"
        if item.get("inputs"):
            op["inputs"] = [
                {**row, "from": f"${ident(row['from'])}"} if row["from"] in made else row
                for row in item["inputs"]
            ]
        if path is not None:
            op["id"] = ident(path)
            made.add(path)
        ops.append(op)
    return ops


def rows_by_path(result: Any) -> dict[str, dict[str, Any]]:
    """An ``edit`` summary's per-node rows by path."""
    return {row["path"]: row for row in result["nodes"]}


def node_problems(result: Any) -> list[dict[str, Any]]:
    """The touched nodes of an ``edit`` echo that report errors."""
    return [row for row in result.get("nodes", []) if row.get("errors")]

"""Helpers shared by the 2.0 workloads (not a test module).

The v2 workloads reuse the 1.4 workloads' scene content (VEX snippets, item builders, the
soak's model) so both tiers measure the same work; :func:`load_1x` loads a 1.4 workload
module by path under its own name, since both tiers' test modules live outside packages.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path
from typing import Any

TIER_1X = Path(__file__).resolve().parents[1]


def load_1x(stem: str) -> Any:
    """The 1.4 workload module ``tests/workloads/<stem>.py``."""
    name = f"hp_workloads_1x_{stem}"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, TIER_1X / f"{stem}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


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
    """An ``edit`` result's per-op rows by path."""
    return {row["path"]: row for row in result["results"] if row.get("path")}


def node_problems(result: Any) -> list[dict[str, Any]]:
    """The touched nodes of an ``edit`` echo that report errors."""
    return [row for row in result.get("nodes", []) if row.get("errors")]

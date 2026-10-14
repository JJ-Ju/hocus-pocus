"""``search`` (spec-2.0 §2.3): one search tool over ``node_type_search`` and ``node_find``.

``{kind: types | nodes, query?, ...options}`` runs the registered implementation of the
1.4 tool for ``kind`` (looked up in the host registry at call time, so the ranking,
synonyms and filters exist once):

* ``types``: ``node_type_search`` (``query``, ``category``, ``include_hidden``,
  ``current_only``, ``limit``). 1.4 has no paging there, so ``search`` pages it: page
  ``n`` asks ``node_type_search`` for the first ``offset + limit`` matches (its ranking is
  deterministic) and keeps the last ``limit``; ``next_cursor`` is added when ``total``
  counts more matches than the pages so far. The first page is otherwise the 1.4 result.
* ``nodes``: ``node_find`` (``query`` as its ``type`` glob, ``root``, ``pattern``,
  ``category``, ``flags``, ``has_errors``, ``recurse_locked``, ``limit``, ``cursor``).

The ``nodes`` result is projected for 2.0 (spec-2.0 M4 "read shapes";
:func:`compact_nodes`): no ``kind`` echo (the caller knows it, as ``inspect`` leaves out
``what``), no ``root`` echo when the call named it, rows without what is default or empty,
and what the rows share said once in ``common``. ``detail: full`` returns ``{kind, ...the
1.4 result}`` unchanged; ``types`` returns ``{kind, ...}`` unchanged.
"""

from __future__ import annotations

from typing import Any

from ._common import CURSOR_HINT, bad_arg
from .registry import HostContext, tool
from .registry import get as get_tool

KINDS = ("types", "nodes")
DETAILS = ("compact", "full")
OPTIONS: dict[str, frozenset[str]] = {
    "types": frozenset(
        {"query", "category", "include_hidden", "current_only", "limit", "cursor", "detail"}
    ),
    "nodes": frozenset(
        {
            "detail",
            "query",
            "root",
            "pattern",
            "category",
            "flags",
            "has_errors",
            "recurse_locked",
            "limit",
            "cursor",
        }
    ),  # fmt: skip
}
TYPES_DEFAULT_LIMIT = 20
TYPES_MAX_MATCHES = 1000
"""``node_type_search``'s own ``limit`` cap: the deepest match a types page can reach."""
TYPES_CURSOR = "t:"


# -- 2.0 projections -----------------------------------------------------------------------


def _hoist_majority(rows: list[dict[str, Any]], key: str, common: dict[str, Any]) -> None:
    """Move ``key`` into ``common`` with the value most rows share (two or more); rows
    with another value keep their own, which overrides ``common``."""
    values = [row[key] for row in rows if key in row]
    if len(values) < 2 or len(values) < len(rows):
        return
    counts: dict[Any, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    value, n = max(counts.items(), key=lambda kv: kv[1])
    if n < 2:
        return
    common[key] = value
    for row in rows:
        if row[key] == value:
            del row[key]


def compact_node_row(row: dict[str, Any]) -> dict[str, Any]:
    """A ``node_find`` row without what is off, zero or false: ``{path, type, category,
    flags?: [on flags], has_errors?: true, child_count?, input_count?}``."""
    out: dict[str, Any] = {"path": row.get("path"), "type": row.get("type")}
    if "category" in row:
        out["category"] = row["category"]
    flags = row.get("flags")
    if isinstance(flags, dict):
        on = [name for name, value in flags.items() if value]
        if on:
            out["flags"] = on
    if row.get("has_errors"):
        out["has_errors"] = True
    for key in ("child_count", "input_count"):
        if row.get(key):
            out[key] = row[key]
    for key, value in row.items():  # anything a later node_find adds is kept
        if key not in out and key not in ("flags", "has_errors", "child_count", "input_count"):
            out[key] = value
    return out


def compact_nodes(result: dict[str, Any], *, root_given: bool = False) -> dict[str, Any]:
    """``node_find``'s result with compact rows and ``common: {category}`` (after
    ``nodes``): the category most rows share. A row in another category names its type
    with the category, ``Object/geo``, as ``inspect what: type`` takes it.
    ``root`` is left out when the call named it (``root_given``); ``next_cursor`` is the
    last row's path (:data:`NODES_CURSOR`)."""
    rows = [compact_node_row(r) if isinstance(r, dict) else r for r in result.get("nodes", [])]
    common: dict[str, Any] = {}
    _hoist_majority([r for r in rows if isinstance(r, dict)], "category", common)
    for row in rows:  # another category: the type as inspect what: type names it
        if isinstance(row, dict) and "category" in row and isinstance(row.get("type"), str):
            row["type"] = f"{row.pop('category')}/{row['type']}"
    out: dict[str, Any] = {}
    for key, value in result.items():
        if key == "root" and root_given:
            continue
        if key == "next_cursor" and isinstance(value, str) and value.startswith(NODES_CURSOR):
            value = value[len(NODES_CURSOR) :]
        out[key] = rows if key == "nodes" else value
        if key == "nodes" and common:
            out["common"] = common
    return out


def _detail(args: dict[str, Any]) -> str:
    detail = args.get("detail", "compact")
    if detail not in DETAILS:
        raise bad_arg(f"'detail' must be compact or full; got {detail!r}.")
    return detail


def _types_offset(cursor: Any) -> int:
    if cursor is None:
        return 0
    if isinstance(cursor, str) and cursor.startswith(TYPES_CURSOR):
        digits = cursor[len(TYPES_CURSOR) :]
        if digits.isdigit():
            return int(digits)
    raise bad_arg(f"Invalid cursor {cursor!r} for kind types.", hint=CURSOR_HINT)


def _types(args: dict[str, Any], ctx: HostContext) -> dict[str, Any]:
    limit = args.get("limit", TYPES_DEFAULT_LIMIT)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
        raise bad_arg("'limit' must be an integer from 1 to 1000.")
    offset = _types_offset(args.get("cursor"))
    if offset + limit > TYPES_MAX_MATCHES:
        raise bad_arg(
            f"kind types pages reach the first {TYPES_MAX_MATCHES} matches only.",
            hint="Narrow the query or pass category.",
        )
    call = {k: v for k, v in args.items() if k not in ("cursor", "limit")}
    if offset or "limit" in args:
        call["limit"] = offset + limit
    result = get_tool("node_type_search").fn(call, ctx)
    if offset:
        result["results"] = result["results"][offset:]
    shown = offset + len(result["results"])
    if result["results"] and isinstance(result.get("total"), int) and shown < result["total"]:
        result["next_cursor"] = f"{TYPES_CURSOR}{shown}"
    return result


NODES_CURSOR = "after:"
"""``node_find``'s cursor prefix. A compact nodes page's ``next_cursor`` is the last row's
path without it (the page resumes after that path); ``cursor`` takes either form."""


def _nodes(args: dict[str, Any], ctx: HostContext) -> dict[str, Any]:
    call = {k: v for k, v in args.items() if k != "query"}
    if args.get("query") is not None:
        call["type"] = args["query"]
    cursor = call.get("cursor")
    if isinstance(cursor, str) and cursor.startswith("/"):
        call["cursor"] = NODES_CURSOR + cursor
    return get_tool("node_find").fn(call, ctx)


@tool("search")
def search(args: dict[str, Any], ctx: HostContext) -> dict[str, Any]:
    kind = args.get("kind")
    if kind not in KINDS:
        raise bad_arg(f"'kind' must be types or nodes; got {kind!r}.", candidates=list(KINDS))
    options = {k: v for k, v in args.items() if k != "kind"}
    extra = sorted(set(options) - OPTIONS[kind])
    if extra:
        raise bad_arg(
            f"kind: {kind} does not take {', '.join(extra)}.",
            hint=f"{kind} takes {', '.join(sorted(OPTIONS[kind]))} (docs/tools.md, search).",
        )
    full = _detail(options) == "full"
    options.pop("detail", None)
    if kind == "types":
        query = options.get("query")
        if not isinstance(query, str) or not query.strip():
            raise bad_arg("kind: types needs query (a name, label or keyword).")
        types = _types(options, ctx)
        return {"kind": kind, **types}
    nodes = _nodes(options, ctx)
    if full:
        return {"kind": kind, **nodes}
    return compact_nodes(nodes, root_given=options.get("root") is not None)

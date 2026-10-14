"""``search`` (spec-2.0 §2.3): one search tool over ``node_type_search`` and ``node_find``.

``{kind: types | nodes, query?, ...options}`` runs the registered implementation of the
1.4 tool for ``kind`` (looked up in the host registry at call time, so the ranking,
synonyms and filters exist once) and returns ``{kind, ...its result}`` unchanged:

* ``types``: ``node_type_search`` (``query``, ``category``, ``include_hidden``,
  ``current_only``, ``limit``). 1.4 has no paging there, so ``search`` pages it: page
  ``n`` asks ``node_type_search`` for the first ``offset + limit`` matches (its ranking is
  deterministic) and keeps the last ``limit``; ``next_cursor`` is added when ``total``
  counts more matches than the pages so far. The first page is otherwise the 1.4 result.
* ``nodes``: ``node_find`` (``query`` as its ``type`` glob, ``root``, ``pattern``,
  ``category``, ``flags``, ``has_errors``, ``recurse_locked``, ``limit``, ``cursor``).
"""

from __future__ import annotations

from typing import Any

from ._common import CURSOR_HINT, bad_arg
from .registry import HostContext, tool
from .registry import get as get_tool

KINDS = ("types", "nodes")
OPTIONS: dict[str, frozenset[str]] = {
    "types": frozenset({"query", "category", "include_hidden", "current_only", "limit", "cursor"}),
    "nodes": frozenset(
        {
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


def _nodes(args: dict[str, Any], ctx: HostContext) -> dict[str, Any]:
    call = {k: v for k, v in args.items() if k != "query"}
    if args.get("query") is not None:
        call["type"] = args["query"]
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
    if kind == "types":
        query = options.get("query")
        if not isinstance(query, str) or not query.strip():
            raise bad_arg("kind: types needs query (a name, label or keyword).")
        return {"kind": kind, **_types(options, ctx)}
    return {"kind": kind, **_nodes(options, ctx)}

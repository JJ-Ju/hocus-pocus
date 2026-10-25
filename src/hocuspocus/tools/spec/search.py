"""Catalogue entry for ``search`` (spec-2.0 §2.3; BIBLE §4.9)."""

from __future__ import annotations

from ._helpers import CATEGORIES, ToolSpec, _cursor, _enum, _flags, _i, _obj, _s

SPEC = ToolSpec(
    name="search",
    profiles=("minimal", "core", "full"),
    description=(
        "Search node types or nodes. kind types: query is a name, label or keyword (ranked, "
        "synonyms; current_only hides older versions). kind nodes: under root, query a type "
        "glob; pattern, category, flags, has_errors filter. Compact rows, paged by limit and "
        "cursor."
    ),
    notes=(
        "Each kind takes only its own arguments; any other is invalid_argument naming the "
        "ones it takes (types: query, category, include_hidden, current_only, limit, cursor, "
        "detail; nodes: query, root, pattern, category, flags, has_errors, recurse_locked, "
        "limit, cursor, detail). Defaults: types limit 20 and current_only true; nodes root / "
        "and limit 50. types: query is required; the result is {results, common?, total, "
        "hint?, notes?}, plus next_cursor when total counts more matches than this page (a "
        "types page reaches the first 1000 matches). nodes: query (optional) is a type glob, "
        "pattern a name glob; the result is {root?, nodes, common?, total, next_cursor?}. "
        "Compact (detail: compact, the default; detail: full returns {kind, ...} with every "
        "field of every row): what is default or empty is omitted and kind is not echoed. "
        "nodes: root is omitted when the call named it; a row is {path, type}, plus flags "
        "(the list of flags that are on) when any is on, has_errors only when true, "
        "child_count and input_count only when above 0; common: {category} holds the "
        "category most rows share, and a row in another category names its type as "
        "Category/type (Object/geo); next_cursor is the last row's path (cursor takes it, or "
        "after:<path>). types: a row is {name, label, description} with description capped "
        "at 80 characters, plus inputs as 'min-max' unless 1-1, deprecated and hidden only "
        "when true, other_versions only when non-empty, current and is_current_version: "
        "false for an older version; version is not given (a namespaced version is in the "
        "name); common hoists category, child_category and typical_parents when every row "
        "shares them, and typical_parents (where a type of that category goes) also when "
        "only some rows carry it."
    ),
    input_schema=_obj(
        {
            "kind": _enum(("types", "nodes")),
            "query": _s("types: name or keyword; nodes: type glob."),
            "category": _enum(CATEGORIES),
            "root": _s(),
            "pattern": _s("nodes: name glob."),
            "flags": _flags("locked"),
            "has_errors": {"type": "boolean"},
            "recurse_locked": {"type": "boolean"},
            "include_hidden": {"type": "boolean"},
            "current_only": {"type": "boolean"},
            "limit": _i(None, minimum=1, maximum=1000),
            "cursor": _cursor(),
            "detail": _enum(("compact", "full")),
        },
        ("kind",),
    ),
    read_only=True,
    examples=(
        {"kind": "types", "query": "scatter"},
        {"kind": "types", "query": "noise", "category": "Vop", "limit": 5},
        {"kind": "nodes", "root": "/obj", "query": "*file*", "has_errors": True},
    ),
)

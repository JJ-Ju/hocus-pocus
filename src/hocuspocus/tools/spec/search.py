"""Catalogue entry for ``search`` (spec-2.0 §2.3; BIBLE §4.9)."""

from __future__ import annotations

from ._helpers import CATEGORIES, ToolSpec, _cursor, _enum, _flags, _i, _obj, _s

SPEC = ToolSpec(
    name="search",
    profiles=("minimal", "core", "full"),
    description=(
        "Search node types or nodes. kind types: node_type_search (query is a name, label "
        "or keyword; 1.4 ranking, synonyms, current_only). kind nodes: node_find under root "
        "(query is a type glob; pattern, category, flags, has_errors). Returns the 1.4 "
        "tool's result with compact rows, paged by limit and cursor."
    ),
    notes=(
        "Each kind takes its 1.4 tool's arguments; any other is invalid_argument naming "
        "the ones it takes. Defaults are the 1.4 tool's (types: limit 20, current_only "
        "true; nodes: root /, limit 50). types: query is required; the result is "
        "node_type_search's {results, common?, total, hint?, notes?}, plus next_cursor when "
        "total counts more matches than this page (node_type_search itself has no paging; a "
        "types page reaches the first 1000 matches). nodes: query (optional) is node_find's "
        "type glob, pattern its name glob; the result is node_find's {root?, nodes, "
        "common?, total, next_cursor?}. Compact (detail: compact, the default; detail: full "
        "returns {kind, ...the 1.4 result} unchanged): what is default or empty is omitted "
        "and kind is not echoed. nodes: root is omitted when the call named it; a row is "
        "{path, type}, plus flags (the list of flags that are on) when any is on, "
        "has_errors only when true, child_count and input_count only when above 0; common: "
        "{category} holds the category most rows share, and a row in another category names "
        "its type as Category/type (Object/geo); next_cursor is the last row's path (cursor "
        "takes it, or node_find's after:<path>). types: a row is {name, label, "
        "description} with description capped at 80 characters, plus inputs as 'min-max' "
        "unless 1-1, deprecated and hidden only when true, other_versions only when "
        "non-empty, current and is_current_version: false for an older version; version is "
        "not given (a namespaced version is in the name); common hoists category, "
        "child_category and typical_parents when every row shares them, and "
        "typical_parents (where a type of that category goes) also when only some rows "
        "carry it."
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

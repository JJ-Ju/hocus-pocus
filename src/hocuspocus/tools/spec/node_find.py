"""Catalogue entry for ``node_find`` (BIBLE §4.4)."""

from __future__ import annotations

from ._helpers import CATEGORIES, ToolSpec, _b, _cursor, _enum, _flags, _limit, _obj, _s

SPEC = ToolSpec(
    name="node_find",
    profiles=("compat_1x",),
    description=(
        "Search a subtree for nodes (name and type globs, category, flags, has_errors). Rows: "
        "path, type, category, flags, input_count, child_count, has_errors. Locked HDAs are not"
        " entered unless recurse_locked. Paged by limit and cursor."
    ),
    input_schema=_obj(
        {
            "root": _s(None, default="/"),
            "pattern": _s("Name glob.", default="*"),
            "type": _s("Type name glob."),
            "category": _enum(CATEGORIES),
            "flags": _flags("locked"),
            "has_errors": {"type": "boolean"},
            "recurse_locked": _b(False),
            "limit": _limit(),
            "cursor": _cursor(),
        }
    ),
    read_only=True,
    examples=({"root": "/obj", "type": "*file*"}, {"has_errors": True, "limit": 20}),
)

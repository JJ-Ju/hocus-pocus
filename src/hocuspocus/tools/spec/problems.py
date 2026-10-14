"""Catalogue entry for ``problems`` (BIBLE §4.6)."""

from __future__ import annotations

from ._helpers import ToolSpec, _b, _cursor, _limit, _n, _obj, _s

SPEC = ToolSpec(
    name="problems",
    description=(
        "Explain red nodes: lists nodes in a subtree with errors or warnings, broken channel "
        "references, missing files, unconnected required inputs; errored nodes changed since "
        "their last cook are recooked first. cook_uncooked cooks never-cooked nodes too. Paged "
        "by limit and cursor."
    ),
    notes=(
        "A TOP node with failed work items is a failed_work_items row with count, work_item "
        "{id, index} and the first item's error in message. "
        "Locked HDAs are skipped unless recurse_locked. A scan budget (10 s, or half of "
        "timeout_s) can end a page early with incomplete: true and a next_cursor that continues"
        " the walk without losing rows."
    ),
    input_schema=_obj(
        {
            "root": _s(None, default="/"),
            "include_warnings": _b(True),
            "cook_uncooked": _b(False),
            "recurse_locked": _b(False),
            "timeout_s": _n(None, minimum=1, default=30),
            "limit": _limit(),
            # §4.1: list tools take limit and cursor; the §4.6 row lists only limit.
            "cursor": _cursor(),
        }
    ),
    read_only=True,
    examples=({"root": "/obj/geo1"}, {"include_warnings": False, "cook_uncooked": True}),
)

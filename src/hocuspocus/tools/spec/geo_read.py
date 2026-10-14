"""Catalogue entry for ``geo_read`` (BIBLE §4.6)."""

from __future__ import annotations

from ._helpers import ToolSpec, _arr, _b, _cursor, _enum, _i, _list, _n, _obj, _out, _s, _t

SPEC = ToolSpec(
    name="geo_read",
    description=(
        "Read attribute values like the geometry spreadsheet: count rows of one class from "
        "start, optionally within group, at frame. stats adds min/max/mean and "
        "unique strings over the whole class. Page by passing next_cursor as cursor."
    ),
    input_schema=_obj(
        {
            "path": _s("SOP or OBJ path."),
            # bible-silent: class default; point matches the spreadsheet's default.
            "class": _enum(("point", "prim", "vertex", "detail"), "point"),
            "attribs": _arr({"type": "string"}),
            "start": _i(None, minimum=0, default=0),
            "count": _i(None, minimum=1, maximum=10000, default=50),
            "group": _s(),
            "stats": _b(False),
            # §4.1: cursors are opaque strings everywhere; overrides start.
            "cursor": _cursor(),
            "frame": _n(),
        },
        ("path",),
    ),
    output_schema=_out(
        {
            "path": _t("string"),
            "class": _t("string"),
            "columns": _list(),
            "rows": {"type": "array", "items": {"type": "array"}},
            "start": _t("integer"),
            "total": _t("integer"),
            "next_cursor": _t("string"),
            "truncated": _t("boolean"),
            "stats": _t("object"),
        },
        ("columns", "rows", "total"),
    ),
    read_only=True,
    examples=(
        {"path": "/obj/geo1/OUT", "attribs": ["P", "Cd"], "count": 10},
        {"path": "/obj/geo1/OUT", "class": "prim", "stats": True},
    ),
)

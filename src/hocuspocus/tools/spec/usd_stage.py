"""Catalogue entry for ``usd_stage`` (BIBLE §4.7)."""

from __future__ import annotations

from ._helpers import ToolSpec, _arr, _b, _cursor, _enum, _i, _limit, _n, _obj, _s

SPEC = ToolSpec(
    name="usd_stage",
    profiles=("compat_1x",),
    description=(
        "Read a LOP's USD stage: prims (path, type) under prim (path or glob) to depth; "
        "include adds attributes (attribs: name glob), xform, bindings, layers. summary: "
        "type counts, world bbox. Paged (limit, cursor)."
    ),
    notes=(
        "time is a time code (default the current frame). prim globs: * within a path "
        "segment, ** across segments, | between alternatives (each a path or glob, e.g. "
        "/lights|/cameras); matches are listed with their subtrees to depth, in stage order. "
        "An invalid alternative is invalid_argument, as is an exact one that names no prim. "
        "Attribute values are authored values at time; arrays up to 4 elements (8 for "
        "strings and tokens) are listed in full, longer ones as {len, first}. xform gives "
        "local, and world only when it differs. total is on every page (counted up to "
        "100000, then total_capped). summary returns {total_prims, counts_by_type, "
        "bbox_world: {min, max, size}} for the whole subtree (default and render purposes). "
        "A ROP in a LOP network (usd_rop, usdrender_rop) has no stage: the LOP it renders "
        "(its loppath, else its input) is read, with a note. layers.stack rows are "
        "{identifier, save_path?, owner_node?, time_codes?}: where Houdini saves an "
        "anonymous layer (a sopimport's save path) or a file layer's path when it differs "
        "from the identifier, the LOP that made it, and [start, end] when the layer authors "
        "them; paths use forward slashes."
    ),
    input_schema=_obj(
        {
            "lop_path": _s(),
            "prim": _s(None, default="/"),
            "depth": _i(None, minimum=1, default=1),
            "include": _arr(_enum(("attributes", "xform", "bindings", "layers")), default=[]),
            "attribs": _s(),
            "summary": _b(False),
            "time": _n(),
            "limit": _limit(),
            # §4.1: list tools take limit and cursor.
            "cursor": _cursor(),
        },
        ("lop_path",),
    ),
    read_only=True,
    examples=(
        {"lop_path": "/stage/OUT"},
        {"lop_path": "/stage/OUT", "prim": "/geo", "depth": 3, "include": ["attributes"]},
    ),
)

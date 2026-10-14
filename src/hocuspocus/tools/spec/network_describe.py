"""Catalogue entry for ``network_describe`` (BIBLE §4.4)."""

from __future__ import annotations

from ._helpers import ToolSpec, _b, _cursor, _enum, _i, _obj, _s

SPEC = ToolSpec(
    name="network_describe",
    description=(
        "Read a whole network as Houdini's hou.data childrenAsData (types, non-default parms, "
        "expressions, wiring, flags) to depth; data feeds network_build. format outline is a "
        "compact tree (type, display node, error count, input sources, flags that are on); "
        "python is asCode for one node. Locked HDAs stay closed unless recurse_locked. Pages "
        "end at the response budget (next_cursor)."
    ),
    notes=(
        "depth defaults to 1, and to 2 for outline. A locked HDA appears as {type, hda_locked}."
        " Outline rows: path, name, type, children_count (left out at 0), display, errors, "
        "inputs (source path per input slot, path:n when the source's output n is not 0, "
        "null for an empty slot before a wired one; left "
        'out when nothing is wired), flags (only the ones that are on, e.g. ["display", '
        '"render"]; left out when none), and hda_locked only for locked assets not shipped with'
        " Houdini. Truncated pages carry truncated and next_cursor."
    ),
    input_schema=_obj(
        {
            "root": _s(),
            "depth": _i(None, minimum=1),
            "include_defaults": _b(False),
            "include_positions": _b(False),
            "recurse_locked": _b(False),
            "format": _enum(("data", "python", "outline"), "data"),
            "cursor": _cursor(),
        },
        ("root",),
    ),
    read_only=True,
    examples=(
        {"root": "/obj/geo1"},
        {"root": "/obj/geo1", "depth": 2, "include_positions": True},
        {"root": "/", "format": "outline"},
    ),
)

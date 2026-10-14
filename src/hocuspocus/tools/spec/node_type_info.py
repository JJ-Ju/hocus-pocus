"""Catalogue entry for ``node_type_info`` (BIBLE §4.7)."""

from __future__ import annotations

from ._helpers import CATEGORIES, ToolSpec, _b, _enum, _obj, _s

SPEC = ToolSpec(
    name="node_type_info",
    profiles=("compat_1x",),
    description=(
        "Describe one node type: label, version, named inputs and outputs, parms by folder. "
        "detail compact gives name, label, type, default rows; full adds size, range, menu and "
        "folder; folders lists folders with parm counts. folder and parms (globs, a|b) narrow "
        "the parms."
    ),
    notes=(
        'folder takes a label, an "A / B" path, or "" / "(no folder)" for the top-level parms. '
        "include_help adds the first ~2 KB of the node help. With folder or parms the inputs "
        "list becomes inputs_count, and detail full leaves out the folder list. In detail "
        "full a script menu (pdg_cachemode) or a menu built from input geometry (a SOP "
        "group) is evaluated on a temporary instance: menu {items, dynamic: true}, or items "
        "[] with a note when it evaluates empty there; so is a string menu only the node "
        "builds (a Copernicus signature). Menu labels lose their ![icon] markup. A compact "
        "listing over 8 KB leaves out the parms a menu hides at its default (the per-pattern "
        "parms of the other patterns): variants {menu parm: parms left out} and a note; pass "
        "parms or detail full to list them. A wildcard parms glob lists the parms it matches "
        "at the start of a name or label word first (*pin*: Pin Type); those it matches only "
        "inside a word (damping) follow, named in substring_matches with a note and marked "
        "matched_by: substring in detail full. An alternative without wildcards "
        "(*pin*|group: group) is an exact match, never a substring match."
    ),
    input_schema=_obj(
        {
            "type": _s("Sop/scatter, or scatter with category."),
            "category": _enum(CATEGORIES),
            "include_parms": _b(True),
            "include_help": _b(False),
            "folder": _s(),
            "parms": _s("Name or label glob, e.g. *seed* or dist|inset."),
            "detail": _enum(("compact", "full", "folders"), "compact"),
        },
        ("type",),
    ),
    read_only=True,
    examples=(
        {"type": "Sop/scatter"},
        {"type": "Sop/scatter", "parms": "*seed*"},
        {"type": "Sop/rbdmaterialfracture", "detail": "folders"},
    ),
)

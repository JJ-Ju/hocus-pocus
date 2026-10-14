"""Catalogue entry for ``node_type_search`` (BIBLE §4.7)."""

from __future__ import annotations

from ._helpers import CATEGORIES, ToolSpec, _b, _enum, _limit, _list, _obj, _out, _s, _t

SPEC = ToolSpec(
    name="node_type_search",
    profiles=("compat_1x",),
    description=(
        "Find node types by name, label, description or keyword, in all 18 categories or one. "
        "Rows: name, label, category, version, description (clipped), input range, deprecated. "
        "Current versions only, older ones named in other_versions, unless current_only is "
        "false. Exact names rank first; total counts every match."
    ),
    notes=(
        "total is the real number of matching types, not a cap: a plain-language query also "
        "matches on single description words, so broad queries can match hundreds of types. "
        "Raise limit (up to 1000) to see them all. Cop types also match the labels of their "
        "menus (remap's Threshold, blend's Over), and compositing words name their Cop type "
        "(threshold: remap, gradient: ramp, composite or over: blend, text: font, write: "
        "rop_image). A network type's row adds child_category and typical_parents (CopNet "
        "copnet: /img); when every row shares them they are said once, in common. "
        "is_current_version is on rows only with current_only false. Results with legacy "
        "Cop2 types carry a note that Copernicus is Cop."
    ),
    input_schema=_obj(
        {
            "query": _s(),
            "category": _enum(CATEGORIES),
            "limit": _limit(20),
            "include_hidden": _b(False),
            "current_only": _b(True),
        },
        ("query",),
    ),
    output_schema=_out(
        {
            "results": {
                "type": "array",
                "items": _out(
                    {
                        "name": _t("string"),
                        "label": _t("string"),
                        "category": _t("string"),
                        "version": _t("string"),
                        "description": _t("string"),
                        "other_versions": _list(),
                    },
                    ("name", "category"),
                ),
            },
            "total": _t("integer"),
        },
        ("results",),
    ),
    read_only=True,
    examples=({"query": "scatter"}, {"query": "noise", "category": "Vop", "limit": 5}),
)

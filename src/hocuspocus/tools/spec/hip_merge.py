"""Catalogue entry for ``hip_merge`` (BIBLE §4.3)."""

from __future__ import annotations

from ._helpers import ToolSpec, _b, _list, _obj, _out, _s, _t

SPEC = ToolSpec(
    name="hip_merge",
    profiles=("core", "full"),
    description=(
        "Merge the nodes matching node_pattern from another hip file into the current scene. "
        "dry_run only reports collisions (no undo step, allowed read-only). Colliding nodes are"
        " renamed unless overwrite_on_conflict."
    ),
    input_schema=_obj(
        {
            "path": _s("Hip file to merge."),
            "node_pattern": _s(None, default="*"),
            "overwrite_on_conflict": _b(False),
            "dry_run": _b(False),
        },
        ("path",),
    ),
    # bible-silent: result keys besides collisions.
    output_schema=_out(
        {
            "path": _t("string"),
            "dry_run": _t("boolean"),
            "collisions": _list(),
            "merged": _list(),
            "scene_generation": _t("integer"),
        },
        ("collisions",),
    ),
    examples=(
        {"path": "C:/lib/rig.hip", "dry_run": True},
        {"path": "C:/lib/rig.hip", "node_pattern": "/obj/rig*"},
    ),
)

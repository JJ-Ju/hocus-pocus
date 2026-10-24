"""Catalogue entry for ``hip_open`` (BIBLE §4.3)."""

from __future__ import annotations

from ._helpers import ToolSpec, _b, _list, _obj, _on_unsaved, _out, _s, _t

SPEC = ToolSpec(
    name="hip_open",
    profiles=("minimal", "core", "full"),
    description=(
        "Load a hip file, replacing the current scene; on_unsaved as in hip_new. Load warnings "
        "are returned in warnings, not raised, unless ignore_load_warnings is false. hip_merge "
        "adds nodes instead."
    ),
    input_schema=_obj(
        {
            "path": _s("Hip file."),
            "on_unsaved": _on_unsaved(),
            "ignore_load_warnings": _b(True),
        },
        ("path",),
    ),
    output_schema=_out(
        {"path": _t("string"), "warnings": _list(), "scene_generation": _t("integer")},
        ("path", "warnings", "scene_generation"),
    ),
    destructive=True,
    examples=(
        {"path": "C:/work/shot.hip"},
        {"path": "$JOB/shot_v002.hip", "on_unsaved": "discard"},
    ),
)

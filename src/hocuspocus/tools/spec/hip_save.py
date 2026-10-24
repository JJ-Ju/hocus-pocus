"""Catalogue entry for ``hip_save`` (BIBLE §4.3)."""

from __future__ import annotations

from ._helpers import ToolSpec, _b, _obj, _out, _s, _t

SPEC = ToolSpec(
    name="hip_save",
    profiles=("minimal", "core", "full"),
    description=(
        "Save the hip file. path saves as (creating directories; an untitled scene needs it); "
        "increment saves to the next version number in the file name; backup keeps a backup "
        "copy. Returns the real saved path, dirty after save, and bytes."
    ),
    input_schema=_obj(
        {
            "path": _s("Save-as target."),
            "increment": _b(False),
            "backup": _b(False),
        }
    ),
    output_schema=_out(
        {"path": _t("string"), "dirty": _t("boolean"), "bytes": _t("integer")},
        ("path", "dirty"),
    ),
    examples=({}, {"path": "C:/work/shot_v002.hip"}, {"increment": True}),
)

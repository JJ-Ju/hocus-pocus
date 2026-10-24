"""Catalogue entry for ``time`` (BIBLE §4.7)."""

from __future__ import annotations

from ._helpers import ToolSpec, _arr, _list, _n, _obj, _out, _t

SPEC = ToolSpec(
    name="time",
    profiles=("core", "full"),
    description=(
        "Read or set playbar time. With no arguments returns frame, fps and range. frame sets "
        "the current frame, range [start, end] the frame range, fps the frame rate."
    ),
    input_schema=_obj(
        {
            "frame": _n(),
            "range": _arr({"type": "number"}, "[start, end]", minItems=2, maxItems=2),
            "fps": _n(None, minimum=1),
        }
    ),
    output_schema=_out(
        {"frame": _t("number"), "fps": _t("number"), "range": _list("number")},
        ("frame", "fps", "range"),
    ),
    # Not read_only: setting changes the scene. Reads must not dirty it, so the host
    # registers time with scene=False and marks dirty itself (§4.1).
    idempotent=True,
    examples=({}, {"frame": 24}, {"range": [1, 120], "fps": 24}),
)

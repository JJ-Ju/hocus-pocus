"""Catalogue entry for ``geo_info`` (BIBLE §4.6)."""

from __future__ import annotations

from ._helpers import ToolSpec, _enum, _frame, _list, _nullable, _obj, _objs, _out, _s, _t

SPEC = ToolSpec(
    name="geo_info",
    description=(
        "Summarise the geometry of a SOP (or an OBJ's display SOP): point, prim "
        "and vertex counts, bounding box, primitive types, attributes per class with type and "
        "size, detail attribute values, groups with counts. On a Cop node: the image's layer "
        "type, resolution and channel min/max/mean."
    ),
    notes=(
        "frame evaluates the geometry at that frame without moving the playbar. intrinsics "
        "lists every volume as a row under volume_columns [name, prim, resolution, "
        "voxel_size, min, max] and every VDB under vdb_columns [name, prim, class, "
        "value_type, active_voxels, voxel_size] (at most 100 each; volume_total or vdb_total "
        "then counts them all), and the first packed primitives. Detail attribute values are"
        " capped: arrays at 16 items, strings at 200 characters, and a dict longer than 200 "
        "characters as {elided, keys}; hou vectors and matrices are lists. geo_read reads "
        "per-element values. A Cop node (or a COP network's display node) gives kind: image, "
        "output, layer_type (Mono, RGB, RGBA, ...), resolution, data_window, pixel_scale, "
        "storage, border, constant?, channels {r: {min, max, mean}, ...} of its first "
        "output, and other_outputs [{name, layer_type}]. attributes: names lists only the "
        "attribute names per class (no types or detail values). Solver internals (Vellum "
        "and DOP bookkeeping such as pprevious, hitnml, dPw, varmap, and names starting "
        "with __) are left out and counted in internal_attribute_count with a note; "
        "geo_read with attribs reads them."
    ),
    input_schema=_obj(
        {
            "path": _s("SOP or OBJ path."),
            "frame": _frame(),
            "attributes": _enum(("full", "names"), "full"),
        },
        ("path",),
    ),
    output_schema=_out(
        {
            "path": _t("string"),
            "point_count": _t("integer"),
            "prim_count": _t("integer"),
            "vertex_count": _t("integer"),
            "bbox": _nullable(_out({k: _list("number") for k in ("min", "max", "size", "center")})),
            "prim_types": {"type": "object", "additionalProperties": _t("integer")},
            "attributes": _out(
                {
                    k: {"type": "array", "items": {"type": ["object", "string"]}}
                    for k in ("point", "vertex", "prim", "detail")
                }
            ),
            "groups": _out({k: _objs() for k in ("point", "prim", "edge", "vertex")}),
            "intrinsics": _t("object"),
        },
    ),
    read_only=True,
    examples=({"path": "/obj/geo1/OUT"}, {"path": "/obj/geo1", "frame": 1}),
)

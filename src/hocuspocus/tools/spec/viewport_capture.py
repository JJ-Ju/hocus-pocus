"""Catalogue entry for ``viewport_capture`` (BIBLE §4.7)."""

from __future__ import annotations

from ._helpers import ToolSpec, _arr, _enum, _frame, _image, _list, _obj, _out, _s, _t

SPEC = ToolSpec(
    name="viewport_capture",
    description=(
        "Look at /obj, a LOP stage or a COP: a PNG (long side at most 1024), path, size, "
        "camera_used, scene. camera: OBJ or LOP camera, or camera prim (lop_path); cop_path: "
        "a Cop node's image. auto: the "
        "GUI viewer if present and no camera, else a Flipbook ROP (headless too) framed per "
        "fit. Leaves no nodes, undo step or dirty flag."
    ),
    notes=(
        "fit has no default: without it the viewer source captures the view as it is and the "
        "ROP source frames all; fit none reuses the last framing. With fit the viewer "
        "frames all or selected for the grab and puts the view back, as "
        "it does after looking through camera; context is the viewer's network, and notes say "
        "when that is not the captured scene. Without camera or lop_path the stage's display "
        "LOP is captured when /obj displays nothing; otherwise a note names it. A stage renders "
        "through the ROP's LOP source (scene: stage, lop_path). The ROP source (flipbook_rop; "
        "opengl_rop is its 1.3 name and does the same) tries the Flipbook ROP, then the "
        "deprecated OpenGL ROP, then a temporary Karma CPU ROP (2 samples, same camera and "
        "resolution): headless, a ROP whose render process crashes hands the frame to the "
        "next, a note says why, and later stage captures with source auto skip that ROP. "
        "Headless, the first Flipbook capture starts a render process (about 3 s) that later "
        "captures reuse (about 0.3 s) until it is 2 minutes idle. source_used is viewer, flipbook_rop, opengl_rop or karma. Lights are refused as "
        "cameras; camera errors list the scene's cameras. path also writes the PNG there. Both "
        "files are "
        "opaque, on the same grey as the image (the Flipbook and OpenGL ROPs write a "
        "transparent background). image.attached is true when the PNG went out as MCP image content. "
        "cop_path (a Cop node, or a COP network's display node) renders it through a "
        "temporary rop_image in its network (about 0.2 s, deleted afterwards, outside undo): "
        "scene cop, layer {layer_type, resolution, data_window}, the image at the COP's own "
        "resolution (resolution is ignored). Without camera, lop_path or cop_path a note "
        "names the COP networks under /img. lop_path naming a ROP in a LOP network "
        "(usdrender_rop, usd_rop: no output stage) captures the LOP it renders (loppath, "
        "else its input), with a note."
    ),
    input_schema=_obj(
        {
            "camera": _s(),
            "lop_path": _s(),
            "cop_path": _s(),
            "frame": _frame(),
            "resolution": _arr(
                {"type": "integer", "minimum": 16}, minItems=2, maxItems=2, default=[1024, 768]
            ),
            "fit": _enum(("all", "selected", "none")),
            "source": _enum(("auto", "viewer", "flipbook_rop", "opengl_rop"), "auto"),
            "path": _s("Also write the PNG here (must end in .png)."),
        }
    ),
    output_schema=_out(
        {
            "image": _image(),
            "path": _t("string"),
            "width": _t("integer"),
            "height": _t("integer"),
            "camera_used": _t("string"),
            "scene": _t("string"),
            "source_used": _t("string"),
            "frame": _t("number"),
            "rendered": _list("integer"),
            "also_written": _t("string"),
            "fit_used": _t("string"),
            "notes": _list(),
        },
        ("path", "width", "height"),
    ),
    # Not read_only: in the GUI the ROP source creates a temporary camera and ROP
    # (deleted afterwards, outside undo) and Houdini may mark the hip modified (§4.7).
    idempotent=True,
    examples=({}, {"camera": "/obj/cam1", "frame": 48, "source": "flipbook_rop"}),
)

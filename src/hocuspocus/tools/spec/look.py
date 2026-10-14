"""Catalogue entry for ``look`` (spec-2.0 §2.5; BIBLE §4.9, v2 profile)."""

from __future__ import annotations

from ._helpers import ToolSpec, _arr, _enum, _frame, _image, _list, _obj, _on, _out, _s, _t

SPEC = ToolSpec(
    name="look",
    description=(
        "Look at the scene: a PNG (long side at most 1024). target: an object, SOP, LOP, Cop "
        "node or ROP (default the display). quality draft is a Flipbook ROP (headless too), "
        "lit adds the scene's lights (Karma when there are none), final renders Karma. "
        "Returns backend_used, chain, scene, context, camera_used, notes. Leaves no nodes, "
        "undo step or dirty flag."
    ),
    notes=(
        "Replaces viewport_capture (2.0): the same renderers, chosen by quality. target "
        "kinds: omitted, /obj unless it displays nothing and /stage has a display LOP (a note "
        "names a stage or COP network it did not show); an object frames it (fit_used "
        "target); a SOP frames it, showing it in the render when it lacks the display flag "
        "(the flag is moved for the render only); a LOP, a LOP network (its display LOP) or "
        "a ROP in a LOP network (the LOP it renders) is a stage (scene stage, lop_path); a "
        "Cop node or COP network (its display node) is its own image at its own resolution "
        "(scene cop, layer; quality, resolution and fit do not apply); a ROP in /out looks "
        "through its camera and lends final its samples. A camera or light as target is "
        "invalid_argument: pass it as camera (an OBJ camera, a LOP camera, or a camera prim "
        "on the stage). quality draft: the Flipbook ROP, then the OpenGL ROP, then (headless, "
        "after a render process crash) a Karma CPU ROP at 2 samples. lit: the same with "
        "full lighting and shadows when the scene has lights, else Karma at 2 samples with "
        "its default light (a note says so). final: Karma at the target ROP's samples per "
        "pixel, else 32 (samples in the result); seconds, not a draft. source viewer (GUI "
        "only, draft only, never a stage or COP) grabs the Scene Viewer as the user sees it "
        "(context is the viewer's network; the view is put back); headless it is "
        "ui_required. chain is the planned order of backends; backend_used the one that "
        "drew; notes say why an earlier one did not. fit: all, selected or none (reuse the "
        "last automatic framing); without camera an automatic camera frames the target, "
        "else everything (camera_used temporary). on (v2 profile) picks the Houdini (pid, "
        "instance name or role); the bridge routes it, as for cook and render. Headless, the Flipbook and OpenGL ROPs render a "
        "snapshot of the scene in a child hython, kept warm between looks (about 0.3 s after "
        "a 3 s first start): every node, the asset libraries outside $HFS, $HIP/$JOB, global "
        "variables and hou.session; not the current take (a note says so), in-memory "
        "simulation caches (the child re-simulates to the frame) or variables set with "
        "hou.putenv. Karma and Cop images render the live scene in the host. image.attached "
        "is true when the PNG went out as MCP image content."
    ),
    input_schema=_obj(
        {
            "target": _s("Object, SOP, LOP, Cop node or ROP path."),
            "quality": _enum(("draft", "lit", "final"), "draft"),
            "camera": _s(),
            "frame": _frame(),
            "resolution": _arr(
                {"type": "integer", "minimum": 16}, minItems=2, maxItems=2, default=[1024, 768]
            ),
            "fit": _enum(("all", "selected", "none")),
            "source": _enum(("auto", "viewer"), "auto"),
            "on": _on(),
        }
    ),
    output_schema=_out(
        {
            "image": _image(),
            "backend_used": _t("string"),
            "chain": _list(),
            "quality": _t("string"),
            "target": _t(["string", "null"]),
            "scene": _t("string"),
            "context": _t("string"),
            "camera_used": _t("string"),
            "fit_used": _t("string"),
            "samples": _t("integer"),
            "frame": _t("number"),
            "path": _t("string"),
            "width": _t("integer"),
            "height": _t("integer"),
            "rendered": _list("integer"),
            "notes": _list(),
        },
        ("backend_used", "chain", "scene", "path", "width", "height"),
    ),
    # As viewport_capture: in the GUI the ROP backends make a temporary camera and ROP
    # (deleted afterwards, outside undo) and Houdini may mark the hip modified.
    idempotent=True,
    profile="v2",
    examples=(
        {},
        {"target": "/obj/geo1/scatter1", "quality": "lit", "resolution": [640, 480]},
        {"target": "/out/karma1", "quality": "final", "frame": 24},
    ),
)

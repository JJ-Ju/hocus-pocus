"""Catalogue entry for ``look`` (spec-2.0 §2.5; BIBLE §4.9)."""

from __future__ import annotations

from ._helpers import ToolSpec, _arr, _enum, _frame, _image, _list, _obj, _on, _out, _s, _t

SPEC = ToolSpec(
    name="look",
    profiles=("minimal", "core", "full"),
    description=(
        "Look at the scene: a PNG (long side at most 1024). target: an object, SOP, LOP, Cop "
        "node or ROP (default the display). quality draft is a Flipbook ROP (headless too), "
        "lit adds the scene's lights (Karma when there are none), final renders Karma. "
        "Returns backend_used, chain, scene, context, camera_used, notes. Leaves no nodes, "
        "undo step or dirty flag."
    ),
    notes=(
        "The renderer is chosen by quality. target "
        "kinds: omitted, /obj unless it displays nothing and /stage has a display LOP (a note "
        "names a stage or COP network it did not show); an object frames it (fit_used "
        "target); a SOP frames it and shows it alone (2.1): the render draws only that SOP's "
        "geometry, in its object's world space, wherever it is (inside a subnet or a locked "
        "asset, in a hidden object, outside /obj), through a temporary object in the scene "
        "that renders (headless the child's copy) with an Object Merge of it; no flag of "
        "yours moves, the object's own material is kept, a note says so, and source viewer "
        "is not isolated; a LOP, a LOP network (its display LOP) or "
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
        "drew; notes say why an earlier one did not, and which renderer lit used. resolution "
        "is honoured on every backend (Karma too; 2.1) and rendered is the image's real size "
        "(a note if a renderer drew another); without resolution, a look through an OBJ "
        "camera (camera, or a ROP target's) takes the camera's aspect at 1024 on the long "
        "side, and an explicit resolution of another aspect gets a note. fit: all, selected or none (reuse the "
        "last automatic framing); without camera an automatic camera frames the target, "
        "else everything (camera_used temporary). on picks the Houdini (pid, "
        "instance name or role); the bridge routes it, as for cook and render. Headless, the Flipbook and OpenGL ROPs render a "
        "snapshot of the scene in a child hython, kept warm between looks (about 0.3 s after "
        "a 3 s first start), with the geometry the host already cooked for what the look "
        "shows (2.1: the child draws it instead of cooking the networks again, so a slow "
        "chain costs its cook once, in the host; that first cook can take longer than the "
        "call, and a render process that runs out of time names cook and Karma in its "
        "hint). The snapshot has"
        " every node, the asset libraries outside $HFS, $HIP/$JOB, global "
        "variables and hou.session; not the current take (a note says so), in-memory "
        "simulation caches (the child re-simulates to the frame) or variables set with "
        "hou.putenv. Karma and Cop images render the live scene in the host. image.attached "
        "is true when the PNG went out as MCP image content. output (2.1) also writes the "
        "image to that file, at its rendered size, flattened onto grey: PNG, or JPEG for "
        ".jpg/.jpeg; $HIP and ~ expand, parent folders are made, an existing file is "
        "replaced, and a path outside approved_roots is path_not_allowed before anything "
        "renders. The result's output is the absolute path; the image is still returned "
        "inline (path is the copy under the state dir, which keeps only the newest 50)."
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
            "output": _s("Also save the image to this .png or .jpg file."),
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
            "output": _t("string"),
            "notes": _list(),
        },
        ("backend_used", "chain", "scene", "path", "width", "height"),
    ),
    # In the GUI the ROP backends make a temporary camera and ROP
    # (deleted afterwards, outside undo) and Houdini may mark the hip modified.
    idempotent=True,
    examples=(
        {},
        {"target": "/obj/geo1/scatter1", "quality": "lit", "resolution": [640, 480]},
        {"target": "/out/karma1", "quality": "final", "frame": 24, "output": "$HIP/f24.png"},
    ),
)

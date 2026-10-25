"""Catalogue entry for ``render`` (BIBLE §4.7)."""

from __future__ import annotations

from ._helpers import (
    _JOB_STATES,
    ToolSpec,
    _arr,
    _b,
    _image,
    _list,
    _n,
    _obj,
    _objs,
    _on,
    _out,
    _s,
    _t,
)

SPEC = ToolSpec(
    name="render",
    profiles=("core", "full"),
    description=(
        "Render any ROP (Karma, Flipbook, USD, ...) or writer SOP (File Cache, rop_geometry) "
        "for frames [start, end, inc] (default the ROP's own frame range), optionally "
        "overriding output. Waits up to wait_s (default the job threshold): if done, returns "
        "outputs, a thumbnail and notes; else job_id to poll with job."
    ),
    notes=(
        "Above 5 outputs the result, inline or from job result, has outputs_summary and "
        "outputs_sample (the first 2 and last 2) instead of outputs; the summary is {count, "
        "pattern, missing_count}, its first and last being the sample's ends (2.1, D67), while a "
        "cancelled job's partial summary also names first and last; missing lists up to 20 "
        "paths. Every "
        "expected output is checked against approved_roots. look is the quick picture."
        " Headless, a Flipbook or OpenGL ROP renders in a short-lived child hython (a few "
        "seconds to start), since a second viewport render can crash the host; so does a "
        "Karma or USD Render ROP (2.1, D74), on a snapshot of the scene, so Houdini's main "
        "thread stays free for other calls while husk renders (the scene re-cooks in the "
        "child; a take other than the root and a simulation held only in memory are not "
        "carried, and a note says so). In a GUI session every ROP renders in Houdini itself."
        " notes warn when the scene has no lights, when the thumbnail (as sent, flattened onto "
        "grey) is nearly black, and when every pixel is transparent (empty), "
        "and say why an image output has no thumbnail (an extension it cannot read). "
        "thumbnail.image.attached is true when the image went out as MCP image content. The "
        "thumbnail is inline only, flattened onto grey; the ROP's own output files are left as "
        "written, alpha included. USD render ROPs (Lop usdrender_rop, Driver usdrender): "
        "outputs come from outputimage, else the RenderProduct productName of the render "
        "settings the ROP uses (EXR thumbnails too), never lopoutput; output overrides "
        "outputimage; a note says when nothing resolves; a husk failure carries the end of "
        "its log in detail.log_tail. Without frames a ROP or writer SOP (File Cache, "
        "rop_geometry or rop_alembic SOP) renders its own Valid Frame Range, or the current "
        "frame when set to Render Current Frame; a note says which. A File Cache renders "
        "through the ROP inside it (no output override), then turns on Load from Disk as its "
        "Save to Disk button does (side_effects: {parm: [old, new]}). A cancelled render's "
        "job result is the cancelled error with detail {last_status, partial: "
        "{outputs_summary}} (the files written before the cancel). A Cop node is not a ROP: "
        "the error's candidates are the rop_image nodes in its network (look with it as "
        "target shows it). A COP image needs no lights, so no lights note. A thumbnail "
        "PIL cannot read (a float TIFF) is converted with iconvert; if that fails too, a note "
        "says why. A ROP whose output is one file for the range (USD layer, Alembic archive, "
        "a path without $F) renders it in one call (a cancel waits for its end) and is read "
        "back: a USD layer set or Alembic archive with fewer frames than asked fails with "
        "cook_failed; a USD export without time samples gets a static-stage note. outputs "
        "lists each file once; a USD export adds layers: [{path, bytes, time_samples, "
        "time_codes?}], its root layer, every layer file it composes (a sopimport save path) "
        "and USD files the render wrote beside it, at most 20. A layer another USD ROP "
        "also writes (the same lopoutput, or a sopimport save path both export) gets "
        "shared_with [ROPs] and a note; one whose time samples this render replaced with "
        "fewer, or with a range not covering the old one, gets overwrote_samples (the old "
        "count) and a first note naming both counts. camera overrides the ROP's "
        "camera for this render (restored afterwards): an OBJ camera for its camera parm, a "
        "camera prim for a ROP reading a stage (cameraprim) or a USD render ROP "
        "(override_camera). A ROP whose camera parm names a missing node fails with "
        "node_not_found naming the parm, the scene's cameras as candidates. On a Flipbook or "
        "OpenGL ROP a camera that does not fit opsource (a prim or camera LOP at obj, an OBJ "
        "camera at lop) is invalid_argument naming opsource; an override adds a note "
        "(Rendered through <camera> (<parm> restored).). "
        "(2.0, spec-2.0 §2.5) on runs this call on another Houdini without moving the pin: a pid, a name (houdini_connect {pid, name}) or a role (editor or worker; the least busy live one, by jobs_running then busy). The result's _meta.instance names it and its job is recorded against it. A pid or name the bridge remembers that has exited is instance_lost, one it never knew houdini_offline with the candidates; a role nobody has is houdini_offline. Without on the call goes to the pinned or selected Houdini as always."
    ),
    input_schema=_obj(
        {
            "rop_path": _s(),
            "frames": _arr(
                {"type": "number"}, "[start, end] or [start, end, inc]", minItems=2, maxItems=3
            ),
            "output": _s("Output path override."),
            "camera": _s(),
            "wait_s": _n(None, minimum=0),
            "thumbnail": _b(True),
            "on": _on(),
        },
        ("rop_path",),
    ),
    output_schema=_out(
        {
            "job_id": _t("string"),
            "state": {"type": "string", "enum": _JOB_STATES},
            "rop_path": _t("string"),
            "frames": _list("number"),
            "outputs": _list(),
            "outputs_summary": _t("object"),
            "missing": _list(),
            "layers": _objs(),
            "thumbnail": _out(
                {
                    "path": _t("string"),
                    "width": _t("integer"),
                    "height": _t("integer"),
                    "image": _image(),
                }
            ),
            "notes": _list(),
        },
        ("job_id", "state"),
    ),
    examples=(
        {"rop_path": "/out/karma1"},
        {"rop_path": "/out/karma1", "frames": [1, 24], "wait_s": 0},
    ),
)

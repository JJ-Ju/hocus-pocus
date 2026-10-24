"""``look`` (spec-2.0 §2.5): one tool for a picture of the scene, the backend chosen from a
``quality`` level.

``{target?, quality: draft | lit | final, camera?, frame?, resolution?, fit?, source?,
output?}``
resolves ``target`` into a kind (:mod:`hocuspocus.host.look.spec`), asks the policy
(:func:`hocuspocus.host.look.select.plan`) for a chain of backends, renders along it
(:mod:`hocuspocus.host.look.run`) and returns the
image plus ``{backend_used, chain, quality, target, scene, context, camera_used, fit_used,
frame, path, width, height, rendered, notes, output?}``. ``on`` is the bridge's: it routes the
call to an instance and is ignored here.

Registered with ``scene=False`` (a look leaves no nodes, undo step
or dirty flag; its temporary nodes are made outside undo) and ``main_thread=False``
(headless, the child hython renders while the main thread stays free).
"""

from __future__ import annotations

from typing import Any

from ..dispatch import call_timeout
from ..look import run, select
from ..look.base import ROP_LABELS
from ..look.cop import cop_size
from ..look.image import finish_capture, image_size
from ..look.spec import (
    ISOLATED_NOTE,
    VIEWER_SOP_NOTE,
    LookSpec,
    parse_look_args,
    resolve_target,
)
from .registry import HostContext, tool

LABELS = {**ROP_LABELS, "viewer": "Scene Viewer"}


def _context(target: dict[str, Any]) -> str | None:
    """The network the picture shows: ``/obj``, the LOP network, the COP network."""
    if target["scene"] == "obj":
        return "/obj"
    if target["scene"] == "stage":
        return target["lop"].parent().path()
    path = target.get("cop") or ""
    return path.rsplit("/", 1)[0] or "/"


def _finish(spec: LookSpec, used: str, plan: select.Plan, info: dict[str, Any]) -> dict[str, Any]:
    job = spec.prepared
    assert job is not None
    notes = [*plan.notes, *info.pop("notes", [])]
    if spec.kind == "sop" and used != "rop_image":
        note = VIEWER_SOP_NOTE if used == "viewer" else ISOLATED_NOTE
        notes.append(note.format(sop=spec.target))
    if spec.quality == "lit" and used in ("flipbook", "opengl"):
        notes.append(select.LIT_VIEWPORT_NOTE.format(rop=LABELS[used]))
    size = cop_size(info) if used == "rop_image" else job.res
    if used != "rop_image":
        # Review 26 P1 #5: rendered is the image's real size; say when it is not the one asked.
        actual = image_size(job.out_file)
        if actual is not None and actual != tuple(job.res):
            notes.append(
                f"The {LABELS.get(used, used)} rendered {actual[0]}x{actual[1]}, not the "
                f"{job.res[0]}x{job.res[1]} asked."
            )
            size = actual
    context = info.pop("context", None) or _context(job.target)
    out: dict[str, Any] = {
        "backend_used": used,
        "chain": list(plan.chain),
        "quality": spec.quality,
        "target": spec.target,
        **info,
        "context": context,
    }
    if notes:
        out["notes"] = notes
    # output (2.1): the flattened capture at its rendered size, also written there (PNG
    # or JPEG); the image is still returned inline (BIBLE §8: never only a path).
    return finish_capture(job.out_file, size, job.frame, out, job.extra_path)


@tool("look", scene=False, main_thread=False)
def look(args: dict[str, Any], ctx: HostContext) -> dict[str, Any]:
    spec = parse_look_args(args)
    timeout_s = float(call_timeout(None) or ctx.config.default_timeout_s)
    return run.execute(
        spec, ctx, timeout_s, resolve=resolve_target, choose=select.plan, finish=_finish
    )

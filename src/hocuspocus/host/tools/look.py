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

from hocuspocus.tools.errors import ToolError

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


LOOK_JOB_TIMEOUT_S = 3600.0
"""How long a look may run as a job (2.1, D75): a final Karma look at 1024x768 took more
than the 30 s a call waits (2.0-vs-2.1 comparison runs)."""


def _wait_s(args: dict[str, Any], ctx: HostContext) -> float:
    wait = args.get("wait_s")
    if wait is None:
        return float(ctx.config.job_threshold_s)
    if isinstance(wait, bool) or not isinstance(wait, int | float) or wait < 0:
        raise ToolError("invalid_argument", "'wait_s' must be a number >= 0.")
    return float(wait)


@tool("look", scene=False, main_thread=False)
def look(args: dict[str, Any], ctx: HostContext) -> dict[str, Any]:
    """Runs as a job (2.1, D75): the call waits ``wait_s`` (default ``job_threshold_s``)
    and returns the picture, or ``{job_id, state: "running"}`` whose ``job result`` is the
    picture, as ``render`` does. A call on Houdini's main thread itself runs inline."""
    spec = parse_look_args(args)
    wait_s = _wait_s(args, ctx)

    def picture(timeout_s: float) -> dict[str, Any]:
        return run.execute(
            spec, ctx, timeout_s, resolve=resolve_target, choose=select.plan, finish=_finish
        )

    if getattr(ctx, "jobs", None) is None or ctx.executor.on_main_thread():
        return picture(float(call_timeout(None) or ctx.config.default_timeout_s))
    job = ctx.jobs.start(
        "look", lambda _job: picture(LOOK_JOB_TIMEOUT_S), label=spec.target or "the display"
    )
    job.message = f"look {spec.quality}: rendering"
    job.done_event.wait(wait_s)
    if job.state == "done":
        ctx.jobs.discard(job.id)
        return job.result
    if job.state in ("failed", "cancelled") and job.error:
        ctx.jobs.discard(job.id)
        raise ToolError.from_dict(job.error)
    status = job.status()
    status["hint"] = (
        "Poll with job {action: 'status' | 'result', job_id}; the result is the picture."
    )
    return status

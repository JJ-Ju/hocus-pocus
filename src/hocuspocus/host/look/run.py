"""Running a look: resolve and plan on the main thread, render along the chain, write
the PNG, for ``look`` (``host/tools/look.py``).

Threads, as in 1.4: in a GUI session the whole call is one main-thread step (the
backends render in-process). Headless, :func:`prepare` is one short main-thread step
(resolve, frame, snapshot) and the chain runs on the request thread, so a child hython
renders without holding the main thread; Karma hops back to it. A call already on the
main thread runs everything inline.
"""

from __future__ import annotations

import shutil
import tempfile
import time
from collections.abc import Callable
from typing import Any

from hocuspocus.tools.errors import ToolError

from . import select
from .base import Env, LookResult, add_notes, on_main
from .spec import LookSpec, Prepared

CHILD_BACKENDS = frozenset({"flipbook", "opengl"})


def gather_env(ctx: Any, *, lights: bool = False) -> Env:
    """What the policy needs to know about this Houdini. Main thread."""
    from .framing import scene_has_lights
    from .viewer import _scene_viewer

    return Env(
        ui=bool(ctx.ui),
        rops=frozenset(select.available_capture_rops()),
        viewer=bool(ctx.ui) and _scene_viewer() is not None,
        lights=scene_has_lights() if lights else False,
    )


def prepare(
    spec: LookSpec,
    ctx: Any,
    resolve: Callable[[LookSpec], dict[str, Any]],
    choose: Callable[[LookSpec, Env], select.Plan],
    tmp_dir: str,
    deadline: float,
) -> tuple[Prepared, select.Plan]:
    """Resolve the target, plan the chain, pick the output file and, headless, snapshot
    the scene for a child. Main thread."""
    from . import child
    from .framing import _capture_spec
    from .image import capture_targets

    target = resolve(spec)
    if spec.kind is None:
        spec.kind = "lop" if target["scene"] == "stage" else "obj"
    plan = choose(spec, gather_env(ctx, lights=spec.quality == "lit"))
    frame, extra_path, out_file = capture_targets(spec.parsed(), ctx)
    job = Prepared(
        target=target,
        frame=frame,
        res=spec.res,
        out_file=out_file,
        extra_path=extra_path,
        tmp_dir=tmp_dir,
        samples=plan.samples,
        deadline=deadline,
    )
    if plan.chain[0] not in ("viewer", "rop_image"):
        fit = spec.fit
        if not spec.fit_given and target.get("focus"):
            fit = "target"
        job.capture, job.info = _capture_spec(target, spec.res, fit, out_file, ctx.scene.generation)
        job.capture["rop_parms"].update(plan.rop_parms)
        if target.get("isolate"):
            job.capture["isolate"] = dict(target["isolate"])
        if not ctx.ui and CHILD_BACKENDS & set(plan.chain):
            # /obj: the child draws the geometry the host cooked (review 26 P2).
            obj = target["scene"] == "obj"
            job.snapshot = child.snapshot_scene(
                tmp_dir,
                frame=frame if obj else None,
                isolate=job.capture.get("isolate") if obj else None,
            )
    return job, plan


def run_chain(
    spec: LookSpec, ctx: Any, chain: tuple[str, ...]
) -> tuple[str, LookResult, list[str]]:
    """Render along ``chain``: ``(backend used, its result, chain notes)``."""
    table = select.backends()
    if chain[0] in ("viewer", "rop_image") or len(chain) == 1:
        return chain[0], table[chain[0]].render(spec, ctx), []
    if not ctx.ui:
        results: dict[str, LookResult] = {}

        def render_rop(rop_type: str) -> dict[str, Any]:
            results[rop_type] = table[rop_type].render(spec, ctx)
            return {"notes": results[rop_type].notes}

        def render_karma() -> None:
            results["karma"] = table["karma"].render(spec, ctx)

        used, _, notes = select.run_capture_chain(
            list(chain),
            stage=spec.kind == "lop",
            source="auto",
            render_rop=render_rop,
            render_karma=render_karma,
        )
        return used, results.get(used, LookResult()), notes
    # GUI: in-process. A ROP that renders no image hands over to the next viewport ROP; a
    # crash here would take Houdini down, so there is no crash fallback (and no Karma).
    failures: list[tuple[str, str]] = []
    rops = [t for t in chain if t != "karma"]
    for i, rop_type in enumerate(rops):
        try:
            result = table[rop_type].render(spec, ctx)
        except ToolError as exc:
            if exc.code != "cook_failed" or i == len(rops) - 1:
                raise
            failures.append((rop_type, f"produced no image ({exc.message})"))
            continue
        note = select.fallback_note(failures, rop_type)
        return rop_type, result, [note] if note else []
    raise ToolError("internal", "This Houdini has neither a Flipbook ROP nor an OpenGL ROP.")


def execute(
    spec: LookSpec,
    ctx: Any,
    timeout_s: float,
    *,
    resolve: Callable[[LookSpec], dict[str, Any]],
    choose: Callable[[LookSpec, Env], select.Plan],
    finish: Callable[[LookSpec, str, select.Plan, dict[str, Any]], dict[str, Any]],
) -> dict[str, Any]:
    """One look, on the threads described in the module docstring. ``finish`` turns the
    merged ``info`` into the tool's result (and writes the PNG out)."""
    if ctx.ui and not ctx.executor.on_main_thread():
        return ctx.executor.run(
            lambda: execute(spec, ctx, timeout_s, resolve=resolve, choose=choose, finish=finish),
            timeout_s,
        )
    deadline = time.monotonic() + timeout_s
    tmp_dir = tempfile.mkdtemp(prefix="hp-render-")
    try:
        job, plan = on_main(
            ctx, lambda: prepare(spec, ctx, resolve, choose, tmp_dir, deadline), timeout_s
        )
        spec.prepared = job
        used, result, chain_notes = run_chain(spec, ctx, plan.chain)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
    info = dict(job.info)
    info.update(result.info)
    target_note = job.target.get("note")
    if ctx.ui:
        notes = [*job.held.get("notes", []), *result.notes, *chain_notes, target_note]
    else:
        notes = [target_note, *result.notes, *chain_notes]
    info.pop("notes", None)
    add_notes(info, *job.info.get("notes", []), *result.info.get("notes", []), *notes)
    return finish(spec, used, plan, info)

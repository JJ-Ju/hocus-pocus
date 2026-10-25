"""``edit``: one transaction for every kind of scene change (spec-2.0 §2.4, BIBLE §4.5).

The tool is a thin front end of the transaction engine (``host/tx.py``): it parses
``ops`` into a plan and runs it inside the one undo group the dispatcher opens
(``HocusPocus: edit <n> ops``). Validation is the run (BIBLE D56): each op is checked
against the scene the earlier ops left, a failing op is reverted and the rest are checked
too, then the whole call is compensated and every problem raised at once. ``dry_run``
runs the plan in check mode and compensates it (no undo step, no dirty flag, no event,
allowed in read-only mode: ``_changed: false``). ``partial: true`` keeps what worked,
``partial: "stop"`` the ops before the first failure (D57).

The echo cooks the touched nodes after the main-thread work (D58): as a job of one
main-thread step per slice of nodes, which the call waits on for up to
``job_threshold_s``; a cook that outlasts it leaves its rows ``cook_state: "cooking"`` and
the result a ``job_id`` whose result is those rows.
"""

from __future__ import annotations

import threading
import time
from typing import Any

from .. import tx
from ..dispatch import AFTER_KEY, after_allowed
from ._common import arg_bool
from .registry import HostContext, tool

CHANGED_KEY = "_changed"

COOK_SLICE_S = 0.25
"""A cook job step cooks nodes until this much time has passed (at least one node), so a
build of small nodes costs a few main-thread hand-offs, not one per node."""

COOK_STEP_TIMEOUT_S = 24 * 3600.0
"""Main-thread budget of one cook step (a cook cannot be interrupted)."""


@tool("edit")
def edit(args: dict[str, Any], ctx: HostContext) -> dict[str, Any]:
    dry_run = arg_bool(args, "dry_run", False)
    partial = tx.partial_mode(args)
    mode = tx.return_mode(args)
    plan = tx.parse_ops(args.get("ops"), partial=partial)
    if dry_run:
        rows = tx.dry_run(plan, ctx)
        return {"dry_run": True, "ops": len(plan.ops), "plan": rows, CHANGED_KEY: False}
    result = tx.execute(plan, ctx)
    targets = tx.cook_targets(result)
    deferred = bool(targets) and _can_defer(ctx)
    out = tx.echo(result, mode, pending=[sid for sid, _ in targets] if deferred else ())
    tx.watch(node for node, _cook in result.touched())
    if deferred:
        out[AFTER_KEY] = lambda done, remaining: _cook_after(
            ctx, result, targets, mode, done, remaining
        )
    return out


def _can_defer(ctx: HostContext) -> bool:
    """Cooks move off the call's main-thread work when a job can run them: not when the
    call itself came in on the main thread (a GUI shell, in-process tests)."""
    return getattr(ctx, "jobs", None) is not None and after_allowed()


class _Cooks:
    """What the cook job has cooked, shared with the call that waits on it."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.rows: dict[int, dict[str, Any]] = {}
        """Session id -> the node's row after its cook (``tx.node_block``)."""
        self.handed_off = False
        """True once the call returned without waiting for the rest."""
        self.later: list[int] = []
        """Session ids cooked after the hand-off: the job's result."""


def _cook_after(
    ctx: HostContext,
    result: tx.Result,
    targets: list[tuple[int, Any]],
    mode: str,
    out: dict[str, Any],
    remaining: float,
) -> dict[str, Any]:
    """The dispatcher's after-step (D58): cook ``targets`` as a job, wait up to
    ``job_threshold_s`` (within the call's timeout), and fill in the rows."""
    cooks = _Cooks()
    total = len(targets)
    label = targets[0][1].path() if total == 1 else f"edit: {total} nodes"

    def work(job: Any) -> dict[str, Any]:
        index = 0
        while index < total:
            batch = job.run_main(
                lambda start=index: _cook_slice(targets, start, mode, cooks), COOK_STEP_TIMEOUT_S
            )
            index += max(1, batch)
            job.set_progress(index, total)
        with cooks.lock:
            later = [cooks.rows[sid] for sid in cooks.later if sid in cooks.rows]
        return {"nodes": later}

    job = ctx.jobs.start("cook", work, label=label)
    wait = max(0.0, min(float(ctx.config.job_threshold_s), remaining))
    finished = job.done_event.wait(wait)
    with cooks.lock:
        cooks.handed_off = True
        cooked = dict(cooks.rows)
    tx.patch_rows(out, result.rows, cooked, collapse=mode != "full")
    if finished:
        ctx.jobs.discard(job.id)
        if job.state != "done" and job.error:
            out.setdefault("notes", []).append(
                f"Cooking the nodes failed: {job.error.get('message')}"
            )
        return out
    pending = total - len(cooked)
    out["job_id"] = job.id
    out["state"] = "running"
    out["message"] = (
        f"The edit is applied; cooking {pending} of its nodes outlasted {wait:g} s and goes on "
        f"as a job: their rows say cook_state cooking, and job {{action: result, job_id: "
        f"{job.id}}} returns them."
    )
    return out


def _cook_slice(targets: list[tuple[int, Any]], start: int, mode: str, cooks: _Cooks) -> int:
    """Main thread: cook ``targets[start:]`` until :data:`COOK_SLICE_S` has passed; return
    how many were cooked (deleted nodes count, uncooked)."""
    began = time.perf_counter()
    count = 0
    for sid, node in targets[start:]:
        count += 1
        if tx._session_id(node) is not None:  # a later call may have deleted it
            row = tx.node_block(node, tx.node_problems(node, True), mode)
            with cooks.lock:
                cooks.rows[sid] = row
                if cooks.handed_off:
                    cooks.later.append(sid)
        if time.perf_counter() - began >= COOK_SLICE_S:
            break
    return count

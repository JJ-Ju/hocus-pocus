"""``pdg``: cook, inspect, cancel and dirty a TOP node or TOP network.

See docs/BIBLE.md §4.7 and §7. ``top_path`` is a TOP node or a TOP network; for a
network, ``cook`` cooks its display node, ``status``/``workitems`` aggregate every TOP
in it, ``dirty`` dirties the whole graph and ``cancel`` cancels the graph's cook.

Registered off the main thread (like ``cook``) so each action decides how to reach
``hou``: short actions are one executor call. ``cook`` always starts the cook in the
background (``cookWorkItems(block=False)``) and runs a job that polls the node with short
main-thread steps until the graph stops cooking, so the main thread is never held for
the length of a cook. With ``block: false`` the call returns the job at once; with
``block: true`` it waits ``min(timeout_s, job_threshold_s)`` (the call's effective
timeout, as ``cook`` does) and returns the result, or ``{job_id, state: "running"}``.
Cancelling the job cancels the cook. No undo group: PDG work items are not hip state;
``cook``, ``dirty`` and ``cancel`` are still refused in read-only mode.
"""

from __future__ import annotations

import time
from typing import Any

from hocuspocus.tools.errors import ToolError

from ..dispatch import call_timeout
from ._diag import a_or_an
from .nodes import bad_arg, get_node, page
from .registry import HostContext, tool

ACTIONS = ("cook", "status", "workitems", "cancel", "dirty")
POLL_S = 0.1
JOB_POLL_TIMEOUT_S = 30.0
START_GRACE_S = 2.0
"""How long the job waits for a graph that shows neither cooking nor work items before
it accepts that the cook produced nothing (right after ``cookWorkItems(block=False)``
the graph can still look idle)."""
OUTPUT_FILE_CAP = 20
ERROR_CAP = 5


# -- node resolution --------------------------------------------------------------------


def _is_top_network(node: Any) -> bool:
    import hou

    try:
        return node.childTypeCategory() == hou.topNodeTypeCategory()
    except Exception:
        return False


def resolve_top(path: Any) -> Any:
    import hou

    node = get_node(path, field="top_path")
    if not isinstance(node, hou.TopNode) and not _is_top_network(node):
        raise ToolError(
            "invalid_argument",
            f"{node.path()} is {a_or_an(node.type().category().name())} node, not a TOP node or "
            "network.",
            hint="Pass a TOP node (e.g. /obj/topnet1/ropfetch1) or a TOP network path.",
        )
    return node


def _cook_target(node: Any) -> Any:
    if not _is_top_network(node):
        return node
    display = node.displayNode()
    if display is None:
        raise ToolError(
            "invalid_argument",
            f"TOP network {node.path()} has no display node to cook.",
            hint="Set the display flag on the TOP node to cook, or pass that node's path.",
        )
    return display


def _tops(node: Any) -> list[Any]:
    """The TOP nodes ``node`` stands for (itself, or a network's TOP children)."""
    import hou

    if not _is_top_network(node):
        return [node]
    return [
        child
        for child in node.children()
        if isinstance(child, hou.TopNode) and not child.type().name().endswith("scheduler")
    ]


# -- reading state ----------------------------------------------------------------------


def _snake(name: str) -> str:
    out = []
    for i, ch in enumerate(name):
        if ch.isupper() and i:
            out.append("_")
        out.append(ch.lower())
    return "".join(out)


def _cook_state(top: Any) -> str:
    try:
        return _snake(top.getCookState(False).name())
    except Exception:
        return "unknown"


def _is_cooking(top: Any) -> bool:
    try:
        pdg_node = top.getPDGNode()
        if pdg_node is not None and pdg_node.context.cooking:
            return True
    except Exception:
        pass
    return _cook_state(top) in ("cooking", "waiting")


def _node_status(top: Any) -> dict[str, Any]:
    # Counted from the PDG node's work items: hou.TopNode.workItemStates() is a cached
    # UI count that lags behind dirty/cancel until PDG events are processed.
    pdg_node = top.getPDGNode()
    items = list(pdg_node.workItems) if pdg_node is not None else []
    states: dict[str, int] = {}
    for item in items:
        key = _snake(item.state.name)
        states[key] = states.get(key, 0) + 1
    row: dict[str, Any] = {
        "path": top.path(),
        "cook_state": _cook_state(top),
        "states": dict(sorted(states.items())),
        "total": len(items),
        "cooked": states.get("cooked_success", 0) + states.get("cooked_cache", 0),
        "failed": states.get("cooked_fail", 0),
    }
    errors = [str(e).strip() for e in top.errors() if str(e).strip()]
    if errors:
        row["errors"] = errors[:ERROR_CAP]
    warnings = [str(w).strip() for w in top.warnings() if str(w).strip()]
    if warnings:
        row["warnings"] = warnings[:ERROR_CAP]
    return row


def status_block(node: Any) -> dict[str, Any]:
    if not _is_top_network(node):
        out = _node_status(node)
        out["cooking"] = _is_cooking(node)
        return out
    rows = [_node_status(top) for top in _tops(node)]
    totals: dict[str, int] = {}
    for row in rows:
        for key, n in row["states"].items():
            totals[key] = totals.get(key, 0) + n
    return {
        "path": node.path(),
        "cooking": any(_is_cooking(top) for top in _tops(node)),
        "states": totals,
        "total": sum(r["total"] for r in rows),
        "cooked": sum(r["cooked"] for r in rows),
        "failed": sum(r["failed"] for r in rows),
        "nodes": rows,
    }


def _work_item_row(item: Any, owner: str | None) -> dict[str, Any]:
    files = [f.path for f in item.outputFiles]
    row: dict[str, Any] = {
        "id": int(item.id),
        "name": item.name,
        "index": int(item.index),
        "state": _snake(item.state.name),
        "output_files": files[:OUTPUT_FILE_CAP],
    }
    if len(files) > OUTPUT_FILE_CAP:
        row["output_files_total"] = len(files)
    if owner is not None:
        row["node"] = owner
    return row


def work_items(node: Any) -> list[dict[str, Any]]:
    network = _is_top_network(node)
    rows: list[dict[str, Any]] = []
    for top in _tops(node):
        pdg_node = top.getPDGNode()
        if pdg_node is None:
            continue
        items = sorted(pdg_node.workItems, key=lambda w: (w.index, w.id))
        rows.extend(_work_item_row(item, top.path() if network else None) for item in items)
    return rows


# -- actions ----------------------------------------------------------------------------


def _cook_now(path: str, block: bool) -> str:
    """Start (or, with ``block``, run) the cook of ``path``'s target. Main thread."""
    target = _cook_target(resolve_top(path))
    target.cookWorkItems(block=block)
    return target.path()


def _cancel(path: str) -> dict[str, Any]:
    node = resolve_top(path)
    node.cancelCook()
    return status_block(node)


def _dirty(path: str) -> dict[str, Any]:
    node = resolve_top(path)
    if _is_top_network(node):
        node.dirtyAllWorkItems(False)
    else:
        node.dirtyWorkItems(False)
    return status_block(node)


def _start_cook_job(
    ctx: HostContext, path: str, timeout_s: float, wait_s: float = 0.0
) -> dict[str, Any]:
    target = ctx.executor.run(lambda: _cook_now(path, False), timeout_s)

    def poll() -> dict[str, Any]:
        node = resolve_top(target)
        return {"cooking": _is_cooking(node), "status": status_block(node)}

    def work(job: Any) -> dict[str, Any]:
        began = time.monotonic()
        seen = False
        try:
            while True:
                job.check_cancelled()
                snapshot = job.run_main(poll, JOB_POLL_TIMEOUT_S)
                status = snapshot["status"]
                total = status.get("total") or 0
                seen = seen or snapshot["cooking"] or total > 0
                if total:
                    done = (
                        status["cooked"]
                        + status["failed"]
                        + status["states"].get("cooked_cancel", 0)
                    )
                    job.progress(done / total, f"{done}/{total} work items finished")
                idle = not snapshot["cooking"]
                if idle and (seen or time.monotonic() - began > START_GRACE_S):
                    return {"path": target, "ok": status["failed"] == 0, "status": status}
                time.sleep(POLL_S)
        except ToolError as exc:
            if exc.code == "cancelled":
                ctx.executor.run(lambda: resolve_top(target).cancelCook(), JOB_POLL_TIMEOUT_S)
            raise

    started = ctx.jobs.start("pdg", work, label=target)
    if wait_s > 0 and started.done_event.wait(wait_s):
        # Returned synchronously: the caller never saw a job_id, so keep job list clean.
        ctx.jobs.discard(started.id)
        if started.state == "done":
            return started.result
        raise ToolError.from_dict(started.error or {"code": "internal", "message": "cook failed"})
    return {
        "job_id": started.id,
        "state": "running",
        "path": target,
        "message": (
            f"Cooking {target} in the background; poll with job {{action: status, job_id: "
            f"{started.id}}} and fetch the result with action result."
        ),
    }


@tool("pdg", main_thread=False, scene=False)
def pdg_tool(args: dict[str, Any], ctx: HostContext) -> dict[str, Any]:
    action = args.get("action")
    if action not in ACTIONS:
        raise bad_arg(f"'action' must be one of {', '.join(ACTIONS)}.")
    path = args.get("top_path")
    if not isinstance(path, str) or not path:
        raise bad_arg("'top_path' must be a TOP node or TOP network path.")
    block = args.get("block", False)
    if not isinstance(block, bool):
        raise bad_arg("'block' must be a boolean.")
    timeout_s = float(ctx.config.default_timeout_s)
    raw_timeout = args.get("timeout_s")
    if (
        isinstance(raw_timeout, int | float)
        and not isinstance(raw_timeout, bool)
        and raw_timeout > 0
    ):
        timeout_s = float(raw_timeout)
    else:
        # The request-level timeout (the dispatcher's effective timeout).
        timeout_s = float(call_timeout(timeout_s) or timeout_s)
    if action in ("cook", "dirty", "cancel") and ctx.config.read_only:
        raise ToolError(
            "read_only",
            f"pdg {action} changes work items, and the host is in read-only mode.",
            hint="Use action status or workitems, or set read_only = false and restart the host.",
        )

    def run(fn: Any) -> Any:
        if ctx.executor.on_main_thread():
            return fn()
        return ctx.executor.run(fn, timeout_s)

    if action == "status":
        return run(lambda: status_block(resolve_top(path)))
    if action == "workitems":
        limit, cursor = args.get("limit"), args.get("cursor")

        def items() -> dict[str, Any]:
            node = resolve_top(path)
            rows = work_items(node)
            chunk, nxt = page(rows, limit, cursor)
            out: dict[str, Any] = {"path": node.path(), "work_items": chunk, "total": len(rows)}
            if nxt is not None:
                out["next_cursor"] = nxt
            return out

        return run(items)
    if action == "cancel":
        return run(lambda: _cancel(path))
    if action == "dirty":
        return run(lambda: _dirty(path))

    # cook
    if ctx.executor.on_main_thread():
        # Called inline on the main thread (GUI shell, tests): no job can make progress.
        target = _cook_now(path, True)
        status = status_block(resolve_top(target))
        return {"path": target, "ok": status["failed"] == 0, "status": status}
    wait_s = min(timeout_s, float(ctx.config.job_threshold_s)) if block else 0.0
    return _start_cook_job(ctx, path, timeout_s, wait_s)

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

import contextlib
import os
import re
import time
from typing import Any

from hocuspocus.tools.errors import ToolError

from ..dispatch import call_timeout
from . import events
from ._common import bad_arg, get_node, page, refuse_if_read_only
from ._diag import a_or_an
from .hip import check_allowed
from .registry import HostContext, tool
from .session import scene_dirty

ACTIONS = ("cook", "status", "workitems", "cancel", "dirty")
POLL_S = 0.1
JOB_POLL_TIMEOUT_S = 30.0
START_GRACE_S = 2.0
"""How long the job waits for a graph that shows neither cooking nor work items before
it accepts that the cook produced nothing (right after ``cookWorkItems(block=False)``
the graph can still look idle)."""
CANCEL_WAIT_S = 10.0
"""How long pdg cancel waits for the cook (and its job) to stop before it reports."""
OUTPUT_FILE_CAP = 20
ATTRIB_VALUES_CAP = 20
ERROR_CAP = 5
FAILURES_CAP = 5
"""Failed work items listed in a cook result (review 14 papercut 1)."""
ITEM_ERROR_CHARS = 400
LOG_TAIL_BYTES = 64 * 1024
_STAMP = re.compile(r"^\[\d{1,2}:\d{2}:\d{2}(?:\.\d+)?\]\s*")
_EXIT_CODE = re.compile(r"exit code\s*=?\s*(-?\d+)", re.IGNORECASE)
_ERROR_LINE = re.compile(
    r"\berror\b|^[\w.]*(?:Error|Exception|Interrupt|Exit)\b.*:|\bfailed\b", re.IGNORECASE
)


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


def _finished(top: Any) -> tuple[int, int, int]:
    """(finished, total, cancelled) work items of one TOP node."""
    pdg_node = top.getPDGNode()
    items = list(pdg_node.workItems) if pdg_node is not None else []
    finished = cancelled = 0
    for item in items:
        state = _snake(item.state.name)
        if state in ("cooked_success", "cooked_cache", "cooked_fail", "cooked_cancel"):
            finished += 1
        if state == "cooked_cancel":
            cancelled += 1
    return finished, len(items), cancelled


def pdg_state(top: Any) -> dict[str, int]:
    """``node_info``'s ``pdg_state`` for a TOP node: cooked, failed and total items."""
    pdg_node = top.getPDGNode()
    items = list(pdg_node.workItems) if pdg_node is not None else []
    states = [_snake(item.state.name) for item in items]
    return {
        "cooked": sum(state in ("cooked_success", "cooked_cache") for state in states),
        "failed": states.count("cooked_fail"),
        "total": len(items),
    }


def failed_items_problem(top: Any) -> dict[str, Any] | None:
    """A ``problems`` row for a TOP node with failed work items, or None."""
    state = pdg_state(top)
    if not state["failed"]:
        return None
    [first] = failures([top], cap=1)
    message = f"{top.path()}: {state['failed']} of {state['total']} work items failed"
    if first.get("error"):
        message += f"; work item {first['id']}: {first['error']}"
    row: dict[str, Any] = {
        "path": top.path(),
        "type": top.type().name(),
        "kind": "failed_work_items",
        "count": state["failed"],
        "work_item": {"id": first["id"], "index": first["index"]},
    }
    if first.get("log_path"):
        row["log_path"] = first["log_path"]
    row["message"] = message
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


def _log_path(item: Any) -> str | None:
    try:
        uri = str(item.logURI or "")
    except Exception:
        return None
    path = uri[5:] if uri.startswith("file:") else uri
    return path.replace("\\", "/") if path and os.path.isfile(path) else None


def _read_tail(path: str) -> str:
    try:
        with open(path, "rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - LOG_TAIL_BYTES))
            return handle.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


def error_lines(text: str) -> str:
    """The lines of a work item log that say why it failed, newest last, at most
    :data:`ITEM_ERROR_CHARS` (the tail is kept). Falls back to the last line."""
    lines: list[str] = []
    for raw in text.splitlines():
        line = _STAMP.sub("", raw).strip()
        if not line or line.startswith("Traceback (most recent call last)"):
            continue
        lines.append(line)
    picked = [
        line
        for line in lines
        if _ERROR_LINE.search(line) and not _EXIT_CODE.search(line) and line not in ("^", "~")
    ]
    if not picked:
        picked = [line for line in lines if not _EXIT_CODE.search(line)][-1:]
    unique: list[str] = []
    for line in picked:
        if line not in unique:
            unique.append(line)
    out = " | ".join(unique[-4:])
    return out if len(out) <= ITEM_ERROR_CHARS else "..." + out[-(ITEM_ERROR_CHARS - 3) :]


def item_failure(item: Any) -> dict[str, Any]:
    """``error``, ``log_path`` and ``exit_code`` of a failed work item, where known.

    In-process items keep their log in ``logMessages``; out-of-process items write it to
    the scheduler's ``pdgtemp/<pid>/logs/<item>.log`` (``logURI``), which ends with the
    process exit code."""
    text = ""
    try:
        text = str(item.logMessages or "")
    except Exception:
        text = ""
    path = _log_path(item)
    if path is not None:
        text = text + "\n" + _read_tail(path)
    out: dict[str, Any] = {}
    error = error_lines(text)
    if error:
        out["error"] = error
    if path is not None:
        out["log_path"] = path
    codes = _EXIT_CODE.findall(text)
    if codes:
        out["exit_code"] = int(codes[-1])
    return out


def _attrib_value(item: Any, name: str) -> Any:
    try:
        attrib = item.attrib(name)
    except Exception:
        return _MISSING
    if attrib is None:
        return _MISSING
    try:
        values = list(attrib.values)
    except Exception:
        return _MISSING
    values = [v if isinstance(v, int | float | str | bool) else str(v) for v in values]
    if len(values) == 1:
        return values[0]
    return values[:ATTRIB_VALUES_CAP]


_MISSING = object()


def _work_item_row(
    item: Any, top: Any, owner: str | None, attribs: list[str] | None = None
) -> dict[str, Any]:
    files = [f.path.replace("\\", "/") for f in item.outputFiles]
    row: dict[str, Any] = {"id": int(item.id)}
    if item.name != f"{top.name()}_{item.id}":
        row["name"] = item.name  # the default name only repeats the node and id
    row["index"] = int(item.index)
    row["state"] = _snake(item.state.name)
    row["output_files"] = files[:OUTPUT_FILE_CAP]
    if len(files) > OUTPUT_FILE_CAP:
        row["output_files_total"] = len(files)
    if owner is not None:
        row["node"] = owner
    if row["state"].startswith("cooked_"):
        with contextlib.suppress(Exception):
            row["cook_time_s"] = round(float(item.cookDuration), 3)
    if attribs:
        values = {name: _attrib_value(item, name) for name in attribs}
        row["attribs"] = {k: v for k, v in values.items() if v is not _MISSING}
    if row["state"] == "cooked_fail":
        row.update(item_failure(item))
    return row


def relative_outputs(rows: list[dict[str, Any]]) -> str | None:
    """Rewrite the rows' ``output_files`` relative to their common directory and return
    it (review 14 papercut 8: one 128-character prefix was half of every page)."""
    files = [f for row in rows for f in row.get("output_files", [])]
    if not files:
        return None
    try:
        root = os.path.commonpath([os.path.dirname(f) for f in files]).replace("\\", "/")
    except ValueError:  # different drives
        return None
    if not root or root.rstrip("/").endswith(":") or root == "/":
        return None
    prefix = root.rstrip("/") + "/"
    for row in rows:
        if row.get("output_files"):
            row["output_files"] = [f[len(prefix) :] for f in row["output_files"]]
    return root


STATE_ALIASES = {
    "failed": ("cooked_fail",),
    "cancelled": ("cooked_cancel",),
    "success": ("cooked_success",),
    "cache": ("cooked_cache",),
    "cooked": ("cooked_success", "cooked_cache"),
}
STATES = (
    "uncooked",
    "waiting",
    "scheduled",
    "cooking",
    "cooked_success",
    "cooked_cache",
    "cooked_fail",
    "cooked_cancel",
)


def state_filter(raw: Any) -> tuple[str, ...] | None:
    if raw is None:
        return None
    if isinstance(raw, str):
        if raw in STATE_ALIASES:
            return STATE_ALIASES[raw]
        if raw in STATES:
            return (raw,)
    raise bad_arg(
        f"'state' must be a work item state; got {raw!r}.",
        hint="Use failed, cancelled, success, cache, cooked (success or cache) or a state name.",
        candidates=[*STATE_ALIASES, *STATES],
    )


def attrib_names(raw: Any) -> list[str] | None:
    if raw is None:
        return None
    if not isinstance(raw, list) or not all(isinstance(n, str) and n for n in raw):
        raise bad_arg("'attribs' must be a list of work item attribute names.")
    return list(dict.fromkeys(raw))


def graph_tops(target: Any) -> list[Any]:
    """``target`` and every TOP node upstream of it, upstream first."""
    import hou

    order: list[Any] = []
    seen: set[int] = set()

    def visit(node: Any) -> None:
        if node is None or node.sessionId() in seen or not isinstance(node, hou.TopNode):
            return
        seen.add(node.sessionId())
        for parent in node.inputs():
            visit(parent)
        order.append(node)

    visit(target)
    return order


def failures(tops: list[Any], cap: int = FAILURES_CAP) -> list[dict[str, Any]]:
    """The first ``cap`` failed work items of ``tops``, with their errors."""
    out: list[dict[str, Any]] = []
    for top in tops:
        pdg_node = top.getPDGNode()
        if pdg_node is None:
            continue
        for item in sorted(pdg_node.workItems, key=lambda w: (w.index, w.id)):
            if _snake(item.state.name) != "cooked_fail":
                continue
            row: dict[str, Any] = {"node": top.path(), "id": int(item.id), "index": int(item.index)}
            row.update(item_failure(item))
            out.append(row)
            if len(out) >= cap:
                return out
    return out


def cook_result(target: Any) -> dict[str, Any]:
    """The result of a finished cook of ``target``: its status, and the first failed work
    items of its graph (``target`` and its upstream TOPs) when any failed."""
    status = status_block(target)
    failed = failures(graph_tops(target))
    out: dict[str, Any] = {
        "path": target.path(),
        "ok": status["failed"] == 0 and not failed,
        "status": status,
    }
    if failed:
        out["failures"] = failed
    return out


def work_items(
    node: Any, states: tuple[str, ...] | None = None, attribs: list[str] | None = None
) -> list[dict[str, Any]]:
    network = _is_top_network(node)
    rows: list[dict[str, Any]] = []
    for top in _tops(node):
        pdg_node = top.getPDGNode()
        if pdg_node is None:
            continue
        items = sorted(pdg_node.workItems, key=lambda w: (w.index, w.id))
        if states is not None:
            items = [item for item in items if _snake(item.state.name) in states]
        owner = top.path() if network else None
        rows.extend(_work_item_row(item, top, owner, attribs) for item in items)
    return rows


# -- the saved hip ----------------------------------------------------------------------


def _loads_hip(top: Any) -> bool:
    """Whether ``top``'s work items run in processes that load the saved hip file: the
    ROP TOPs (ROP Fetch, ROP Geometry, ...) unless their cook type is In-Process."""
    name = top.type().name().split("::")[0]
    if not name.startswith("rop") or name == "ropnet":
        return False
    parm = top.parm("pdg_cooktype")
    if parm is None:
        return True
    try:
        items, labels = parm.menuItems(), parm.menuLabels()
        label = labels[items.index(str(parm.eval()))]
    except Exception:
        return True
    return "in-process" not in label.lower()


def ensure_saved(target: Any, save: bool, ctx: HostContext) -> str | None:
    """Refuse to cook a graph whose out-of-process items would load a stale or missing
    hip (review 14 papercut 2); with ``save`` save the scene first. Returns the saved
    path, or None when nothing was saved. Main thread."""
    import hou

    loaders = [top.path() for top in graph_tops(target) if _loads_hip(top)]
    if not loaders:
        return None
    named = ", ".join(loaders[:3]) + (" ..." if len(loaders) > 3 else "")
    if hou.hipFile.isNewFile():
        raise ToolError(
            "unsaved_changes",
            f"The scene is untitled, and the work items of {named} run out of process and "
            "load the saved hip file.",
            hint="Save the scene with hip_save {path} first, then cook.",
        )
    if not scene_dirty(ctx):
        return None
    path = hou.hipFile.path()
    if not save:
        raise ToolError(
            "unsaved_changes",
            f"The scene has unsaved changes, and the work items of {named} run out of process "
            f"and load the saved {path}, so they would cook the old scene.",
            hint="Pass save: true to save the scene before cooking, or call hip_save first.",
        )
    check_allowed(path, ctx)
    hou.hipFile.save()
    return hou.hipFile.path()


# -- actions ----------------------------------------------------------------------------


def _cook_now(
    path: str, block: bool, ctx: HostContext, save: bool = False
) -> tuple[str, str | None]:
    """Start (or, with ``block``, run) the cook of ``path``'s target, after
    :func:`ensure_saved`. Returns the target path and the saved hip path. Main thread."""
    target = _cook_target(resolve_top(path))
    saved = ensure_saved(target, save, ctx)
    target.cookWorkItems(block=block)
    return target.path(), saved


def _cancel_now(path: str, jobs: list[dict[str, Any]]) -> list[str]:
    """Cancel the cook of ``path`` and return the ids of the running ``pdg`` jobs that
    cook a graph containing it (cancelling the cook alone left them to report done)."""
    import hou

    node = resolve_top(path)
    paths = {node.path(), *(top.path() for top in _tops(node))}
    owning: list[str] = []
    for job in jobs:
        if job.get("tool") != "pdg" or job.get("state") != "running":
            continue
        label = job.get("label") or ""
        target = hou.node(label) if label else None
        graph = {top.path() for top in graph_tops(target)} if target is not None else {label}
        if graph & paths:
            owning.append(job["job_id"])
    node.cancelCook()
    return owning


def _cancel(ctx: HostContext, path: str, run: Any) -> dict[str, Any]:
    owning = run(lambda: _cancel_now(path, ctx.jobs.list()))
    for job_id in owning:
        ctx.jobs.cancel(job_id)
    deadline = time.monotonic() + CANCEL_WAIT_S
    for job_id in owning:
        ctx.jobs.get(job_id).done_event.wait(max(0.0, deadline - time.monotonic()))
    while True:
        status = run(lambda: status_block(resolve_top(path)))
        if not status["cooking"] or time.monotonic() > deadline:
            break
        time.sleep(POLL_S)
    status["cancelled"] = True
    status["jobs_cancelled"] = owning
    return status


def _dirty(path: str) -> dict[str, Any]:
    node = resolve_top(path)
    if _is_top_network(node):
        node.dirtyAllWorkItems(False)
    else:
        node.dirtyWorkItems(False)
    return status_block(node)


def _start_cook_job(
    ctx: HostContext, path: str, timeout_s: float, wait_s: float = 0.0, save: bool = False
) -> dict[str, Any]:
    target, saved = ctx.executor.run(lambda: _cook_now(path, False, ctx, save), timeout_s)

    def poll() -> dict[str, Any]:
        # The whole graph: the target's own items are only the last stage (review 14
        # papercut 3 saw 0/8 while the upstream ROP fetch had finished 7 of 8).
        tops = graph_tops(resolve_top(target))
        rows = [(top.name(), *_finished(top)) for top in tops]
        return {"cooking": any(_is_cooking(top) for top in tops), "rows": rows}

    def work(job: Any) -> dict[str, Any]:
        began = time.monotonic()
        seen = False
        try:
            while True:
                job.check_cancelled()
                snapshot = job.run_main(poll, JOB_POLL_TIMEOUT_S)
                rows = snapshot["rows"]
                total = sum(row[2] for row in rows)
                seen = seen or snapshot["cooking"] or total > 0
                if total:
                    done = sum(row[1] for row in rows)
                    job.set_progress(done, total, f"{done}/{total} work items finished")
                    job.set_extra("nodes", {name: f"{d}/{t}" for name, d, t, _ in rows})
                idle = not snapshot["cooking"]
                if idle and (seen or time.monotonic() - began > START_GRACE_S):
                    result = job.run_main(lambda: cook_result(resolve_top(target)))
                    cancelled = sum(row[3] for row in rows)
                    _record_done(result, cancelled=bool(cancelled))
                    if cancelled:
                        # Never "done" for a cook whose items were cancelled (papercut 4).
                        raise ToolError(
                            "cancelled",
                            f"The cook of {target} was cancelled: {cancelled} work item(s) "
                            "did not finish.",
                            hint="Cook again with pdg cook; finished items come from the cache.",
                            detail=result,
                        )
                    return result
                time.sleep(POLL_S)
        except ToolError as exc:
            if exc.code == "cancelled" and not isinstance(exc.detail, dict):
                # Cancelled through job (the cook still runs); a cook that ended with
                # cancelled items carries its result in detail and is already recorded.
                ctx.executor.run(lambda: resolve_top(target).cancelCook(), JOB_POLL_TIMEOUT_S)
                events.record_pdg(target, "cook_done", ok=False, cancelled=True)
            raise

    events.record_pdg(target, "cook_start")
    started = ctx.jobs.start("pdg", work, label=target)
    if wait_s > 0 and started.done_event.wait(wait_s):
        # Returned synchronously: the caller never saw a job_id, so keep job list clean.
        ctx.jobs.discard(started.id)
        if started.state == "done":
            return _with_saved(started.result, saved)
        raise ToolError.from_dict(started.error or {"code": "internal", "message": "cook failed"})
    return _with_saved(
        {
            "job_id": started.id,
            "state": "running",
            "path": target,
            "message": (
                f"Cooking {target} in the background; poll with job {{action: status, job_id: "
                f"{started.id}}} and fetch the result with action result."
            ),
        },
        saved,
    )


def _record_done(result: dict[str, Any], cancelled: bool = False) -> None:
    """``events``: the failed items and the end of a cook (review 14 papercut 6)."""
    for failure in result.get("failures", []):
        detail = {k: failure[k] for k in ("id", "index", "error") if k in failure}
        events.record_pdg(failure["node"], "work_item_failed", **detail)
    status = result.get("status") or {}
    extra: dict[str, Any] = {"ok": bool(result.get("ok")), "states": status.get("states", {})}
    if cancelled:
        extra["cancelled"] = True
    events.record_pdg(result.get("path", ""), "cook_done", **extra)


def _with_saved(result: dict[str, Any], saved: str | None) -> dict[str, Any]:
    if saved is not None:
        result = dict(result, saved=saved)
    return result


@tool("pdg", main_thread=False, scene=False)
def pdg_tool(args: dict[str, Any], ctx: HostContext) -> dict[str, Any]:
    action = args.get("action")
    if action not in ACTIONS:
        raise bad_arg(f"'action' must be one of {', '.join(ACTIONS)}.")
    path = args.get("top_path")
    if not isinstance(path, str) or not path:
        raise bad_arg("'top_path' must be a TOP node or TOP network path.")
    block = args.get("block", False)
    save = args.get("save", False)
    if not isinstance(block, bool) or not isinstance(save, bool):
        raise bad_arg("'block' and 'save' must be booleans.")
    # The dispatcher's effective timeout: args.timeout_s, else the request's, else the
    # config default (Dispatcher.effective_timeout).
    default_s = float(ctx.config.default_timeout_s)
    timeout_s = float(call_timeout(default_s) or default_s)
    if action in ("cook", "dirty", "cancel"):
        refuse_if_read_only(ctx, f"pdg {action}")

    def run(fn: Any) -> Any:
        if ctx.executor.on_main_thread():
            return fn()
        return ctx.executor.run(fn, timeout_s)

    if action == "status":
        return run(lambda: status_block(resolve_top(path)))
    if action == "workitems":
        limit, cursor = args.get("limit"), args.get("cursor")
        states = state_filter(args.get("state"))
        attribs = attrib_names(args.get("attribs"))

        def items() -> dict[str, Any]:
            node = resolve_top(path)
            rows = work_items(node, states, attribs)
            chunk, nxt = page(rows, limit, cursor)
            out: dict[str, Any] = {"path": node.path()}
            root = relative_outputs(chunk)
            if root is not None:
                out["output_root"] = root
            out["work_items"] = chunk
            out["total"] = len(rows)
            if nxt is not None:
                out["next_cursor"] = nxt
            return out

        return run(items)
    if action == "cancel":
        return _cancel(ctx, path, run)
    if action == "dirty":
        return run(lambda: _dirty(path))

    # cook
    if ctx.executor.on_main_thread():
        # Called inline on the main thread (GUI shell, tests): no job can make progress.
        target, saved = _cook_now(path, True, ctx, save)
        events.record_pdg(target, "cook_start")
        result = cook_result(resolve_top(target))
        _record_done(result)
        return _with_saved(result, saved)
    # Like cook and render: a blocking call waits at most job_threshold_s, then hands back
    # the job (BIBLE §7); block: false returns the job at once.
    wait_s = min(timeout_s, float(ctx.config.job_threshold_s)) if block else 0.0
    result = _start_cook_job(ctx, path, timeout_s, wait_s, save)
    if block and wait_s < timeout_s and result.get("state") == "running":
        # Review 14 papercut 9: say that timeout_s was not what the call waited.
        result["notes"] = [
            f"block waited {wait_s:g} s (job_threshold_s), not timeout_s {timeout_s:g} s; "
            "poll the job."
        ]
    return result

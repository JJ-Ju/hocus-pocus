"""Cook and diagnostics tools: ``cook`` and ``problems``.

See docs/BIBLE.md §4.6, §5.3 (``cook`` raises ``OperationFailed``; the useful text is in
``errors()`` afterwards) and §7 (jobs).

``cook`` is registered off the main thread: it validates paths with one short
main-thread call, then cooks node by node as a job (each node is one main-thread step).
When the job finishes within ``min(timeout_s, job_threshold_s)`` the call returns the
result directly; otherwise it returns ``{job_id, state: "running"}`` for ``job``. A node
that fails to cook is reported (``ok: false`` with its errors), never raised.
"""

from __future__ import annotations

import contextlib
import os
import re
import time
from typing import Any

from hocuspocus.tools.errors import ToolError
from hocuspocus.tools.migration import hint_tool

from ..dispatch import call_timeout
from ._common import bad_arg, number, parse_limit
from ._diag import (
    COOKABLE_CATEGORIES,
    REFRESH_CATEGORIES,
    collect_problems,
    is_slow,
    require_node,
    timed_cook,
    upstream_first,
)
from .readers import press_reload
from .registry import HostContext, tool

JOB_STEP_TIMEOUT_S = 24 * 3600.0
"""Main-thread budget for one node's cook inside a job (cooks are not interruptible)."""


# -- cook ------------------------------------------------------------------------------


def _number(
    args: dict[str, Any], key: str, default: float | None, *, positive: bool = False
) -> Any:
    value = args.get(key, default)
    if value is None:
        return None
    value = number(value, key)
    if positive and value <= 0:
        raise bad_arg(f"'{key}' must be greater than 0.")
    return value


def _paths_arg(args: dict[str, Any]) -> list[str]:
    paths = args.get("paths")
    if isinstance(paths, str):
        paths = [paths]
    if not isinstance(paths, list) or not paths:
        raise ToolError("invalid_argument", "'paths' must be a non-empty list of node paths.")
    for path in paths:
        if not isinstance(path, str) or not path.strip():
            raise ToolError("invalid_argument", "Every entry in 'paths' must be a node path.")
    return [p.strip() for p in paths]


WARM_CACHE_HINT = (
    "cook_time_ms is this node's own cook; its inputs were already cooked and are not "
    "included and were not recooked. Use profile: true to time the whole input chain, or "
    'force: "chain" to recook it.'
)

INPUT_PROBLEMS_LISTED = 10
"""``force: "chain"`` lists at most this many inputs with errors or warnings per node."""

SUMMARIES = ("none", "bbox")
MAX_FRAMES = 10000


def cook_node(path: str, *, force: bool, frame: float | None) -> dict[str, Any]:
    """Cook one node at ``frame`` (restoring the current frame) and report it. Main thread."""
    import hou

    node = require_node(path)
    previous = hou.frame()
    switch = frame is not None and frame != previous
    if switch:
        hou.setFrame(frame)
    try:
        # D80: a forced cook does not reload a File COP's image; its own button does.
        reloaded = force and press_reload(node)
        report = collect_problems(node, cook=True, force=force)
    finally:
        if switch:
            hou.setFrame(previous)
    row: dict[str, Any] = {"path": node.path(), "ok": not report["errors"]}
    row.update(report)
    if reloaded:
        row["reloaded"] = True
    if report["cook_state"] == "error":
        row["ok"] = False
    if force and "hint" not in row and report.get("cook_time_ms", 1.0) < 1.0 and _has_inputs(node):
        # Review 11 B7: a warm cache makes a forced cook look free.
        row["hint"] = WARM_CACHE_HINT
    return row


def _has_inputs(node: Any) -> bool:
    try:
        return any(i is not None for i in node.inputs())
    except Exception:
        return False


def dependency_order(node: Any) -> list[Any]:
    """``node.inputAncestors()`` ordered so every node comes after its inputs, then ``node``.

    Wired inputs are walked depth first; ancestors reached only through reference inputs
    come first (they feed the wired chain). Nodes that cannot cook are left out.
    """
    wired = upstream_first(node)
    seen = {n.sessionId() for n in wired}
    try:
        ancestors = list(node.inputAncestors())
    except Exception:
        ancestors = []
    extra = [a for a in reversed(ancestors) if a.sessionId() not in seen]
    return [n for n in [*extra, *wired, node] if hasattr(n, "cook")]


INACTIVE_LISTED = 10
"""A profile's ``inactive.paths`` lists at most this many of the skipped nodes."""


def cook_path(node: Any) -> tuple[list[Any], list[str]]:
    """``(nodes to profile, inactive paths)``: the input ancestors of ``node`` that a
    normal cook of it cooks, in dependency order and ending with ``node``, and the paths
    of the other ancestors (a Switch's unselected inputs, what feeds a bypassed or locked
    node; review 26 P1 #8: profiling them made "interiors off costs nothing" look false).

    Houdini answers which inputs the last cook used
    (``inputAncestors(only_used_inputs=True)``), so a dirty node is cooked normally first.
    A chain that simulates is not pre-cooked (that cook would solve its frames and the
    profile would time a cache read), nor is a cook that fails or uses nothing: then
    every ancestor is profiled, as before 2.1. Main thread."""
    import hou

    every = dependency_order(node)
    ancestors = every[:-1]
    if not ancestors:
        return every, []
    try:
        dirty = bool(node.needsToCook())
    except Exception:
        dirty = True
    if dirty:
        if any(_dop_networks(n) for n in every):
            return every, []
        with contextlib.suppress(hou.OperationFailed):
            node.cook(force=False)
    try:
        used = node.inputAncestors(only_used_inputs=True)
    except Exception:
        used = ()
    if not used:
        return every, []
    ids = {n.sessionId() for n in used}
    for end in [n for n in used if _is_block_end(n)]:
        # Houdini leaves a for-each body out of the used inputs; the block_end cooks it.
        with contextlib.suppress(Exception):
            ids.update(a.sessionId() for a in end.inputAncestors())
    active = [n for n in ancestors if n.sessionId() in ids]
    inactive = [n.path() for n in ancestors if n.sessionId() not in ids]
    return [*active, node], inactive


def _is_block_end(node: Any) -> bool:
    try:
        return node.type().name().split("::")[0] == "block_end"
    except Exception:
        return False


def _loop_begin(end: Any) -> Any:
    """The ``block_begin`` a ``block_end`` names in ``blockpath``, or None."""
    try:
        path = end.parm("blockpath").eval()
        return end.node(path) if path else None
    except Exception:
        return None


def _loop_body(end: Any, begin: Any) -> list[str]:
    """Paths of the nodes cooked once per iteration: ``begin`` and every input ancestor of
    ``end`` that is downstream of ``begin``."""
    if begin is None:
        return []
    begin_id = begin.sessionId()
    body = [begin.path()]
    try:
        ancestors = list(end.inputAncestors())
    except Exception:
        ancestors = []
    for node in ancestors:
        with contextlib.suppress(Exception):
            if any(a.sessionId() == begin_id for a in node.inputAncestors()):
                body.append(node.path())
    return body


def _perf_cook_stats(
    tree: Any, out: dict[str, tuple[float, int]] | None = None
) -> dict[str, tuple[float, int]]:
    """``{node path: (cook ms, cook count)}`` from ``hou.PerfMonProfile.stats()``. A node's
    ``Cook`` includes the nodes inside it (an HDA's contents) but not its inputs, which
    are recorded as nodes of their own (verified on 22.0.466)."""
    out = {} if out is None else out
    if not isinstance(tree, dict):
        return out
    path = tree.get("path")
    if isinstance(path, str) and path.startswith("/"):
        cook_ms, count = 0.0, 0
        for per_thread in (tree.get("stats") or {}).values():
            for values in (per_thread or {}).values():
                cook_ms += float(values.get("Cook", 0.0) or 0.0)
                count += int(values.get("Cook Count", 0) or 0)
        if count:
            out[path] = (cook_ms, count)
    for child in tree.get("children") or ():
        _perf_cook_stats(child, out)
    return out


def _perf_cook(
    node: Any, *, solve: bool = False
) -> tuple[float, BaseException | None, dict[str, Any] | None]:
    """Force-cook ``node`` under Houdini's performance monitor: cook stats, or with
    ``solve`` DOP solve stats only. Returns the wall time, the cook failure, and the
    profile's stats tree, or None when the monitor could not be used (another profile is
    recording, or the API failed). A stopped profile cannot be deleted, so in a GUI
    session it stays in the Performance Monitor's list."""
    import hou

    profile = None
    with contextlib.suppress(Exception):
        if hou.perfMon.activeProfile() is None:
            options = hou.PerfMonRecordOptions(
                cook_stats=not solve, solve_stats=solve, draw_stats=False,
                gpu_draw_stats=False, viewport_stats=False, script_stats=False,
                render_stats=False, thread_stats=False, frame_stats=False,
                memory_stats=False, errors=False,
            )  # fmt: skip
            profile = hou.perfMon.startProfile(f"HocusPocus cook profile {node.path()}", options)
    try:
        elapsed, failure = timed_cook(node, True)
    finally:
        if profile is not None:
            with contextlib.suppress(Exception):
                profile.stop()
    tree = None
    if profile is not None:
        with contextlib.suppress(Exception):
            tree = profile.stats()
    return elapsed, failure, tree if isinstance(tree, dict) else None


def solve_ms(tree: dict[str, Any]) -> float:
    """The DOP solve time a solve-stats profile recorded, from its root's per-thread,
    per-frame ``Solve`` (verified on 22.0.466: 0 entries when a cook read cached frames).
    No ``hou``."""
    total = 0.0
    for per_thread in (tree.get("stats") or {}).values():
        for values in (per_thread or {}).values():
            with contextlib.suppress(TypeError, ValueError, AttributeError):
                total += float(values.get("Solve", 0.0) or 0.0)
    return total


SIM_NETS_CAP = 3


def _dop_networks(node: Any) -> list[Any]:
    """The DOP networks a node simulates with: itself (a DOP network SOP or object), else
    the ones inside it (``pyrosolver``'s ``dopnet1``), at most :data:`SIM_NETS_CAP`."""
    import hou

    def is_dopnet(candidate: Any) -> bool:
        try:
            category = candidate.childTypeCategory()
        except Exception:
            return False
        return category is not None and category == hou.dopNodeTypeCategory()

    if is_dopnet(node):
        return [node]
    try:
        children = node.allSubChildren(recurse_in_locked_nodes=True)
    except Exception:
        return []
    return [child for child in children if is_dopnet(child)][:SIM_NETS_CAP]


def _sim_states(nets: list[Any]) -> list[dict[str, Any]]:
    """``{path, time, memory, frame, start}`` per DOP network: the simulation's time,
    memory (bytes) and current frame, and the network's start frame."""
    import hou

    states = []
    for net in nets:
        with contextlib.suppress(Exception):
            sim = net.simulation()
            start = net.parm("startframe")
            time_now = float(sim.time())
            states.append(
                {
                    "path": net.path(),
                    "time": time_now,
                    "memory": int(sim.memoryUsage()),
                    "frame": round(hou.timeToFrame(time_now), 4),
                    "start": float(start.eval()) if start is not None else hou.timeToFrame(0.0),
                }
            )
    return states


SAME_TIME_S = 1e-6
CURRENT_FRAME = "current_frame"
"""``resimulated`` when a cook re-solved only the frame the simulation already stood on."""


def resimulated(
    before: dict[str, Any] | None, after: dict[str, Any], solve: float | None
) -> bool | str | None:
    """Whether a cook stepped the simulation: ``False`` (it read cached frames),
    ``"current_frame"`` (it re-solved only the frame the simulation already stood on),
    ``True`` (it simulated frames the cache did not hold), or None when Houdini gave no
    reliable signal (review 20 N3).

    ``solve`` is the DOP solve time the performance monitor recorded (:func:`solve_ms`),
    the reliable signal for whether anything was solved. It is booked on the frame being
    evaluated however many frames were stepped, so how many comes from the simulation
    state: a warm solver whose inputs a profile force-cooked re-solves its current frame
    (review 24 N3: 77 ms "solves" on a warm Vellum solver read as a full re-run), and its
    time does not move. Without ``solve`` (the monitor could not be used) the time moves
    on a cache read too (a 4 ms cook of frame 24 read as ``resimulated: true``): a changed
    memory size means frames were simulated (the current one only when the time stayed),
    an unchanged time and size that nothing was, and anything else is unknown. No ``hou``."""
    stayed = before is not None and abs(after["time"] - before["time"]) < SAME_TIME_S
    held = before is not None and before["memory"] > 0
    if solve is not None:
        if solve <= 0.0:
            return False
        return CURRENT_FRAME if stayed and held else True
    if before is None:
        return None
    if after["memory"] != before["memory"]:
        return CURRENT_FRAME if stayed and held else True
    if stayed:
        return False
    return None


def simulated_frames(
    before: dict[str, Any] | None, after: dict[str, Any], verdict: bool | str | None
) -> list[float | int] | None:
    """``[first, last]`` frames a cook simulated, when the state tells: the current frame
    for ``"current_frame"``; from the start frame for a simulation that was empty or reset;
    from the frame after the one it stood on when it moved forward. None otherwise (a
    cache read, or a jump whose cached frames are unknown). No ``hou``."""
    if "frame" not in after:
        return None
    last = _num(after["frame"])
    if verdict == CURRENT_FRAME:
        return [last, last]
    if verdict is not True:
        return None
    start = after.get("start")
    if (
        before is None
        or before["memory"] <= 0
        or (start is not None and before.get("frame", start) <= start)
    ):
        return [_num(start), last] if start is not None else None
    if before["time"] < after["time"] and "frame" in before:
        return [_num(round(before["frame"] + 1, 4)), last]
    return None


def _profile_step(node_path: str) -> dict[str, Any]:
    """Force-cook one chain node and time it. A ``block_end`` is cooked under the
    performance monitor so its loop body can be attributed (review 12 papercut 5). Main
    thread."""
    node = require_node(node_path)
    loop: dict[str, Any] | None = None
    if _is_block_end(node):
        begin = _loop_begin(node)
        before = begin.cookCount() if begin is not None else None
        elapsed, failure, tree = _perf_cook(node)
        stats = _perf_cook_stats(tree) if tree is not None else None
        loop = {"block_end": node.path(), "body": _loop_body(node, begin), "stats": stats}
        if begin is not None:
            loop["block_begin"] = begin.path()
            with contextlib.suppress(Exception):
                loop["iterations"] = begin.cookCount() - before
    else:
        nets = _dop_networks(node)
        before = _sim_states(nets)
        solve = None
        if nets:
            elapsed, failure, tree = _perf_cook(node, solve=True)
            solve = solve_ms(tree) if tree is not None else None
        else:
            elapsed, failure = timed_cook(node, True)
        after = _sim_states(nets)
    row: dict[str, Any] = {
        "path": node.path(),
        "type": node.type().name(),
        "cook_time_ms": round(elapsed, 1),
    }
    if loop is None and after:
        import hou

        # Review 17 P2-10: a force-cook of a solver reads the simulation cache when it
        # holds the frame; say whether this cook simulated anything (review 20 N3).
        first = before[0] if before and before[0]["path"] == after[0]["path"] else None
        verdict = resimulated(first, after[0], solve)
        row["simulation"] = {
            "dopnet": after[0]["path"],
            "resimulated": verdict,
            "frame": _num(round(hou.timeToFrame(after[0]["time"]), 4)),
        }
        frames = simulated_frames(first, after[0], verdict)
        if frames is not None:
            row["simulation"]["simulated_frames"] = frames
    if loop is not None:
        row["_loop"] = loop
    if failure is not None:
        try:
            errors = [str(e).strip() for e in node.errors() if str(e).strip()]
        except Exception:
            errors = []
        row["error"] = errors[0] if errors else f"{type(failure).__name__}: {failure}"
    return row


def _frame_list(raw: Any) -> list[float]:
    hint = "For example [1, 96] or [1, 96, 2]."
    if (
        not isinstance(raw, list)
        or len(raw) not in (2, 3)
        or any(isinstance(v, bool) or not isinstance(v, int | float) for v in raw)
    ):
        raise ToolError(
            "invalid_argument",
            "'frame_range' must be [start, end] or [start, end, step] numbers.",
            hint=hint,
        )
    start, end = float(raw[0]), float(raw[1])
    step = float(raw[2]) if len(raw) == 3 else 1.0
    if step <= 0 or end < start:
        raise ToolError(
            "invalid_argument", f"'frame_range' {raw} needs start <= end and step > 0.", hint=hint
        )
    count = int((end - start) / step + 1e-9) + 1
    if count > MAX_FRAMES:
        raise ToolError(
            "invalid_argument",
            f"'frame_range' {raw} covers {count} frames; at most {MAX_FRAMES} per call.",
            hint="Use a larger step or split the range.",
        )
    return [start + i * step for i in range(count)]


def _num(value: float) -> float | int:
    return int(value) if float(value).is_integer() else round(value, 4)


def _geometry_of(node: Any) -> Any:
    """The node's geometry: a SOP's own, an object's display SOP's, else None."""
    try:
        category = node.type().category().name()
        if category == "Object":
            node = node.displayNode()
        elif category != "Sop":
            return None
        return node.geometry() if node is not None else None
    except Exception:
        return None


def _bbox_row(node: Any) -> dict[str, Any]:
    geo = _geometry_of(node)
    if geo is None:
        return {"point_count": None, "prim_count": None, "bbox_min": None, "bbox_max": None}
    points = geo.intrinsicValue("pointcount")
    row: dict[str, Any] = {
        "point_count": points,
        "prim_count": geo.intrinsicValue("primitivecount"),
    }
    if points:
        box = geo.boundingBox()
        row["bbox_min"] = [round(v, 5) for v in box.minvec()]
        row["bbox_max"] = [round(v, 5) for v in box.maxvec()]
    else:
        row["bbox_min"] = row["bbox_max"] = None
    return row


def _frame_step(
    paths: list[str], frame: float, force: bool, summary: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Cook every path at ``frame`` (leaving the frame set). Main thread."""
    import hou

    hou.setFrame(frame)
    reports, rows = [], []
    for path in paths:
        node = require_node(path)
        report = collect_problems(node, cook=True, force=force)
        report["path"] = node.path()
        reports.append(report)
        if summary == "bbox":
            row: dict[str, Any] = {"frame": _num(frame)}
            if len(paths) > 1:
                row["path"] = node.path()
            row.update(_bbox_row(node))
            if report["errors"]:
                row["errors"] = report["errors"][:3]
            rows.append(row)
    return reports, rows


_SAME_KEYS = ("path", "point_count", "prim_count", "bbox_min", "bbox_max", "errors")


def collapse_frames(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Summary rows only where something changed (review 17 P2-8: 48 rows, 4 changes): a
    run of frames with the same counts, bbox and errors is its first row plus
    ``through``, the run's last frame. Per node when several are cooked. No ``hou``."""
    out: list[dict[str, Any]] = []
    last: dict[Any, dict[str, Any]] = {}
    for row in rows:
        key = row.get("path")
        previous = last.get(key)
        if previous is not None and all(previous.get(k) == row.get(k) for k in _SAME_KEYS):
            previous["through"] = row["frame"]
            continue
        row = dict(row)
        out.append(row)
        last[key] = row
    return out


MAX_FRAME_ROWS = 12
"""``summary: bbox`` rows a ``frame_range`` result carries at most (spec-2.0 §7 M4)."""


def frame_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """``{frames}`` for a result: :func:`collapse_frames`, and past :data:`MAX_FRAME_ROWS`
    runs only the first and last six with ``frames_truncated: true`` and ``frames_rows``,
    the number of runs (review 22 soak: 24 bbox rows were 3 KB of a 24-frame cook). The
    same rows go into a job's result, so a pushed-progress completion carries no more."""
    runs = collapse_frames(rows)
    if len(runs) <= MAX_FRAME_ROWS:
        return {"frames": runs}
    half = MAX_FRAME_ROWS // 2
    return {
        "frames": runs[:half] + runs[-half:],
        "frames_truncated": True,
        "frames_rows": len(runs),
    }


def _merge_frame_report(
    merged: dict[str, dict[str, Any]], report: dict[str, Any], frame: float
) -> None:
    """Fold one frame's report into the node's row: the first failing frame's errors win,
    warnings and messages are the last frame's, cook_time_ms is summed."""
    path = report["path"]
    row = merged.get(path)
    if row is None:
        row = merged[path] = {"path": path, "ok": True, "cook_time_ms": 0.0}
    row["cook_time_ms"] = round(row["cook_time_ms"] + report.get("cook_time_ms", 0.0), 1)
    if report["errors"] and row["ok"]:
        row["ok"] = False
        row["errors"] = report["errors"]
        row["first_error_frame"] = _num(frame)
    if row["ok"]:
        row["errors"] = report["errors"]
    row["warnings"] = report["warnings"]
    row["messages"] = report["messages"]
    row["cook_state"] = report["cook_state"] if row["ok"] else "error"


def _restore_frame(ctx: HostContext, previous: float) -> None:
    """Put the playhead back, even after a cancel (which refuses further job steps)."""
    import hou

    from .visual import run_with_fallback

    run_with_fallback(ctx.executor, lambda: hou.setFrame(previous), 60.0)


FRAME_EPS = 1e-6


class Playhead:
    """The playbar around a ranged cook (docs/parity.md G4). No ``hou``: the caller reads
    and sets the frame on the main thread.

    In a GUI session every frame of ``cook {frame_range}`` is a visible ``setFrame``
    between idle ticks, and the user may scrub in between. The cook needs its frames, so
    a step still sets its own; but at the end the playbar goes back to the start frame
    only when nobody moved it during the job. When the user moved it, it stays where the
    user put it last (a scrub before the last step is put back after it)."""

    def __init__(self, start: float) -> None:
        self.start = start
        self.last: float | None = None
        """The frame the last step set."""
        self.user: float | None = None
        """The frame the user moved the playbar to during the job, if they did."""

    def before_step(self, now: float) -> None:
        if self.last is not None and abs(now - self.last) > FRAME_EPS:
            self.user = now

    def stepped(self, frame: float) -> None:
        self.last = frame

    def finish(self, now: float) -> tuple[str, float]:
        """``(action, frame)``: ``restore`` (set ``frame``, the start), ``user`` (set
        ``frame``, where the user moved it before the last step) or ``moved`` (leave it:
        the user moved it after the last step)."""
        self.before_step(now)
        if self.user is None:
            return "restore", self.start
        if abs(now - self.user) <= FRAME_EPS:
            return "moved", now
        return "user", self.user

    def note(self, action: str, frame: float, ui: bool) -> str | None:
        if action == "restore":
            if not ui:
                return None
            return (
                "The GUI playbar stepped through the cooked frames and was put back to frame "
                f"{_num(frame)}."
            )
        return (
            f"The playbar was moved to frame {_num(frame)} during the cook, so it was left "
            f"there rather than put back to frame {_num(self.start)}."
        )


def _finish_playhead(ctx: HostContext, playhead: Playhead) -> str | None:
    """Put the playbar where :class:`Playhead` says, even after a cancel; the note to
    add, if any. Never raises."""
    import hou

    from .visual import run_with_fallback

    outcome: dict[str, Any] = {}

    def finish() -> None:
        action, frame = playhead.finish(hou.frame())
        if action != "moved":
            hou.setFrame(frame)
        outcome.update(action=action, frame=frame)

    failed = run_with_fallback(ctx.executor, finish, 60.0)
    if failed or not outcome:
        return None
    return playhead.note(outcome["action"], outcome["frame"], bool(ctx.ui))


class _Inline:
    """Stands in for a job when ``cook`` runs on the main thread itself (GUI shell, tests)."""

    def run_main(self, fn: Any, timeout_s: float | None = None) -> Any:
        return fn()

    def set_progress(self, current: int, total: int, message: str | None = None) -> None:
        pass


def _plain(job: Any, paths: list[str], force: bool, frame: float | None) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for index, path in enumerate(paths):
        job.set_progress(index, len(paths), f"cooking {path}")
        try:
            results.append(
                job.run_main(
                    lambda p=path: cook_node(p, force=force, frame=frame), JOB_STEP_TIMEOUT_S
                )
            )
        except ToolError as exc:
            if exc.code != "cancelled":
                raise
            from .visual import cancelled_with_partial

            done = f"{len(results)} of {len(paths)} nodes"
            raise cancelled_with_partial(job, {"results": results}, done) from exc
    job.set_progress(len(paths), len(paths), "done")
    return results


def _chain_inputs(path: str, frame: float | None) -> list[str]:
    """The input ancestors a normal cook of ``path`` uses, in dependency order (D53's
    :func:`cook_path`), at ``frame``. Main thread."""
    import hou

    node = require_node(path)
    previous = hou.frame()
    switch = frame is not None and frame != previous
    if switch:
        hou.setFrame(frame)
    try:
        nodes, _inactive = cook_path(node)
    finally:
        if switch:
            hou.setFrame(previous)
    return [n.path() for n in nodes[:-1]]


def _chained(job: Any, paths: list[str], frame: float | None) -> list[dict[str, Any]]:
    """``force: "chain"`` (2.1, D81): force-cook each node's used input chain, inputs
    first (each pressing its reload button, D80), one main-thread step per node, then the
    node itself. Each node's row adds ``inputs_cooked``, ``inputs_reloaded`` and the inputs
    that still report errors or warnings in ``input_problems``. An input shared by two
    named nodes is cooked once."""
    results: list[dict[str, Any]] = []
    done: set[str] = set()
    for index, path in enumerate(paths):
        job.set_progress(index, len(paths), f"cooking the inputs of {path}")
        try:
            inputs = job.run_main(lambda p=path: _chain_inputs(p, frame), JOB_STEP_TIMEOUT_S)
            cooked, reloaded, problems = 0, [], []
            for source in inputs:
                if source in done:
                    continue
                row = job.run_main(
                    lambda p=source: cook_node(p, force=True, frame=frame), JOB_STEP_TIMEOUT_S
                )
                done.add(source)
                cooked += 1
                if row.get("reloaded"):
                    reloaded.append(source)
                issues = {k: row[k] for k in ("errors", "warnings") if row.get(k)}
                if issues:
                    problems.append({"path": source, **issues})
            row = job.run_main(
                lambda p=path: cook_node(p, force=True, frame=frame), JOB_STEP_TIMEOUT_S
            )
        except ToolError as exc:
            if exc.code != "cancelled":
                raise
            from .visual import cancelled_with_partial

            done_text = f"{len(results)} of {len(paths)} nodes"
            raise cancelled_with_partial(job, {"results": results}, done_text) from exc
        done.add(row["path"])
        row.pop("hint", None)  # the warm-cache hint: its inputs were just recooked
        row["inputs_cooked"] = cooked
        if reloaded:
            row["inputs_reloaded"] = reloaded[:INPUT_PROBLEMS_LISTED]
        if problems:
            row["input_problems"] = problems[:INPUT_PROBLEMS_LISTED]
            if len(problems) > INPUT_PROBLEMS_LISTED:
                row["input_problems_total"] = len(problems)
        results.append(row)
    job.set_progress(len(paths), len(paths), "done")
    return results


def _profiled(
    job: Any, ctx: HostContext, paths: list[str], frame: float | None, timeout_s: float
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Force-cook the part of every node's input chain that a normal cook of it cooks
    (:func:`cook_path`), in dependency order, one step per node."""
    import hou

    skipped: list[str] = []

    def chain_paths() -> list[str]:
        ordered: list[str] = []
        for path in paths:
            used, inactive = cook_path(require_node(path))
            for node in used:
                if node.path() not in ordered:
                    ordered.append(node.path())
            skipped.extend(p for p in inactive if p not in skipped)
        return ordered

    previous = job.run_main(hou.frame, timeout_s)
    rows: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    try:
        if frame is not None:
            job.run_main(lambda: hou.setFrame(frame), timeout_s)
        # After the frame is set: which inputs a normal cook uses can depend on it.
        chain = job.run_main(chain_paths, JOB_STEP_TIMEOUT_S)
        skipped[:] = [p for p in skipped if p not in chain]  # used by another named node
        steps = len(chain) + len(paths)
        for index, path in enumerate(chain):
            job.set_progress(index, steps, f"{index}/{steps} steps done, cooking {path}")
            rows.append(job.run_main(lambda p=path: _profile_step(p), JOB_STEP_TIMEOUT_S))
        for index, path in enumerate(paths):
            # Already cooked by the chain: this reads its errors and warnings.
            job.set_progress(len(chain) + index, steps, f"checking {path}")
            results.append(
                job.run_main(
                    lambda p=path: cook_node(p, force=False, frame=None), JOB_STEP_TIMEOUT_S
                )
            )
    finally:
        if frame is not None:
            _restore_frame(ctx, previous)
    job.set_progress(steps, steps, "done")
    extra = _attribute_loops(rows)
    total_ms = round(sum(r["cook_time_ms"] for r in rows if "in_loop" not in r), 1)
    by_path = {r["path"]: r for r in rows}
    for result in results:
        # The named node's profiled cook, not the cached re-check that follows it (0.0).
        if result["path"] in by_path:
            result["cook_time_ms"] = by_path[result["path"]]["cook_time_ms"]
    rows.sort(key=lambda r: r["cook_time_ms"], reverse=True)
    out = {"chain": rows[:10], "chain_total": len(rows), "total_ms": total_ms}
    if skipped:
        # Review 26 P1 #8: inputs a normal cook does not cook (a Switch's other inputs, a
        # bypassed or locked node's) are not profiled; say which were left out.
        out["inactive"] = {"count": len(skipped), "paths": skipped[:INACTIVE_LISTED]}
    out.update(extra)
    notes = [_sim_note(row) for row in rows if "simulation" in row]
    if notes:
        out["notes"] = notes
    return results, out


def _sim_note(row: dict[str, Any]) -> str:
    sim = row["simulation"]
    if sim["resimulated"] is None:
        return (
            f"{row['path']} cooked {sim['dopnet']} at frame {sim['frame']}, but whether it "
            "re-simulated or read cached frames is unknown (Houdini's performance monitor was "
            "unavailable), so resimulated is null. Reset the simulation (its resimulate button) "
            "to time a full run."
        )
    if sim["resimulated"] == CURRENT_FRAME:
        return (
            f"{row['path']} re-solved only frame {sim['frame']} in {sim['dopnet']}: profile "
            "force-cooks the solver's inputs, so Houdini re-steps the frame the simulation "
            "stands on, and the frames before it came from the simulation cache; its "
            "cook_time_ms is that one step. Reset the simulation (its resimulate button) to "
            "time a full run."
        )
    if sim["resimulated"]:
        frames = sim.get("simulated_frames")
        what = f"frames {frames[0]}-{frames[1]}" if frames else f"frames up to frame {sim['frame']}"
        return (
            f"{row['path']} simulated {what} in {sim['dopnet']}; its cook_time_ms includes "
            "that simulation."
        )
    return (
        f"{row['path']} did not re-simulate: {sim['dopnet']}'s cache already held frame "
        f"{sim['frame']}, so its cook_time_ms is a cache read. Reset the simulation (its "
        "resimulate button) to time a full run."
    )


def _attribute_loops(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Give loop-body rows their cost across every iteration of the loop.

    A body node's own step cooks it once, outside the loop; the real cost is paid when
    the ``block_end`` cooks the body once per iteration. With the performance monitor's
    stats a body row gets ``cook_time_ms`` (all iterations), ``cooks``,
    ``per_iteration_ms`` and ``in_loop``; without them (``attribution: "loop-level"``) it
    keeps its one standalone cook and is marked ``in_loop``. Either way ``total_ms``
    counts the loop once, at its ``block_end``. An outer loop, profiled after an inner
    one, re-attributes the inner body across all its own iterations."""
    by_path = {r["path"]: r for r in rows}
    loops: list[dict[str, Any]] = []
    attribution = "per_node"
    for row in rows:
        loop = row.pop("_loop", None)
        if loop is None:
            continue
        stats = loop["stats"]
        entry: dict[str, Any] = {"block_end": loop["block_end"]}
        if "block_begin" in loop:
            entry["block_begin"] = loop["block_begin"]
        if "iterations" in loop:
            entry["iterations"] = loop["iterations"]
        entry["total_ms"] = row["cook_time_ms"]
        measured = stats is not None
        for path in loop["body"]:
            body_row = by_path.get(path)
            if body_row is None:
                continue
            body_row["in_loop"] = loop["block_end"]
            if stats is not None and path in stats:
                cook_ms, count = stats[path]
                body_row["cook_time_ms"] = round(cook_ms, 1)
                body_row["cooks"] = count
                body_row["per_iteration_ms"] = round(cook_ms / count, 2)
            else:
                measured = False
                for key in ("cooks", "per_iteration_ms"):
                    body_row.pop(key, None)
        entry["attribution"] = "perf_monitor" if measured else "loop-level"
        if not measured:
            attribution = "loop-level"
        elif attribution == "per_node":
            attribution = "perf_monitor"
        loops.append(entry)
    out: dict[str, Any] = {"attribution": attribution}
    if loops:
        out["loops"] = loops
    return out


def _ranged(
    job: Any,
    ctx: HostContext,
    paths: list[str],
    frames: list[float],
    force: bool,
    summary: str,
    timeout_s: float,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Cook every frame as its own main-thread step (a sim advances one frame per step)."""
    import hou

    playhead = Playhead(job.run_main(hou.frame, timeout_s))
    total = len(frames)
    frame_rows: list[dict[str, Any]] = []
    merged: dict[str, dict[str, Any]] = {}
    started = time.perf_counter()
    cooked = 0
    playbar_note: str | None = None

    def step(frame: float) -> Any:
        playhead.before_step(hou.frame())
        out = _frame_step(paths, frame, force, summary)
        playhead.stepped(frame)
        return out

    try:
        for index, value in enumerate(frames):
            # The count is current, the frames finished (review 20 N7).
            job.set_progress(
                index, total, f"{index}/{total} frames done, cooking frame {_num(value)}"
            )
            reports, rows = job.run_main(lambda f=value: step(f), JOB_STEP_TIMEOUT_S)
            cooked += 1
            frame_rows.extend(rows)
            for report in reports:
                _merge_frame_report(merged, report, value)
    except ToolError as exc:
        if exc.code != "cancelled":
            raise
        # Review 17 P1-6: job result keeps what was cooked before the cancel.
        from .visual import cancelled_with_partial

        partial: dict[str, Any] = {"frames_cooked": cooked, "results": list(merged.values())}
        if summary == "bbox":
            partial.update(frame_summary(frame_rows))
        raise cancelled_with_partial(job, partial, f"{cooked} of {total} frames") from exc
    finally:
        playbar_note = _finish_playhead(ctx, playhead)
    job.set_progress(total, total, "done")
    increment = frames[1] - frames[0] if total > 1 else 1.0
    extra: dict[str, Any] = {
        "frame_range": [_num(frames[0]), _num(frames[-1]), _num(increment)],
        "frames_cooked": total,
        "total_ms": round((time.perf_counter() - started) * 1000, 1),
    }
    if summary == "bbox":
        extra.update(frame_summary(frame_rows))
    if playbar_note:
        extra["notes"] = [playbar_note]
    return [merged[p] for p in paths], extra


def writer_notes(paths: list[str]) -> list[str]:
    """Notes for nodes a cook does not make write anything (review 17 P0-1, review 18
    papercut 8): a ROP renders only through ``render``, and a File Cache passes its input
    through until saved. Main thread."""
    import hou

    from .visual import writer_rop

    notes = []
    for path in paths:
        node = hou.node(path)
        rop = writer_rop(node) if node is not None else None
        if rop is None:
            continue
        if rop is node:
            notes.append(
                f"Cooking {path} does not write files; render {{rop_path: {path}}} renders it."
            )
        else:
            notes.append(
                f"Cooking {path} does not write files: a cook passes its input through. "
                f"render {{rop_path: {path}}} saves its frame range as a job with progress and "
                f"cancel; {hint_tool('parm_set', path=f'{path}/execute', press=True)} saves in "
                "one blocking call."
            )
    return notes


@tool("cook", main_thread=False, scene=False)
def cook(args: dict[str, Any], ctx: HostContext) -> dict[str, Any]:
    paths = _paths_arg(args)
    force_arg = args.get("force", False)
    if force_arg is None:
        force_arg = False
    if not (isinstance(force_arg, bool) or force_arg == "chain"):
        raise bad_arg(
            f"'force' must be true, false or \"chain\" (got {force_arg!r}).",
            hint='force: true recooks the named nodes; "chain" recooks their inputs too.',
        )
    chain = force_arg == "chain"
    force = bool(force_arg)
    frame = _number(args, "frame", None)
    timeout_s = _number(args, "timeout_s", 30.0, positive=True)
    wait_arg = _number(args, "wait_s", None)
    if wait_arg is not None and wait_arg < 0:
        raise ToolError("invalid_argument", "'wait_s' must be a number >= 0.")
    profile = bool(args.get("profile", False))
    summary = args.get("summary", "none")
    if summary not in SUMMARIES:
        raise ToolError("invalid_argument", "'summary' must be 'bbox' or 'none'.")
    frames = None if args.get("frame_range") is None else _frame_list(args["frame_range"])
    if frames is not None and (profile or frame is not None):
        raise ToolError(
            "invalid_argument",
            "'frame_range' cannot be combined with 'profile' or 'frame'.",
            hint="Profile at one frame, or cook a range without profile.",
        )
    if chain and (frames is not None or profile):
        raise bad_arg(
            "force: \"chain\" cannot be combined with 'frame_range' or 'profile'.",
            hint="profile already force-cooks the input chain; cook a range with force: true.",
        )

    notes: list[str] = []

    def resolve() -> list[str]:
        resolved = [require_node(p).path() for p in paths]
        notes[:] = writer_notes(resolved)
        return resolved

    def work(job: Any, resolved: list[str]) -> dict[str, Any]:
        extra: dict[str, Any] = {}
        if frames is not None:
            results, extra = _ranged(job, ctx, resolved, frames, force, summary, timeout_s)
        elif profile:
            results, extra = _profiled(job, ctx, resolved, frame, timeout_s)
        elif chain:
            results = _chained(job, resolved, frame)
        else:
            results = _plain(job, resolved, force, frame)
        out: dict[str, Any] = {"ok": all(r["ok"] for r in results), "results": results}
        if frame is not None:
            out["frame"] = frame
        out.update(extra)
        if notes:
            out["notes"] = [*notes, *extra.get("notes", [])]
        return out

    if ctx.executor.on_main_thread():
        # Called inline on the main thread (GUI shell, tests): no job can make progress.
        return work(_Inline(), resolve())

    resolved = ctx.executor.run(resolve, timeout_s)
    label = resolved[0] if len(resolved) == 1 else f"{len(resolved)} nodes"
    started = ctx.jobs.start("cook", lambda job: work(job, resolved), label=label)
    # An explicit wait_s is the caller's own threshold, as on render (review 17 P2-8).
    wait_s = (
        float(wait_arg)
        if wait_arg is not None
        else min(timeout_s, float(ctx.config.job_threshold_s))
    )
    if started.done_event.wait(wait_s):
        # Returned synchronously: the caller never saw a job_id, so keep job list clean.
        ctx.jobs.discard(started.id)
        if started.state == "done":
            return started.result
        raise ToolError.from_dict(started.error or {"code": "internal", "message": "cook failed"})
    return {
        "job_id": started.id,
        "state": "running",
        "message": (
            f"Cooking {label} runs as a job (waited {wait_s:g}s); poll with "
            f"job {{action: status, job_id: {started.id}}} and fetch the result with action result."
        ),
    }


# -- problems ----------------------------------------------------------------------------

KIND_ORDER = {
    "error": 0,
    "failed_work_items": 0,
    "broken_reference": 1,
    "missing_file": 2,
    "unconnected_input": 3,
    "warning": 4,
}

# A literal first argument only: "material"+opdigits($CH) is built at run time.
_CH_RE = re.compile(
    r"\b(ch|chf|chi|chs|chsraw|chv|chp|chramp|chexpr|chexprf|chexprt)"
    r"\s*\(\s*[\"']([^\"']+)[\"']\s*[,)]"
)
_OP_RE = re.compile(
    r"\b(point|prim|vertex|detail|npoints|nprims|nvertices|bbox|centroid|opinputpath"
    r"|pointattrib|primattrib|details|points|prims)\s*\(\s*[\"']([^\"']+)[\"']\s*[,)]"
)
_PY_RE = re.compile(r"\bhou\.(parm|parmTuple|node)\(\s*[\"']([^\"']+)[\"']\s*[,)]")
_BACKTICK_RE = re.compile(r"`([^`]*)`")
_DYNAMIC = ("$", "`", "*", "?", "@", "^", "{", "[", " ")
_SEQUENCE_VAR_RE = re.compile(r"\$\{?(?:FF|SF|F\d*|T)(?![A-Za-z0-9_])")
"""Frame/time variables ($F, $F4, ${F}, $FF, $SF, $T) mark a sequence; $TEMP or $FOO do not."""
_SEQUENCE_MARKERS = (
    "<UDIM>",
    "<udim>",
    "%(UDIM",
    "<UVTILE",
    "%0",
    "*",
)
_SKIP_FILE_PREFIXES = ("op:", "temp:", "opdef:", "oplib:", "http:", "https:", "ftp:")
_SKIP_FILE_VALUES = {"stdout", "stdin", "ip", "md", "iprsocket", "null:"}
_OUTPUT_PARM_HINTS = ("output", "picture", "savepath", "savefile", "outfile", "export")
_SEARCH_SUBDIRS = ("", "geo/", "pic/", "vex/include/", "ocl/include/", "config/")
_NO_FILE_CHECK_CATEGORIES = {"Driver", "Top", "TopNet"}


def _row(node: Any, kind: str, message: str, **extra: Any) -> dict[str, Any]:
    row: dict[str, Any] = {"path": node.path(), "type": node.type().name(), "kind": kind}
    row.update({k: v for k, v in extra.items() if v is not None})
    row["message"] = message
    return row


def _parm_exists(node: Any, ref: str) -> bool:
    ref = ref[3:] if ref.startswith("op:") else ref
    return node.parm(ref) is not None or node.parmTuple(ref) is not None


def _node_exists(node: Any, ref: str) -> bool:
    ref = ref[3:] if ref.startswith("op:") else ref
    return node.node(ref) is not None


def _is_dynamic(ref: str) -> bool:
    return any(token in ref for token in _DYNAMIC) or ref.startswith(("opinput:", "opdef:"))


def expression_references(expression: str, language: str) -> list[tuple[str, str]]:
    """``[(kind, ref)]`` references in an expression; kind is ``parm`` or ``node``."""
    refs: list[tuple[str, str]] = []
    for match in _CH_RE.finditer(expression):
        refs.append(("parm", match.group(2)))
    if language == "hscript":
        for match in _OP_RE.finditer(expression):
            refs.append(("node", match.group(2)))
    else:
        for match in _PY_RE.finditer(expression):
            refs.append(("node" if match.group(1) == "node" else "parm", match.group(2)))
    return [(k, r) for k, r in refs if r.strip() and not _is_dynamic(r)]


def _broken_references(node: Any, parm: Any) -> list[dict[str, Any]]:
    import hou

    rows: list[dict[str, Any]] = []
    expressions: list[tuple[str, str]] = []
    try:
        if parm.isAtDefault():
            # Default expressions often reference a parent the type expects (HDA
            # internals, spare parms); only values the user set are worth reporting.
            return rows
        keys = parm.keyframes()
    except Exception:
        keys = ()
    if keys:
        seen: set[str] = set()
        for key in keys:
            try:
                text = key.expression()
                lang = key.expressionLanguage()
            except Exception:
                continue
            if text and text not in seen:
                seen.add(text)
                expressions.append(
                    (text, "python" if lang == hou.exprLanguage.Python else "hscript")
                )
    else:
        template = parm.parmTemplate()
        if template.type() == hou.parmTemplateType.String:
            try:
                raw = parm.unexpandedString()
            except Exception:
                raw = ""
            for chunk in _BACKTICK_RE.findall(raw):
                expressions.append((chunk, "hscript"))
            if (
                raw
                and template.stringType() == hou.stringParmType.NodeReference
                and "/" in raw  # skips menu tokens and placeholders like _input1_obj_
                and not _is_dynamic(raw)
                and not _node_exists(node, raw)
            ):
                rows.append(
                    _row(
                        node,
                        "broken_reference",
                        f"{node.path()}/{parm.name()} points at node {raw!r}, which does not exist.",
                        parm=parm.name(),
                        ref=raw,
                    )
                )
    for text, lang in expressions:
        for kind, ref in expression_references(text, lang):
            exists = _parm_exists(node, ref) if kind == "parm" else _node_exists(node, ref)
            if not exists:
                rows.append(
                    _row(
                        node,
                        "broken_reference",
                        f"{node.path()}/{parm.name()} expression {text.strip()!r} references "
                        f"{kind} {ref!r}, which does not exist.",
                        parm=parm.name(),
                        ref=ref,
                    )
                )
    return rows


def _file_exists(path: str) -> bool:
    if os.path.exists(path):
        return True
    if os.path.isabs(path) or re.match(r"^[A-Za-z]:[\\/]", path):
        return False
    import hou

    for base in (hou.text.expandString("$HIP"), hou.text.expandString("$JOB")):
        if base and os.path.exists(os.path.join(base, path)):
            return True
    # Bare names resolve through HOUDINI_PATH subdirectories (defcam.bgeo, Mandril.pic).
    for prefix in _SEARCH_SUBDIRS:
        try:
            hou.findFile(prefix + path)
            return True
        except Exception:
            continue
    return False


def _missing_file(node: Any, parm: Any) -> dict[str, Any] | None:
    import hou

    template = parm.parmTemplate()
    if template.type() != hou.parmTemplateType.String:
        return None
    if template.stringType() != hou.stringParmType.FileReference:
        return None
    name = parm.name().lower()
    if any(hint in name for hint in _OUTPUT_PARM_HINTS):
        return None
    try:
        if parm.isAtDefault():
            return None
        raw = parm.unexpandedString().strip()
    except Exception:
        return None
    if not raw or raw.lower() in _SKIP_FILE_VALUES or raw.lower().startswith(_SKIP_FILE_PREFIXES):
        return None
    if _SEQUENCE_VAR_RE.search(raw) or any(marker in raw for marker in _SEQUENCE_MARKERS):
        return None
    mode = node.parm("filemode")
    if mode is not None and mode.evalAsString() == "write":
        return None
    try:
        expanded = parm.evalAsString().strip()
    except Exception:
        return None
    if not expanded or expanded.lower().startswith(_SKIP_FILE_PREFIXES):
        return None
    if _file_exists(expanded):
        return None
    return _row(
        node,
        "missing_file",
        f"{node.path()}/{parm.name()} reads {expanded!r}, which does not exist"
        + (f" (raw {raw!r})." if raw != expanded else "."),
        parm=parm.name(),
        file=expanded,
    )


def _unconnected_inputs(node: Any) -> list[dict[str, Any]]:
    try:
        required = node.type().minNumInputs()
    except Exception:
        return []
    rows = []
    if required <= 0:
        return rows
    try:
        labels = node.inputLabels()
    except Exception:
        labels = ()
    for index in range(required):
        if node.input(index) is None:
            label = labels[index] if index < len(labels) else f"input {index}"
            rows.append(
                _row(
                    node,
                    "unconnected_input",
                    f"{node.path()} needs input {index} ({label}) connected; it is empty.",
                    input=index,
                    label=label,
                )
            )
    return rows


_NODE_PATH_RE = re.compile(r"(?<![\w:./$`-])(/[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*)")
"""An absolute node path in a message (``/mat/mt_glass``); not a drive path's tail."""


def _now_exists(node: Any, text: str) -> str | None:
    """A hint when an error or warning names a node that exists now (2.1, D81): the
    message predates it (a Material SOP cooked before its material existed, r21 friction
    4), and the node has not cooked since. None otherwise."""
    import hou

    try:
        if node.needsToCook():
            return None
    except Exception:
        return None
    found = []
    for path in _NODE_PATH_RE.findall(text):
        path = path.rstrip(".")
        if path in found or path == node.path() or node.path().startswith(path + "/"):
            continue  # the node itself or a network around it says nothing
        with contextlib.suppress(Exception):
            if hou.node(path) is not None:
                found.append(path)
    if not found:
        return None
    recheck = hint_tool("cook", paths=[node.path()], force=True)
    names = ", ".join(found[:3])
    verb = "exists" if len(found) == 1 else "exist"
    tail = f"; {recheck} rechecks it" if recheck else ""
    return f"{names} {verb} now: this message may predate it{tail}."


_RECHECK_CATEGORIES = REFRESH_CATEGORIES | {"Object"}
"""An object's errors and warnings mirror its display SOP's, so it is rechecked too."""


def node_problems(
    node: Any, *, include_warnings: bool, cook_uncooked: bool
) -> tuple[list[dict[str, Any]], bool]:
    """All problem rows for one node and whether it was cooked. Main thread."""
    rows: list[dict[str, Any]] = []
    category = node.type().category().name()
    should_cook = False
    try:
        if node.needsToCook():
            # Errors on a node changed since its last cook may be gone: recheck them
            # (cheap categories only) so problems never lists a fixed node.
            should_cook = (cook_uncooked and category in COOKABLE_CATEGORIES) or (
                category in _RECHECK_CATEGORIES
                and bool(node.errors() or node.warnings())
                and not is_slow(node)
            )
    except Exception:
        should_cook = False
    report = collect_problems(node, cook=should_cook)
    for text in report["errors"]:
        rows.append(_row(node, "error", f"{node.path()}: {text}", hint=_now_exists(node, text)))
    if include_warnings:
        for text in report["warnings"]:
            rows.append(
                _row(node, "warning", f"{node.path()}: {text}", hint=_now_exists(node, text))
            )
    try:
        # Parms inside a locked asset are the asset's own (often non-default, often
        # referencing parents the asset expects); scanning them is slow and noisy.
        in_locked = bool(node.isInsideLockedHDA())
    except Exception:
        in_locked = False
    if not in_locked:
        check_files = node.type().category().name() not in _NO_FILE_CHECK_CATEGORIES
        for parm in node.parms():
            try:
                if parm.isAtDefault():
                    continue  # only values the user set are worth checking
                rows.extend(_broken_references(node, parm))
                if check_files:
                    missing = _missing_file(node, parm)
                    if missing is not None:
                        rows.append(missing)
            except Exception:
                continue
    rows.extend(_unconnected_inputs(node))
    if category == "Top":
        # Failed work items leave the node itself error-free (review 14 papercut 5).
        from .pdg import failed_items_problem

        with contextlib.suppress(Exception):
            failed = failed_items_problem(node)
            if failed is not None:
                rows.append(failed)
    return rows, should_cook


def _mirrored_texts(node: Any, texts: dict[str, set[str]]) -> set[str]:
    """Error/warning texts already reported by an object's display SOP."""
    try:
        display = node.displayNode() if node.type().category().name() == "Object" else None
    except Exception:
        display = None
    return texts.get(display.path(), set()) if display is not None else set()


PROBLEMS_BUDGET_S = 10.0
"""Default scan budget; ``timeout_s`` sets it to half the call's timeout instead."""


def _parse_problems_cursor(cursor: Any) -> tuple[int, int, int | None]:
    """``"<rows>"``, ``"<rows>@<start>"`` or ``"<rows>@<start>:<end>"`` -> (row offset,
    first node, end node or None). ``start``/``end`` index the walk order; an ``end``
    rescans exactly that slice (a later page of rows within a partial scan)."""
    if cursor in (None, ""):
        return 0, 0, None
    end: int | None = None
    try:
        rows, _, nodes = str(cursor).partition("@")
        start, _, stop = nodes.partition(":")
        offset, node_start = int(rows), int(start or 0)
        end = int(stop) if stop else None
    except ValueError:
        offset = node_start = -1
    if offset < 0 or node_start < 0 or (end is not None and end <= node_start):
        raise ToolError(
            "invalid_argument",
            f"Invalid cursor {cursor!r}.",
            hint="Pass next_cursor from the previous result unchanged.",
        )
    return offset, node_start, end


def _problems_budget(args: dict[str, Any]) -> float:
    raw = args.get("timeout_s")
    if isinstance(raw, int | float) and not isinstance(raw, bool) and raw > 0:
        return float(raw) * 0.5
    return min(PROBLEMS_BUDGET_S, float(call_timeout(60.0) or 60.0) * 0.5)


def problems(args: dict[str, Any], ctx: HostContext) -> dict[str, Any]:
    root_path = args.get("root") or "/"
    include_warnings = bool(args.get("include_warnings", True))
    cook_uncooked = bool(args.get("cook_uncooked", False))
    recurse_locked = bool(args.get("recurse_locked", False))
    limit = parse_limit(args.get("limit"))
    offset, node_start, node_end = _parse_problems_cursor(args.get("cursor"))
    budget_s = _problems_budget(args)
    deadline = time.monotonic() + budget_s
    root = require_node(root_path, field="root")
    nodes = [] if root.path() == "/" else [root]
    nodes.extend(
        root.allSubChildren(
            top_down=True,
            recurse_in_locked_nodes=recurse_locked,
            sync_delayed_definition=recurse_locked,  # locked HDA contents load lazily
        )
    )

    ranked: list[tuple[int, int, dict[str, Any]]] = []
    cooked = 0
    flagged: set[str] = set()
    texts: dict[str, set[str]] = {}
    seen_rows: set[tuple[str, str, str]] = set()
    # Children before their containers, so a rechecked object sees its fresh SOPs.
    order = list(reversed(list(enumerate(nodes))))
    scan_end = len(order) if node_end is None else min(node_end, len(order))
    for index in range(node_start, scan_end):
        if node_end is None and index > node_start and time.monotonic() > deadline:
            scan_end = index
            break
        position, node = order[index]
        node_rows, was_cooked = node_problems(
            node, include_warnings=include_warnings, cook_uncooked=cook_uncooked
        )
        cooked += int(was_cooked)
        mirrored = _mirrored_texts(node, texts)
        kept = []
        for row in node_rows:
            text = row["message"].split(": ", 1)[-1]
            if row["kind"] in ("error", "warning"):
                if text in mirrored:
                    continue  # an object repeating its display SOP's message
                texts.setdefault(row["path"], set()).add(text)
            key = (row["path"], row["kind"], row["message"])
            if key in seen_rows:
                continue
            seen_rows.add(key)
            kept.append(row)
        if kept:
            flagged.add(node.path())
        ranked.extend((KIND_ORDER.get(row["kind"], 9), position, row) for row in kept)
    ranked.sort(key=lambda item: item[:2])
    ordered = [item[2] for item in ranked]
    counts: dict[str, int] = {}
    for row in ordered:
        counts[row["kind"]] = counts.get(row["kind"], 0) + 1
    page = ordered[offset : offset + limit]
    incomplete = scan_end < len(order)
    partial = incomplete or node_start > 0
    result: dict[str, Any] = {
        "root": root.path(),
        "problems": page,
        "total": len(ordered),
        "counts": counts,
        "nodes_scanned": scan_end - node_start,
        "nodes_with_problems": len(flagged),
    }
    if cook_uncooked or cooked:
        result["cooked"] = cooked
    suffix = f"@{node_start}:{scan_end}" if partial else ""
    if offset + limit < len(ordered):
        # More rows in this slice of nodes: the next page rescans the same slice.
        result["next_cursor"] = f"{offset + limit}{suffix}"
    elif incomplete:
        result["next_cursor"] = f"0@{scan_end}"
    if partial:
        # total, counts and nodes_with_problems cover only this slice of the walk.
        result["nodes_total"] = len(order)
        result["node_offset"] = node_start
    if incomplete:
        result["incomplete"] = True
        result["message"] = (
            f"Stopped after {budget_s:g} s with {len(order) - scan_end} of {len(order)} nodes "
            "left to scan; pass next_cursor to continue."
        )
    elif not ordered:
        result["message"] = f"No problems under {root.path()}." + (
            ""
            if cook_uncooked
            else " Uncooked nodes report no errors; pass cook_uncooked to cook them first."
        )
    return result

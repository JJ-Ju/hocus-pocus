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

import os
import re
import time
from typing import Any

from hocuspocus.tools.errors import ToolError

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
    "included. Use profile: true to time the whole input chain."
)

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
        report = collect_problems(node, cook=True, force=force)
    finally:
        if switch:
            hou.setFrame(previous)
    row: dict[str, Any] = {"path": node.path(), "ok": not report["errors"]}
    row.update(report)
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


def _profile_step(node_path: str) -> dict[str, Any]:
    """Force-cook one chain node and time it. Main thread."""
    node = require_node(node_path)
    elapsed, failure = timed_cook(node, True)
    row: dict[str, Any] = {
        "path": node.path(),
        "type": node.type().name(),
        "cook_time_ms": round(elapsed, 1),
    }
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


class _Inline:
    """Stands in for a job when ``cook`` runs on the main thread itself (GUI shell, tests)."""

    def run_main(self, fn: Any, timeout_s: float | None = None) -> Any:
        return fn()

    def set_progress(self, current: int, total: int, message: str | None = None) -> None:
        pass


def _plain(job: Any, paths: list[str], force: bool, frame: float | None) -> list[dict[str, Any]]:
    results = []
    for index, path in enumerate(paths):
        job.set_progress(index, len(paths), f"cooking {path}")
        results.append(
            job.run_main(lambda p=path: cook_node(p, force=force, frame=frame), JOB_STEP_TIMEOUT_S)
        )
    job.set_progress(len(paths), len(paths), "done")
    return results


def _profiled(
    job: Any, ctx: HostContext, paths: list[str], frame: float | None, timeout_s: float
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Force-cook every node's input chain in dependency order, one step per node."""
    import hou

    def chain_paths() -> list[str]:
        ordered: list[str] = []
        for path in paths:
            for node in dependency_order(require_node(path)):
                if node.path() not in ordered:
                    ordered.append(node.path())
        return ordered

    chain = job.run_main(chain_paths, timeout_s)
    previous = job.run_main(hou.frame, timeout_s)
    steps = len(chain) + len(paths)
    rows: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    try:
        if frame is not None:
            job.run_main(lambda: hou.setFrame(frame), timeout_s)
        for index, path in enumerate(chain):
            job.set_progress(index, steps, f"cooking {path} ({index + 1}/{len(chain)})")
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
    total_ms = round(sum(r["cook_time_ms"] for r in rows), 1)
    rows.sort(key=lambda r: r["cook_time_ms"], reverse=True)
    return results, {"chain": rows[:10], "chain_total": len(rows), "total_ms": total_ms}


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

    previous = job.run_main(hou.frame, timeout_s)
    total = len(frames)
    frame_rows: list[dict[str, Any]] = []
    merged: dict[str, dict[str, Any]] = {}
    started = time.perf_counter()
    try:
        for index, value in enumerate(frames):
            job.set_progress(index, total, f"frame {index + 1}/{total}")
            reports, rows = job.run_main(
                lambda f=value: _frame_step(paths, f, force, summary), JOB_STEP_TIMEOUT_S
            )
            frame_rows.extend(rows)
            for report in reports:
                _merge_frame_report(merged, report, value)
    finally:
        _restore_frame(ctx, previous)
    job.set_progress(total, total, "done")
    step = frames[1] - frames[0] if total > 1 else 1.0
    extra: dict[str, Any] = {
        "frame_range": [_num(frames[0]), _num(frames[-1]), _num(step)],
        "frames_cooked": total,
        "total_ms": round((time.perf_counter() - started) * 1000, 1),
    }
    if summary == "bbox":
        extra["frames"] = frame_rows
    return [merged[p] for p in paths], extra


@tool("cook", main_thread=False, scene=False)
def cook(args: dict[str, Any], ctx: HostContext) -> dict[str, Any]:
    paths = _paths_arg(args)
    force = bool(args.get("force", False))
    frame = _number(args, "frame", None)
    timeout_s = _number(args, "timeout_s", 30.0, positive=True)
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

    def resolve() -> list[str]:
        return [require_node(p).path() for p in paths]

    def work(job: Any, resolved: list[str]) -> dict[str, Any]:
        extra: dict[str, Any] = {}
        if frames is not None:
            results, extra = _ranged(job, ctx, resolved, frames, force, summary, timeout_s)
        elif profile:
            results, extra = _profiled(job, ctx, resolved, frame, timeout_s)
        else:
            results = _plain(job, resolved, force, frame)
        out: dict[str, Any] = {"ok": all(r["ok"] for r in results), "results": results}
        if frame is not None:
            out["frame"] = frame
        out.update(extra)
        return out

    if ctx.executor.on_main_thread():
        # Called inline on the main thread (GUI shell, tests): no job can make progress.
        return work(_Inline(), resolve())

    resolved = ctx.executor.run(resolve, timeout_s)
    label = resolved[0] if len(resolved) == 1 else f"{len(resolved)} nodes"
    started = ctx.jobs.start("cook", lambda job: work(job, resolved), label=label)
    wait_s = min(timeout_s, float(ctx.config.job_threshold_s))
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
            f"Cooking {label} is taking longer than {wait_s:g}s; poll with "
            f"job {{action: status, job_id: {started.id}}} and fetch the result with action result."
        ),
    }


# -- problems ----------------------------------------------------------------------------

KIND_ORDER = {
    "error": 0,
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
        rows.append(_row(node, "error", f"{node.path()}: {text}"))
    if include_warnings:
        for text in report["warnings"]:
            rows.append(_row(node, "warning", f"{node.path()}: {text}"))
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
            hint="Pass next_cursor from the previous problems result unchanged.",
        )
    return offset, node_start, end


def _problems_budget(args: dict[str, Any]) -> float:
    raw = args.get("timeout_s")
    if isinstance(raw, int | float) and not isinstance(raw, bool) and raw > 0:
        return float(raw) * 0.5
    return min(PROBLEMS_BUDGET_S, float(call_timeout(60.0) or 60.0) * 0.5)


@tool("problems")
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

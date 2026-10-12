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
from ._diag import (
    COOKABLE_CATEGORIES,
    REFRESH_CATEGORIES,
    collect_problems,
    is_slow,
    require_node,
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
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ToolError("invalid_argument", f"'{key}' must be a number.")
    if positive and value <= 0:
        raise ToolError("invalid_argument", f"'{key}' must be greater than 0.")
    return float(value)


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
    return row


@tool("cook", main_thread=False, scene=False)
def cook(args: dict[str, Any], ctx: HostContext) -> dict[str, Any]:
    paths = _paths_arg(args)
    force = bool(args.get("force", False))
    frame = _number(args, "frame", None)
    timeout_s = _number(args, "timeout_s", 30.0, positive=True)

    def resolve() -> list[str]:
        return [require_node(p).path() for p in paths]

    def finish(results: list[dict[str, Any]]) -> dict[str, Any]:
        out: dict[str, Any] = {"ok": all(r["ok"] for r in results), "results": results}
        if frame is not None:
            out["frame"] = frame
        return out

    if ctx.executor.on_main_thread():
        # Called inline on the main thread (GUI shell, tests): no job can make progress.
        resolved = resolve()
        return finish([cook_node(p, force=force, frame=frame) for p in resolved])

    resolved = ctx.executor.run(resolve, timeout_s)

    def work(job: Any) -> dict[str, Any]:
        results = []
        for index, path in enumerate(resolved):
            job.progress(index / len(resolved), f"cooking {path}")
            results.append(
                job.run_main(
                    lambda p=path: cook_node(p, force=force, frame=frame), JOB_STEP_TIMEOUT_S
                )
            )
        job.progress(1.0, "done")
        return finish(results)

    label = resolved[0] if len(resolved) == 1 else f"{len(resolved)} nodes"
    started = ctx.jobs.start("cook", work, label=label)
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
    limit = args.get("limit", 50)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
        raise ToolError("invalid_argument", "'limit' must be an integer from 1 to 1000.")
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

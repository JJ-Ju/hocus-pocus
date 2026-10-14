"""``inspect`` (spec-2.0 §2.3): one read tool over the 1.4 reads.

``{target?, what, ...options}`` dispatches to the registered implementation of the 1.4 tool
that reads ``what`` (``node_info``, ``parm_get``, ``network_describe``, ``geo_info`` /
``geo_read``, ``usd_stage``, ``problems``, ``node_type_info``, ``events``, ``job``), looked
up in the host registry at call time, so the read code exists once and a reimplementation
of a 1.4 tool (spec-2.0 §4, ``host/tx.py``) is picked up here too. The result is
``{etag, ...the 1.4 result}``: the caller knows its ``what`` and ``target``, so they are not
echoed. Two reads are shaped for 2.0 (:func:`shape`): ``node`` rows leave out
``session_id``; ``outline`` leaves out ``format`` and, per row, ``name`` when it is the
path's last segment, ``errors: 0``, and ``inputs`` unless ``wiring: true``.

Registered with ``main_thread=False`` because two of its reads must not hold the main
thread (``events`` and ``job`` run off it in 1.4); the others run on it through the
executor, in one main-thread step together with their etag, as the 1.4 tool would.

The etag (spec-2.0 §2.7) is ``"<pid>:<scene_generation>:<h>"``, ``h`` the first 16 hex
digits of a BLAKE2b digest of the canonical JSON of the result body (sorted keys, compact
separators; :func:`hocuspocus.host.resources.content_etag`). The host builds the body
anyway, so the etag moves exactly when the answer does: a recook that changes nothing (a
``look``, a ``cook`` elsewhere) keeps it, and a resource read with ``If-None-Match`` answers
``not_modified``. ``scene_generation`` moves on every hip load, clear and merge.
"""

from __future__ import annotations

import fnmatch
from collections.abc import Callable
from typing import Any

from hocuspocus.tools.errors import ToolError

from ..dispatch import _CALL, call_timeout, current_request_id
from ..resources import content_etag
from ._common import bad_arg, get_node
from .registry import HostContext, tool
from .registry import get as get_tool

WHATS: tuple[str, ...] = (
    "node", "parms", "network", "outline", "geo", "image", "stage", "problems", "type",
    "events", "jobs",
)  # fmt: skip
"""``what`` values, in the order of spec-2.0 §2.3."""

GEO_READ_OPTIONS = frozenset({"class", "attribs", "start", "count", "group", "stats", "cursor"})

OPTIONS: dict[str, frozenset[str]] = {
    "node": frozenset({"paths", "include", "include_defaults", "recurse_locked"}),
    "parms": frozenset({"paths", "frame", "include", "full_strings", "include_defaults", "parms"}),
    "network": frozenset(
        {"depth", "include_defaults", "include_positions", "recurse_locked", "cursor"}
    ),
    "outline": frozenset({"depth", "recurse_locked", "cursor", "wiring"}),
    "geo": frozenset({"frame", "attributes", "rows"}) | GEO_READ_OPTIONS,
    "image": frozenset({"frame"}),
    "stage": frozenset(
        {"prim", "depth", "include", "attribs", "summary", "time", "limit", "cursor"}
    ),
    "problems": frozenset(
        {"include_warnings", "cook_uncooked", "recurse_locked", "timeout_s", "limit", "cursor"}
    ),
    "type": frozenset({"category", "include_parms", "include_help", "folder", "parms", "detail"}),
    "events": frozenset({"since", "limit"}),
    "jobs": frozenset({"job_id"}),
}
"""The options each ``what`` takes: the arguments of its 1.4 tool (spec ``notes``)."""

TARGET_REQUIRED = frozenset({"network", "geo", "image", "stage", "type"})
NO_TARGET = frozenset({"events", "jobs"})


# -- running a 1.4 read -------------------------------------------------------------------


def _impl(name: str) -> Callable[[dict[str, Any], HostContext], Any]:
    registered = get_tool(name)
    if registered is None:  # pragma: no cover - every 1.4 read is registered
        raise ToolError("internal", f"inspect: the {name} implementation is not registered.")
    return registered.fn


def _on_main(ctx: HostContext, fn: Callable[[], Any]) -> Any:
    """``fn()`` on the main thread, with the call's timeout and request id visible to it
    (``call_timeout``, ``current_request_id``) as they are to a main-thread tool."""
    timeout_s = call_timeout(float(getattr(ctx.config, "default_timeout_s", 30.0)))
    request_id = current_request_id()

    def work() -> Any:
        saved = (getattr(_CALL, "timeout_s", None), getattr(_CALL, "request_id", None))
        _CALL.timeout_s, _CALL.request_id = timeout_s, request_id
        try:
            return fn()
        finally:
            _CALL.timeout_s, _CALL.request_id = saved

    return ctx.executor.run(work, timeout_s)


# -- arguments -----------------------------------------------------------------------------


def _check_args(what: str, target: Any, options: dict[str, Any]) -> None:
    allowed = OPTIONS[what]
    extra = sorted(set(options) - allowed)
    if extra:
        raise bad_arg(
            f"what: {what} does not take {', '.join(extra)}.",
            hint=f"{what} takes {', '.join(sorted(allowed)) or 'no options'} "
            "(docs/tools.md, inspect notes).",
        )
    if what in NO_TARGET and target is not None:
        raise bad_arg(f"what: {what} takes no target.", hint="Leave target out.")
    if target is not None and (not isinstance(target, str) or not target):
        raise bad_arg("'target' must be a non-empty path string.")
    if what in TARGET_REQUIRED and target is None:
        noun = "a node type such as Sop/scatter" if what == "type" else "a node path"
        raise bad_arg(f"what: {what} needs target ({noun}).")
    if what in ("node", "parms"):
        if target is None and options.get("paths") is None:
            raise bad_arg(f"what: {what} needs target or paths.")
        if target is not None and options.get("paths") is not None:
            raise bad_arg("Pass target or paths, not both.")
    if what == "outline" and not isinstance(options.get("wiring", False), bool):
        raise bad_arg("'wiring' must be a boolean.")
    if what == "geo":
        rows = options.get("rows", False)
        if not isinstance(rows, bool):
            raise bad_arg("'rows' must be a boolean.")
        wrong = sorted(set(options) & (frozenset({"attributes"}) if rows else GEO_READ_OPTIONS))
        if wrong:
            mode = "rows: true (geo_read)" if rows else "the geo summary (geo_info)"
            raise bad_arg(
                f"{', '.join(wrong)} {'is' if len(wrong) == 1 else 'are'} not an option of {mode}.",
                hint="rows: true reads values (class, attribs, start, count, group, stats, "
                "cursor); without it the summary takes attributes.",
            )


def _glob_match(text: str, pattern: str) -> bool:
    return any(
        fnmatch.fnmatchcase(text.lower(), alt.strip().lower())
        for alt in pattern.split("|")
        if alt.strip()
    )


def _node_parm_paths(node: Any, pattern: Any, include_defaults: bool) -> list[str]:
    """The parm tuple paths of ``node`` that ``what: parms`` reads: those whose name or
    label matches ``pattern`` (a glob, ``a|b``), else the non-default ones (all with
    ``include_defaults``). Valueless templates (folders, separators, labels, buttons) are
    left out, as node_info leaves them out."""
    import hou

    from . import nodes

    names = getattr(nodes, "_VALUELESS_TEMPLATES", ("Folder", "FolderSet", "Separator", "Label"))
    skip = {getattr(hou.parmTemplateType, n) for n in names if hasattr(hou.parmTemplateType, n)}
    is_block = getattr(nodes, "_is_multiparm_block", lambda template: False)
    if pattern is not None and (not isinstance(pattern, str) or not pattern.strip()):
        raise bad_arg("'parms' must be a non-empty glob such as *seed* or size|t.")
    paths = []
    for parm_tuple in node.parmTuples():
        try:
            template = parm_tuple.parmTemplate()
            if template.type() in skip and not is_block(template):
                continue
            if pattern is not None:
                if not (
                    _glob_match(parm_tuple.name(), pattern)
                    or _glob_match(template.label() or "", pattern)
                ):
                    continue
            elif not include_defaults and parm_tuple.isAtDefault():
                continue
        except Exception:
            continue
        paths.append(f"{node.path()}/{parm_tuple.name()}")
    return paths


def _parms_args(target: Any, options: dict[str, Any]) -> dict[str, Any] | None:
    """``parm_get`` arguments (``None`` when a node has no parm to read)."""
    import hou

    rest = {k: v for k, v in options.items() if k not in ("parms", "include_defaults", "paths")}
    node = hou.node(target) if isinstance(target, str) and target.startswith("/") else None
    if node is None:
        if "parms" in options or "include_defaults" in options:
            raise bad_arg(
                "parms and include_defaults apply when target is a node.",
                hint="Pass the node's path as target, or parm paths without them.",
            )
        paths = options.get("paths") if target is None else [target]
        return {"paths": paths, **rest}
    include_defaults = options.get("include_defaults", False)
    if not isinstance(include_defaults, bool):
        raise bad_arg("'include_defaults' must be a boolean.")
    paths = _node_parm_paths(node, options.get("parms"), include_defaults)
    return {"paths": paths, **rest} if paths else None


def _image_check(target: str) -> None:
    from .visual import cop_image_node, is_cop_network

    node = get_node(target, field="target")
    if cop_image_node(node) is None and not is_cop_network(node):
        raise bad_arg(
            f"{node.path()} is not a Cop node or COP network.",
            hint="what: image reads Copernicus images; what: geo reads SOP geometry.",
        )


# -- etag ----------------------------------------------------------------------------------


def make_etag(ctx: HostContext, body: Any) -> str:
    """``<pid>:<scene_generation>:<16 hex>`` of the canonical body (without its etag)."""
    return content_etag(ctx.scene.generation, body, pid=ctx.pid)


# -- 2.0 shaping ---------------------------------------------------------------------------


INSPECT_ONLY = frozenset({"wiring"})
"""Options ``inspect`` takes itself; they are not passed to the 1.4 read."""


def _compact_outline(rows: Any, wiring: bool) -> None:
    for row in rows if isinstance(rows, list) else ():
        if not isinstance(row, dict):
            continue
        path = row.get("path")
        if isinstance(path, str) and row.get("name") == path.rsplit("/", 1)[-1]:
            del row["name"]
        if row.get("errors") == 0:
            del row["errors"]
        if row.get("children_count") == 0:
            del row["children_count"]
        if not wiring:
            row.pop("inputs", None)
        _compact_outline(row.get("children"), wiring)


def shape(what: str, result: dict[str, Any], options: dict[str, Any]) -> dict[str, Any]:
    """The 2.0 shape of a 1.4 read (in place): what the caller already knows, or did not
    ask for, is left out."""
    if what == "node":
        for row in result.get("nodes") or ():
            if isinstance(row, dict):
                row.pop("session_id", None)
    elif what == "outline":
        result.pop("format", None)
        _compact_outline(result.get("nodes"), options.get("wiring") is True)
    return result


# -- the tool ------------------------------------------------------------------------------


def _scene_read(
    ctx: HostContext, what: str, target: Any, options: dict[str, Any]
) -> dict[str, Any]:
    """One main-thread step: the 1.4 read, shaped for 2.0, with its etag."""
    if what == "node":
        paths = options.get("paths") if target is None else [target]
        args = {"paths": paths, **{k: v for k, v in options.items() if k != "paths"}}
        result = _impl("node_info")(args, ctx)
    elif what == "parms":
        parm_args = _parms_args(target, options)
        result = {"parms": []} if parm_args is None else _impl("parm_get")(parm_args, ctx)
    elif what in ("network", "outline"):
        root = target if target is not None else "/"
        fmt = "data" if what == "network" else "outline"
        passed = {k: v for k, v in options.items() if k not in INSPECT_ONLY}
        result = _impl("network_describe")({"root": root, "format": fmt, **passed}, ctx)
    elif what == "geo":
        rows = options.get("rows", False)
        args = {"path": target, **{k: v for k, v in options.items() if k != "rows"}}
        result = _impl("geo_read" if rows else "geo_info")(args, ctx)
    elif what == "image":
        _image_check(target)
        result = _impl("geo_info")({"path": target, **options}, ctx)
    elif what == "stage":
        result = _impl("usd_stage")({"lop_path": target, **options}, ctx)
    elif what == "problems":
        args = dict(options) if target is None else {"root": target, **options}
        result = _impl("problems")(args, ctx)
    else:  # type
        result = _impl("node_type_info")({"type": target, **options}, ctx)
    body = shape(what, result, options)
    return {"etag": make_etag(ctx, body), **body}


@tool("inspect", main_thread=False)
def inspect(args: dict[str, Any], ctx: HostContext) -> dict[str, Any]:
    what = args.get("what")
    if what not in WHATS:
        raise bad_arg(
            f"'what' must be one of {', '.join(WHATS)}; got {what!r}.",
            candidates=list(WHATS),
        )
    target = args.get("target")
    options = {k: v for k, v in args.items() if k not in ("what", "target")}
    _check_args(what, target, options)
    if what == "events":
        result = _impl("events")(options, ctx)
    elif what == "jobs":
        job_id = options.get("job_id")
        call = {"action": "list"} if job_id is None else {"action": "status", "job_id": job_id}
        result = _impl("job")(call, ctx)
    else:
        return _on_main(ctx, lambda: _scene_read(ctx, what, target, options))
    return {"etag": make_etag(ctx, result), **result}

"""Resource templates with ETags (spec-2.0 §2.7, §4): ``GET /hp/v2/resource?uri=...``.

A ``houdini://`` URI is parsed here into the ``inspect`` (or ``search``, or the host's
``houdini_status``) call it stands for, and that call runs through the host dispatcher
exactly as ``POST /hp/v1/call`` runs it, so the resource body is byte for byte the tool's
result for the same options (the ``inspect`` result carries its ``etag``). The route answers ``{uri, etag, body}``, or ``{uri, etag, not_modified: true}``
when the request's ``If-None-Match`` names the current etag (the read still runs: the
saving is the bytes on the wire and in the model's context).

Templates (RFC 6570; a ``{path}`` may be percent-encoded, ``%2Fobj%2Fgeo1``, or plain,
``obj/geo1``; list values are comma-separated)::

    houdini://node/{path}{?include,parms,include_defaults}   inspect node (parms: what parms)
    houdini://outline{?root,depth}                           inspect outline
    houdini://network/{path}{?depth,format}                  inspect network (format outline)
    houdini://geo/{path}{?frame,class,attribs,start,count,stats}  inspect geo (rows with any
                                                              of class..stats)
    houdini://image/{path}                                   inspect image
    houdini://stage/{lop}{?prim,include,time,summary}        inspect stage
    houdini://type/{category}/{name}{?parms,folder,detail}   inspect type
    houdini://types{?q,category,limit,cursor}                search kind types
    houdini://problems{?root}                                inspect problems
    houdini://events{?since,limit}                           inspect events
    houdini://jobs                                           inspect jobs
    houdini://status                                         the host's houdini_status
    houdini://instances                                      served by the bridge only

Every etag is :func:`content_etag`: ``<pid>:<scene_generation>:<16 hex>``, the first 16
hex digits of a BLAKE2b digest of the canonical JSON of the body (sorted keys, compact
separators, an ``inspect`` body without its own ``etag`` key), so it moves exactly when
the body does and a recook that changes nothing keeps it (spec-2.0 §2.7, M4). The
``inspect`` result carries the same etag (``host/tools/inspect.py``). ``_meta.events_seq`` (the event ring buffer's last seq)
lets the bridge's subscription poller skip re-reading nodes while nothing happened.

Parsing is pure Python (no ``hou``), shared with the bridge (``bridge/resources.py``).
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qsl, unquote

from hocuspocus.tools.errors import ToolError

SCHEME = "houdini://"
ETAG_HEX = 16

TEMPLATES: tuple[tuple[str, str, str], ...] = (
    (
        "houdini://node/{path}{?include,parms,include_defaults}",
        "node",
        "inspect what: node (with parms: what: parms, a glob).",
    ),
    ("houdini://outline{?root,depth}", "outline", "inspect what: outline (root / by default)."),
    (
        "houdini://network/{path}{?depth,format}",
        "network",
        "inspect what: network (format: outline for the outline).",
    ),
    (
        "houdini://geo/{path}{?frame,class,attribs,start,count,stats}",
        "geo",
        "inspect what: geo; class, attribs, start, count or stats read rows.",
    ),
    ("houdini://image/{path}", "image", "inspect what: image (a Cop node or COP network)."),
    ("houdini://stage/{lop}{?prim,include,time,summary}", "stage", "inspect what: stage."),
    (
        "houdini://type/{category}/{name}{?parms,folder,detail}",
        "type",
        "inspect what: type, e.g. houdini://type/Sop/scatter.",
    ),
    ("houdini://types{?q,category,limit,cursor}", "types", "search kind: types (q is the query)."),
    ("houdini://problems{?root}", "problems", "inspect what: problems (root / by default)."),
    ("houdini://events{?since,limit}", "events", "inspect what: events."),
)
"""The §2.7 templates as the bridge advertises them: ``(template, name, description)``."""

PARAMS: dict[str, tuple[str, ...]] = {
    "node": ("include", "parms", "include_defaults"),
    "outline": ("root", "depth"),
    "network": ("depth", "format"),
    "geo": ("frame", "class", "attribs", "start", "count", "stats"),
    "image": (),
    "stage": ("prim", "include", "time", "summary"),
    "type": ("parms", "folder", "detail"),
    "types": ("q", "category", "limit", "cursor"),
    "problems": ("root",),
    "events": ("since", "limit"),
    "jobs": (),
    "status": (),
    "instances": (),
}
"""The query variables each kind takes."""

WITH_PATH = frozenset({"node", "network", "geo", "image", "stage", "type"})
BRIDGE_ONLY = frozenset({"instances"})
SUBSCRIBABLE = frozenset({"status", "jobs", "events", "node"})
"""Kinds a client may subscribe to (spec-2.0 §2.7)."""
GEO_ROWS = frozenset({"class", "attribs", "start", "count", "stats"})

_INTS = frozenset({"depth", "start", "count", "limit"})
_NUMBERS = frozenset({"frame", "time"})
_BOOLS = frozenset({"include_defaults", "stats", "summary"})
_LISTS = frozenset({"include", "attribs"})
_TRUE = ("1", "true", "yes", "on", "")
_FALSE = ("0", "false", "no", "off")


@dataclass(frozen=True)
class Route:
    """What a resource URI reads: ``tool`` with ``args`` (``tool`` empty for a kind only
    the bridge serves)."""

    uri: str
    kind: str
    tool: str
    args: dict[str, Any] = field(default_factory=dict)


def _bad(message: str, hint: str | None = None) -> ToolError:
    return ToolError(
        "invalid_argument",
        message,
        hint=hint or "resources/templates/list lists the templates (houdini://node/{path}, ...).",
    )


def _node_path(raw: str) -> str:
    path = unquote(raw)
    return "/" + path.lstrip("/")


def _value(name: str, raw: str) -> Any:
    if name in _BOOLS:
        low = raw.strip().lower()
        if low in _TRUE:
            return True
        if low in _FALSE:
            return False
        raise _bad(f"Resource variable {name} must be true or false, not {raw!r}.")
    if name in _INTS:
        try:
            return int(raw)
        except ValueError:
            raise _bad(f"Resource variable {name} must be an integer, not {raw!r}.") from None
    if name in _NUMBERS:
        try:
            number = float(raw)
        except ValueError:
            raise _bad(f"Resource variable {name} must be a number, not {raw!r}.") from None
        return int(number) if number.is_integer() and "." not in raw else number
    if name in _LISTS:
        return [part.strip() for part in raw.split(",") if part.strip()]
    if name == "since":
        return int(raw) if raw.isdigit() else raw
    return raw


def parse(uri: Any) -> Route:
    """Parse a ``houdini://`` resource URI (spec-2.0 §2.7); raises ``invalid_argument``."""
    if not isinstance(uri, str) or not uri.startswith(SCHEME):
        raise _bad(f"Not a houdini:// resource URI: {uri!r}.")
    rest = uri[len(SCHEME) :]
    location, _, query = rest.partition("?")
    kind, _, tail = location.partition("/")
    if kind not in PARAMS:
        raise _bad(
            f"Unknown resource houdini://{kind}.",
            hint="Resources: " + ", ".join(f"houdini://{k}" for k in PARAMS) + ".",
        )
    if kind in WITH_PATH and not tail.strip("/"):
        raise _bad(f"houdini://{kind}/ needs a path, e.g. houdini://{kind}/obj/geo1.")
    if kind not in WITH_PATH and tail:
        raise _bad(f"houdini://{kind} takes no path; options go in the query (?name=value).")
    allowed = PARAMS[kind]
    options: dict[str, Any] = {}
    for name, raw in parse_qsl(query, keep_blank_values=True):
        if name not in allowed:
            raise _bad(
                f"houdini://{kind} does not take {name}.",
                hint=f"houdini://{kind} takes {', '.join(allowed) or 'no variables'}.",
            )
        options[name] = _value(name, raw)
    return Route(uri, kind, *_call(kind, tail, options))


def _call(kind: str, tail: str, q: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    if kind == "status":
        return "houdini_status", {}
    if kind in BRIDGE_ONLY:
        return "", {}
    if kind == "jobs":
        return "inspect", {"what": "jobs"}
    if kind == "events":
        return "inspect", {"what": "events", **q}
    if kind == "types":
        args = {k: v for k, v in q.items() if k != "q"}
        if "q" in q:
            args = {"query": q["q"], **args}
        return "search", {"kind": "types", **args}
    if kind in ("outline", "problems"):
        args = {k: v for k, v in q.items() if k != "root"}
        if "root" in q:
            args = {"target": _node_path(str(q["root"])), **args}
        return "inspect", {"what": kind, **args}
    if kind == "type":
        category, _, name = unquote(tail).strip("/").partition("/")
        if not category or not name:
            raise _bad("houdini://type/{category}/{name} needs both, e.g. houdini://type/Sop/box.")
        return "inspect", {"what": "type", "target": f"{category}/{name}", **q}
    target = _node_path(tail)
    if kind == "node":
        what = "parms" if "parms" in q else "node"
        return "inspect", {"what": what, "target": target, **q}
    if kind == "network":
        fmt = q.pop("format", "data")
        if fmt not in ("data", "outline"):
            raise _bad(f"format must be data or outline, not {fmt!r}.")
        return "inspect", {"what": "network" if fmt == "data" else "outline", "target": target, **q}
    if kind == "geo":
        rows = {"rows": True} if GEO_ROWS & set(q) else {}
        return "inspect", {"what": "geo", "target": target, **rows, **q}
    return "inspect", {"what": kind, "target": target, **q}  # image, stage


# -- etags ------------------------------------------------------------------------------------


def content_etag(generation: Any, body: Any, *, pid: Any = None) -> str:
    """``<pid>:<scene_generation>:<16 hex>``: BLAKE2b of the canonical JSON of ``body``
    (an ``etag`` key in it left out)."""
    if isinstance(body, dict) and "etag" in body:
        body = {k: v for k, v in body.items() if k != "etag"}
    blob = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
    digest = hashlib.blake2b(blob.encode("utf-8"), digest_size=ETAG_HEX // 2).hexdigest()
    return f"{pid or os.getpid()}:{generation}:{digest}"


def etag_matches(if_none_match: Any, etag: str) -> bool:
    """HTTP ``If-None-Match`` semantics: ``*``, or one of a comma list (quotes and ``W/``
    ignored)."""
    if not isinstance(if_none_match, str) or not if_none_match.strip():
        return False
    for candidate in if_none_match.split(","):
        tag = candidate.strip()
        if tag == "*":
            return True
        if tag.startswith("W/"):
            tag = tag[2:]
        if tag.strip('"') == etag:
            return True
    return False


def _events_seq() -> int | None:
    try:
        from .tools.events import LOG
    except Exception:  # noqa: BLE001 - no ring buffer outside a host
        return None
    return LOG.last_seq


# -- the route --------------------------------------------------------------------------------


def serve(
    app: Any,
    uri: Any,
    if_none_match: Any = None,
    *,
    max_response_bytes: Any = None,
    timeout_s: Any = None,
) -> dict[str, Any]:
    """The ``GET /hp/v2/resource`` envelope: ``{ok, result: {uri, etag, body} |
    {uri, etag, not_modified: true}, _meta}``, or the call's error envelope. ``app`` is the
    :class:`~hocuspocus.host.server.HostApp` (its ``call`` and ``meta``)."""
    from .dispatch import error_envelope

    try:
        route = parse(uri)
        if not route.tool:
            raise _bad(
                f"houdini://{route.kind} is served by the bridge (hocuspocus-mcp), not the host."
            )
    except ToolError as exc:
        return error_envelope(exc, app.meta())
    budget = {"max_response_bytes": max_response_bytes} if max_response_bytes else {}
    envelope = app.call(route.tool, dict(route.args), timeout_s, **budget)
    if not envelope.get("ok"):
        return envelope
    body = envelope.get("result")
    meta = dict(envelope.get("_meta") or {})
    if route.tool == "inspect" and isinstance(body, dict) and isinstance(body.get("etag"), str):
        etag = body["etag"]
    else:
        etag = content_etag(meta.get("scene_generation"), body)
    meta["etag"] = etag
    seq = _events_seq()
    if seq is not None:
        meta["events_seq"] = seq
    if etag_matches(if_none_match, etag):
        result: dict[str, Any] = {"uri": route.uri, "etag": etag, "not_modified": True}
    else:
        result = {"uri": route.uri, "etag": etag, "body": body}
    return {"ok": True, "result": result, "_meta": meta}

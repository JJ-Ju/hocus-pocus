"""Resources with ETags and subscriptions for the ``v2`` profile (spec-2.0 §2.7).

:func:`install` is the one hook ``bridge/server.py`` calls; for every other profile it
does nothing and the 1.4 resource list stays as it is. In ``v2``:

* ``resources/list`` lists the concrete resources (``houdini://status``, ``instances``,
  ``jobs``, ``outline``, ``problems``, ``events``, ``hocuspocus://guide``, ``tools``) and
  ``resources/templates/list`` the RFC 6570 templates of :mod:`hocuspocus.host.resources`.
* ``resources/read`` sends a ``houdini://`` URI to the selected Houdini's
  ``GET /hp/v2/resource`` with the client's ``_meta["If-None-Match"]`` (or
  ``_meta.etag``) and returns ``_meta.etag``; on a match the result has no contents and
  ``_meta.not_modified: true``. The text is the JSON the matching ``inspect`` or
  ``search`` call returns. ``status`` and ``instances`` are served here
  (``houdini_status``) with a content etag ``bridge:<16 hex>``.
* Subscriptions for ``status``, ``jobs``, ``events`` and ``node/{path}``: through
  ``resources/subscribe`` on a handshake-era (2025) session, through
  ``subscriptions/listen`` (``resource_subscriptions``) on a 2026-07-28 one. While any
  exists, :class:`ResourceHub` polls every :data:`POLL_INTERVAL_S` (the progress poller's
  cadence): one ``houdini://jobs`` read with ``If-None-Match`` is the heartbeat (its
  ``_meta.events_seq`` and ``scene_generation`` say whether anything happened), ``node``
  and ``events`` are re-read only when they moved (or every :data:`FALLBACK_TICKS`
  ticks, for changes the ring buffer does not see), and ``notifications/resources/updated``
  goes out when a resource's etag differs from the one it had.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import logging
import re
import threading
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

import anyio
import mcp_types as types
from mcp.server.lowlevel.server import NotificationOptions
from mcp.server.subscriptions import InMemorySubscriptionBus, ListenHandler, ResourceUpdated
from mcp.shared.exceptions import MCPError

from ..host import resources as host_resources
from ..tools.errors import ToolError
from ..tools.profiles import is_2x
from . import budget
from . import instances as registry
from .client import DELIVERY_HINT, OFFLINE_HINT, REINSTALL_HINT
from .instructions import guide_text, tools_text

if TYPE_CHECKING:
    from .server import Bridge

__all__ = ["ResourceHub", "fetch", "host_resource", "install", "read"]

log = logging.getLogger(__name__)

POLL_INTERVAL_S = 0.5
FALLBACK_TICKS = 10
"""Every this many ticks ``node`` subscriptions are re-read even when no event arrived (a
node that no tool has read yet is not watched by the ring buffer)."""
READ_TIMEOUT_S = 30.0
MAX_STALE = 5
JOBS_URI = "houdini://jobs"
GUIDE_URI = "hocuspocus://guide"
TOOLS_URI = "hocuspocus://tools"
ROUTE = "/hp/v2/resource"
IF_NONE_MATCH_KEYS = ("If-None-Match", "if-none-match", "ifNoneMatch", "etag")
HOUDINI_CACHE = "no-cache"
"""``_meta.cache_control`` of a ``houdini://`` read: keep it, but revalidate with its etag."""
STATIC_CACHE = "max-age=86400"

RESOURCES: tuple[tuple[str, str, str, str], ...] = (
    ("houdini://status", "status", "application/json", "houdini_status (subscribable)."),
    ("houdini://instances", "instances", "application/json", "Every live Houdini."),
    ("houdini://jobs", "jobs", "application/json", "inspect what: jobs (subscribable)."),
    ("houdini://outline", "outline", "application/json", "The scene as a compact tree."),
    ("houdini://problems", "problems", "application/json", "inspect what: problems."),
    ("houdini://events", "events", "application/json", "inspect what: events (subscribable)."),
    (GUIDE_URI, "guide", "text/markdown", "The HocusPocus operating manual."),
    (TOOLS_URI, "tools", "text/markdown", "The tool reference and resource templates (large)."),
)


def enabled(bridge: Bridge) -> bool:
    """The 2.0 resources are served on every 2.0 profile; ``compat_1x`` serves 1.4's."""
    profile = getattr(bridge.config, "profile", None)
    return isinstance(profile, str) and is_2x(profile)


def v2_guide_text() -> str:
    """The 2.0 guide, whose resources paragraph names these templates (the 2.0 profiles
    serve it; ``compat_1x`` serves the 1.4 one from ``Bridge.read_resource``)."""
    return guide_text()


def v2_tools_text(tools: Any) -> str:
    lines = ["", "## Resource templates", ""]
    lines += [f"- `{tpl}`: {desc}" for tpl, _name, desc in host_resources.TEMPLATES]
    lines += [f"- `{uri}`: {desc}" for uri, _name, _mime, desc in RESOURCES]
    return tools_text(tools).rstrip("\n") + "\n" + "\n".join(lines) + "\n"


def list_resources() -> list[types.Resource]:
    return [
        types.Resource(uri=uri, name=name, mime_type=mime, description=desc)
        for uri, name, mime, desc in RESOURCES
    ]


def list_templates() -> list[types.ResourceTemplate]:
    return [
        types.ResourceTemplate(
            uri_template=tpl, name=name, mime_type="application/json", description=desc
        )
        for tpl, name, desc in host_resources.TEMPLATES
    ]


def _digest(value: Any) -> str:
    blob = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.blake2b(blob.encode("utf-8"), digest_size=8).hexdigest()


def if_none_match(meta: Any) -> str | None:
    """The client's validator from a request's ``_meta``."""
    if not isinstance(meta, dict):
        return None
    for key in IF_NONE_MATCH_KEYS:
        value = meta.get(key)
        if isinstance(value, str) and value:
            return value
    return None


# -- talking to the host -----------------------------------------------------------------------


def host_resource(
    client: Any,
    uri: str,
    if_none_match: str | None,
    *,
    timeout_s: float = READ_TIMEOUT_S,
    max_response_bytes: int | None = None,
) -> tuple[bool, dict[str, Any], dict[str, Any]]:
    """``GET /hp/v2/resource`` on one host: ``(ok, result_or_error, meta)``. A client with
    its own ``resource`` method (a test fake) answers instead."""
    own = getattr(client, "resource", None)
    if callable(own):
        return own(
            uri,
            if_none_match=if_none_match,
            timeout_s=timeout_s,
            max_response_bytes=max_response_bytes,
        )
    from .client import _parse_envelope

    query = f"uri={quote(uri, safe='')}&timeout_s={timeout_s:g}"
    if max_response_bytes:
        query += f"&max_response_bytes={int(max_response_bytes)}"
    headers = {
        "Accept": "application/json",
        "Host": f"{client.host}:{client.port}",
        "Authorization": f"Bearer {client.token}",
    }
    if if_none_match:
        headers["If-None-Match"] = if_none_match
    conn = http.client.HTTPConnection(client.host, client.port, timeout=client.connect_timeout_s)
    try:
        try:
            conn.connect()
        except (TimeoutError, OSError) as exc:
            raise ToolError(
                "houdini_offline",
                f"No HocusPocus host is listening on {client.host}:{client.port}.",
                hint=OFFLINE_HINT,
                detail={
                    "reason": "refused"
                    if isinstance(exc, ConnectionRefusedError)
                    else "unreachable",
                    "port": client.port,
                },
            ) from exc
        try:
            if conn.sock is not None:
                conn.sock.settimeout(timeout_s + 15.0)
            conn.request("GET", f"{ROUTE}?{query}", headers=headers)
            response = conn.getresponse()
            raw, status = response.read(), response.status
        except (TimeoutError, OSError, http.client.HTTPException) as exc:
            raise ToolError(
                "delivery_unknown",
                f"No complete answer to the resource read from port {client.port} "
                f"({exc.__class__.__name__}: {exc}).",
                hint=DELIVERY_HINT,
            ) from exc
    finally:
        conn.close()
    text = raw.decode("utf-8", errors="replace")
    try:
        data: Any = json.loads(text) if text else None
    except ValueError:
        data = text
    if status == 404:
        raise ToolError(
            "version_mismatch",
            f"The Houdini host on port {client.port} does not serve {ROUTE} (a 1.4 host).",
            hint=REINSTALL_HINT,
        )
    client._check_status(status, data)
    return _parse_envelope(data)


def _verified(bridge: Bridge, inst: registry.Instance) -> bool:
    return (inst.pid, inst.port, inst.token) in getattr(bridge, "_verified", set())


def _from_host(
    bridge: Bridge,
    route: host_resources.Route,
    uri_for: Callable[[registry.Instance], str],
    validator: str | None,
) -> tuple[registry.Instance, bool, dict[str, Any], dict[str, Any]]:
    stale: list[str] = []
    for _attempt in range(MAX_STALE):
        inst, _warnings, _ambiguous = bridge._resolve("inspect", dict(route.args))
        try:
            if not _verified(bridge, inst):
                bridge.verify(inst)
        except registry.StaleEntry as exc:
            stale.append(str(exc))
            continue
        client = bridge.client_for(inst)
        try:
            ok, result, meta = host_resource(
                client,
                uri_for(inst),
                validator,
                timeout_s=float(bridge.config.default_timeout_s),
                max_response_bytes=bridge.config.max_response_bytes,
            )
        except ToolError as exc:
            if registry.is_stale_error(exc):
                stale.append(exc.message)
                bridge.forget(inst, exc.message)
                continue
            raise
        return inst, ok, result, meta
    raise ToolError(
        "houdini_offline",
        "Every registered Houdini instance was stale (" + "; ".join(stale) + ").",
        hint=OFFLINE_HINT,
    )


_SINCE_RE = re.compile(r"([?&]since=)([^&]*)")


def _events_cursor(route: host_resources.Route, pid: int) -> tuple[str | None, Any]:
    """For ``houdini://events``: the bare seq to send for a ``<pid>:<seq>`` cursor (``0``
    for another Houdini's cursor) and, then, ``(cursor_pid, since)`` for the reset note."""
    from .server import events_cursor

    since = route.args.get("since")
    if since is None:
        return None, None
    cursor_pid, seq = events_cursor({"since": since})
    if cursor_pid not in (None, pid):
        return "0", (cursor_pid, since)
    return str(seq), None


def _events_uri(uri: str, route: host_resources.Route, pid: int) -> str:
    seq, _foreign = _events_cursor(route, pid)
    if seq is None:
        return uri
    return _SINCE_RE.sub(lambda m: m.group(1) + seq, uri, count=1)


def fetch(bridge: Bridge, uri: str, validator: str | None = None) -> dict[str, Any]:
    """Read one resource: ``{ok, etag, body?, not_modified?, meta}`` or ``{ok: False,
    error, meta}``. Raises ``ToolError`` for a URI it cannot parse."""
    route = host_resources.parse(uri)
    if route.kind in ("status", "instances"):
        from .local_tools import LOCAL_TOOLS

        with bridge._lock:
            status = LOCAL_TOOLS["houdini_status"](bridge, {})
        body = status
        if route.kind == "instances":
            body = {k: status[k] for k in ("instances", "recent", "warnings") if k in status}
        etag = f"bridge:{_digest(body)}"
        if host_resources.etag_matches(validator, etag):
            return {"ok": True, "etag": etag, "not_modified": True, "meta": {}}
        return {"ok": True, "etag": etag, "body": body, "meta": {}}
    if route.kind == "events":
        _events_cursor(route, 0)  # a malformed cursor is invalid_argument before any call
        inst, ok, result, meta = _from_host(
            bridge, route, lambda inst: _events_uri(uri, route, inst.pid), validator
        )
    else:
        inst, ok, result, meta = _from_host(bridge, route, lambda inst: uri, validator)
    from .server import instance_meta, tag_events

    meta = dict(meta)
    meta["instance"] = instance_meta(inst)
    if not ok:
        return {"ok": False, "error": result, "meta": meta}
    etag = result.get("etag") or meta.get("etag")
    if result.get("not_modified"):
        return {"ok": True, "etag": etag, "not_modified": True, "meta": meta}
    body = result.get("body")
    if not isinstance(body, dict):
        body = {"result": body}
    if route.kind == "events":
        body = tag_events(body, inst, _events_cursor(route, inst.pid)[1])
    return {"ok": True, "etag": etag, "body": body, "meta": meta}


def _error(payload: dict[str, Any]) -> MCPError:
    from .server import _TRANSPORT_CODES

    code = types.INTERNAL_ERROR if payload.get("code") in _TRANSPORT_CODES else types.INVALID_PARAMS
    message = f"{payload.get('code')}: {payload.get('message')}"
    if payload.get("hint"):
        message += f" ({payload['hint']})"
    return MCPError(code, message, payload)


def read(bridge: Bridge, uri: str, meta: Any = None) -> types.ReadResourceResult:
    """``resources/read`` in ``v2``."""
    validator = if_none_match(meta)
    if uri in (GUIDE_URI, TOOLS_URI):
        text = v2_guide_text() if uri == GUIDE_URI else v2_tools_text(bridge.tools)
        etag = f"bridge:{_digest(text)}"
        out = {"etag": etag, "cache_control": STATIC_CACHE}
        if host_resources.etag_matches(validator, etag):
            return types.ReadResourceResult(contents=[], meta={**out, "not_modified": True})
        return types.ReadResourceResult(
            contents=[
                types.TextResourceContents(
                    uri=uri, text=text, mime_type="text/markdown", meta={"etag": etag}
                )
            ],
            meta=out,
        )
    try:
        got = fetch(bridge, uri, validator)
    except ToolError as exc:
        raise _error(exc.to_dict()) from exc
    if not got["ok"]:
        raise _error(got["error"])
    out = {"etag": got["etag"], "cache_control": HOUDINI_CACHE}
    if "instance" in got["meta"]:
        out["instance"] = got["meta"]["instance"]
    if got.get("not_modified"):
        return types.ReadResourceResult(contents=[], meta={**out, "not_modified": True})
    result, _images = budget.extract_images(got["body"])
    result, cuts = budget.apply_budget(result, bridge.config.max_response_bytes)
    if cuts:
        out[budget.TRUNCATION_META_KEY] = cuts
    return types.ReadResourceResult(
        contents=[
            types.TextResourceContents(
                uri=uri,
                text=budget.dumps(result),
                mime_type="application/json",
                meta={"etag": got["etag"]},
            )
        ],
        meta=out,
    )


# -- subscriptions -----------------------------------------------------------------------------


def subscribable(uri: str) -> bool:
    try:
        return host_resources.parse(uri).kind in host_resources.SUBSCRIBABLE
    except ToolError:
        return False


def _connection_key(ctx: Any) -> int:
    """One key per client connection (``ctx.session`` is a per-request proxy)."""
    return id(getattr(ctx.session, "_connection", ctx.session))


class ResourceHub:
    """Who is subscribed to what, the etags they last saw, and the poller.

    Subscribers are opaque keys: a handshake-era ``ServerSession`` (notified with
    ``send_resource_updated``) or a listen-stream token (notified through the bus, whose
    :class:`ListenHandler` filters by the stream's URIs)."""

    def __init__(self, bridge: Bridge, interval_s: float = POLL_INTERVAL_S) -> None:
        self.bridge = bridge
        self.interval_s = interval_s
        self.bus = InMemorySubscriptionBus()
        self.listen = ListenHandler(self.bus)
        self._subs: dict[str, set[Any]] = {}
        self._sessions: dict[int, Any] = {}
        self._etags: dict[str, str] = {}
        self._gate: tuple[Any, ...] | None = None
        self._jobs_etag: str | None = None
        self._ticks = 0
        self._lock = threading.Lock()

    # -- bookkeeping --------------------------------------------------------------------

    def uris(self) -> list[str]:
        with self._lock:
            return [uri for uri, subs in self._subs.items() if subs]

    def add(self, uri: str, key: Any, session: Any = None) -> None:
        with self._lock:
            self._subs.setdefault(uri, set()).add(key)
            if session is not None:
                self._sessions[key] = session

    def remove(self, uri: str | None, key: Any) -> None:
        with self._lock:
            for name in [uri] if uri is not None else list(self._subs):
                subs = self._subs.get(name)
                if subs is None:
                    continue
                subs.discard(key)
                if not subs:
                    del self._subs[name]
                    self._etags.pop(name, None)
            if not any(key in subs for subs in self._subs.values()):
                self._sessions.pop(key, None)

    def etag_of(self, uri: str, validator: str | None = None) -> str:
        """The resource's etag now; an error is a state of its own (``error:<code>``)."""
        try:
            got = fetch(self.bridge, uri, validator)
        except ToolError as exc:
            return f"error:{exc.code}"
        except Exception:  # noqa: BLE001 - the poller must never die
            log.debug("resource poll of %s failed", uri, exc_info=True)
            return "error:internal"
        if not got["ok"]:
            return f"error:{got['error'].get('code')}"
        return str(got["etag"])

    def baseline(self, uri: str) -> None:
        """Record the etag a new subscriber starts from (before its subscribe returns, so
        a change right after it is not missed)."""
        etag = self.etag_of(uri)
        with self._lock:
            self._etags.setdefault(uri, etag)

    # -- the poll -------------------------------------------------------------------------

    def check(self) -> list[str]:
        """One tick: the subscribed URIs whose etag changed (and remember the new ones)."""
        uris = self.uris()
        if not uris:
            return []
        self._ticks += 1
        host_kinds = {uri: host_resources.parse(uri).kind for uri in uris}
        fresh: dict[str, str] = {}
        moved = self._ticks % FALLBACK_TICKS == 0
        if any(kind != "status" for kind in host_kinds.values()):
            gate, jobs_etag = self._heartbeat()
            moved = moved or gate != self._gate
            self._gate = gate
            if jobs_etag is not None:
                fresh[JOBS_URI] = jobs_etag
        changed = []
        for uri, kind in host_kinds.items():
            with self._lock:
                last = self._etags.get(uri)
            if kind == "jobs" and uri in fresh:
                etag = fresh[uri]
            elif kind in ("status", "jobs") or moved or last is None or last.startswith("error:"):
                etag = self.etag_of(uri, last)
            else:
                continue
            with self._lock:
                if uri not in self._subs:
                    continue
                if last is not None and etag != last:
                    changed.append(uri)
                self._etags[uri] = etag
        return changed

    def _heartbeat(self) -> tuple[tuple[Any, ...], str | None]:
        """``(pid, scene_generation, events_seq)`` and the jobs etag, from one
        ``houdini://jobs`` read with ``If-None-Match``."""
        try:
            got = fetch(self.bridge, JOBS_URI, self._jobs_etag)
        except ToolError as exc:
            return ("error", exc.code), f"error:{exc.code}"
        except Exception:  # noqa: BLE001 - the poller must never die
            log.debug("resource heartbeat failed", exc_info=True)
            return ("error", "internal"), "error:internal"
        meta = got["meta"]
        pid = (meta.get("instance") or {}).get("pid")
        gate = (pid, meta.get("scene_generation"), meta.get("events_seq"))
        if not got["ok"]:
            return gate, f"error:{got['error'].get('code')}"
        self._jobs_etag = str(got["etag"])
        return gate, self._jobs_etag

    async def notify(self, uri: str) -> None:
        with self._lock:
            keys = list(self._subs.get(uri, ()))
            sessions = [(key, self._sessions[key]) for key in keys if key in self._sessions]
        for key, session in sessions:
            try:
                await session.send_resource_updated(uri)
            except Exception:  # noqa: BLE001 - a closed session drops its subscriptions
                log.debug("resource notification failed; dropping the session", exc_info=True)
                self.remove(None, key)
        if len(sessions) < len(keys):
            await self.bus.publish(ResourceUpdated(uri=uri))

    async def run(self) -> None:
        while True:
            await anyio.sleep(self.interval_s)
            if not self.uris():
                continue
            changed = await anyio.to_thread.run_sync(self.check)
            for uri in changed:
                await self.notify(uri)

    # -- MCP handlers ---------------------------------------------------------------------

    def _check_uri(self, uri: str) -> None:
        if not subscribable(uri):
            raise MCPError(
                types.INVALID_PARAMS,
                f"Cannot subscribe to {uri}: subscriptions cover houdini://status, "
                "houdini://jobs, houdini://events and houdini://node/{path}.",
                {"uri": uri},
            )

    async def on_subscribe(self, ctx: Any, params: types.SubscribeRequestParams) -> Any:
        uri = str(params.uri)
        self._check_uri(uri)
        await anyio.to_thread.run_sync(self.baseline, uri)
        self.add(uri, _connection_key(ctx), ctx.session)
        return types.EmptyResult()

    async def on_unsubscribe(self, ctx: Any, params: types.UnsubscribeRequestParams) -> Any:
        self.remove(str(params.uri), _connection_key(ctx))
        return types.EmptyResult()

    async def on_listen(self, ctx: Any, params: types.SubscriptionsListenRequestParams) -> Any:
        uris = [
            str(uri)
            for uri in (params.notifications.resource_subscriptions or ())
            if subscribable(str(uri))
        ]
        key = object()
        for uri in uris:
            await anyio.to_thread.run_sync(self.baseline, uri)
            self.add(uri, key)
        try:
            return await self.listen(ctx, params)
        finally:
            self.remove(None, key)


# -- the hook --------------------------------------------------------------------------------


def install(server: Any, bridge: Bridge) -> ResourceHub | None:
    """Give a ``v2`` bridge's server the 2.0 resources (handlers, the poller in the
    server's lifespan, ``listChanged``). Any other profile: nothing changes."""
    if not enabled(bridge):
        return None
    hub = ResourceHub(bridge)

    async def on_list_resources(ctx: Any, params: Any) -> types.ListResourcesResult:
        return types.ListResourcesResult(resources=list_resources())

    async def on_list_templates(ctx: Any, params: Any) -> types.ListResourceTemplatesResult:
        return types.ListResourceTemplatesResult(resource_templates=list_templates())

    async def on_read(ctx: Any, params: types.ReadResourceRequestParams) -> Any:
        meta = params.meta if params.meta is not None else getattr(ctx, "meta", None)
        return await anyio.to_thread.run_sync(read, bridge, str(params.uri), meta)

    server.add_request_handler("resources/list", types.PaginatedRequestParams, on_list_resources)
    server.add_request_handler(
        "resources/templates/list", types.PaginatedRequestParams, on_list_templates
    )
    server.add_request_handler("resources/read", types.ReadResourceRequestParams, on_read)
    server.add_request_handler(
        "resources/subscribe", types.SubscribeRequestParams, hub.on_subscribe
    )
    server.add_request_handler(
        "resources/unsubscribe", types.UnsubscribeRequestParams, hub.on_unsubscribe
    )
    server.add_request_handler(
        "subscriptions/listen", types.SubscriptionsListenRequestParams, hub.on_listen
    )

    inner = server.lifespan

    @asynccontextmanager
    async def lifespan(srv: Any) -> AsyncIterator[Any]:
        async with inner(srv) as state, anyio.create_task_group() as group:
            group.start_soon(hub.run)
            try:
                yield state
            finally:
                hub.listen.close()
                group.cancel_scope.cancel()

    server.lifespan = lifespan
    create = server.create_initialization_options

    def create_initialization_options(
        notification_options: NotificationOptions | None = None, *args: Any, **kwargs: Any
    ) -> Any:
        options = notification_options or NotificationOptions()
        options.resources_changed = True
        return create(options, *args, **kwargs)

    server.create_initialization_options = create_initialization_options
    server.resource_hub = hub
    return hub

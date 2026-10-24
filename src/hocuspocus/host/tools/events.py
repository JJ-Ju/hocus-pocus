"""``events``: a host-side ring buffer of hip, node and PDG events. See docs/BIBLE.md §4.7.

The buffer holds the last :data:`RING_SIZE` events, each ``{seq, time, kind, path,
origin, detail?}`` with a monotonic ``seq`` (it survives scene clears, not a host
restart). ``origin`` is ``"agent"`` for changes made inside a HocusPocus call and
``"other"`` for the user's (or Houdini's) own; inside a call that sets parms explicitly,
parm writes it did not make are ``"houdini"`` (:func:`note_explicit`). Kinds are Houdini's event names:

* hip: ``BeforeClear``, ``AfterClear``, ``BeforeLoad``, ``AfterLoad``, ``AfterMerge``,
  ``AfterSave`` (``path`` is the hip file). The clear inside a load is not reported.
* nodes: ``ChildCreated``/``ChildDeleted`` directly under the context managers
  (``/obj``, ``/stage``, ``/mat``, ``/out``, ``/tasks``) and under watched networks;
  ``NameChanged``, ``ParmTupleChanged`` (``detail.components`` names the components of a
  multi-component tuple whose value or keys changed, ``detail.keyed`` those that now have
  keyframes; bursts on one tuple within :data:`COALESCE_S` collapse into one event with
  the union of components), ``FlagChanged`` (``detail.
  flags`` names the flags and their new values), ``SpareParmsChanged``, ``InputRewired``
  and ``BeingDeleted`` on watched nodes.
* ``hda_contents_rebuilt``: one event for an asset whose contents ``hda create``,
  ``match`` or ``unlock`` rebuilt (``detail.events`` counts what it stands for).
* ``pdg``: ``detail.event`` is ``cook_start``, ``cook_done`` (``ok``, ``states``,
  ``cancelled``) or ``work_item_failed`` (``node``, ``id``, ``index``, ``error``),
  recorded by the ``pdg`` tool.

A node is watched once a tool calls :func:`watch_node` on it (tools that create, edit or
read nodes do), and automatically shortly after it is created directly under a context
manager (deferred, so its creation script is not recorded). Node events are not
recorded while a hip clear/load/merge is in progress (they would be one
``ChildDeleted``/``ChildCreated`` per node).

Events from a HocusPocus call are held until the call's main-thread work ends
(:func:`agent_work`, the executor's work wrapper), then filtered and published at once:
a call that fails and is rolled back publishes nothing, a node created and deleted in
the same work (a rollback, a temporary node) publishes nothing, and changes made while
undo is disabled (tool-internal set/restore, such as ``render``'s output parm) are never
recorded.

The host calls :func:`install` when it starts and :func:`uninstall` when it stops (both
on the main thread). The ``events`` tool only reads the buffer, so it runs off the main
thread.
"""

from __future__ import annotations

import contextlib
import logging
import threading
import time
from collections import deque
from collections.abc import Callable, Iterator
from typing import Any

from ._common import ROW_ENVELOPE_BYTES, compact_size, int_arg, response_budget
from .registry import HostContext, tool

log = logging.getLogger("hocuspocus.host.events")

RING_SIZE = 2000
COALESCE_S = 0.1
SPARE_BURST_S = 0.5
"""ParmTupleChanged events this close before a SpareParmsChanged on the same node are
the template change itself (the folder and the new parms), not value edits."""
WATCH_CAP = 5000
DEDUPE_WINDOW = 16
DEDUPE_S = 0.5
"""A ``ChildCreated``/``ChildDeleted`` repeating one of the last :data:`DEDUPE_WINDOW`
events within this many seconds, with nothing on that path and no hip event in between,
is the same change seen twice (review 16 N2)."""
MANAGERS = ("/obj", "/stage", "/mat", "/out", "/tasks")
DEFAULT_LIMIT = 50
HIP_KINDS = ("BeforeClear", "AfterClear", "BeforeLoad", "AfterLoad", "AfterMerge", "AfterSave")
TOPNET_SAVE_PARMS = ("taskgraphfile", "checkpointfile", None)
"""Parms Houdini writes on a TOP network when the hip is saved (review 14 papercut 6)."""
STAGE_SAVE_PARMS = ("rendergallerysource", None)
"""Parms Houdini writes on /stage when the hip is saved (review 18 papercut 10)."""
AGENT = "agent"
OTHER = "other"
HOUDINI = "houdini"
"""A parm Houdini wrote itself inside a call that set other parms explicitly (a camera's
``*Converted`` parms, a light's guide scale, ``labelparm*``; review 23 papercut 9)."""


def _now_iso() -> str:
    now = time.time()
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(now)) + f".{int(now % 1 * 1000):03d}Z"


class EventLog:
    """Thread-safe ring buffer with a monotonic sequence number.

    Between :meth:`begin` and :meth:`end` (one HocusPocus main-thread work item) events
    recorded on that thread are held in a pending list and published by :meth:`end`."""

    def __init__(self, size: int = RING_SIZE) -> None:
        self._buf: deque[dict[str, Any]] = deque(maxlen=size)
        self._lock = threading.Lock()
        self._seq = 0
        self._recent_parm: dict[tuple[str, str | None], tuple[dict[str, Any], float]] = {}
        self._pending: list[dict[str, Any]] | None = None
        self._pending_thread: int | None = None
        self._collapse: list[dict[str, Any]] = []
        self._child_seen: dict[tuple[str, str, str], float] = {}
        self.on_other: Callable[[dict[str, Any]], None] | None = None
        """Called (outside the lock) with every published ``origin: other`` node event:
        the host marks the scene dirty from it (docs/parity.md G1)."""

    @property
    def last_seq(self) -> int:
        return self._seq

    # -- the pending batch --------------------------------------------------------

    def begin(self) -> bool:
        """Start holding this thread's events. False when a batch is already open."""
        with self._lock:
            if self._pending is not None:
                return False
            self._pending = []
            self._pending_thread = threading.get_ident()
            return True

    def collapsing(self) -> bool:
        return bool(self._collapse)

    def holding(self) -> bool:
        return self._pending is not None and self._pending_thread == threading.get_ident()

    def end(self, *, discard: bool = False) -> None:
        """Publish the held events (none with ``discard``), filtered by :func:`_settle`."""
        with self._lock:
            pending, self._pending, self._pending_thread = self._pending or [], None, None
            if discard:
                return
            for event in _settle(pending):
                self._seq += 1
                event["seq"] = self._seq
                self._buf.append(_ordered(event))

    # -- recording ----------------------------------------------------------------

    def record(
        self,
        kind: str,
        path: str,
        detail: dict[str, Any] | None = None,
        *,
        origin: str | None = None,
        after: str | None = None,
    ) -> dict[str, Any] | None:
        """Record one event. ``after`` (held events only) places it after the last held
        event on that path or below, so a nested node's late ``ChildCreated`` follows its
        parent's rather than the whole batch."""
        with self._lock:
            for group in self._collapse:
                if _under(path, group["scope"]):
                    group["count"] += 1
                    return None
            held = self._pending is not None and self._pending_thread == threading.get_ident()
            event: dict[str, Any] = {
                "seq": None,
                "time": _now_iso(),
                "kind": kind,
                "path": path,
                "origin": origin or (AGENT if held else OTHER),
            }
            if detail:
                event["detail"] = detail
            if kind in ("ChildCreated", "ChildDeleted") and self._repeat(event, held):
                return None
            if held and origin in (None, HOUDINI):
                pending = self._pending
                assert pending is not None
                at = len(pending)
                if after is not None:
                    hits = [i for i, e in enumerate(pending) if _under(e["path"], after)]
                    at = hits[-1] + 1 if hits else at
                pending.insert(at, event)
            else:
                self._seq += 1
                event["seq"] = self._seq
                self._buf.append(event)
        if event["origin"] == OTHER and kind not in HIP_KINDS and kind != "pdg":
            listener = self.on_other
            if listener is not None:
                with contextlib.suppress(Exception):
                    listener(event)
        return event

    def _repeat(self, event: dict[str, Any], held: bool) -> bool:
        """Whether ``event`` repeats one of the last :data:`DEDUPE_WINDOW` events on its
        path (a context manager also watched as a node, after ``network_describe`` of
        /stage, reported each top-level ``ChildCreated`` twice). Lock held."""
        key = (event["kind"], event["path"], event["origin"])
        mono = time.monotonic()
        last = self._child_seen.get(key)
        if len(self._child_seen) > 256:
            self._child_seen = {k: t for k, t in self._child_seen.items() if mono - t <= DEDUPE_S}
        self._child_seen[key] = mono
        if last is None or mono - last > DEDUPE_S:
            return False
        recent = self._pending if held and self._pending is not None else self._buf
        for i, other in enumerate(reversed(recent)):
            if i >= DEDUPE_WINDOW or other["kind"] in HIP_KINDS:
                break
            if other["path"] == event["path"]:
                return other["kind"] == event["kind"] and other["origin"] == event["origin"]
        return False

    def _alive(self, event: dict[str, Any]) -> bool:
        """Whether ``event`` can still absorb a coalesced change (lock held)."""
        if event["seq"] is None:
            return self._pending is not None and any(e is event for e in self._pending)
        return bool(self._buf) and event["seq"] >= self._buf[0]["seq"]

    def record_parm(
        self,
        path: str,
        parm: str | None,
        components: list[str] | None = None,
        keyed: list[str] | None = None,
        order: list[str] | None = None,
        origin: str | None = None,
    ) -> None:
        """``ParmTupleChanged``, coalesced per (node, parm tuple) within :data:`COALESCE_S`.

        ``components`` are the changed components of a multi-component tuple and ``keyed``
        those of them that have keyframes now (review 16 papercut 9: a key on ``ry`` read
        as ``{parm: r, count: 3}``). A coalesced event keeps the union, in ``order`` (the
        tuple's component order)."""
        key = (path, parm)
        mono = time.monotonic()
        effective = origin or (AGENT if self.holding() else OTHER)
        with self._lock:
            recent = self._recent_parm.get(key)
            if recent is not None:
                event, last = recent
                if (
                    mono - last <= COALESCE_S
                    and self._alive(event)
                    and event["origin"] == effective
                ):
                    detail = event.setdefault("detail", {})
                    _merge_components(detail, components or [], keyed or [], order or [])
                    event["time"] = _now_iso()
                    self._recent_parm[key] = (event, mono)
                    return
            if len(self._recent_parm) > 256:
                self._recent_parm = {
                    k: v for k, v in self._recent_parm.items() if mono - v[1] <= SPARE_BURST_S
                }
        detail: dict[str, Any] = {"parm": parm} if parm else {}
        if parm and components:
            _merge_components(detail, components, keyed or [], order or [])
        event = self.record("ParmTupleChanged", path, detail or None, origin=origin)
        if event is not None:
            with self._lock:
                self._recent_parm[key] = (event, mono)

    def drop_recent_parms(self, path: str, within_s: float = SPARE_BURST_S) -> None:
        """Forget the ``ParmTupleChanged`` events recorded on ``path`` in the last
        ``within_s`` seconds (a spare parm template change is not a value edit)."""
        mono = time.monotonic()
        with self._lock:
            for key, (event, last) in list(self._recent_parm.items()):
                if key[0] != path or mono - last > within_s:
                    continue
                del self._recent_parm[key]
                if event["seq"] is None:
                    if self._pending is not None:
                        self._pending[:] = [e for e in self._pending if e is not event]
                else:
                    with contextlib.suppress(ValueError):
                        self._buf.remove(event)

    @contextlib.contextmanager
    def collapsed(self, path: str, kind: str, scope: str | None = None) -> Iterator[None]:
        """Record events on ``scope`` (default ``path``) and below as one ``kind`` event
        on ``path`` (``detail.events`` counts them) when the block ends, or nothing when
        there were none."""
        group = {"path": path, "scope": scope or path, "count": 0}
        with self._lock:
            self._collapse.append(group)
        try:
            yield
        finally:
            with self._lock:
                self._collapse.remove(group)
            if group["count"]:
                self.record(kind, path, {"events": group["count"]})

    # -- reading ------------------------------------------------------------------

    def read(self, since: int, limit: int, budget: int | None = None) -> dict[str, Any]:
        """Events after ``since``: at most ``limit`` and, with ``budget``, at most that many
        bytes (at least one event). ``next_since`` is the seq of the last event returned,
        so a page cut by either never skips an event (review 22 finding 1)."""
        with self._lock:
            events = list(self._buf)
            last = self._seq
            snapshot = [
                dict(e, detail=dict(e["detail"])) if "detail" in e else dict(e) for e in events
            ]
        out: dict[str, Any] = {}
        if since > last:
            # The host restarted (seq starts again at 1): everything buffered is new.
            out["reset"] = True
            since = 0
        oldest = snapshot[0]["seq"] if snapshot else last + 1
        newer = [e for e in snapshot if e["seq"] > since]
        chunk = newer[:limit]
        if budget is not None:
            used = ROW_ENVELOPE_BYTES
            for kept, event in enumerate(chunk):
                used += compact_size(event) + 1
                if kept and used > budget:
                    chunk = chunk[:kept]
                    break
        out["events"] = chunk
        out["next_since"] = chunk[-1]["seq"] if chunk else max(since, last)
        out["dropped"] = max(0, oldest - since - 1)
        if len(newer) > len(chunk):
            out["more"] = True
        return out


def _merge_components(
    detail: dict[str, Any], components: list[str], keyed: list[str], order: list[str]
) -> None:
    """Fold one change's ``components``/``keyed`` into a ParmTupleChanged ``detail``."""
    if not components:
        return
    seen = detail.get("components", [])
    merged = seen + [c for c in components if c not in seen]
    rank = {name: i for i, name in enumerate(order)}
    merged.sort(key=lambda c: rank.get(c, len(rank)))
    was_keyed = detail.get("keyed", [])
    now_keyed = [c for c in merged if c in keyed or (c in was_keyed and c not in components)]
    detail["components"] = merged
    if now_keyed:
        detail["keyed"] = now_keyed
    else:
        detail.pop("keyed", None)


def _ordered(event: dict[str, Any]) -> dict[str, Any]:
    """``seq`` first, as in events recorded directly."""
    return {"seq": event["seq"], **{k: v for k, v in event.items() if k != "seq"}}


def _under(path: str, root: str) -> bool:
    return path == root or path.startswith(root + "/")


def _settle(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop the work item's transient nodes: a node created and deleted within it (a
    rolled-back batch item, a tool's temporary node) leaves no event, and neither does
    anything recorded on it or below it in between."""
    out = list(events)
    while True:
        pair = None
        for i, event in enumerate(out):
            if event["kind"] != "ChildCreated":
                continue
            for j in range(i + 1, len(out)):
                if out[j]["kind"] == "ChildDeleted" and out[j]["path"] == event["path"]:
                    pair = (i, j, event["path"])
                    break
            if pair:
                break
        if pair is None:
            return out
        i, j, path = pair
        out = out[:i] + [e for e in out[i + 1 : j] if not _under(e["path"], path)] + out[j + 1 :]


LOG = EventLog()


# -- hou wiring -------------------------------------------------------------------------


class _Hooks:
    def __init__(self) -> None:
        self.installed = False
        self.owner: Any = None
        """Whoever :func:`install` wired the hooks for (the session's :class:`Host`); only
        that owner's :func:`uninstall` removes them."""
        self.hip_busy = False
        self.muted = 0
        self.watched: dict[int, Any] = {}
        self.flags: dict[int, dict[str, bool]] = {}
        self.tuples: dict[int, dict[str, tuple[Any, ...]]] = {}
        """Per watched node, the last seen state of each multi-component parm tuple, to
        name the components a ParmTupleChanged changed."""
        self.managers: list[Any] = []
        self.post: Any = None
        self.executor: Any = None
        self.pending: set[int] = set()
        self.created: set[int] = set()
        """Session ids whose ChildCreated the open work item recorded."""
        self.explicit: set[tuple[str, str]] = set()
        """(node path, parm tuple name) the open work item set explicitly (:func:`note_explicit`)."""


_HOOKS = _Hooks()


@contextlib.contextmanager
def muted() -> Iterator[None]:
    """Record no node events inside the block (HocusPocus's own temporary nodes)."""
    _HOOKS.muted += 1
    try:
        yield
    finally:
        _HOOKS.muted -= 1


def collapsed(path: str, kind: str = "hda_contents_rebuilt", scope: str | None = None) -> Any:
    """See :meth:`EventLog.collapsed`."""
    return LOG.collapsed(path, kind, scope)


def _rolled_back(exc: BaseException) -> bool:
    """Whether a failed call's changes were undone (so its events never happened)."""
    detail = getattr(exc, "detail", None)
    if isinstance(detail, dict) and detail.get("rolled_back") is False:
        return False
    return getattr(exc, "code", None) is not None  # a ToolError: the dispatcher rolled back


def agent_work(fn: Callable[[], Any]) -> Any:
    """The executor's work wrapper: events recorded while ``fn`` runs are the agent's,
    held and published together when it returns (see the module docstring)."""
    if not LOG.begin():
        return fn()
    _HOOKS.created = set()
    _HOOKS.explicit = set()
    discard = False
    try:
        return fn()
    except BaseException as exc:
        discard = _rolled_back(exc)
        raise
    finally:
        _HOOKS.created = set()
        _HOOKS.explicit = set()
        LOG.end(discard=discard)


def note_explicit(target: Any) -> None:
    """The running call sets ``target`` (a parm or parm tuple) itself: its
    ``ParmTupleChanged`` is the agent's. Once a call has noted one, the parm writes it did
    not note are Houdini's own (callbacks, converted and computed parms) and are recorded
    with ``origin: "houdini"`` (review 23 papercut 9). Main thread; never raises."""
    if not LOG.holding():
        return
    with contextlib.suppress(Exception):
        parm_tuple = target.tuple() if hasattr(target, "tuple") else target
        _HOOKS.explicit.add((parm_tuple.node().path(), parm_tuple.name()))


def _parm_origin(path: str, name: str | None) -> str | None:
    """``houdini`` for a parm write the running call did not make itself; else None (the
    default: the agent's inside a call, the user's outside one)."""
    if not _HOOKS.explicit or not LOG.holding():
        return None
    return None if (path, name) in _HOOKS.explicit else HOUDINI


def hip_done() -> None:
    """A hip load, merge or clear is over, whether or not it succeeded. A failed load
    never sends ``AfterLoad``/``AfterMerge``, which would leave node events silenced."""
    _HOOKS.hip_busy = False


def _node_types() -> tuple[Any, ...]:
    import hou

    E = hou.nodeEventType
    return (
        E.NameChanged,
        E.ParmTupleChanged,
        E.FlagChanged,
        E.InputRewired,
        E.BeingDeleted,
        E.ChildCreated,
        E.ChildDeleted,
        E.SpareParmTemplatesChanged,
    )


def _manager_types() -> tuple[Any, ...]:
    import hou

    return (hou.nodeEventType.ChildCreated, hou.nodeEventType.ChildDeleted)


def _safe_path(node: Any) -> str:
    try:
        return node.path()
    except Exception:
        return ""


def _child_detail(child: Any) -> dict[str, Any] | None:
    try:
        return {"type": child.type().name()}
    except Exception:
        return None


def _quiet() -> bool:
    """No node events: a hip load is running, a tool muted them, or a HocusPocus call
    changes the scene with undo disabled (tool-internal set/restore and probes)."""
    if _HOOKS.hip_busy or _HOOKS.muted:
        return True
    if LOG.collapsing():
        # Houdini disables undo itself while it rebuilds an asset (matchCurrentDefinition);
        # those changes are counted into the collapsed event.
        return False
    if LOG.holding():
        import hou

        with contextlib.suppress(Exception):
            return not hou.undos.areEnabled()
    return False


def _created(child: Any) -> None:
    if child is not None and LOG.holding():
        with contextlib.suppress(Exception):
            _HOOKS.created.add(child.sessionId())


def _on_manager_event(**kwargs: Any) -> None:
    try:
        if _quiet():
            return
        import hou

        child = kwargs.get("child_node")
        kind = kwargs["event_type"].name()
        LOG.record(kind, _safe_path(child), _child_detail(child))
        if kwargs["event_type"] == hou.nodeEventType.ChildCreated and child is not None:
            _created(child)
            _watch_later(child.sessionId())
    except Exception:
        log.debug("manager event callback failed", exc_info=True)


def _flag_change(node: Any) -> dict[str, bool]:
    from .nodes import node_flags  # lazy: nodes imports this module

    try:
        sid = node.sessionId()
    except Exception:
        return {}
    now = node_flags(node)
    before = _HOOKS.flags.get(sid, {})
    _HOOKS.flags[sid] = now
    return {name: value for name, value in now.items() if before.get(name) != value}


def _component_state(parm: Any) -> tuple[Any, Any]:
    """What a component's change can touch: its raw value (an expression's text) and its
    keyframes."""
    try:
        value = parm.rawValue()
    except Exception:
        value = None
    try:
        keys = tuple(
            (
                k.frame(),
                k.expression() if k.isExpressionSet() else None,
                k.value() if k.isValueSet() else None,
            )
            for k in parm.keyframes()
        )
    except Exception:
        keys = ()
    return value, keys


def _tuple_state(parm_tuple: Any) -> tuple[Any, ...]:
    return tuple(_component_state(p) for p in parm_tuple)


def _snapshot_tuples(node: Any) -> None:
    """Remember every multi-component parm tuple of a newly watched node."""
    states: dict[str, tuple[Any, ...]] = {}
    for parm_tuple in node.parmTuples():
        with contextlib.suppress(Exception):
            if len(parm_tuple) > 1:
                states[parm_tuple.name()] = _tuple_state(parm_tuple)
    _HOOKS.tuples[node.sessionId()] = states


def _changed_components(node: Any, parm_tuple: Any) -> tuple[list[str], list[str], list[str]]:
    """``(changed, keyed, order)`` for a multi-component tuple; empty for one component.
    Without a snapshot (a tuple added later) the non-default components count as changed."""
    try:
        parms = list(parm_tuple)
        if len(parms) < 2:
            return [], [], []
        order = [p.name() for p in parms]
        now = _tuple_state(parm_tuple)
        states = _HOOKS.tuples.setdefault(node.sessionId(), {})
        before = states.get(parm_tuple.name())
        states[parm_tuple.name()] = now
        if before is None or len(before) != len(now):
            changed = [p.name() for p in parms if not p.isAtDefault()]
        else:
            changed = [order[i] for i in range(len(now)) if now[i] != before[i]]
        keyed = [order[i] for i in range(len(now)) if order[i] in changed and now[i][1]]
        return changed, keyed, order
    except Exception:
        return [], [], []


def _is_topnet(node: Any) -> bool:
    import hou

    try:
        return node.childTypeCategory() == hou.topNodeTypeCategory()
    except Exception:
        return False


def _ramp_of(parm_tuple: Any) -> str | None:
    """The ramp parm a ramp key's tuple belongs to, or None for other tuples."""
    import hou

    try:
        parent = parm_tuple[0].parentMultiParm()
        if parent is not None and parent.parmTemplate().type() == hou.parmTemplateType.Ramp:
            return parent.name()
    except Exception:
        pass
    return None


def _on_node_event(**kwargs: Any) -> None:
    try:
        if _quiet():
            return
        node = kwargs.get("node")
        kind = kwargs["event_type"].name()
        path = _safe_path(node)
        if kind == "ParmTupleChanged":
            tuple_ = kwargs.get("parm_tuple")
            name = tuple_.name() if tuple_ is not None else None
            if (name in TOPNET_SAVE_PARMS and _is_topnet(node)) or (
                name in STAGE_SAVE_PARMS and path == "/stage"
            ):
                return  # Houdini's own bookkeeping when the hip is saved
            ramp = _ramp_of(tuple_) if tuple_ is not None else None
            if ramp is not None:
                # A ramp edit touches every key's tuples (ramp1pos, ramp1c, ...): one event
                # for the ramp (review 18 papercut 10).
                LOG.record_parm(path, ramp, origin=_parm_origin(path, ramp))
                return
            changed, keyed, order = (
                _changed_components(node, tuple_) if tuple_ is not None else ([], [], [])
            )
            LOG.record_parm(path, name, changed, keyed, order, origin=_parm_origin(path, name))
        elif kind == "SpareParmTemplatesChanged":
            LOG.drop_recent_parms(path)
            LOG.record("SpareParmsChanged", path)
        elif kind == "FlagChanged":
            changed = _flag_change(node)
            if changed:  # a spare parm edit also sends FlagChanged, with no flag changed
                LOG.record(kind, path, {"flags": changed})
        elif kind == "NameChanged":
            LOG.record(kind, path, {"old_name": kwargs.get("old_name")})
        elif kind == "InputRewired":
            LOG.record(kind, path, {"input": kwargs.get("input_index")})
        elif kind in ("ChildCreated", "ChildDeleted"):
            if any(node == manager for manager in _HOOKS.managers):
                return  # _on_manager_event already records a context manager's children
            child = kwargs.get("child_node")
            LOG.record(kind, _safe_path(child), _child_detail(child))
            if kind == "ChildCreated":
                _created(child)
        elif kind == "BeingDeleted":
            LOG.record(kind, path)
            with contextlib.suppress(Exception):
                _HOOKS.watched.pop(node.sessionId(), None)
                _HOOKS.flags.pop(node.sessionId(), None)
                _HOOKS.tuples.pop(node.sessionId(), None)
        else:
            LOG.record(kind, path)
    except Exception:
        log.debug("node event callback failed", exc_info=True)


def watch_node(node: Any) -> bool:
    """Record events on ``node`` from now on. Main thread; never raises.

    Inside a HocusPocus call, a node whose parent was created in the same call and was
    not yet watched when the node was made gets the ``ChildCreated`` its parent could not
    record (review 14 papercut 6: a geo and its CONTROLS null in one ``node_create``).

    Returns whether the node is watched (False when hooks are not installed, the node is
    gone, or :data:`WATCH_CAP` nodes are already watched).
    """
    if not _HOOKS.installed or node is None:
        return False
    try:
        sid = node.sessionId()
        if sid in _HOOKS.watched:
            return True
        if len(_HOOKS.watched) >= WATCH_CAP:
            return False
        if LOG.holding() and sid not in _HOOKS.created and not _quiet():
            parent = node.parent()
            if parent is not None and parent.sessionId() in _HOOKS.created:
                LOG.record("ChildCreated", node.path(), _child_detail(node), after=parent.path())
                _HOOKS.created.add(sid)
        node.addEventCallback(_node_types(), _on_node_event)
        _HOOKS.watched[sid] = node
        from .nodes import node_flags

        _HOOKS.flags[sid] = node_flags(node)
        _snapshot_tuples(node)
        return True
    except Exception:
        log.debug("watch_node failed", exc_info=True)
        return False


def _watch_later(session_id: int) -> None:
    """Watch a node the user created once its creation has finished.

    Attaching inside ``ChildCreated`` would record the creation script's own work (a
    light sets ~100 parms and builds ~40 children). The executor runs the posted call
    after the current main-thread work: the next idle tick in the GUI, the next queue
    item headless.
    """
    if _HOOKS.post is None:
        return
    first = not _HOOKS.pending
    _HOOKS.pending.add(session_id)
    if first:
        _HOOKS.post(_flush_pending)


def _flush_pending() -> None:
    import hou

    pending, _HOOKS.pending = _HOOKS.pending, set()
    for sid in pending:
        node = hou.nodeBySessionId(sid)
        if node is not None:
            watch_node(node)


def _attach_managers() -> None:
    import hou

    _detach_managers()
    for path in MANAGERS:
        node = hou.node(path)
        if node is None:
            continue
        try:
            node.addEventCallback(_manager_types(), _on_manager_event)
            _HOOKS.managers.append(node)
        except Exception:
            log.debug("cannot watch %s", path, exc_info=True)


def _detach_managers() -> None:
    for node in _HOOKS.managers:
        with contextlib.suppress(Exception):
            node.removeEventCallback(_manager_types(), _on_manager_event)
    _HOOKS.managers = []


def _forget_watched() -> None:
    for node in list(_HOOKS.watched.values()):
        with contextlib.suppress(Exception):
            node.removeEventCallback(_node_types(), _on_node_event)
    _HOOKS.watched.clear()
    _HOOKS.flags.clear()
    _HOOKS.tuples.clear()


def _on_hip_event(event_type: Any) -> None:
    try:
        import hou

        kind = event_type.name()
        loading = hou.hipFile.isLoadingHipFile()
        if kind in ("BeforeClear", "BeforeLoad", "BeforeMerge"):
            _HOOKS.hip_busy = True
        if kind in HIP_KINDS and not (loading and kind in ("BeforeClear", "AfterClear")):
            LOG.record(kind, hou.hipFile.path())
        if kind in ("AfterClear", "AfterLoad"):
            # Watched nodes are gone; manager nodes survive, but re-attach to be safe.
            _HOOKS.watched.clear()
            _HOOKS.flags.clear()
            _HOOKS.tuples.clear()
            _attach_managers()
        if kind in ("AfterLoad", "AfterMerge") or (kind == "AfterClear" and not loading):
            _HOOKS.hip_busy = False
    except Exception:
        log.debug("hip event callback failed", exc_info=True)


def install(
    post: Any = None, executor: Any = None, on_other: Any = None, owner: Any = None
) -> None:
    """Register the hip callback and the context-manager callbacks. Main thread; idempotent.

    The hooks are process-wide: the first caller (``owner``, the host) owns them; while
    they are installed a later call (a second in-process host) changes nothing.

    ``post(fn)`` queues ``fn`` for the main thread after the current work (the host's
    ``MainThreadExecutor.post``); without it, nodes the user creates are reported but
    not watched. ``executor`` (the host's ``MainThreadExecutor``) gets
    :func:`agent_work` as its work wrapper, which tells HocusPocus's own changes apart.
    ``on_other(event)`` is called for every ``origin: other`` node event (the host marks
    the scene dirty from it).
    """
    if _HOOKS.installed:
        return
    import hou

    _HOOKS.owner = owner
    _HOOKS.post = post
    LOG.on_other = on_other
    if executor is not None and hasattr(executor, "work_wrapper"):
        executor.work_wrapper = agent_work
        _HOOKS.executor = executor

    hou.hipFile.addEventCallback(_on_hip_event)
    _HOOKS.installed = True
    _HOOKS.hip_busy = False
    _attach_managers()


def uninstall(owner: Any = None) -> None:
    """Remove every callback :func:`install` and :func:`watch_node` added. Never raises.

    With ``owner``, only when that owner installed them: a second host stopping leaves the
    session host's hooks alone. Without it, unconditionally."""
    if not _HOOKS.installed:
        return
    if owner is not None and owner is not _HOOKS.owner:
        return
    with contextlib.suppress(Exception):
        import hou

        hou.hipFile.removeEventCallback(_on_hip_event)
    _detach_managers()
    _forget_watched()
    _HOOKS.pending.clear()
    _HOOKS.post = None
    LOG.on_other = None
    if _HOOKS.executor is not None:
        _HOOKS.executor.work_wrapper = None
        _HOOKS.executor = None
    _HOOKS.owner = None
    _HOOKS.installed = False


def record_pdg(path: str, event: str, **detail: Any) -> None:
    """A ``pdg`` event from the ``pdg`` tool (always the agent's). Any thread."""
    LOG.record("pdg", path, {"event": event, **detail}, origin=AGENT)


# -- the tool ---------------------------------------------------------------------------


@tool("events", main_thread=False)
def events(args: dict[str, Any], ctx: HostContext) -> dict[str, Any]:
    since = int_arg(args, "since", 0, 0)
    limit = int_arg(args, "limit", DEFAULT_LIMIT, 1, 1000)
    return LOG.read(since, limit, response_budget(ctx))

"""``events``: a host-side ring buffer of hip and node events. See docs/BIBLE.md §4.7.

The buffer holds the last :data:`RING_SIZE` events, each ``{seq, time, kind, path,
detail?}`` with a monotonic ``seq`` (it survives scene clears, not a host restart). Kinds
are Houdini's event names:

* hip: ``BeforeClear``, ``AfterClear``, ``BeforeLoad``, ``AfterLoad``, ``AfterMerge``,
  ``AfterSave`` (``path`` is the hip file). The clear inside a load is not reported.
* nodes: ``ChildCreated``/``ChildDeleted`` directly under the context managers
  (``/obj``, ``/stage``, ``/mat``, ``/out``, ``/tasks``) and under watched networks;
  ``NameChanged``, ``ParmTupleChanged`` (bursts on one parm tuple within
  :data:`COALESCE_S` collapse into one event with ``count``), ``FlagChanged``,
  ``InputRewired`` and ``BeingDeleted`` on watched nodes.

A node is watched once a tool calls :func:`watch_node` on it (tools that create or edit
nodes should, after the node exists), and automatically shortly after it is created
directly under a context manager (deferred, so its creation script is not recorded).
Node events are not recorded while a hip clear/load/merge is in progress (they would be
one ``ChildDeleted``/``ChildCreated`` per node).

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
from collections.abc import Iterator
from typing import Any

from .nodes import bad_arg
from .registry import HostContext, tool

log = logging.getLogger("hocuspocus.host.events")

RING_SIZE = 2000
COALESCE_S = 0.1
WATCH_CAP = 5000
MANAGERS = ("/obj", "/stage", "/mat", "/out", "/tasks")
DEFAULT_LIMIT = 50
HIP_KINDS = ("BeforeClear", "AfterClear", "BeforeLoad", "AfterLoad", "AfterMerge", "AfterSave")


def _now_iso() -> str:
    now = time.time()
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(now)) + f".{int(now % 1 * 1000):03d}Z"


class EventLog:
    """Thread-safe ring buffer with a monotonic sequence number."""

    def __init__(self, size: int = RING_SIZE) -> None:
        self._buf: deque[dict[str, Any]] = deque(maxlen=size)
        self._lock = threading.Lock()
        self._seq = 0
        self._recent_parm: dict[tuple[str, str | None], tuple[dict[str, Any], float]] = {}

    @property
    def last_seq(self) -> int:
        return self._seq

    def record(self, kind: str, path: str, detail: dict[str, Any] | None = None) -> dict[str, Any]:
        with self._lock:
            self._seq += 1
            event: dict[str, Any] = {
                "seq": self._seq,
                "time": _now_iso(),
                "kind": kind,
                "path": path,
            }
            if detail:
                event["detail"] = detail
            self._buf.append(event)
            return event

    def record_parm(self, path: str, parm: str | None) -> None:
        """``ParmTupleChanged``, coalesced per (node, parm tuple) within :data:`COALESCE_S`."""
        key = (path, parm)
        mono = time.monotonic()
        with self._lock:
            recent = self._recent_parm.get(key)
            if recent is not None:
                event, last = recent
                if mono - last <= COALESCE_S and self._buf and event["seq"] >= self._buf[0]["seq"]:
                    detail = event.setdefault("detail", {})
                    detail["count"] = detail.get("count", 1) + 1
                    event["time"] = _now_iso()
                    self._recent_parm[key] = (event, mono)
                    return
            if len(self._recent_parm) > 256:
                self._recent_parm = {
                    k: v for k, v in self._recent_parm.items() if mono - v[1] <= COALESCE_S
                }
        event = self.record("ParmTupleChanged", path, {"parm": parm} if parm else None)
        with self._lock:
            self._recent_parm[key] = (event, mono)

    def read(self, since: int, limit: int) -> dict[str, Any]:
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
        out["events"] = chunk
        out["next_since"] = chunk[-1]["seq"] if chunk else max(since, last)
        out["dropped"] = max(0, oldest - since - 1)
        if len(newer) > limit:
            out["more"] = True
        return out


LOG = EventLog()


# -- hou wiring -------------------------------------------------------------------------


class _Hooks:
    def __init__(self) -> None:
        self.installed = False
        self.hip_busy = False
        self.muted = 0
        self.watched: dict[int, Any] = {}
        self.managers: list[Any] = []
        self.watch_overflow = 0
        self.post: Any = None
        self.pending: set[int] = set()


_HOOKS = _Hooks()


@contextlib.contextmanager
def muted() -> Iterator[None]:
    """Record no node events inside the block (HocusPocus's own temporary nodes)."""
    _HOOKS.muted += 1
    try:
        yield
    finally:
        _HOOKS.muted -= 1


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


def _on_manager_event(**kwargs: Any) -> None:
    try:
        if _HOOKS.hip_busy or _HOOKS.muted:
            return
        import hou

        child = kwargs.get("child_node")
        kind = kwargs["event_type"].name()
        LOG.record(kind, _safe_path(child), _child_detail(child))
        if kwargs["event_type"] == hou.nodeEventType.ChildCreated and child is not None:
            _watch_later(child.sessionId())
    except Exception:
        log.debug("manager event callback failed", exc_info=True)


def _on_node_event(**kwargs: Any) -> None:
    try:
        if _HOOKS.hip_busy or _HOOKS.muted:
            return
        node = kwargs.get("node")
        kind = kwargs["event_type"].name()
        path = _safe_path(node)
        if kind == "ParmTupleChanged":
            tuple_ = kwargs.get("parm_tuple")
            LOG.record_parm(path, tuple_.name() if tuple_ is not None else None)
        elif kind == "NameChanged":
            LOG.record(kind, path, {"old_name": kwargs.get("old_name")})
        elif kind == "InputRewired":
            LOG.record(kind, path, {"input": kwargs.get("input_index")})
        elif kind in ("ChildCreated", "ChildDeleted"):
            child = kwargs.get("child_node")
            LOG.record(kind, _safe_path(child), _child_detail(child))
        elif kind == "BeingDeleted":
            LOG.record(kind, path)
            with contextlib.suppress(Exception):
                _HOOKS.watched.pop(node.sessionId(), None)
        else:
            LOG.record(kind, path)
    except Exception:
        log.debug("node event callback failed", exc_info=True)


def watch_node(node: Any) -> bool:
    """Record events on ``node`` from now on. Main thread; never raises.

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
            _HOOKS.watch_overflow += 1
            return False
        node.addEventCallback(_node_types(), _on_node_event)
        _HOOKS.watched[sid] = node
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


def watched_count() -> int:
    return len(_HOOKS.watched)


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
            _attach_managers()
        if kind in ("AfterLoad", "AfterMerge") or (kind == "AfterClear" and not loading):
            _HOOKS.hip_busy = False
    except Exception:
        log.debug("hip event callback failed", exc_info=True)


def install(post: Any = None) -> None:
    """Register the hip callback and the context-manager callbacks. Main thread; idempotent.

    ``post(fn)`` queues ``fn`` for the main thread after the current work (the host's
    ``MainThreadExecutor.post``); without it, nodes the user creates are reported but
    not watched.
    """
    if _HOOKS.installed:
        return
    import hou

    _HOOKS.post = post

    hou.hipFile.addEventCallback(_on_hip_event)
    _HOOKS.installed = True
    _HOOKS.hip_busy = False
    _attach_managers()


def uninstall() -> None:
    """Remove every callback :func:`install` and :func:`watch_node` added. Never raises."""
    if not _HOOKS.installed:
        return
    with contextlib.suppress(Exception):
        import hou

        hou.hipFile.removeEventCallback(_on_hip_event)
    _detach_managers()
    _forget_watched()
    _HOOKS.pending.clear()
    _HOOKS.post = None
    _HOOKS.installed = False


# -- the tool ---------------------------------------------------------------------------


def _int_arg(args: dict[str, Any], key: str, default: int, low: int, high: int | None) -> int:
    value = args.get(key, default)
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int) or value < low:
        raise bad_arg(f"'{key}' must be an integer >= {low}.")
    if high is not None and value > high:
        raise bad_arg(f"'{key}' must be at most {high}.")
    return value


@tool("events", main_thread=False)
def events(args: dict[str, Any], ctx: HostContext) -> dict[str, Any]:
    since = _int_arg(args, "since", 0, 0, None)
    limit = _int_arg(args, "limit", DEFAULT_LIMIT, 1, 1000)
    return LOG.read(since, limit)

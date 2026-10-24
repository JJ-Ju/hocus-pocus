"""Host tool registry: ``@tool("name")`` maps catalogue names to implementations.

An implementation is ``fn(args: dict, ctx: HostContext) -> dict``. It runs on Houdini's
main thread (unless registered with ``main_thread=False``) and raises
:class:`~hocuspocus.tools.errors.ToolError` for user-level failures.

The ``scene=False`` convention (docs/BIBLE.md §4.1). By default a tool whose catalogue
entry is not ``read_only`` is *mutating*: the dispatcher refuses it in read-only mode,
wraps it in one labelled undo group, records the label and marks the scene dirty. Some
tools cannot live with that and register with ``scene=False``, taking on whichever of
those duties apply themselves:

* ``undo`` — ``hou.undos.performUndo``/``performRedo`` raise inside an undo group.
* ``time``, ``hda`` — reads (``time`` with no arguments, ``hda list``)
  must not open an undo group or dirty the scene; setting opens its own group and marks
  dirty.
* ``cook``, ``pdg``, ``render``, ``job`` — a cook, PDG work items, rendered files and
  host-side jobs are not hip state; these also run off the main thread
  (``main_thread=False``) so they can wait on jobs and reach ``hou`` only through the
  executor.
* ``look`` — a look leaves the scene as it was (its camera and ROP are temporary), so it must not add an undo step or dirty the scene. It also runs off the
  main thread: headless, it snapshots the scene in one executor call and waits for the
  child hython without holding the main thread; the GUI path is one executor call.

A mutating tool whose call turned out to change nothing (a ``dry_run``) returns
``"_changed": False`` in its result dict: the dispatcher strips it, records no undo
label, leaves the dirty flag alone, and lets ``dry_run: true`` calls through in
read-only mode (refusing them afterwards if the marker is missing).

The catalogue annotations describe what the agent sees, not the registration: these
tools are ``readOnlyHint: false`` (they can change something), ``destructiveHint:
false``, and ``idempotentHint: true`` when repeating the call is harmless (``time``,
``cook``, ``job``, ``look``). A unit test pins the ``scene=False`` set.
"""

from __future__ import annotations

import importlib
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from hocuspocus.tools import catalog

log = logging.getLogger("hocuspocus.host.tools")

ToolFn = Callable[[dict[str, Any], "HostContext"], Any]

INTERNAL_TOOLS = frozenset({"session_info"})
"""Host-only names the bridge calls that are not in the agent-facing catalogue."""

TOOL_MODULES = (
    "session",
    "hip",
    "code",
    "state",
    "parms",
    "nodes",
    "network",
    "cook",
    "types",
    "geo",
    "visual",
    "hda",
    "usd",
    "pdg",
    "events",
    "inspect",
    "search",
    "edit",
    "look",
)
"""Modules under ``hocuspocus.host.tools`` imported by :func:`load_all`."""


@dataclass(frozen=True)
class HostTool:
    name: str
    fn: ToolFn
    read_only: bool | None = None
    """Fallback when the catalogue has no entry; the catalogue's ``read_only`` wins."""
    main_thread: bool = True
    """False for tools that never touch ``hou`` (e.g. ``job``): they skip the executor."""
    scene: bool = True
    """False when the dispatcher must not open an undo group, refuse in read-only mode or
    mark the scene dirty for this tool; it does whatever applies itself (see the module
    docstring)."""

    @property
    def spec(self) -> catalog.ToolSpec | None:
        return catalog.get(self.name)

    @property
    def mutating(self) -> bool:
        if not self.scene:
            return False
        spec = self.spec
        if spec is not None:
            return not spec.read_only
        return not bool(self.read_only)


DIRTY_SOURCES = ("tracked", "user_event", "houdini_flag")
"""Why the scene is dirty (``houdini_status.connected.hip.dirty_source``): ``tracked``, a
HocusPocus call changed it; ``user_event``, an ``origin: other`` node event (the user's own
edit) arrived since the last save, load or clear; ``houdini_flag``, a GUI Houdini marked
the hip modified between two HocusPocus calls (an edit on a node no event watches)."""


@dataclass
class SceneState:
    """Scene generation counter and the host's dirty flag (docs/BIBLE.md §3.2).

    One dirty source in both modes (docs/parity.md G1): the tracked flag (agent
    mutations) OR a change made outside HocusPocus since the last save, load or clear.
    Houdini's own ``hasUnsavedChanges()`` is never read directly: hython reports True
    even after a save, and the GUI flips it for HocusPocus's own temporary nodes (type
    probes, render overrides, captures)."""

    generation: int = 0
    dirty: bool = False
    """Tracked dirty flag: set by agent mutations, cleared by save, load and clear."""
    user_dirty: str | None = None
    """``user_event`` or ``houdini_flag`` once something outside HocusPocus changed the
    scene since the last save, load or clear; None otherwise."""
    houdini_flag: bool | None = None
    """GUI only: Houdini's ``hasUnsavedChanges()`` at the end of the last HocusPocus
    main-thread work item (None when unknown). A False -> True change before the next
    work item is a change made outside HocusPocus (:meth:`check_houdini_flag`)."""
    clean_events: int = 0
    """Incremented on every save/load/clear so the dispatcher can tell whether a
    mutating call left the scene clean."""
    recent: list[str] = field(default_factory=list)
    """Hip files saved or loaded in this session, newest first. hython never writes
    ``file.history``, so ``recent`` would otherwise stay empty headless."""
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def note_file(self, path: str, limit: int = 10) -> None:
        if not path:
            return
        with self._lock:
            key = path.replace("\\", "/")
            self.recent = [key, *[p for p in self.recent if p != key]][:limit]

    def bump(self) -> int:
        with self._lock:
            self.generation += 1
            return self.generation

    def mark_dirty(self) -> None:
        self.dirty = True

    def mark_user_dirty(self, source: str = "user_event") -> None:
        """Something outside HocusPocus changed the scene. The first source is kept."""
        with self._lock:
            if self.user_dirty is None:
                self.user_dirty = source

    def mark_clean(self) -> None:
        with self._lock:
            self.dirty = False
            self.user_dirty = None
            self.houdini_flag = False
            self.clean_events += 1

    @property
    def is_dirty(self) -> bool:
        return self.dirty or self.user_dirty is not None

    @property
    def dirty_source(self) -> str | None:
        """``tracked``, ``user_event`` or ``houdini_flag`` (:data:`DIRTY_SOURCES`), or None
        when the scene is clean."""
        return "tracked" if self.dirty else self.user_dirty

    def check_houdini_flag(self, flag: bool) -> None:
        """GUI, before a HocusPocus work item: Houdini's flag went False -> True since the
        last one ended, so the user changed the scene in between."""
        if flag and self.houdini_flag is False:
            self.mark_user_dirty("houdini_flag")

    def note_houdini_flag(self, flag: bool) -> None:
        """GUI, after a HocusPocus work item: Houdini's flag as that work left it (its
        own temporary nodes may have set it; that is not the user's change)."""
        self.houdini_flag = bool(flag)


@dataclass
class HostContext:
    """What a tool implementation may use."""

    config: Any
    executor: Any
    logger: logging.Logger
    scene: SceneState
    jobs: Any
    undo: Any
    ui: bool = False
    port: int = 0
    pid: int = 0
    started: str = ""
    label: str = ""
    extras: dict[str, Any] = field(default_factory=dict)


_REGISTRY: dict[str, HostTool] = {}


def tool(
    name: str,
    *,
    read_only: bool | None = None,
    main_thread: bool = True,
    scene: bool = True,
) -> Callable[[ToolFn], ToolFn]:
    """Register ``fn`` as the host implementation of tool ``name``."""

    def decorator(fn: ToolFn) -> ToolFn:
        if name in _REGISTRY and _REGISTRY[name].fn is not fn:
            log.warning("host tool %r registered twice; the later definition wins", name)
        _REGISTRY[name] = HostTool(name, fn, read_only, main_thread, scene)
        return fn

    return decorator


def get(name: str) -> HostTool | None:
    return _REGISTRY.get(name)


def registered() -> dict[str, HostTool]:
    return dict(_REGISTRY)


def load_all() -> dict[str, HostTool]:
    for module in TOOL_MODULES:
        importlib.import_module(f"hocuspocus.host.tools.{module}")
    return registered()


def validate(logger: logging.Logger | None = None) -> dict[str, list[str]]:
    """Cross-check registrations against the catalogue. Logs, never raises."""
    logger = logger or log
    names = set(_REGISTRY)
    catalog_names = {spec.name for spec in catalog.TOOLS}
    unknown = sorted(names - catalog_names - INTERNAL_TOOLS)
    missing = sorted(
        spec.name for spec in catalog.TOOLS if not spec.bridge_local and spec.name not in names
    )
    if not catalog.TOOLS:
        logger.warning("tool catalogue is empty; skipping host/catalogue cross-check")
        return {"unknown": [], "missing": []}
    if unknown:
        logger.warning("host tools not in the catalogue: %s", ", ".join(unknown))
    if missing:
        logger.info("catalogue tools not implemented by this host yet: %s", ", ".join(missing))
    return {"unknown": unknown, "missing": missing}

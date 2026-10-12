"""Host tool registry: ``@tool("name")`` maps catalogue names to implementations.

An implementation is ``fn(args: dict, ctx: HostContext) -> dict``. It runs on Houdini's
main thread (unless registered with ``main_thread=False``) and raises
:class:`~hocuspocus.tools.errors.ToolError` for user-level failures.
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
    """False for tools that change host state only (``job``): no undo group, no
    ``read_only`` refusal, no dirty marking."""

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

    @property
    def headless_ok(self) -> bool:
        spec = self.spec
        return True if spec is None else spec.headless_ok


@dataclass
class SceneState:
    """Scene generation counter and the host's view of the dirty flag."""

    generation: int = 0
    dirty: bool = False
    """Tracked dirty flag. Authoritative headless, where ``hasUnsavedChanges()`` is
    always True in hython 22.0; the GUI asks Houdini instead."""
    clean_events: int = 0
    """Incremented on every save/load/clear so the dispatcher can tell whether a
    mutating call left the scene clean."""
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def bump(self) -> int:
        with self._lock:
            self.generation += 1
            return self.generation

    def mark_dirty(self) -> None:
        self.dirty = True

    def mark_clean(self) -> None:
        with self._lock:
            self.dirty = False
            self.clean_events += 1


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

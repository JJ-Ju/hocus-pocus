"""The instance registry as the bridge sees it. Stdlib only. See docs/BIBLE.md §3.2, §3.3, §3.6.

Each running host writes ``<state_dir>/instances/<pid>.json``. The bridge reads them,
deletes entries whose pid is dead, and picks a target with :func:`select`.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..host.registry import pid_alive
from ..tools import paths
from ..tools.errors import ToolError

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Instance:
    pid: int
    port: int
    token: str
    hp: int = 1
    houdini: str = ""
    ui: bool = False
    hip: str = ""
    started: str = ""
    generation: int = 0
    label: str = ""
    launched_by: int | None = None
    """The pid of the HocusPocus bridge that launched this Houdini, if one did."""
    name: str = ""
    """A name the agent gave this Houdini with ``houdini_connect {pid, name}`` (1.3)."""
    file: Path | None = field(default=None, compare=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any], file: Path | None = None) -> Instance:
        return cls(
            pid=int(data["pid"]),
            port=int(data["port"]),
            token=str(data["token"]),
            hp=int(data.get("hp", 1)),
            houdini=str(data.get("houdini") or ""),
            ui=bool(data.get("ui", False)),
            hip=str(data.get("hip") or ""),
            started=str(data.get("started") or ""),
            generation=int(data.get("generation") or 0),
            label=str(data.get("label") or ""),
            launched_by=_optional_pid(data.get("launched_by")),
            name=str(data.get("name") or ""),
            file=file,
        )

    def public(self) -> dict[str, Any]:
        """The agent-visible view (never the token)."""
        return {
            "pid": self.pid,
            "port": self.port,
            "label": self.label,
            "houdini": self.houdini,
            "ui": self.ui,
            "hip": self.hip,
            "started": self.started,
            "generation": self.generation,
            "launched_by": self.launched_by,
            **({"name": self.name} if self.name else {}),
        }

    def candidate(self) -> dict[str, Any]:
        """How an error names this instance as a choice: ``{pid, label, ui, hip, name?}``."""
        out: dict[str, Any] = {"pid": self.pid, "label": self.label, "ui": self.ui, "hip": self.hip}
        if self.name:
            out["name"] = self.name
        return out

    def describe(self) -> str:
        """``3084 'editor' (houdinifx, GUI, city.hip)``: one instance in a sentence."""
        hip = self.hip.replace("\\", "/").rsplit("/", 1)[-1] if self.hip else "untitled"
        name = f" '{self.name}'" if self.name else ""
        return f"{self.pid}{name} ({self.label or 'houdini'}, {'GUI' if self.ui else 'headless'}, {hip})"


def _optional_pid(value: Any) -> int | None:
    try:
        pid = int(value)
    except (TypeError, ValueError):
        return None
    return pid if pid > 0 else None


# -- liveness and identity ------------------------------------------------------------------
#
# ``pid_alive`` is the host's stdlib-only helper (one implementation for both processes).


class StaleEntry(Exception):
    """A registry entry whose pid is alive but whose port is not that host (review 10
    section 1.4): the pid was reused after a crash, or the port by another host."""


STALE_REASONS = frozenset({"refused", "unauthorized"})
"""``houdini_offline`` reasons that prove an entry stale: nothing listens on its port, or
the listener rejects its token. Either way the request never ran."""


def is_stale_error(exc: ToolError) -> bool:
    detail = exc.detail if isinstance(exc.detail, dict) else {}
    return exc.code == "houdini_offline" and detail.get("reason") in STALE_REASONS


def check_identity(inst: Instance, client: Any) -> dict[str, Any]:
    """``/health`` of ``inst``; raises :class:`StaleEntry` when the answer is not that host.

    Stale: the port refuses connections, or answers with another pid. A host whose
    ``/health`` carries no pid is taken at its word."""
    try:
        health = client.health()
    except ToolError as exc:
        if is_stale_error(exc):
            raise StaleEntry(f"pid {inst.pid}: {exc.message}") from exc
        raise
    pid = health.get("pid") if isinstance(health, dict) else None
    if isinstance(pid, int) and not isinstance(pid, bool) and pid != inst.pid:
        raise StaleEntry(
            f"the registry entry for pid {inst.pid} is stale: port {inst.port} is served by "
            f"pid {pid}"
        )
    return health


def forget(inst: Instance) -> bool:
    """Delete ``inst``'s registry file. Returns whether it was removed."""
    if inst.file is None:
        return False
    try:
        inst.file.unlink()
    except FileNotFoundError:
        return False
    except OSError as exc:
        log.debug("cannot remove stale registry entry %s: %s", inst.file, exc)
        return False
    log.info("removed stale registry entry for pid %s", inst.pid)
    return True


# -- scanning --------------------------------------------------------------------------------


def read_entries(directory: Path) -> list[Instance]:
    """Parse every ``*.json`` entry; unparsable files are skipped (they may be mid-write)."""
    found: list[Instance] = []
    try:
        files = sorted(directory.glob("*.json"))
    except OSError:
        return found
    for file in files:
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
            found.append(Instance.from_dict(data, file))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            log.debug("skipping registry entry %s: %s", file, exc)
    return found


def scan(
    directory: Path | None = None,
    *,
    prune: bool = True,
    alive: Callable[[int], bool] = pid_alive,
) -> list[Instance]:
    """Live instances, most recently started first. Dead entries are deleted when ``prune``."""
    directory = directory if directory is not None else paths.instances_dir()
    live: list[Instance] = []
    for inst in read_entries(directory):
        if alive(inst.pid):
            live.append(inst)
            continue
        if prune and inst.file is not None:
            try:
                inst.file.unlink()
                log.info("pruned stale registry entry for dead pid %s", inst.pid)
            except OSError:
                pass
    return sort_recent(live)


def sort_recent(instances: Iterable[Instance]) -> list[Instance]:
    # ISO-8601 UTC timestamps sort lexically; pid breaks ties deterministically.
    return sorted(instances, key=lambda i: (i.started, i.pid), reverse=True)


# -- selection -----------------------------------------------------------------------------


def sort_preferred(instances: Iterable[Instance]) -> list[Instance]:
    """The order the bridge prefers when nothing is pinned: GUI sessions first (the user's
    scene; review 19 papercut 2), then the most recently started."""
    recent = sort_recent(instances)
    return [i for i in recent if i.ui] + [i for i in recent if not i.ui]


@dataclass(frozen=True, slots=True)
class Selection:
    instance: Instance | None
    warnings: tuple[str, ...] = ()
    live_count: int = 0
    pinned: bool = False
    """True when ``instance`` is the one ``houdini_connect`` pinned."""
    lost_pid: int | None = None
    """The pinned pid when it is no longer live (``instance`` is then None)."""
    candidates: tuple[Instance, ...] = ()
    """Every live instance, in preference order."""

    @property
    def multiple(self) -> bool:
        return self.live_count > 1

    @property
    def ambiguous(self) -> bool:
        """Several live instances and none pinned: mutating tools must refuse."""
        return not self.pinned and self.instance is not None and self.live_count > 1


def select(instances: list[Instance], preferred_pid: int | None = None) -> Selection:
    """BIBLE §3.3 rule 3 (1.3): the pinned instance, never another one in its place (a dead
    pin is ``lost_pid``) → the only live one → with several, the preferred one
    (:func:`sort_preferred`) for reads only, with a warning."""
    ordered = sort_preferred(instances)
    if preferred_pid is not None:
        for inst in ordered:
            if inst.pid == preferred_pid:
                return Selection(inst, (), len(ordered), pinned=True, candidates=tuple(ordered))
        return Selection(None, (), len(ordered), lost_pid=preferred_pid, candidates=tuple(ordered))
    if not ordered:
        return Selection(None, (), 0)
    chosen = ordered[0]
    warnings: list[str] = []
    if len(ordered) > 1:
        warnings.append(ambiguity_warning(chosen, ordered))
    return Selection(chosen, tuple(warnings), len(ordered), candidates=tuple(ordered))


def ambiguity_warning(chosen: Instance, ordered: list[Instance]) -> str:
    choices = "; ".join(inst.describe() for inst in ordered)
    return (
        f"{len(ordered)} Houdini instances are running and none is pinned: reads go to pid "
        f"{chosen.pid}, and tools that change a scene refuse with ambiguous_instance. Pin one "
        f"with houdini_connect {{pid}}: {choices}."
    )


def set_name(inst: Instance, name: str) -> None:
    """Store ``name`` in ``inst``'s registry entry (the host keeps it on later rewrites)."""
    from ..host.registry import _write_private_atomic

    if inst.file is None:
        return
    try:
        data = json.loads(inst.file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ToolError(
            "houdini_offline",
            f"Cannot read the registry entry of pid {inst.pid}: {exc}",
            retryable=False,
        ) from exc
    if name:
        data["name"] = name
    else:
        data.pop("name", None)
    _write_private_atomic(inst.file, json.dumps(data, indent=1))


# -- launch records ----------------------------------------------------------------------

LAUNCH_RECORD_MAX_AGE_S = 7 * 24 * 3600.0


class LaunchLog:
    """``<state_dir>/launches/<pid>.json``: which bridge launched which Houdini.

    The registry entry of a Houdini that died with the bridge that launched it is gone (or
    pruned) by the time a later bridge starts, so the launch is recorded separately: the
    later bridge can then say *why* nothing is running (review 11 B1).
    """

    def __init__(self, directory: Path | None = None) -> None:
        self.directory = directory if directory is not None else paths.state_dir() / "launches"

    def record(self, inst: Instance, *, mode: str, outlives_server: bool) -> None:
        data = {
            "pid": inst.pid,
            "launched_by": os.getpid(),
            "mode": mode,
            "hip": inst.hip,
            "started": inst.started,
            "outlives_server": outlives_server,
            "recorded": time.time(),
        }
        try:
            paths.ensure_private_dir(self.directory)
            (self.directory / f"{inst.pid}.json").write_text(json.dumps(data), encoding="utf-8")
        except OSError as exc:
            log.debug("cannot record launch of pid %s: %s", inst.pid, exc)

    def _entries(self) -> list[tuple[Path, dict[str, Any]]]:
        out = []
        try:
            files = sorted(self.directory.glob("*.json"))
        except OSError:
            return out
        for file in files:
            try:
                data = json.loads(file.read_text(encoding="utf-8"))
                int(data["pid"])
            except (OSError, ValueError, KeyError, TypeError):
                continue
            out.append((file, data))
        return out

    def take_orphans(
        self, *, own_pid: int | None = None, alive: Callable[[int], bool] = pid_alive
    ) -> list[dict[str, Any]]:
        """Records of launched Houdinis that have exited, launched by another bridge;
        each is reported once (its file is removed). Stale records are pruned."""
        own_pid = os.getpid() if own_pid is None else own_pid
        found: list[dict[str, Any]] = []
        now = time.time()
        for file, data in self._entries():
            pid = int(data["pid"])
            if alive(pid):
                continue
            launcher = _optional_pid(data.get("launched_by"))
            if launcher is not None and launcher != own_pid:
                recorded = data.get("recorded")
                fresh = not isinstance(recorded, int | float) or (
                    now - recorded < LAUNCH_RECORD_MAX_AGE_S
                )
                if fresh:
                    found.append(dict(data, launcher_alive=alive(launcher)))
            with contextlib.suppress(OSError):
                file.unlink()
        found.sort(key=lambda d: str(d.get("started") or ""), reverse=True)
        return found

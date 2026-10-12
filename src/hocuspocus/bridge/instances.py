"""The instance registry as the bridge sees it. Stdlib only. See docs/BIBLE.md §3.2, §3.3, §3.6.

Each running host writes ``<state_dir>/instances/<pid>.json``. The bridge reads them,
deletes entries whose pid is dead, and picks a target with :func:`select`.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import sys
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..tools import paths

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
        }


def _optional_pid(value: Any) -> int | None:
    try:
        pid = int(value)
    except (TypeError, ValueError):
        return None
    return pid if pid > 0 else None


# -- liveness ------------------------------------------------------------------------------


def pid_alive(pid: int) -> bool:
    """Cross-platform "is this process running" check."""
    if pid <= 0:
        return False
    if sys.platform == "win32":
        return _pid_alive_windows(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _pid_alive_windows(pid: int) -> bool:
    import ctypes
    from ctypes import wintypes

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    STILL_ACTIVE = 259
    ERROR_ACCESS_DENIED = 5

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)

    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        # Access denied means it exists but belongs to someone else.
        return ctypes.get_last_error() == ERROR_ACCESS_DENIED
    try:
        code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return True
        return code.value == STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


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


@dataclass(frozen=True, slots=True)
class Selection:
    instance: Instance | None
    warnings: tuple[str, ...] = ()
    live_count: int = 0

    @property
    def multiple(self) -> bool:
        return self.live_count > 1


def select(instances: list[Instance], preferred_pid: int | None = None) -> Selection:
    """BIBLE §3.3 rule 3: explicit → the only live one → the most recent (with a warning)."""
    ordered = sort_recent(instances)
    warnings: list[str] = []
    if preferred_pid is not None:
        for inst in ordered:
            if inst.pid == preferred_pid:
                return Selection(inst, (), len(ordered))
        warnings.append(
            f"The Houdini you were driving (pid {preferred_pid}) has exited; changes made in it "
            "since its last save are lost. Selecting another live instance."
        )
    if not ordered:
        return Selection(None, tuple(warnings), 0)
    chosen = ordered[0]
    if len(ordered) > 1:
        others = ", ".join(str(i.pid) for i in ordered[1:])
        warnings.append(
            f"{len(ordered)} Houdini instances are running; using the most recent (pid {chosen.pid}). "
            f"Others: {others}. Pin one with houdini_connect {{pid}}."
        )
    return Selection(chosen, tuple(warnings), len(ordered))


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

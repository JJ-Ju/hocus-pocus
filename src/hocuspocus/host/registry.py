"""Per-instance registry files: ``<state_dir>/instances/<pid>.json``. Stdlib only.

See docs/BIBLE.md §3.2. Each live host writes one entry with its port and token; the
bridge discovers hosts by listing the directory and treats entries whose pid is dead as
stale. Writes are atomic (temp file + ``os.replace``) and user-private where the OS
allows (POSIX mode 0600; on Windows the per-user ``%LOCALAPPDATA%`` ACL applies).
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import secrets
import sys
import threading
import time
from pathlib import Path
from typing import Any

from hocuspocus.tools.catalog import HP_RPC_VERSION
from hocuspocus.tools.paths import ensure_private_dir

log = logging.getLogger("hocuspocus.host.registry")

ENTRY_FIELDS = (
    "hp",
    "pid",
    "port",
    "token",
    "houdini",
    "ui",
    "hip",
    "started",
    "generation",
    "label",
)


REPLACE_TRIES = 10
REPLACE_DELAY_S = 0.02
"""Backoff for ``os.replace``: on Windows it raises PermissionError while a reader (the
bridge) has the target open. 10 tries, doubling from 20 ms and capped at 250 ms, wait
about 1.3 s in total."""


def new_token() -> str:
    return secrets.token_urlsafe(32)


def pid_alive(pid: int) -> bool:
    """True when a process with ``pid`` exists. Never signals or terminates anything.

    Windows: ``OpenProcess`` + ``GetExitCodeProcess`` (``os.kill`` there would *terminate*
    the process). POSIX: ``os.kill(pid, 0)``, and a zombie (exited, not yet reaped by its
    parent) counts as dead (:func:`_is_zombie`). A process that exited with code 259
    (``STILL_ACTIVE``) is indistinguishable from a live one; that is acceptable here.
    """
    if not isinstance(pid, int) or pid <= 0:
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
    return not _is_zombie(pid)


def _is_zombie(pid: int) -> bool:
    """True when ``pid`` has exited but its parent has not reaped it, which
    ``kill(pid, 0)`` cannot tell from a live process. A Houdini the bridge launched and
    never waited for stays a zombie child of the bridge after it exits or crashes (POSIX
    only; Windows has no zombies), so without this the bridge took it for alive:
    ``delivery_unknown`` instead of ``houdini_offline``, no ``instance_lost``.

    Our own child: ``waitid(..., WNOWAIT)`` (Linux; macOS from Python 3.13), which leaves
    it for ``Popen`` to reap. Anyone's: the state letter in ``/proc/<pid>/stat`` (Linux).
    """
    waitid = getattr(os, "waitid", None)
    flags = getattr(os, "WEXITED", 0) | getattr(os, "WNOHANG", 0) | getattr(os, "WNOWAIT", 0)
    if waitid is not None and hasattr(os, "P_PID") and flags:
        try:
            if waitid(os.P_PID, pid, flags) is not None:
                return True  # our child, exited, left unreaped
        except (ChildProcessError, OSError):
            pass  # not our child
    state = _proc_state(pid)
    return state == "Z"


def _proc_state(pid: int) -> str | None:
    """The state letter of ``/proc/<pid>/stat`` (``R``, ``S``, ``Z``...), or None where
    there is no ``/proc`` (macOS) or no such process."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="ascii", errors="replace")
    except OSError:
        return None
    # "pid (comm) state ...": comm may hold spaces and parentheses; the state follows
    # the last ")".
    fields = stat.rsplit(")", 1)[-1].split()
    return fields[0] if fields else None


def _pid_alive_windows(pid: int) -> bool:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)

    process_query_limited_information = 0x1000
    error_access_denied = 5
    still_active = 259

    handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
    if not handle:
        # Access denied means the process exists but belongs to someone else.
        return ctypes.get_last_error() == error_access_denied
    try:
        code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return True
        return code.value == still_active
    finally:
        kernel32.CloseHandle(handle)


def _write_private_atomic(path: Path, text: str) -> None:
    ensure_private_dir(path.parent)
    tmp = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    fd = os.open(tmp, flags, 0o600)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(text.encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
        _replace_with_retry(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def _replace_with_retry(src: Path, dst: Path) -> None:
    delay = REPLACE_DELAY_S
    for attempt in range(REPLACE_TRIES):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == REPLACE_TRIES - 1:
                raise
            time.sleep(delay)
            delay = min(delay * 2, 0.25)


def read_entry(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def list_entries(directory: Path) -> list[dict[str, Any]]:
    """All parseable entries, without liveness filtering."""
    entries = []
    if not directory.is_dir():
        return entries
    for path in sorted(directory.glob("*.json")):
        entry = read_entry(path)
        if entry is not None:
            entries.append(entry)
    return entries


def prune_stale(directory: Path, *, alive=pid_alive) -> list[Path]:
    """Delete entries whose pid is provably dead. Returns removed paths.

    An entry that cannot be read or parsed may be mid-replace or held open by another
    reader; it is judged by the pid in its file name, so a transient failure never
    deletes a live host's entry.
    """
    removed: list[Path] = []
    if not directory.is_dir():
        return removed
    for path in directory.glob("*.json"):
        if not path.stem.isdigit():
            continue  # not a registry entry
        entry = read_entry(path)
        pid = entry.get("pid") if entry else None
        if not isinstance(pid, int) or isinstance(pid, bool):
            pid = int(path.stem)
        if not alive(pid):
            try:
                path.unlink()
                removed.append(path)
            except FileNotFoundError:
                pass
            except OSError as exc:
                log.debug("cannot remove stale registry entry %s: %s", path, exc)
    return removed


class InstanceRegistry:
    """This process's registry entry."""

    def __init__(self, directory: Path, pid: int | None = None) -> None:
        self.directory = Path(directory)
        self.pid = os.getpid() if pid is None else pid
        self.path = self.directory / f"{self.pid}.json"
        self._entry: dict[str, Any] = {}
        self._pending = False
        """True when the last write failed: the file is stale and the next update rewrites it."""
        self._lock = threading.Lock()

    @property
    def entry(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._entry)

    def write(self, entry: dict[str, Any]) -> Path:
        with self._lock:
            data = {"hp": HP_RPC_VERSION, "pid": self.pid}
            data.update(entry)
            self._entry = data
            self._pending = True
            _write_private_atomic(self.path, json.dumps(data, indent=1, sort_keys=False))
            self._pending = False
        return self.path

    def update(self, **fields: Any) -> None:
        with self._lock:
            if not self._entry:
                return
            changed = {k: v for k, v in fields.items() if self._entry.get(k) != v}
            if not changed and not self._pending:
                return
            self._entry.update(changed)
            # The bridge writes ``name`` (houdini_connect {pid, name}; 1.3): keep it.
            on_disk = read_entry(self.path) or {}
            if on_disk.get("name"):
                self._entry["name"] = on_disk["name"]
            else:
                self._entry.pop("name", None)
            data = dict(self._entry)
            try:
                _write_private_atomic(self.path, json.dumps(data, indent=1))
            except OSError as exc:
                self._pending = True
                log.warning(
                    "cannot rewrite registry entry %s (%s); retrying on the next update",
                    self.path,
                    exc,
                )
            else:
                self._pending = False

    def remove(self) -> None:
        with self._lock:
            self._entry = {}
            self._pending = False
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass
            except OSError as exc:
                log.warning("cannot remove registry entry %s: %s", self.path, exc)

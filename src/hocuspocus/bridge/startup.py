"""Why a GUI launch has not registered yet (2.1, D60). See docs/BIBLE.md §3.3 rule 7.

A GUI Houdini's host starts from ``uiready.py`` once the UI is up, so a launch that never
registers used to wait out ``wait_s`` and say only "may still be starting". Two sources
now say why:

* **The startup record.** ``hocuspocus.host.autostart`` writes
  ``<state_dir>/startup/<pid>.json`` when it begins (``phase: "starting"``), rewrites it
  when the host fails to start (``"failed"``, with the error and the host log) or when
  ``autostart = false`` (``"disabled"``), and deletes it once the host runs.
  ``uiready.py`` writes ``"failed"`` itself when ``hocuspocus.host`` cannot be imported.
  ``failed`` and ``disabled`` end the wait at once; no record by the deadline while the
  main window is up means the package never ran its autostart.
* **The windows of the launched pid** (Windows). A licensed start shows the splash (titled
  after the executable, exactly: ``houdinifx``) and then the main window (``untitled.hip -
  Houdini ...``). Any other titled window is a dialog Houdini waits on, such as a startup
  script's ``hou.ui.displayMessage`` (a window titled ``Houdini``). One that stays up for
  :data:`DIALOG_GRACE_S` before the main window has appeared ends the wait (a licensed
  start shows nothing there); one shown with the main window up is only named when the
  wait runs out, since a long hip load may show its own windows. The licence window is
  :mod:`licence`'s and is seen first.

Measured on 22.0.466 (Indie, isolated prefs): splash at 2 s, main window at 10.5 s,
registered at 11 s; a ``123.py`` dialog appears at 6.5 s, before the main window, and
Houdini waits on it for good.
"""

from __future__ import annotations

import json
import re
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..tools.errors import ToolError

DIALOG_GRACE_S = 15.0
"""How long a dialog may stay up before a launch reports it (a licensed start shows none)."""
MAIN_TITLE = re.compile(r" - Houdini\b")
"""The main window's title: ``<hip> - Houdini <edition> <version> - Py3.13``."""

WindowProbe = Callable[[int], "list[str]"]


def read_record(directory: Path, pid: int) -> dict[str, Any] | None:
    """The startup record of ``pid``, or ``None``."""
    try:
        data = json.loads((Path(directory) / f"{pid}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def gui_windows(pid: int) -> list[str]:
    """Titles of the visible, titled top-level windows of ``pid`` (Windows; ``[]``
    elsewhere and on any failure)."""
    if sys.platform != "win32":
        return []
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        proc_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        titles: list[str] = []

        def visit(hwnd: Any, _lparam: Any) -> bool:
            owner = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
            if owner.value != pid or not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                if buf.value.strip():
                    titles.append(buf.value.strip())
            return True

        user32.EnumWindows(proc_type(visit), 0)
        return titles
    except Exception:
        return []


def classify(titles: list[str], exe_stem: str) -> tuple[str | None, list[str]]:
    """``(main window title or None, dialog titles)``: the splash (titled exactly after the
    executable, ``houdinifx``; a ``hou.ui`` message is titled ``Houdini``) is neither."""
    main = next((t for t in titles if MAIN_TITLE.search(t)), None)
    dialogs = [t for t in titles if t != main and t != exe_stem]
    return main, dialogs


@dataclass(slots=True)
class StartupWatch:
    """What one GUI launch has shown while it waits (see the module docstring)."""

    pid: int
    exe_stem: str
    directory: Path | None
    probe: WindowProbe | None
    clock: Callable[[], float] = time.monotonic
    started: float = 0.0
    main: str | None = None
    main_at: float | None = None
    dialog: str | None = None
    dialog_at: float | None = None
    titles: list[str] = field(default_factory=list)
    seen_windows: bool = False
    """Whether the probe ever saw a window of the pid (it sees none on Linux and macOS)."""
    record: dict[str, Any] | None = None

    def poll(self, argv: list[str]) -> ToolError | None:
        """One look; an error when the launch cannot register by itself."""
        now = self.clock()
        if not self.started:
            self.started = now
        if self.directory is not None:
            self.record = read_record(self.directory, self.pid)
        phase = (self.record or {}).get("phase")
        if phase == "failed":
            return host_failed(self.pid, argv, self.record or {})
        if phase == "disabled":
            return autostart_disabled(self.pid, argv, self.record or {})
        titles: list[str] = []
        if self.probe is not None:
            try:
                titles = list(self.probe(self.pid))
            except Exception:
                titles = []
        self.titles = titles
        self.seen_windows = self.seen_windows or bool(titles)
        main, dialogs = classify(titles, self.exe_stem)
        if main is not None:
            self.main = main
            if self.main_at is None:
                self.main_at = now
        if dialogs:
            if self.dialog != dialogs[0]:
                self.dialog, self.dialog_at = dialogs[0], now
            if self.main is None and now - (self.dialog_at or now) >= DIALOG_GRACE_S:
                return waiting_on_dialog(self.pid, argv, dialogs, now - (self.dialog_at or now))
        else:
            self.dialog = self.dialog_at = None
        return None

    def reason(self) -> tuple[str, str | None, dict[str, Any]]:
        """For a wait that ran out: ``(sentence, hint or None, detail)``."""
        detail: dict[str, Any] = {"windows": list(self.titles)}
        phase = (self.record or {}).get("phase")
        if phase == "starting":
            log = (self.record or {}).get("log")
            detail.update(reason="host_starting", startup=self.record)
            return (
                "Its HocusPocus host began starting and has not finished.",
                f"read the host log ({log})" if log else None,
                detail,
            )
        if self.dialog is not None:
            detail["reason"] = "dialog"
            return (
                f"Houdini shows a window titled {self.dialog!r}, which may be waiting for an "
                "answer before HocusPocus can start.",
                "an agent cannot answer a dialog: ask the user to answer or close it in "
                "Houdini; the host then registers by itself (houdini_status lists it)",
                detail,
            )
        if self.main is not None:
            up = round(self.clock() - (self.main_at or self.clock()))
            detail["reason"] = "no_autostart"
            return (
                f"Houdini's main window has been up for {up} s ({self.main!r}), but the "
                "HocusPocus package never ran its autostart (uiready.py): the package is not "
                "installed in this Houdini's pref dir, or HOUDINI_USER_PREF_DIR points "
                "elsewhere.",
                "run `hocuspocus install-houdini` for the pref dir this Houdini reads, then "
                "`hocuspocus doctor`; close this Houdini and launch again",
                detail,
            )
        if self.seen_windows:
            return (
                "Houdini has not opened its main window yet (licence check, large hip, slow "
                "start).",
                None,
                detail,
            )
        return "It may still be starting (licence check, large hip).", None, detail


def host_failed(pid: int, argv: list[str], record: dict[str, Any]) -> ToolError:
    error = str(record.get("error") or "an unknown error")
    log = record.get("log")
    detail: dict[str, Any] = {"reason": "host_failed", "pid": pid, "error": error}
    if log:
        detail["log"] = log
    detail["argv"] = list(argv)
    where = f" (host log: {log})" if log else ""
    return ToolError(
        "houdini_offline",
        f"Houdini (pid {pid}) started, but its HocusPocus host failed to start: {error}. "
        "That Houdini is still open, without HocusPocus.",
        hint=f"fix the cause{where}, close that Houdini and launch again; "
        "`hocuspocus doctor` checks the setup",
        detail=detail,
        retryable=False,
    )


def autostart_disabled(pid: int, argv: list[str], record: dict[str, Any]) -> ToolError:
    return ToolError(
        "houdini_offline",
        f"Houdini (pid {pid}) started, but `autostart = false` in hocuspocus.toml keeps its "
        "HocusPocus host from starting. That Houdini is still open, without HocusPocus.",
        hint="set autostart = true (or remove it) in hocuspocus.toml, or start the host in "
        "that Houdini (hocuspocus.host.start()), then houdini_connect {pid}",
        detail={"reason": "autostart_disabled", "pid": pid, "argv": list(argv)},
        retryable=False,
    )


def waiting_on_dialog(pid: int, argv: list[str], dialogs: list[str], up_s: float) -> ToolError:
    title = dialogs[0]
    return ToolError(
        "houdini_offline",
        f"Houdini (pid {pid}) is waiting on a window titled {title!r} (up for {up_s:.0f} s) "
        "before its HocusPocus host could start: a startup dialog, such as a startup "
        "script's hou.ui message. It stays open.",
        hint="an agent cannot answer a dialog: ask the user to answer or close it in "
        "Houdini; the host then registers by itself (houdini_status lists it, attach with "
        "houdini_connect {pid})",
        detail={"reason": "dialog", "pid": pid, "windows": list(dialogs), "argv": list(argv)},
        retryable=False,
    )

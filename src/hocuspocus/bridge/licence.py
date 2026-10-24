"""Telling a Houdini licence failure from other launch failures (2.1, review 26 P1 #1).

Without a licence Houdini 22.0.466 behaves like this (verified on Windows, 2026-10-24,
SideFX login-based licensing logged out, no installed licences):

* ``hython`` prints ``No licenses could be found to run this application.`` and
  ``\\tPlease check for a valid license server host`` to stderr and exits with code 3
  within a second or two.
* ``houdinifx`` prints nothing. About a second after start it opens the License
  Administrator (``hkey.exe``, a child process of houdinifx) and a window of its own titled
  ``Unable to Acquire a License``; it exits with code 3 some seconds later (3-15 s here),
  or waits on the dialog.

The launcher watches for these (:func:`log_excerpt`, :func:`gui_signal`, exit code 3) so
``houdini_connect {launch}`` and ``hocuspocus launch`` answer within seconds with an
error that says what to do, instead of waiting ``wait_s`` (BIBLE §3.3 rule 6, §9).
``hocuspocus doctor`` reports the licence state from ``sesictrl diagnostic`` and
``hserver -l`` next to the install (:func:`licence_state`), as a warning at most.
"""

from __future__ import annotations

import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..tools.errors import ToolError

EXIT_CODE = 3
"""What hython and houdinifx 22.0 exit with when they cannot get a licence."""

LOG_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"No licen[cs]es? could be found[^\r\n]*", re.IGNORECASE),
    re.compile(r"Unable to acquire a licen[cs]e[^\r\n]*", re.IGNORECASE),
    re.compile(r"Please check for a valid licen[cs]e server[^\r\n]*", re.IGNORECASE),
    re.compile(
        r"[^\r\n]*licen[cs]e[^\r\n]*\b(?:expired|not available|unavailable)\b[^\r\n]*", re.I
    ),
)
"""Lines of a launch log that name a licence failure (the first two seen on 22.0.466)."""

DIALOG_TITLES: tuple[str, ...] = ("Unable to Acquire a License",)
"""Titles of the window houdinifx shows when it cannot get a licence."""

ADMIN_NAMES = frozenset({"hkey", "hkey.exe"})
"""The License Administrator executable a licence-less houdinifx starts."""

HINT = (
    "sign in to SideFX in the License Administrator (hkey) or with `sesictrl login`, or "
    "point hserver at a licence server (`hserver -S <host>`), then launch again; an agent "
    "cannot sign in, so ask the user"
)

LOG_TAIL_BYTES = 8192
EXCERPT_CHARS = 400


def read_log_tail(path: str | Path | None, limit: int = LOG_TAIL_BYTES) -> str:
    """The last ``limit`` bytes of a launch log, decoded leniently; ``""`` if unreadable."""
    if not path:
        return ""
    try:
        with open(path, "rb") as fh:
            fh.seek(0, 2)
            size = fh.tell()
            fh.seek(max(0, size - limit))
            data = fh.read()
    except OSError:
        return ""
    return data.decode("utf-8", errors="replace")


def log_excerpt(text: str) -> str | None:
    """The licence lines of ``text`` (stripped, joined with ``" "``), or ``None``."""
    found: list[tuple[int, str]] = []
    for pattern in LOG_PATTERNS:
        for match in pattern.finditer(text or ""):
            line = match.group(0).strip()
            if line and all(line != seen for _, seen in found):
                found.append((match.start(), line))
    if not found:
        return None
    excerpt = " ".join(line for _, line in sorted(found))
    return excerpt[:EXCERPT_CHARS]


@dataclass(frozen=True, slots=True)
class GuiSignal:
    """What a GUI launch showed of a licence failure while it was still running."""

    seen: str
    """``dialog`` (the "Unable to Acquire a License" window) or ``license_administrator``
    (an hkey child process)."""
    title: str | None = None
    admin_pid: int | None = None


GuiProbe = Callable[[int], "GuiSignal | None"]


def gui_signal(pid: int) -> GuiSignal | None:
    """Whether the Houdini with ``pid`` shows the licence dialog or started hkey.

    Never raises: a probe that cannot run answers ``None`` (the launch then waits as
    before and still sees the exit code)."""
    try:
        if sys.platform == "win32":
            title = _win_window_title(pid, DIALOG_TITLES)
            admin = _win_child(pid, ADMIN_NAMES)
        else:
            title = None  # no window titles without a display library; hkey is enough
            admin = _posix_child(pid, ADMIN_NAMES)
    except Exception:
        return None
    if title is not None:
        return GuiSignal("dialog", title=title, admin_pid=admin)
    if admin is not None:
        return GuiSignal("license_administrator", admin_pid=admin)
    return None


def _win_window_title(pid: int, titles: tuple[str, ...]) -> str | None:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    proc_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    wanted = {t.lower() for t in titles}
    found: list[str] = []

    def visit(hwnd: Any, _lparam: Any) -> bool:
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value != pid or not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        if buf.value.strip().lower() in wanted:
            found.append(buf.value.strip())
            return False
        return True

    user32.EnumWindows(proc_type(visit), 0)
    return found[0] if found else None


def _win_child(pid: int, names: frozenset[str]) -> int | None:
    import ctypes
    from ctypes import wintypes

    class ProcessEntry(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", ctypes.c_wchar * 260),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    snapshot = kernel32.CreateToolhelp32Snapshot(0x2, 0)  # TH32CS_SNAPPROCESS
    if not snapshot or snapshot == wintypes.HANDLE(-1).value:
        return None
    try:
        entry = ProcessEntry()
        entry.dwSize = ctypes.sizeof(ProcessEntry)
        ok = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while ok:
            if entry.th32ParentProcessID == pid and entry.szExeFile.lower() in names:
                return int(entry.th32ProcessID)
            ok = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)
    return None


def _posix_child(pid: int, names: frozenset[str]) -> int | None:
    out = subprocess.run(
        ["ps", "-A", "-o", "pid=,ppid=,comm="],
        capture_output=True,
        text=True,
        timeout=2,
        stdin=subprocess.DEVNULL,
    ).stdout
    for line in out.splitlines():
        parts = line.split(None, 2)
        if len(parts) == 3 and parts[1] == str(pid) and Path(parts[2]).name.lower() in names:
            return int(parts[0])
    return None


def launch_error(
    *,
    pid: int,
    mode: str,
    argv: list[str],
    log: str | None,
    exit_code: int | None,
    excerpt: str | None,
    signal: GuiSignal | None = None,
    terminated: bool = False,
) -> ToolError:
    """The ``houdini_offline`` answer for a launch that could not get a licence.

    Not retryable: repeating the launch fails the same way until someone signs in."""
    if excerpt:
        said = f': "{excerpt}"'
    elif signal is not None and signal.title:
        said = f': its window says "{signal.title}"'
    elif signal is not None:
        said = ": it opened the License Administrator (hkey)"
    else:
        said = f" (exit code {exit_code}, which is how Houdini exits without one)"
    message = f"Houdini (pid {pid}) could not get a licence{said}."
    if terminated:
        message += " HocusPocus stopped the Houdini it started."
    detail: dict[str, Any] = {"reason": "licence", "pid": pid, "mode": mode}
    if exit_code is not None:
        detail["exit_code"] = exit_code
    if excerpt:
        detail["log_excerpt"] = excerpt
    if log:
        detail["log"] = log
    if signal is not None:
        detail["seen"] = signal.seen
        if signal.admin_pid is not None:
            detail["license_administrator_pid"] = signal.admin_pid
    detail["argv"] = list(argv)
    return ToolError("houdini_offline", message, hint=HINT, detail=detail, retryable=False)


# -- doctor --------------------------------------------------------------------------------


@dataclass(slots=True)
class LicenceState:
    """What ``sesictrl diagnostic`` and ``hserver -l`` say, parsed (fields ``None`` when a
    tool or line is missing)."""

    tools: list[str] = field(default_factory=list)
    """The tools that answered (``sesictrl``, ``hserver``)."""
    logged_in: bool | None = None
    login_based: bool | None = None
    installed: int | None = None
    """Non-empty lines of the ``Installed licenses:`` section (the local licence server's
    licences; 0 when none are installed)."""
    license_server: str | None = None
    connected_to: str | None = None
    used: str | None = None


ToolRunner = Callable[[list[str]], "str | None"]


def run_tool(argv: list[str], timeout_s: float = 20.0) -> str | None:
    """stdout of a licence tool, or ``None`` when it cannot run, fails or hangs."""
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            stdin=subprocess.DEVNULL,
            errors="replace",
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.stdout if proc.returncode == 0 and proc.stdout else None


def _field(text: str, name: str) -> str | None:
    match = re.search(rf"^\s*{re.escape(name)}\s*:[ \t]*(.*?)\s*$", text, re.MULTILINE)
    return match.group(1) if match else None


def _yes_no(value: str | None) -> bool | None:
    if value is None:
        return None
    word = value.strip().split(" ")[0].lower() if value.strip() else ""
    return True if word == "yes" else False if word == "no" else None


def _section(text: str, title: str) -> list[str] | None:
    """The lines under ``title`` + an ``===`` underline, up to the next titled section."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.strip().lower() == title.lower() and i + 1 < len(lines):
            if not re.fullmatch(r"=+", lines[i + 1].strip() or "-"):
                continue
            body: list[str] = []
            for j in range(i + 2, len(lines)):
                nxt = lines[j + 1].strip() if j + 1 < len(lines) else ""
                if lines[j].strip() and re.fullmatch(r"=+", nxt or "-"):
                    break
                body.append(lines[j])
            return body
    return None


def parse_sesictrl_diagnostic(text: str, state: LicenceState) -> None:
    state.logged_in = _yes_no(_field(text, "Logged In"))
    state.login_based = _yes_no(_field(text, "Login Based Account"))
    server = _field(text, "License server name")
    if server:
        state.license_server = server
    installed = _section(text, "Installed licenses:")
    if installed is not None:
        state.installed = sum(1 for line in installed if line.strip())
    parse_hserver(text, state)  # the diagnostic embeds `hserver -l`


def parse_hserver(text: str, state: LicenceState) -> None:
    connected = _field(text, "Connected To")
    if connected:
        state.connected_to = connected
    used = _field(text, "Used Licenses")
    if used:
        state.used = used


def tool_path(hfs: Path, name: str) -> Path | None:
    exe = hfs / "bin" / (f"{name}.exe" if sys.platform == "win32" else name)
    return exe if exe.is_file() else None


def licence_state(hfs: Path, runner: ToolRunner = run_tool) -> LicenceState:
    """Ask ``sesictrl diagnostic`` and ``hserver -l`` next to ``hfs`` (missing tools are
    skipped: the state then has empty ``tools``)."""
    state = LicenceState()
    sesictrl = tool_path(hfs, "sesictrl")
    if sesictrl is not None:
        text = runner([str(sesictrl), "diagnostic"])
        if text:
            state.tools.append("sesictrl")
            parse_sesictrl_diagnostic(text, state)
    hserver = tool_path(hfs, "hserver")
    if hserver is not None and state.connected_to is None:
        text = runner([str(hserver), "-l"])
        if text:
            state.tools.append("hserver")
            parse_hserver(text, state)
    return state


def _is_sidefx(url: str | None) -> bool:
    return bool(url) and "sidefx.com" in str(url).lower()


def _is_local(url: str | None) -> bool:
    return bool(url) and bool(re.search(r"localhost|127\.0\.0\.1|::1", str(url), re.I))


def verdict(state: LicenceState) -> tuple[str, str]:
    """``(level, text)`` for doctor: ``ok``, ``warn`` or ``info``; never a failure."""
    if not state.tools:
        return "info", "sesictrl and hserver were not found or did not answer; not checked"
    via = f" (via {', '.join(state.tools)})"
    if state.installed:
        return "ok", f"licences are installed on the local licence server{via}"
    if state.logged_in:
        return "ok", f"signed in to SideFX (login-based licensing){via}"
    remote = state.connected_to
    if remote and not _is_sidefx(remote) and not _is_local(remote):
        return "info", f"licences come from {remote}; doctor cannot tell if one is free{via}"
    parts = []
    if state.logged_in is False:
        parts.append("not signed in to SideFX")
    if state.installed == 0:
        parts.append("no installed licences")
    found = "; ".join(parts) or "no licence found"
    return "warn", f"{found}{via}. Houdini will not start: {HINT}"

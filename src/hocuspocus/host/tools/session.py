"""Session tools: ``session_info`` (and ``houdini_status`` for direct calls).

See docs/BIBLE.md §4.2. The bridge's ``houdini_status`` merges the registry, ``/health``
and this call's result into its ``connected`` block.
"""

from __future__ import annotations

import contextlib
import os
import sys
from pathlib import Path
from typing import Any

from hocuspocus.tools.catalog import HP_RPC_VERSION
from hocuspocus.version import __version__

from ..config import resolve_pref_dir
from .registry import HostContext, tool

RECENT_LIMIT = 10


def parse_file_history(text: str, section: str = "HIP") -> list[str]:
    """Parse Houdini's ``file.history``: ``NAME`` lines followed by ``{ ... }`` blocks.

    Returns the entries of ``section`` newest first (Houdini appends new entries).
    """
    entries: list[str] = []
    current: str | None = None
    inside = False
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if not inside:
            if line == "{":
                inside = True
            else:
                current = line
            continue
        if line == "}":
            inside = False
            current = None
            continue
        if current == section:
            entries.append(line)
    seen: set[str] = set()
    newest_first = []
    for entry in reversed(entries):
        if entry not in seen:
            seen.add(entry)
            newest_first.append(entry)
    return newest_first


def recent_files(ctx: HostContext, limit: int = RECENT_LIMIT) -> list[str]:
    """Hip files saved or loaded in this session (newest first), then Houdini's
    ``file.history`` (which only a GUI session writes)."""
    history: list[str] = []
    pref = resolve_pref_dir(getattr(ctx.config, "pref_dir", "") or None)
    if pref is not None:
        try:
            text = (Path(pref) / "file.history").read_text(encoding="utf-8", errors="replace")
            history = parse_file_history(text)
        except OSError:
            pass
    out: list[str] = []
    for path in [*getattr(ctx.scene, "recent", []), *history]:
        key = path.replace("\\", "/")
        if key not in out:
            out.append(key)
    return out[:limit]


def scene_dirty(ctx: HostContext) -> bool:
    """The dirty flag to report.

    GUI: ``hou.hipFile.hasUnsavedChanges()``. Headless: the host's tracked flag, because
    hython 22.0 reports ``hasUnsavedChanges() == True`` even right after a load, clear or
    save (verified on 22.0.466), so it carries no information there.
    """
    if ctx.ui:
        import hou

        try:
            return bool(hou.hipFile.hasUnsavedChanges())
        except Exception:
            return ctx.scene.dirty
    return ctx.scene.dirty


def hip_block(ctx: HostContext, *, include_recent: bool = True) -> dict[str, Any]:
    import hou

    path = hou.hipFile.path()
    block: dict[str, Any] = {
        "path": path,
        "name": hou.hipFile.basename(),
        "dirty": scene_dirty(ctx),
        "is_new": bool(hou.hipFile.isNewFile()),
    }
    if include_recent:
        block["recent"] = recent_files(ctx)
    return block


def _num_out(value: float) -> float | int:
    value = float(value)
    return int(value) if value.is_integer() else round(value, 6)


def time_block() -> dict[str, Any]:
    """The one time block (``houdini_status`` and ``time``): frame, fps, frame range and
    playback range, integral values as integers."""
    import hou

    return {
        "frame": _num_out(hou.frame()),
        "fps": _num_out(hou.fps()),
        "range": [_num_out(v) for v in hou.playbar.frameRange()],
        "playback_range": [_num_out(v) for v in hou.playbar.playbackRange()],
    }


def env_block() -> dict[str, Any]:
    import hou

    return {name: hou.getenv(name) for name in ("HIP", "JOB", "HIPNAME")}


def _windows_memory() -> tuple[int, int] | None:
    """``(working set, peak working set)`` bytes of this process (Windows)."""
    import ctypes
    from ctypes import wintypes

    class Counters(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    query = kernel32.K32GetProcessMemoryInfo
    query.argtypes = (wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD)
    query.restype = wintypes.BOOL
    counters = Counters()
    counters.cb = ctypes.sizeof(Counters)
    if not query(kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
        return None
    return int(counters.WorkingSetSize), int(counters.PeakWorkingSetSize)


def _posix_memory() -> tuple[int | None, int] | None:
    """``(resident set, peak resident set)`` bytes of this process (Linux, macOS)."""
    import resource

    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    peak *= 1 if sys.platform == "darwin" else 1024  # bytes on macOS, KiB on Linux
    rss = None
    with contextlib.suppress(OSError, ValueError, IndexError):
        pages = int(Path("/proc/self/statm").read_text().split()[1])
        rss = pages * os.sysconf("SC_PAGE_SIZE")
    return rss, peak


def memory_block() -> dict[str, Any] | None:
    """``{rss_mb, peak_mb}`` of the Houdini process (review 17 P2-9: an agent filling a
    sim cache could not see memory grow), or None when the platform will not say. Reads
    the OS counters directly (no psutil in hython)."""
    try:
        sizes = _windows_memory() if sys.platform == "win32" else _posix_memory()
    except Exception:
        sizes = None
    if sizes is None:
        return None
    rss, peak = sizes
    mib = 1024 * 1024
    return {
        "rss_mb": round(rss / mib, 1) if rss is not None else None,
        "peak_mb": round(peak / mib, 1),
    }


UNTITLED_NOTE = "$HIP is the launch directory until you hip_save."


def session_info(args: dict[str, Any], ctx: HostContext) -> dict[str, Any]:
    import hou

    config = ctx.config
    hip = hip_block(ctx)
    if hip.get("is_new"):
        hip["note"] = UNTITLED_NOTE
    out = {
        "pid": ctx.pid or os.getpid(),
        "port": ctx.port,
        "houdini": hou.applicationVersionString(),
        "ui": ctx.ui,
        "label": ctx.label,
        "started": ctx.started,
        "hip": hip,
        "time": time_block(),
        "env": env_block(),
        "scene_generation": ctx.scene.generation,
        "host_version": __version__,
        "hp": HP_RPC_VERSION,
        "read_only": bool(config.read_only),
        "allow_python": bool(config.allow_python),
        "profile": config.profile,
    }
    memory = memory_block()
    if memory is not None:
        out["memory"] = memory
    return out


tool("session_info", read_only=True)(session_info)
tool("houdini_status", read_only=True)(session_info)

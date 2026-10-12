"""Session tools: ``session_info`` (and ``houdini_status`` for direct calls).

See docs/BIBLE.md §4.2. The bridge's ``houdini_status`` merges the registry, ``/health``
and this call's result into its ``connected`` block.
"""

from __future__ import annotations

import os
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
    pref = resolve_pref_dir(getattr(ctx.config, "pref_dir", "") or None)
    if pref is None:
        return []
    try:
        text = (Path(pref) / "file.history").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return parse_file_history(text)[:limit]


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


def time_block() -> dict[str, Any]:
    import hou

    start, end = hou.playbar.frameRange()
    return {"frame": hou.frame(), "fps": hou.fps(), "range": [start, end]}


def env_block() -> dict[str, Any]:
    import hou

    return {name: hou.getenv(name) for name in ("HIP", "JOB", "HIPNAME")}


UNTITLED_NOTE = "$HIP is the launch directory until you hip_save."


def session_info(args: dict[str, Any], ctx: HostContext) -> dict[str, Any]:
    import hou

    config = ctx.config
    hip = hip_block(ctx)
    if hip.get("is_new"):
        hip["note"] = UNTITLED_NOTE
    return {
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


tool("session_info", read_only=True)(session_info)
tool("houdini_status", read_only=True)(session_info)

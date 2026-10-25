"""Nodes that read files from disk, and when what they show is older than the file
(2.1, BIBLE D80; review r21 friction 3).

A Copernicus File COP keeps the image it loaded even after the file at the same path is
overwritten, and ``cook(force=True)`` does not reload it (measured on 22.0.466: only its
Reload Image button does; the File SOP and the Sublayer LOP do reload on a forced cook).
So ``cook {force}`` presses a node's own ``reload`` button first (:func:`press_reload`),
which 134 node types have, and ``look`` / ``inspect what: image`` of a COP note a file
that changed on disk after the node loaded it (:func:`stale_file_notes`).

Houdini does not say when a node loaded its file, so the host remembers the file's mtime
when it first sees a Copernicus reader cook, look or render with that file, and again
whenever it presses the reload button: "loaded" means "as far as HocusPocus saw". Main
thread throughout.
"""

from __future__ import annotations

import contextlib
import os
from collections import OrderedDict
from typing import Any

RELOAD_PARM = "reload"
"""Houdini's name for a reader's reload button (File SOP and COP, Alembic, Sublayer, ...)."""

STAMP_MEMORY = 2000
"""``(node, file)`` load stamps remembered (least recently stamped dropped first)."""

MTIME_SLACK_S = 0.001
"""A file is newer than its load only by more than this (file systems round mtimes)."""

NOTES_LISTED = 3
"""Stale readers named in notes per look (the rest are counted)."""

_loaded: OrderedDict[tuple[int, str], float] = OrderedDict()
"""``(sessionId, file path)`` -> the file's mtime when that node last loaded it."""


def reload_button(node: Any) -> Any:
    """The node's own ``reload`` button parm, or None."""
    import hou

    try:
        parm = node.parm(RELOAD_PARM)
        if parm is not None and parm.parmTemplate().type() == hou.parmTemplateType.Button:
            return parm
    except Exception:
        pass
    return None


def press_reload(node: Any) -> bool:
    """Press ``node``'s reload button outside undo (what ``cook {force}`` does before the
    forced cook, D80) and remember the files it now holds. False when it has none or the
    press failed (a callback that raised)."""
    import hou

    parm = reload_button(node)
    if parm is None:
        return False
    try:
        with hou.undos.disabler():
            parm.pressButton()
    except Exception:
        return False
    for path in _files(node, None):
        _stamp(node, path, overwrite=True)
    return True


def _is_cop(node: Any) -> bool:
    import hou

    return isinstance(node, hou.CopNode)


def _files(node: Any, frame: float | None) -> list[str]:
    """The existing files the node's file parms name at ``frame`` (absolute)."""
    import hou

    out: list[str] = []
    try:
        parms = node.parms()
    except Exception:
        return out
    for parm in parms:
        try:
            template = parm.parmTemplate()
            if template.type() != hou.parmTemplateType.String:
                continue
            if template.stringType() != hou.stringParmType.FileReference:
                continue
            value = parm.eval() if frame is None else parm.evalAtFrame(frame)
        except Exception:
            continue
        value = str(value or "").strip()
        if not value or value.startswith(("op:", "opdef:", "oplib:", "temp:")):
            continue
        if not os.path.isabs(value):
            with contextlib.suppress(Exception):
                value = os.path.join(hou.text.expandString("$HIP"), value)
        if os.path.isfile(value):
            out.append(os.path.normpath(value).replace("\\", "/"))
    return out


def _mtime(path: str) -> float | None:
    try:
        return os.path.getmtime(path)
    except OSError:
        return None


def _stamp(node: Any, path: str, *, overwrite: bool) -> float | None:
    """Remember ``path``'s mtime as what ``node`` loaded; returns the stamp kept."""
    try:
        key = (int(node.sessionId()), path)
    except Exception:
        return None
    if key in _loaded and not overwrite:
        _loaded.move_to_end(key)
        return _loaded[key]
    mtime = _mtime(path)
    if mtime is None:
        return None
    _loaded[key] = mtime
    _loaded.move_to_end(key)
    while len(_loaded) > STAMP_MEMORY:
        _loaded.popitem(last=False)
    return mtime


def note_cooked(node: Any) -> None:
    """After a cook: remember the files a Copernicus reader holds, the first time it is
    seen with them (a later cook keeps the image it has, so it does not restamp)."""
    if not _is_cop(node) or reload_button(node) is None:
        return
    for path in _files(node, None):
        _stamp(node, path, overwrite=False)


def stale_readers(node: Any, frame: float | None) -> list[tuple[str, str]]:
    """``(reader path, file)`` for every Copernicus reader that ``node`` is or reads from
    whose file changed on disk after it loaded it; readers seen for the first time are
    stamped as loaded now."""
    try:
        chain = [node, *node.inputAncestors()]
    except Exception:
        chain = [node]
    stale: list[tuple[str, str]] = []
    for reader in chain:
        if not _is_cop(reader) or reload_button(reader) is None:
            continue
        for path in _files(reader, frame):
            loaded = _stamp(reader, path, overwrite=False)
            mtime = _mtime(path)
            if loaded is not None and mtime is not None and mtime > loaded + MTIME_SLACK_S:
                stale.append((reader.path(), path))
    return stale


def stale_file_notes(node: Any, frame: float | None) -> list[str]:
    """The notes :func:`stale_readers` gives a look or an image read: what is stale and
    the call that reloads it."""
    from hocuspocus.tools.migration import hint_tool

    stale = stale_readers(node, frame)
    if not stale:
        return []
    notes = []
    for reader, path in stale[:NOTES_LISTED]:
        reload = hint_tool("cook", paths=[reader], force=True)
        notes.append(
            f"{reader} shows an older copy of {path}: the file changed on disk after the "
            "node loaded it" + (f"; {reload} reloads it." if reload else ".")
        )
    if len(stale) > NOTES_LISTED:
        notes.append(f"{len(stale) - NOTES_LISTED} more file readers upstream are stale too.")
    return notes

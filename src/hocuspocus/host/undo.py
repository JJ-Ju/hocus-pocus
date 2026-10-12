"""Undo groups and label history. See docs/BIBLE.md §3.2 ("Undo").

Every mutating tool call runs inside exactly one ``hou.undos.group`` labelled
``"HocusPocus: <tool> <summary>"``. Read-only tools never open a group. The history of
labels this host opened is kept for the ``undo`` tool.
"""

from __future__ import annotations

import contextlib
import threading
import time
from collections import deque
from collections.abc import Callable, Iterator, Mapping
from typing import Any

LABEL_PREFIX = "HocusPocus: "
LABEL_MAX_CHARS = 120


def _short(text: str, limit: int = 48) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def summarize(tool: str, args: Mapping[str, Any]) -> str:
    """A short, human summary of ``args`` for an undo label."""
    if not isinstance(args, Mapping):
        return ""
    undo_label = args.get("undo_label")
    if isinstance(undo_label, str) and undo_label.strip():
        return _short(undo_label, 80)
    items = args.get("items")
    if isinstance(items, list):
        noun = "parm" if tool.startswith("parm") else "item"
        if tool.startswith("node"):
            noun = "node"
        return f"{len(items)} {noun}{'s' if len(items) != 1 else ''}"
    paths = args.get("paths")
    if isinstance(paths, list):
        if len(paths) == 1:
            return _short(paths[0])
        return f"{len(paths)} paths"
    for key in ("path", "parent", "rop_path", "lop_path", "top_path", "root"):
        value = args.get(key)
        if isinstance(value, str) and value:
            return _short(value)
    code = args.get("code")
    if isinstance(code, str):
        first = next((line for line in code.splitlines() if line.strip()), "")
        return _short(first, 40)
    action = args.get("action")
    if isinstance(action, str):
        return action
    return ""


def make_label(tool: str, args: Mapping[str, Any]) -> str:
    summary = summarize(tool, args)
    label = f"{LABEL_PREFIX}{tool}" + (f" {summary}" if summary else "")
    return label if len(label) <= LABEL_MAX_CHARS else label[: LABEL_MAX_CHARS - 1] + "…"


@contextlib.contextmanager
def hou_undo_group(label: str) -> Iterator[None]:
    """One named undo group; if the body raises, the group's partial work is undone.

    ``hou.undos.group`` records whatever ran before an exception, and Houdini refuses
    ``performUndo()`` inside an open group, so the rollback happens after the group
    closes. It undoes only when the newest undo entry is this group's (an empty group
    records nothing, and an identical label from an earlier call leaves the stack
    unchanged), so it never reverts someone else's work. BIBLE §4.1: a failing call
    rolls back.
    """
    import hou

    before = _undo_labels(hou)
    try:
        with hou.undos.group(label):
            yield
    except BaseException:
        after = _undo_labels(hou)
        if after and after[0] == label and after != before:
            with contextlib.suppress(Exception):  # never mask the original error
                hou.undos.performUndo()
        raise


def _undo_labels(hou: Any) -> tuple[str, ...]:
    try:
        return tuple(hou.undos.undoLabels())
    except Exception:  # pragma: no cover - undo disabled or unavailable
        return ()


UndoGroupFactory = Callable[[str], contextlib.AbstractContextManager[Any]]


class UndoHistory:
    """Labels of undo groups this host opened, newest last."""

    def __init__(self, maxlen: int = 200) -> None:
        self._labels: deque[dict[str, Any]] = deque(maxlen=maxlen)
        self._lock = threading.Lock()

    def record(self, label: str, tool: str) -> None:
        with self._lock:
            self._labels.append({"label": label, "tool": tool, "time": time.time()})

    def labels(self, limit: int = 20) -> list[str]:
        with self._lock:
            return [entry["label"] for entry in list(self._labels)[-limit:]][::-1]

    def entries(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(entry) for entry in list(self._labels)[-limit:]][::-1]

    def last(self) -> str | None:
        with self._lock:
            return self._labels[-1]["label"] if self._labels else None

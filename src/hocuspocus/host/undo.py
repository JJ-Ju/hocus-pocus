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
ROLLED_BACK_MEMORY = 20
"""How many rolled-back calls :class:`UndoHistory` remembers."""
LABEL_MAX_CHARS = 100
"""Labels are ASCII and at most this long, so Houdini stores them verbatim and the
rollback check (newest label == ours) holds (review 10 section 1.7)."""


def _ascii(text: str) -> str:
    return text.encode("ascii", "replace").decode("ascii")


def _short(text: str, limit: int = 48) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 3] + "..."


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
    label = _ascii(f"{LABEL_PREFIX}{tool}" + (f" {summary}" if summary else ""))
    return label if len(label) <= LABEL_MAX_CHARS else label[: LABEL_MAX_CHARS - 3] + "..."


class UndoOutcome:
    """What :func:`hou_undo_group` did, readable after the ``with`` block.

    ``rolled_back`` is True only when the call failed and the scene is back where it
    started: the group's undo entry was undone (verified on the undo stack), or the group
    recorded nothing. It is False when undo is disabled (``hou.undos.areEnabled()``
    false, or a ``disabler`` left active), because then nothing could be undone."""

    __slots__ = ("failed", "redo_after", "rolled_back", "undo_enabled")

    def __init__(self) -> None:
        self.failed = False
        self.rolled_back = False
        self.undo_enabled = True
        self.redo_after: tuple[str, ...] | None = None
        """The redo labels (next first) right after the rollback undid the group, whose
        entry is then the next redo; None when nothing was undone."""


@contextlib.contextmanager
def hou_undo_group(label: str) -> Iterator[UndoOutcome]:
    """One named undo group; if the body raises, the group's partial work is undone.

    ``hou.undos.group`` records whatever ran before an exception, and Houdini refuses
    ``performUndo()`` inside an open group, so the rollback happens after the group
    closes. It undoes only when the newest undo entry is this group's (an empty group
    records nothing, and an identical label from an earlier call leaves the stack
    unchanged), so it never reverts someone else's work. BIBLE §4.1: a failing call
    rolls back. The yielded :class:`UndoOutcome` says whether it did.
    """
    import hou

    outcome = UndoOutcome()
    outcome.undo_enabled = _undo_enabled(hou)
    before = _undo_labels(hou)
    try:
        with hou.undos.group(label):
            yield outcome
    except BaseException:
        outcome.failed = True
        after = _undo_labels(hou)
        if not outcome.undo_enabled:
            outcome.rolled_back = False
        elif after and after[0] == label and after != before:
            with contextlib.suppress(Exception):  # never mask the original error
                hou.undos.performUndo()
                outcome.rolled_back = _undo_labels(hou) != after
                if outcome.rolled_back:
                    outcome.redo_after = _redo_labels(hou)
        else:
            outcome.rolled_back = True  # the group recorded nothing to undo
        raise


def _undo_enabled(hou: Any) -> bool:
    try:
        return bool(hou.undos.areEnabled())
    except Exception:  # pragma: no cover - older builds without areEnabled()
        return True


def _undo_labels(hou: Any) -> tuple[str, ...]:
    try:
        return tuple(hou.undos.undoLabels())
    except Exception:  # pragma: no cover - undo disabled or unavailable
        return ()


def _redo_labels(hou: Any) -> tuple[str, ...]:
    try:
        return tuple(hou.undos.redoLabels())
    except Exception:  # pragma: no cover - undo disabled or unavailable
        return ()


UndoGroupFactory = Callable[[str], contextlib.AbstractContextManager[Any]]


class UndoHistory:
    """Labels of undo groups this host opened, newest last, and the calls that failed and
    were rolled back.

    A rollback undoes the failed call's group, which leaves it on Houdini's redo stack:
    ``undo {action: redo}`` would then re-run code that raised (review 21 papercut 2).
    Houdini cannot drop one redo entry, so :meth:`rolled_back` remembers the redo stack
    as it was right after the rollback; while the current stack still ends with that
    snapshot, the snapshot's top entry is the rolled-back call (:meth:`rolled_back_in`)
    and ``redo`` stops before it. A new undoable change clears Houdini's redo stack, and
    with it the entry."""

    def __init__(self, maxlen: int = 200) -> None:
        self._labels: deque[dict[str, Any]] = deque(maxlen=maxlen)
        self._lock = threading.Lock()
        self._rolled_back: list[tuple[str, ...]] = []

    def record(self, label: str, tool: str) -> None:
        with self._lock:
            self._labels.append({"label": label, "tool": tool, "time": time.time()})

    def labels(self, limit: int = 20) -> list[str]:
        with self._lock:
            return [entry["label"] for entry in list(self._labels)[-limit:]][::-1]

    def rolled_back(self, redo_after: tuple[str, ...] | None) -> None:
        """A failed call was undone; ``redo_after`` is the redo stack right after (its
        first label is the rolled-back call)."""
        if not redo_after:
            return
        with self._lock:
            self._rolled_back.append(tuple(redo_after))
            del self._rolled_back[:-ROLLED_BACK_MEMORY]

    def rolled_back_in(self, redo: Any) -> set[int]:
        """Indexes into ``redo`` (Houdini's redo labels, next first) of rolled-back calls.
        Snapshots the stack no longer ends with are forgotten."""
        redo = tuple(redo)
        found: set[int] = set()
        with self._lock:
            alive = []
            for snapshot in self._rolled_back:
                if len(snapshot) <= len(redo) and redo[len(redo) - len(snapshot) :] == snapshot:
                    alive.append(snapshot)
                    found.add(len(redo) - len(snapshot))
            self._rolled_back = alive
        return found

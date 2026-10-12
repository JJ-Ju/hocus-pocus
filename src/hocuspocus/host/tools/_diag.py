"""Node diagnostics shared by every tool that reports a node after touching it.

See docs/BIBLE.md §4.1 ("every mutation result includes errors/warnings") and §5.3
(``cook(force=True)`` raises; the useful text is in ``errors()`` afterwards).
"""

from __future__ import annotations

import contextlib
import time
from collections import OrderedDict
from typing import Any

SLOW_COOK_MS = 2000.0
"""A node whose last cook through HocusPocus took longer is never force-cooked implicitly."""

REFRESH_CATEGORIES = frozenset({"Sop", "Lop", "Cop", "Cop2", "Chop"})
"""Categories whose stale errors are refreshed with a forced cook (cheap, no sims or TOPs)."""

STALE_HINT = (
    "These errors may predate your last change: the node was not recooked because its last "
    "cook took over {seconds:g} s. Run cook with force: true to recheck."
)

COOK_MEMORY = 2000
"""Nodes whose last cook duration is remembered (least recently cooked dropped first)."""

_last_cook_ms: OrderedDict[int, float] = OrderedDict()
"""``sessionId`` -> duration of the last cook HocusPocus ran on that node (LRU-bounded)."""


def remember_cook(session_id: int, elapsed_ms: float) -> None:
    _last_cook_ms[session_id] = elapsed_ms
    _last_cook_ms.move_to_end(session_id)
    while len(_last_cook_ms) > COOK_MEMORY:
        _last_cook_ms.popitem(last=False)


def _messages(node: Any, getter: str) -> list[str]:
    try:
        values = getattr(node, getter)()
    except Exception:
        values = ()
    out: list[str] = []
    for value in values:
        text = str(value).strip()
        if text and text not in out:  # Houdini can repeat a message; report it once
            out.append(text)
    return out


def _category(node: Any) -> str:
    try:
        return node.type().category().name()
    except Exception:
        return ""


def is_slow(node: Any) -> bool:
    try:
        return _last_cook_ms.get(node.sessionId(), 0.0) > SLOW_COOK_MS
    except Exception:
        return False


def _timed_cook(node: Any, force: bool) -> tuple[float, BaseException | None]:
    started = time.perf_counter()
    failure: BaseException | None = None
    try:
        node.cook(force=force)
    except Exception as exc:
        failure = exc
    elapsed = (time.perf_counter() - started) * 1000
    with contextlib.suppress(Exception):
        remember_cook(node.sessionId(), elapsed)
    return elapsed, failure


def _has_stale_errors(node: Any) -> bool:
    """True when ``node`` reports errors from a cook that is not pending again.

    Querying ``errors()`` is also what makes Houdini drop errors whose cause is gone
    (verified on 22.0.466, docs/BIBLE.md §5.18): after a broken expression is replaced by
    a constant, the next cook succeeds but leaves the old error on the node -- and fails
    every downstream cook -- unless ``errors()`` was read before that cook. A node in
    that state needs a second, forced cook.
    """
    try:
        return bool(node.errors()) and not node.needsToCook()
    except Exception:
        return False


def _upstream_first(node: Any) -> list[Any]:
    """Input ancestors of ``node`` ordered so every node comes after its inputs."""
    order: list[Any] = []
    seen: set[int] = set()
    stack: list[tuple[Any, bool]] = [(node, False)]
    while stack:
        current, expanded = stack.pop()
        try:
            key = current.sessionId()
        except Exception:
            continue
        if expanded:
            if current is not node:
                order.append(current)
            continue
        if key in seen:
            continue
        seen.add(key)
        stack.append((current, True))
        try:
            inputs = [i for i in current.inputs() if i is not None]
        except Exception:
            inputs = []
        stack.extend((i, False) for i in reversed(inputs))
    return order


def refresh_stale_inputs(node: Any) -> list[str]:
    """Force-cook upstream nodes still carrying errors from before a fix; return their paths.

    Only errored ancestors are touched (each query also flushes errors whose cause is gone),
    only in :data:`REFRESH_CATEGORIES`, and never one whose last cook was slow.
    """
    refreshed: list[str] = []
    for ancestor in _upstream_first(node):
        if _category(ancestor) not in REFRESH_CATEGORIES:
            continue
        if _has_stale_errors(ancestor) and not is_slow(ancestor):
            _timed_cook(ancestor, True)
            with contextlib.suppress(Exception):
                refreshed.append(ancestor.path())
    return refreshed


def refresh_stale(node: Any) -> list[str]:
    """Clear errors left from before a fix on ``node`` and its inputs before reading its
    geometry (docs/BIBLE.md §5.18). Errored upstream nodes are force-cooked as in
    :func:`refresh_stale_inputs`, and ``node`` itself when its errors predate a cook that
    is not pending, unless its last cook was slow. Returns the paths force-cooked."""
    if _category(node) not in REFRESH_CATEGORIES:
        return []
    refreshed = refresh_stale_inputs(node)
    if _has_stale_errors(node) and not is_slow(node):
        _timed_cook(node, True)
        with contextlib.suppress(Exception):
            refreshed.append(node.path())
    return refreshed


def collect_problems(node: Any, *, cook: bool = False, force: bool = False) -> dict[str, Any]:
    """Return ``{errors, warnings, messages, cook_state, cook_time_ms?}`` for ``node``.

    With ``cook=True`` the node is cooked first (errors are caught, never raised), after
    upstream nodes with stale errors were refreshed; a node that itself still reports
    errors from an earlier cook is force-cooked unless its last cook was slow, in which
    case ``hint`` says the errors may be stale. Without ``cook``, uncooked nodes report
    ``cook_state: "not_cooked"``.
    """
    import hou

    out: dict[str, Any] = {"errors": [], "warnings": [], "messages": [], "cook_state": "unknown"}
    failure: str | None = None
    if cook and not hasattr(node, "cook"):
        out["cook_state"] = "not_cookable"
    elif cook:
        refreshable = _category(node) in REFRESH_CATEGORIES
        if refreshable:
            refresh_stale_inputs(node)
        stale = _has_stale_errors(node)
        do_force = force or (stale and refreshable and not is_slow(node))
        elapsed, exc = _timed_cook(node, do_force)
        if exc is None:
            out["cook_state"] = "cooked"
        else:
            out["cook_state"] = "error"
            failure = (
                _exception_text(exc)
                if isinstance(exc, hou.OperationFailed)
                else f"{type(exc).__name__}: {exc}"
            )
        out["cook_time_ms"] = round(elapsed, 1)
        if stale and not do_force:
            out["hint"] = STALE_HINT.format(seconds=SLOW_COOK_MS / 1000)
    else:
        with contextlib.suppress(Exception):
            out["cook_state"] = "cooked" if not node.needsToCook() else "not_cooked"
    for key in ("errors", "warnings", "messages"):
        out[key] = _messages(node, key)
    if failure and not out["errors"]:
        # The cook raised but the node recorded nothing: keep the exception text.
        out["errors"].append(failure)
    if out["errors"] and out["cook_state"] != "error":
        out["cook_state"] = "error"
    if not out["errors"]:
        out.pop("hint", None)
    return out


def _exception_text(exc: BaseException) -> str:
    getter = getattr(exc, "instanceMessage", None)
    if callable(getter):
        with contextlib.suppress(Exception):
            text = str(getter()).strip()
            if text:
                return text
    return str(exc).strip() or type(exc).__name__


def cheap_cook_problems(node: Any) -> dict[str, Any]:
    """Cook ``node`` only when it is a cookable leaf (SOP/LOP/COP...) and report problems.

    Used by mutation results. Managers and networks without a cook (``/obj``, ``geo``
    containers) are reported without cooking.
    """
    try:
        cookable = node.type().category().name() in {
            "Sop",
            "Lop",
            "Cop",
            "Cop2",
            "Dop",
            "Chop",
            "Vop",
            "Top",
        }
    except Exception:
        cookable = False
    return collect_problems(node, cook=cookable, force=False)


COOKABLE_CATEGORIES = frozenset({"Sop", "Lop", "Cop", "Cop2", "Chop", "Dop"})
"""Categories ``problems`` cooks when ``cook_uncooked`` is set (no ROPs, TOPs or OBJs)."""


def a_or_an(word: str) -> str:
    """``"an Object"``, ``"a Sop"``: the article for a category or class name."""
    return f"{'an' if word[:1].lower() in 'aeiou' else 'a'} {word}"


def require_node(path: Any, *, field: str = "path") -> Any:
    """Return ``hou.node(path)`` or raise ``node_not_found`` with sibling candidates."""
    import difflib

    import hou

    from hocuspocus.tools.errors import ToolError

    if not isinstance(path, str) or not path.strip():
        raise ToolError("invalid_argument", f"'{field}' must be a non-empty node path.")
    path = path.strip()
    if not path.startswith("/"):
        raise ToolError(
            "invalid_argument",
            f"{path!r} is not an absolute node path.",
            hint="Node paths start at the root, e.g. /obj/geo1/box1.",
        )
    node = hou.node(path)
    if node is not None:
        return node
    parent_path, _, name = path.rstrip("/").rpartition("/")
    parent = hou.node(parent_path or "/")
    candidates: list[str] = []
    if parent is not None:
        names = [child.name() for child in parent.children()]
        base = parent.path().rstrip("/")
        candidates = [
            f"{base}/{n}" for n in difflib.get_close_matches(name, names, n=5, cutoff=0.4)
        ]
        hint = "Check the node name." if candidates else f"{parent.path()} has no similar child."
    else:
        hint = f"The parent {parent_path or '/'} does not exist either."
    raise ToolError("node_not_found", f"No node at {path}.", hint=hint, candidates=candidates)

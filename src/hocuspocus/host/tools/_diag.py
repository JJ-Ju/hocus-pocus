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
    "cook took over {seconds:g} s."
)


def stale_hint(path: str, seconds: float) -> str:
    """:data:`STALE_HINT` plus the forced cook that rechecks, where the profile serves
    ``cook``."""
    from hocuspocus.tools.migration import hint_tool

    recheck = hint_tool("cook", paths=[path], force=True)
    text = STALE_HINT.format(seconds=seconds)
    return f"{text} {recheck} rechecks." if recheck else text


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


def timed_cook(node: Any, force: bool) -> tuple[float, BaseException | None]:
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


def upstream_first(node: Any) -> list[Any]:
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
    for ancestor in upstream_first(node):
        if _category(ancestor) not in REFRESH_CATEGORIES:
            continue
        if _has_stale_errors(ancestor) and not is_slow(ancestor):
            timed_cook(ancestor, True)
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
        timed_cook(node, True)
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

    from ._common import hou_message  # _common imports this module

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
        elapsed, exc = timed_cook(node, do_force)
        if exc is None:
            out["cook_state"] = "cooked"
        else:
            out["cook_state"] = "error"
            failure = (
                hou_message(exc)
                if isinstance(exc, hou.OperationFailed)
                else f"{type(exc).__name__}: {exc}"
            )
        out["cook_time_ms"] = round(elapsed, 1)
        if stale and not do_force:
            out["hint"] = stale_hint(node.path(), SLOW_COOK_MS / 1000)
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


COOKABLE_CATEGORIES = frozenset({"Sop", "Lop", "Cop", "Cop2", "Chop", "Dop"})
"""Categories ``problems`` cooks when ``cook_uncooked`` is set (no ROPs, TOPs or OBJs)."""

CHEAP_COOK_CATEGORIES = COOKABLE_CATEGORIES | {"Vop", "Top"}
"""Categories a mutation result cooks (:func:`cheap_cook_problems`): the node the agent
just touched, so VOPs (which report wiring and type errors on cook) and TOPs are
included. ``problems`` walks whole subtrees and leaves those two to their owners: a VOP
is cooked through its shader or wrangle, and cooking every TOP in a scene could start
work items."""


def cheap_cook_problems(node: Any) -> dict[str, Any]:
    """Cook ``node`` only when it is a cookable leaf (:data:`CHEAP_COOK_CATEGORIES`) and
    report problems.

    Used by mutation results. Managers and networks without a cook (``/obj``, ``geo``
    containers) are reported without cooking.
    """
    return collect_problems(node, cook=_category(node) in CHEAP_COOK_CATEGORIES, force=False)


def a_or_an(word: str) -> str:
    """``"an Object"``, ``"a Sop"``: the article for a category or class name."""
    return f"{'an' if word[:1].lower() in 'aeiou' else 'a'} {word}"


def missing_node_error(path: str, *, message: str | None = None, exclude: Any = None) -> Any:
    """The one ``node_not_found`` for ``path`` (review 21 papercut 4): ``candidates`` are
    near-miss children of the missing node's parent (never ``exclude``, such as the node
    being wired), and the hint names the node search on that parent (``search {kind:
    "nodes", root}``), or on the nearest ancestor that exists when the parent is missing
    too."""
    import difflib

    import hou

    from hocuspocus.tools.errors import ToolError
    from hocuspocus.tools.migration import hint_tool

    parent_path, _, name = path.rstrip("/").rpartition("/")
    parent = hou.node(parent_path or "/")
    candidates: list[str] = []
    if parent is not None:
        skip = {exclude.path()} if exclude is not None and hasattr(exclude, "path") else set()
        base = parent.path().rstrip("/")
        names = [
            child.name() for child in parent.children() if f"{base}/{child.name()}" not in skip
        ]
        candidates = [
            f"{base}/{n}" for n in difflib.get_close_matches(name, names, n=5, cutoff=0.4)
        ]
        listing = f"{hint_tool('node_find', root=parent.path())} lists its children"
        hint = (
            f"Did you mean a candidate? {listing}."
            if candidates
            else f"{parent.path()} has no similar child; {listing}."
        )
    else:
        ancestor, existing = parent_path, None
        while ancestor and existing is None:
            ancestor = ancestor.rpartition("/")[0]
            existing = hou.node(ancestor or "/")
        root = existing.path() if existing is not None else "/"
        hint = (
            f"The parent {parent_path or '/'} does not exist either; "
            f"{hint_tool('node_find', root=root)} lists what does."
        )
    return ToolError(
        "node_not_found", message or f"No node at {path}.", hint=hint, candidates=candidates
    )


def require_node(path: Any, *, field: str = "path") -> Any:
    """Return ``hou.node(path)`` or raise ``node_not_found`` with sibling candidates."""

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
    raise missing_node_error(path)

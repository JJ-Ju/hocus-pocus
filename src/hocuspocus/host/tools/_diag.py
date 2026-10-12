"""Node diagnostics shared by every tool that reports a node after touching it.

See docs/BIBLE.md §4.1 ("every mutation result includes errors/warnings") and §5.3
(``cook(force=True)`` raises; the useful text is in ``errors()`` afterwards).
"""

from __future__ import annotations

import contextlib
import time
from typing import Any


def collect_problems(node: Any, *, cook: bool = False, force: bool = False) -> dict[str, Any]:
    """Return ``{errors, warnings, messages, cook_state, cook_time_ms?}`` for ``node``.

    With ``cook=True`` the node is cooked first (errors are caught, never raised).
    Without it, uncooked nodes report ``cook_state: "not_cooked"`` and empty lists.
    """
    import hou

    out: dict[str, Any] = {"errors": [], "warnings": [], "messages": [], "cook_state": "unknown"}
    failure: str | None = None
    if cook and not hasattr(node, "cook"):
        out["cook_state"] = "not_cookable"
    elif cook:
        started = time.perf_counter()
        try:
            node.cook(force=force)
            out["cook_state"] = "cooked"
        except hou.OperationFailed as exc:
            out["cook_state"] = "error"
            failure = _exception_text(exc)
        except Exception as exc:  # pragma: no cover - defensive
            out["cook_state"] = "error"
            failure = f"{type(exc).__name__}: {exc}"
        out["cook_time_ms"] = round((time.perf_counter() - started) * 1000, 1)
    else:
        with contextlib.suppress(Exception):
            out["cook_state"] = "cooked" if not node.needsToCook() else "not_cooked"
    for key, getter in (("errors", "errors"), ("warnings", "warnings"), ("messages", "messages")):
        try:
            values = getattr(node, getter)()
        except Exception:
            values = ()
        out[key] = [str(v).strip() for v in values if str(v).strip()]
    if failure and not out["errors"]:
        # The cook raised but the node recorded nothing: keep the exception text.
        out["errors"].append(failure)
    if out["errors"] and out["cook_state"] != "error":
        out["cook_state"] = "error"
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

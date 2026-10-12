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
    if cook:
        started = time.perf_counter()
        try:
            node.cook(force=force)
            out["cook_state"] = "cooked"
        except hou.OperationFailed:
            out["cook_state"] = "error"
        except Exception as exc:  # pragma: no cover - defensive
            out["cook_state"] = "error"
            out["messages"].append(f"{type(exc).__name__}: {exc}")
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
    if out["errors"] and out["cook_state"] != "error":
        out["cook_state"] = "error"
    return out


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

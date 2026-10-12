"""Parm tools: ``parm_get``, ``parm_set`` and the shared parm value engine.

STUB: filled by the M1 parms task. Other tool modules import the two helpers below.
"""

from __future__ import annotations

from typing import Any


def set_parm_items(
    node: Any, parms: dict[str, Any], ctx: Any, *, animation: str = "replace"
) -> list[dict[str, Any]]:
    """Apply ``{parm_name: value | {expr, lang}}`` to ``node`` and return per-parm results.

    Used by ``node_create`` (``items[].parms``) and ``network_build``. Same semantics as
    one ``parm_set`` item per entry; raises ToolError on the first failure.
    """
    raise NotImplementedError("M1 parms task")


def summarize_parm(
    parm_or_tuple: Any, *, frame: float | None = None, detail: str = "compact"
) -> dict[str, Any]:
    """Compact ``{name, value, raw, expression?, keyed?, locked?, menu_token?, is_default}``."""
    raise NotImplementedError("M1 parms task")

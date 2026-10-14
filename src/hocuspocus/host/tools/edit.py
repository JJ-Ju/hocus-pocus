"""``edit``: one transaction for every kind of scene change (spec-2.0 §2.4, BIBLE §4.9).

The tool is a thin front end of the transaction engine (``host/tx.py``): it parses
``ops`` into a plan, validates it against the scene as the earlier ops leave it, and runs
it inside the one undo group the dispatcher opens (``HocusPocus: edit <n> ops``).
``dry_run`` stops after validation and returns the plan with resolved paths, changing
nothing (``_changed: false``: no undo step, no dirty flag, allowed in read-only mode).
"""

from __future__ import annotations

from typing import Any

from .. import tx
from ._common import arg_bool
from .registry import HostContext, tool

CHANGED_KEY = "_changed"


@tool("edit")
def edit(args: dict[str, Any], ctx: HostContext) -> dict[str, Any]:
    dry_run = arg_bool(args, "dry_run", False)
    partial = arg_bool(args, "partial", False)
    mode = tx.return_mode(args)
    plan = tx.parse_ops(args.get("ops"), partial=partial)
    # Validation first: a plan with a bad op changes nothing at all. With partial each op
    # stands alone, so a bad op only fails itself when it runs.
    if dry_run or not partial:
        diagnostics = tx.validate(plan, ctx)
        diagnostics.raise_if_any()
        if dry_run:
            return {
                "dry_run": True,
                "ops": len(plan.ops),
                "plan": diagnostics.rows,
                CHANGED_KEY: False,
            }
    result = tx.execute(plan, ctx)
    out = tx.echo(result, mode)
    tx.watch(node for node, _cook in result.touched())
    return out

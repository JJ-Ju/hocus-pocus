"""``edit``: one transaction for every kind of scene change (spec-2.0 §2.4, BIBLE §4.5).

The tool is a thin front end of the transaction engine (``host/tx.py``): it parses
``ops`` into a plan and runs it inside the one undo group the dispatcher opens
(``HocusPocus: edit <n> ops``). Validation is the run (BIBLE D56): each op is checked
against the scene the earlier ops left, a failing op is reverted and the rest are checked
too, then the whole call is compensated and every problem raised at once. ``dry_run``
runs the plan in check mode and compensates it (no undo step, no dirty flag, no event,
allowed in read-only mode: ``_changed: false``). ``partial: true`` keeps what worked,
``partial: "stop"`` the ops before the first failure (D57).
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
    partial = tx.partial_mode(args)
    mode = tx.return_mode(args)
    plan = tx.parse_ops(args.get("ops"), partial=partial)
    if dry_run:
        rows = tx.dry_run(plan, ctx)
        return {"dry_run": True, "ops": len(plan.ops), "plan": rows, CHANGED_KEY: False}
    result = tx.execute(plan, ctx)
    out = tx.echo(result, mode)
    tx.watch(node for node, _cook in result.touched())
    return out

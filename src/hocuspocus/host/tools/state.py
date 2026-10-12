"""State tools. M0 ships ``job``; ``undo``, ``time`` and ``selection`` arrive in M3.

``job`` reads and cancels host-side jobs (docs/BIBLE.md §7). It never touches ``hou``,
so it skips the main-thread executor, opens no undo group and is allowed in read-only
mode (cancelling a job is not a scene mutation).
"""

from __future__ import annotations

from typing import Any

from hocuspocus.tools.errors import ToolError

from .registry import HostContext, tool

JOB_ACTIONS = ("status", "result", "cancel", "list")


@tool("job", main_thread=False, scene=False)
def job(args: dict[str, Any], ctx: HostContext) -> dict[str, Any]:
    action = args.get("action")
    if action not in JOB_ACTIONS:
        raise ToolError("invalid_argument", f"action must be one of {', '.join(JOB_ACTIONS)}.")
    if action == "list":
        return {"jobs": ctx.jobs.list()}
    job_id = args.get("job_id")
    if not isinstance(job_id, str) or not job_id:
        raise ToolError("invalid_argument", f"job_id is required for action {action!r}.")
    if action == "status":
        return ctx.jobs.status(job_id)
    if action == "cancel":
        return ctx.jobs.cancel(job_id)
    data = ctx.jobs.result(job_id)
    if data["state"] in ("failed", "cancelled") and data.get("error"):
        raise ToolError.from_dict(data["error"])
    return data

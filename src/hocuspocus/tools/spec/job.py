"""Catalogue entry for ``job`` (BIBLE §4.7)."""

from __future__ import annotations

from ._helpers import _JOB_STATES, ToolSpec, _b, _enum, _obj, _objs, _out, _s, _t, _v2_on

SPEC = ToolSpec(
    name="job",
    profiles=("core", "full", "compat_1x"),
    description=(
        "Jobs from render, cook or pdg: status (state, progress, message), result (the "
        "tool's result once done), cancel, list."
    ),
    notes=(
        "Job ids are <pid>-<id>: the bridge sends a job call to the Houdini that started the "
        "job, whichever is selected; if that Houdini has exited the answer is instance_lost "
        "with the last status the bridge saw (detail.last_status). A bare id means the "
        "selected Houdini. list shows the selected Houdini's jobs; all: true lists every "
        "live instance's, each row with its pid, plus instances: [{pid, label, jobs, "
        "running}]. Jobs do not survive a Houdini restart. "
        "A pdg cook job counts the work items of the whole graph in current/total and adds "
        "nodes: {name: 'finished/total'}. A frame-by-frame job's message counts the frames "
        "done, as current does. cancel adds cancelled: true, or cancelled: false and a note "
        "when the job had already finished. A cancelled job's result is the cancelled error, "
        "whose detail holds the last status (state cancelled). "
        "Not in compat_1x (spec-2.0 §2.5, §3): job ids are opaque ledger ids such as j7f3a9; the "
        "bridge ledger maps each to its Houdini and job, and job accepts either form (any "
        "profile). Jobs are kept in the ledger across bridge restarts: job status after a "
        "restart answers from the live Houdini, and for one that has exited instance_lost "
        "carries the last status the ledger saw; job result of a finished job whose Houdini "
        "has exited returns the result the ledger kept, if it fetched one before (results "
        "over 16 KB are stored in <state_dir>/jobs/<id>.json). on (pid, name or role) picks "
        "the Houdini for list (and for a bare id); a job id always goes to its own Houdini."
    ),
    input_schema=_obj(
        {
            "action": _enum(("status", "result", "cancel", "list")),
            "job_id": _s("Required except for list."),
            "all": _b(False),
        },
        ("action",),
    ),
    output_schema=_out(
        {
            "job_id": _t("string"),
            "tool": _t("string"),
            "state": {"type": "string", "enum": _JOB_STATES},
            "progress": _t("number"),
            "message": _t("string"),
            "started": _t("string"),
            "elapsed_s": _t("number"),
            "result": {"description": "The tool's result (action result, done)."},
            "jobs": _objs(),
        }
    ),
    # Reads and cancel only touch host-side jobs; repeating any action is harmless.
    idempotent=True,
    v2_extra=_v2_on(),
    examples=(
        {"action": "status", "job_id": "61900-9c3e6f7ca53e"},
        {"action": "list", "all": True},
    ),
)

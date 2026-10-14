"""Catalogue entry for ``pdg`` (BIBLE §4.7)."""

from __future__ import annotations

from ._helpers import ToolSpec, _arr, _b, _cursor, _enum, _limit, _n, _obj, _s

SPEC = ToolSpec(
    name="pdg",
    profiles=("full", "compat_1x"),
    description=(
        "Drive a TOP node: cook its work items as a job (block waits up to timeout_s, capped at"
        " the job threshold), status, workitems (paged; failed items say why), cancel, dirty."
    ),
    notes=(
        "cook, cancel and dirty are refused read-only. "
        "A failed work item carries error (the last error lines of its log, at most 400 "
        "characters), log_path and exit_code (out-of-process items). A cook result (and job "
        "result) has ok: false when any item of the graph failed, and failures lists the first"
        " 5 failed items of the target and its upstream TOPs with their error. Out-of-process "
        "ROP TOPs (ROP Fetch, ...) load the saved hip, so cook refuses an untitled scene or "
        "unsaved changes with unsaved_changes; save: true saves first (approved_roots apply) "
        "and the result names the saved path. A cook job's progress counts the work items of "
        "the whole graph (the target and its upstream TOPs), with nodes: {name: "
        "'finished/total'}; a cook whose items were cancelled ends cancelled, never done. "
        "cancel also cancels the job cooking that graph and returns the status after the cook"
        " stopped, with cancelled: true and jobs_cancelled. node_info on a TOP node adds "
        "pdg_state: {cooked, failed, total}; problems lists TOP nodes with failed items. "
        "workitems rows: id, index, state, output_files (relative to output_root, given once "
        "per page), cook_time_s, name only when it is not <node>_<id>, node for a network; "
        "attribs: [names] adds each item's attribute values (unknown names left out); state "
        "filters: failed, cancelled, success, cache, cooked or a state name. When block "
        "returns a running job before timeout_s, notes says the wait was capped."
    ),
    input_schema=_obj(
        {
            "action": _enum(("cook", "status", "workitems", "cancel", "dirty")),
            "top_path": _s(),
            "block": _b(False),
            "save": _b(False),
            "attribs": _arr({"type": "string"}),
            "state": _s(),
            "timeout_s": _n(None, minimum=1, default=30),
            # bible-silent: "workitems paged" uses the §4.1 limit/cursor convention.
            "limit": _limit(),
            "cursor": _cursor(),
        },
        ("action", "top_path"),
    ),
    # Registered scene=False: work items are not hip state (no undo group).
    examples=(
        {"action": "cook", "top_path": "/tasks/topnet1/ropfetch1"},
        {"action": "workitems", "top_path": "/tasks/topnet1/ropfetch1", "limit": 20},
    ),
)

"""Catalogue entry for ``events`` (BIBLE §4.7)."""

from __future__ import annotations

from ._helpers import ToolSpec, _limit, _obj

SPEC = ToolSpec(
    name="events",
    profiles=("full",),
    description=(
        "What changed since your last call: hip, node (created, renamed, deleted, parms or "
        "flags changed on nodes HocusPocus touched or read) and pdg events with seq and "
        "origin (agent|houdini|other). Pass next_since back as since."
    ),
    notes=(
        "Watched nodes: those HocusPocus created, edited, read with inspect node or listed with"
        " inspect network, and nodes created directly under /obj, /stage, /mat, /out and "
        "/tasks. ParmTupleChanged has detail.parm and, on a multi-component tuple, "
        "components (those whose value or keys changed; a burst within 0.1 s is one event "
        "with their union) and keyed (those of them with keyframes now). FlagChanged has "
        "detail.flags (flag: new value); a spare parm edit is one "
        "SpareParmsChanged; hda create, match and unlock are one hda_contents_rebuilt per "
        "asset; kind pdg has detail.event cook_start, work_item_failed (id, index, error) or"
        " cook_done (ok, states, cancelled). Each Houdini numbers its own events: next_since is"
        " '<pid>:<seq>' (pass it back as since), and a cursor from another Houdini returns "
        "reset: true with a note and that Houdini's events from the start. A call that "
        "fails and is rolled back records "
        "nothing, nor does a node created and deleted within one call, a tool's own "
        "set-and-restore, or Houdini's save-time writes on TOP networks. In a call that "
        "sets parms (parm_set, node_create parms), the parms it did not set but Houdini "
        "wrote (callbacks, a camera's *Converted parms, guide scale) are origin houdini."
    ),
    input_schema=_obj({"since": {"type": ["integer", "string"], "default": 0}, "limit": _limit()}),
    read_only=True,
    examples=({}, {"since": "3084:42", "limit": 20}),
)

"""Catalogue entry for ``cook`` (BIBLE §4.6)."""

from __future__ import annotations

from ._helpers import (
    _JOB_STATES,
    ToolSpec,
    _arr,
    _b,
    _enum,
    _frame,
    _n,
    _obj,
    _objs,
    _on,
    _out,
    _paths,
    _problems,
    _t,
)

SPEC = ToolSpec(
    name="cook",
    profiles=("core", "full"),
    description=(
        "Cook nodes and report per node ok, errors, warnings, cook_time_ms. Cooking never "
        "writes files (render does). profile force-cooks the inputs a cook uses: chain (top 10), "
        "total_ms, attribution; for-each loop bodies show their cost over all iterations "
        "(loops). frame_range cooks frame by frame (sims advance); summary bbox adds bbox "
        "rows. Past wait_s returns job_id for job."
    ),
    notes=(
        "cook_time_ms is the node's own cook; cached inputs are not recooked. force (2.1) "
        "first presses a node's own reload button (File COP and SOP, Alembic, Sublayer and "
        "other readers; a forced cook alone leaves a File COP's old image), and the row says "
        'reloaded: true. force: "chain" (2.1) also force-cooks, inputs first and each once, '
        "the input ancestors a normal cook of the node uses (as profile picks them), so a "
        "result an input kept from before a change (a Material SOP cooked before its "
        "material existed) is redone; each named node's row adds inputs_cooked, "
        "inputs_reloaded and input_problems [{path, errors?, warnings?}] (at most 10, "
        "input_problems_total). It does not combine with profile (which force-cooks the "
        "chain already) or frame_range. Cooking a ROP or "
        "a File Cache writes nothing, and notes say how to write (render, or parm_set press "
        "on its execute button). "
        "frame_range is [start, end, step] and cannot be combined with profile or frame; the "
        "current frame is restored afterwards. Errors left from before a fix are rechecked "
        "unless the last cook took over 2 s (hint: force). With profile, results[].cook_time_ms"
        " is the named node's profiled cook. profile times what a normal cook of the node "
        "cooks: a node that needs cooking is cooked normally first to learn which inputs it "
        "uses, and the ones it does not use (a Switch's other inputs, the inputs of a bypassed "
        "or locked node, and what only they feed) are not cooked and are listed in inactive "
        "{count, paths (at most 10)}; a chain that simulates, or a cook that fails, profiles "
        "every input ancestor (2.1). attribution is per_node, or perf_monitor when a "
        "block_end was cooked under Houdini's performance monitor: each loop body row then has "
        "in_loop, cooks, per_iteration_ms and cook_time_ms over all iterations, and loops lists"
        " {block_end, block_begin, iterations, total_ms}. loop-level means the monitor was "
        "unavailable (another profile was recording) and body rows show one standalone cook. "
        "total_ms counts each loop once, at its block_end. In a GUI session the profile stays "
        "in the Performance Monitor's list. A profiled node that simulates (a DOP network, or "
        "a solver SOP such as pyrosolver with one inside) gets simulation {dopnet, "
        "resimulated, frame} and a note: a force-cook reads frames already in the simulation "
        "cache instead of re-simulating them. It is cooked under the performance monitor, "
        "and resimulated is false when no DOP solve time was recorded (a cache read), "
        "current_frame when only the frame the simulation stood on was re-solved (a warm "
        "solver whose inputs the profile force-cooked), and true when it simulated frames "
        "the cache lacked; simulated_frames [first, last] when known (null, with a note, "
        "when the monitor is unavailable and the simulation state cannot tell). summary bbox "
        "rows appear only when the counts, "
        "bbox or errors change: a row stands for its frame through the frame in through; "
        "past 12 such rows only the first 6 and the last 6 are kept, with frames_truncated: "
        "true and frames_rows (the count), in the result and in the job's result alike. "
        "wait_s is how long the call waits before returning the job (default "
        "min(timeout_s, job threshold); 0 returns the job at once). A cancelled cook's job "
        "result is the cancelled error with detail {last_status, partial: {frames_cooked, "
        "results, frames?}}. "
        "(2.0, spec-2.0 §2.5) on runs this call on another Houdini without moving the pin: a pid, a name (houdini_connect {pid, name}) or a role (editor or worker; the least busy live one, by jobs_running then busy). The result's _meta.instance names it and its job is recorded against it. A pid or name the bridge remembers that has exited is instance_lost, one it never knew houdini_offline with the candidates; a role nobody has is houdini_offline. Without on the call goes to the pinned or selected Houdini as always."
    ),
    input_schema=_obj(
        {
            "paths": _paths(),
            "force": {
                "type": ["boolean", "string"],
                "enum": [False, True, "chain"],
                "default": False,
            },
            "frame": _frame(),
            "timeout_s": _n(None, minimum=1, default=30),
            "profile": _b(False),
            "frame_range": _arr({"type": "number"}, None, minItems=2, maxItems=3),
            "summary": _enum(("none", "bbox"), "none"),
            "wait_s": _n(None, minimum=0),
            "on": _on(),
        },
        ("paths",),
    ),
    output_schema=_out(
        {
            "ok": _t("boolean"),
            "chain": _objs(),
            "attribution": _t("string"),
            "loops": _objs(),
            "inactive": _t("object"),
            "total_ms": _t("number"),
            "frames": _objs(),
            "results": {
                "type": "array",
                "items": _out(
                    {
                        "path": _t("string"),
                        "ok": _t("boolean"),
                        **_problems(),
                        "cook_time_ms": _t("number"),
                        "hint": _t("string"),
                    },
                    ("path", "ok"),
                ),
            },
            "job_id": _t("string"),
            "state": {"type": "string", "enum": _JOB_STATES},
        }
    ),
    # §4.1: a cook changes no hip state but is not a pure read (it computes, may run
    # Python SOPs); repeating it is harmless.
    idempotent=True,
    examples=(
        {"paths": ["/obj/geo1/OUT"]},
        {"paths": ["/obj/geo1/OUT"], "profile": True},
        {"paths": ["/obj/sim/OUT"], "frame_range": [1, 96], "summary": "bbox"},
    ),
)

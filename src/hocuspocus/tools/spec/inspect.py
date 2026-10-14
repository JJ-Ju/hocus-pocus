"""Catalogue entry for ``inspect`` (spec-2.0 §2.3; BIBLE §4.9)."""

from __future__ import annotations

from ._helpers import CATEGORIES, ToolSpec, _arr, _cursor, _enum, _i, _n, _obj, _s

WHATS = (
    "node", "parms", "network", "outline", "geo", "image", "stage", "problems", "type",
    "events", "jobs",
)  # fmt: skip

SPEC = ToolSpec(
    name="inspect",
    profiles=("minimal", "core", "full"),
    description=(
        "Read the scene in one tool. what: node, parms, network, outline, geo (rows: true for "
        "values), image (Cop), stage (USD), problems, type, events or jobs; target is the "
        "node, LOP, Cop or node type. Returns an etag and the matching 1.4 read (node_info, "
        "parm_get, network_describe, geo_info/geo_read, usd_stage, problems, "
        "node_type_info, events, job), compact: defaults and empties left out."
    ),
    notes=(
        "Each what takes its 1.4 tool's arguments; any other option is invalid_argument "
        "naming the ones it takes. The result is the 1.4 tool's, without what and target "
        "(the caller knows them). node: node_info (target or paths; include, "
        "include_defaults, recurse_locked, detail). parms: parm_get (a parm or tuple path as "
        "target, or paths; frame, include, full_strings, detail); with a node as target it "
        "reads the node's non-default parm tuples (all with include_defaults; those whose "
        "name or label match the glob parms, a|b, when given; folders, separators and "
        "buttons left out), and parms: [] when there are none. network: network_describe "
        "format data (target is root; depth, include_defaults, include_positions, "
        "recurse_locked, cursor). outline: network_describe format outline (target default "
        "/; depth, recurse_locked, cursor, wiring), without format; a row leaves out "
        "name when it is the path's last segment, errors at 0, and inputs unless wiring: "
        "true. geo: geo_info (frame, attributes, detail), or with rows: true geo_read "
        "(class, attribs, start, count, group, stats, cursor, frame). image: geo_info on a "
        "Cop node or COP network (frame); another node is invalid_argument. stage: usd_stage "
        "(target is lop_path; prim, depth, include, attribs, summary, time, limit, cursor). "
        "problems: problems (target is root, default /; include_warnings, cook_uncooked, "
        "recurse_locked, timeout_s, limit, cursor). type: node_type_info (target is "
        "type; category, include_parms, include_help, folder, parms, detail). events: "
        "events, no target (since, limit; next_since as with events). jobs: job list, or "
        "job status with job_id, no target. Defaults are the 1.4 tool's. "
        "Compact shapes (detail: compact, the default; detail: full restores the 1.4 shape "
        "of node, parms and geo; node rows never carry "
        "session_id): what is default or empty is omitted. node rows: name omitted when it "
        "is the path's last segment; type is Category/name (Sop/box); flags is the list of "
        "flags that are on, omitted when none; inputs are positional sources, a path (output "
        "0), {path, output} or null, trailing unconnected ones omitted and inputs omitted "
        "when nothing is connected (detail: full gives {index, name, label, from}); outputs "
        "(only with include outputs) are positional lists of destinations, a path (input 0) "
        "or {path, input}; parms is {name: value}, or {name: {value, ...}} when more than the "
        "value matters (expression, expressions {component: text}, language when not "
        "hscript, keyed, locked, menu_token unlike the value, raw unlike the value and the "
        "expression), omitted when no parm is listed; is_default is not given; errors, "
        "warnings and messages omitted when empty, cook_state when cooked, children_count "
        "when 0. parms: {path: value or row} in the order read (keyed by tuple name when "
        "target is a node; the rows when two share a key), rows as in node plus type when "
        "not float, int, string or toggle, hda_locked when true, keyframes when any, and the "
        "include sections asked for; is_default, kind, tuple and component_names are not "
        "given. geo (summary): attributes per class as {name: type}, the type 'float3', "
        "'float3:color' or 'int[]' (size when not 1, :type_info when set), detail attributes "
        "as {name: {type, value}} with an elided dict value as {elided, key_count}, "
        "attributes: names as name lists, empty classes omitted; groups per class as {name: "
        "count}, omitted when empty; bbox without center (the middle of min and max); "
        "volume and vdb columns with one value in every row (resolution, voxel_size, class) "
        "said once in volume_common / vdb_common; internal_attribute_count kept, its note "
        "omitted (geo_read with attribs reads those attributes); rows: true reads and images "
        "unchanged. "
        "etag is <pid>:<scene_generation>:<16 hex>, the first 16 hex digits of a BLAKE2b "
        "digest of the result's canonical JSON (sorted keys, compact): it moves exactly "
        "when the answer does, and the matching houdini:// resource has the same etag, so "
        "a read with If-None-Match after a change that left this answer alone (a look, a "
        "cook elsewhere) is not_modified."
    ),
    input_schema=_obj(
        {
            "what": _enum(WHATS),
            "target": _s("Node, parm, LOP, Cop or type path."),
            "paths": _arr({"type": "string"}, "node, parms: several paths.", minItems=1),
            "include": _arr({"type": "string"}),
            "include_defaults": {"type": "boolean"},
            "recurse_locked": {"type": "boolean"},
            "frame": _n(),
            "full_strings": {"type": "boolean"},
            "parms": _s("parms, type: name or label glob."),
            "depth": _i(None, minimum=1),
            "include_positions": {"type": "boolean"},
            "wiring": {"type": "boolean"},
            "cursor": _cursor(),
            "attributes": _enum(("full", "names")),
            "rows": {"type": "boolean"},
            "class": _enum(("point", "prim", "vertex", "detail")),
            "attribs": {"type": ["string", "array"], "items": {"type": "string"}},
            "start": _i(None, minimum=0),
            "count": _i(None, minimum=1, maximum=10000),
            "group": _s(),
            "stats": {"type": "boolean"},
            "prim": _s(),
            "summary": {"type": "boolean"},
            "time": _n(),
            "limit": _i(None, minimum=1, maximum=1000),
            "include_warnings": {"type": "boolean"},
            "cook_uncooked": {"type": "boolean"},
            "timeout_s": _n(None, minimum=1),
            "category": _enum(CATEGORIES),
            "include_parms": {"type": "boolean"},
            "include_help": {"type": "boolean"},
            "folder": _s(),
            "detail": _enum(("compact", "full", "folders")),
            "since": {"type": ["integer", "string"]},
            "job_id": _s(),
        },
        ("what",),
    ),
    read_only=True,
    examples=(
        {"what": "parms", "target": "/obj/geo1/box1", "parms": "size|t"},
        {"what": "geo", "target": "/obj/geo1/OUT", "rows": True, "attribs": ["P"], "count": 5},
        {"what": "type", "target": "Sop/scatter", "parms": "*seed*"},
    ),
)

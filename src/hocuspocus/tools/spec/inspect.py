"""Catalogue entry for ``inspect`` (spec-2.0 §2.3; BIBLE §4.9)."""

from __future__ import annotations

from ._helpers import CATEGORIES, ToolSpec, _arr, _cursor, _enum, _i, _n, _obj, _s

WHATS = (
    "node", "parms", "network", "outline", "geo", "image", "stage", "problems", "type",
    "events", "jobs", "guide", "tool",
)  # fmt: skip

SPEC = ToolSpec(
    name="inspect",
    profiles=("minimal", "core", "full"),
    description=(
        "Read the scene. what: node, parms, network, outline, geo (rows: true for "
        "values; group_by: stats per value), image (Cop), stage (USD), problems, type, events or jobs; target is the "
        "node, LOP, Cop or node type. guide (target: topic) and tool (target: name) read the "
        "docs, no Houdini needed. Returns an etag and the read, compact: defaults and "
        "empties left out."
    ),
    notes=(
        "Each what takes the arguments listed for it below. An option that chooses what is read "
        "(frame, paths, cursor, class, ...) and that the what does not take is "
        "invalid_argument naming the ones it takes; an option that only shapes the answer "
        "(include_defaults, recurse_locked, full_strings, detail, include_positions, wiring) "
        "is ignored with a note instead (2.1, D51): geo, parms, image and stage read inside "
        "locked assets anyway, and parm paths are read whatever their value. guide and tool "
        "(2.1, D54) are answered by the MCP server itself, with or without a Houdini: guide "
        "is the operating guide (hocuspocus://guide) as {etag, text, topics}, or with "
        "target the section whose title matches it (copernicus, spare parm, two houdinis; "
        "an unknown topic is invalid_argument with the titles as candidates); tool needs "
        "target, a tool name, and returns that tool's reference as {etag, text}: "
        "description, notes, arguments and examples, the text of docs/tools.md and "
        "hocuspocus://tools. They take no other option. The result leaves out what and target "
        "(the caller knows them). node: target or paths; include, "
        "include_defaults, recurse_locked, full_strings, detail. parms: a parm or "
        "tuple path as target, or paths; frame, include, full_strings, detail; with a node "
        "as target it reads the node's non-default parm tuples (all with include_defaults; "
        "those whose name or label match the glob parms, a|b or a,b, when given; those in "
        "folder, "
        "a folder label or A / B path, when given; folders, separators and buttons left "
        "out), and parms: [] when there are none; detail folders lists the node's own parm "
        "folders, spare parms included, as {folders: [{folder, parms}]} (2.1). "
        "full_strings returns strings over 200 characters whole instead of {elided, head}, "
        "for node rows too (2.1), at any length: a result over the response budget comes "
        "back whole with over_budget: true. network: the network "
        "as data (target is root; depth, include_defaults, include_positions, "
        "recurse_locked, cursor). outline: one row per node (target default "
        "/; depth, recurse_locked, cursor, wiring, detail); a row leaves out "
        "name when it is the path's last segment, errors at 0, and inputs unless wiring: "
        "true. geo: the summary (frame, attributes, full_strings, detail), or with rows: true "
        "the rows (class, attribs, start, count, group, stats, cursor, frame, full_strings); "
        "the summary also takes stats: true and attribs (2.1): stats per class as rows: true "
        "gives them (min, max, mean; unique for strings) for the attributes attribs names, "
        "else for every point, prim and vertex attribute up to 24; attribs is a list or one "
        "string of names separated by commas or spaces, everywhere it is taken; "
        "full_strings (2.1) gives detail attribute values whole (strings, arrays, dicts), "
        "which are otherwise capped at 200 characters and 16 items (256 in rows). geo with "
        "group_by (2.1), a string or int prim attribute (surface, name, mat_id) or else a "
        "point one, gives one row per value under columns, largest first: value, prims, "
        "points, triangles (closed polygons, n-2 each), area, bbox_min, bbox_max (point "
        "groups: value, points, bbox_min, bbox_max), then name.min, name.max and name.mean "
        "for each numeric attribute in attribs (prim, point or vertex attributes of the "
        "group's prims); group (a group name or pattern such as @mat_id==3) limits the "
        "elements counted; frame, count (default 50) and cursor page the rows, total counts "
        "the values, and a page over the response budget ends early with truncated: true and "
        "next_cursor. rows, class, stats and attributes do not combine with it. image: the image read of a "
        "Cop node or COP network (frame), with notes naming a File COP it reads whose file "
        "changed on disk after loading (2.1); another node is invalid_argument. stage: the "
        "composed USD stage (target is the LOP; prim, depth, include, attribs, summary, time, limit, cursor); "
        "include bindings adds each prim's bound material; rows that list attributes also "
        "list authored relationships such as material:binding as relationships [{name, "
        "targets}] (filtered by attribs too), and with attributes or bindings a geometry "
        "prim's GeomSubsets (per-face materials) as subsets [{name, faces, family?, "
        "material?}], at most 16 (subsets_total) (2.1). "
        "problems: the scan for errors (target is root, default /; include_warnings, cook_uncooked, "
        "recurse_locked, timeout_s, limit, cursor, detail). type: a node type (target is "
        "its name; category, include_parms, include_help, folder, parms, detail). events: "
        "events, no target (since, limit; next_since as with events). jobs: job list, or "
        "job status with job_id, no target. "
        "Compact shapes (detail: compact, the default; detail: full restores the unabridged "
        "shape of node, parms, outline, geo, problems and type; node rows never carry "
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
        "given; detail: full rows also give the parm's disable_when, hide_when (2.1). geo (summary): attributes per class as {name: type}, the type 'float3', "
        "'float3:color' or 'int[]' (size when not 1, :type_info when set), detail attributes "
        "as {name: {type, value}} with an elided dict value as {elided, key_count}, "
        "attributes: names as name lists, empty classes omitted; groups per class as {name: "
        "count}, omitted when empty; bbox without center (the middle of min and max); "
        "volume and vdb columns with one value in every row (resolution, voxel_size, class) "
        "said once in volume_common / vdb_common; internal_attribute_count kept, its note "
        "omitted (rows: true with attribs reads those attributes); rows: true reads and images "
        "unchanged. outline: also children_count omitted when children lists that many. "
        "problems: counts omitted when empty, nodes_with_problems when 0. type (detail "
        "compact or folders): is_current_version omitted when true, version when empty, the "
        "detail: compact echo and its constant hint (detail: full adds menus, ranges, hidden "
        "parms, per-parm help and disable_when / hide_when), include_help reads nodes.zip or "
        "an asset's HelpText section (help_source), inputs_count unless detail: folders; inputs and outputs "
        "are their labels, outputs omitted when there is only the default Output 1; type "
        "with detail: full is the unabridged type read. "
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
            "group_by": _s(),
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

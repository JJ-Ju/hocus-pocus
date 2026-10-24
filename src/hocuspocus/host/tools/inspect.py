"""``inspect`` (spec-2.0 §2.3): one read tool over the 1.4 reads.

``{target?, what, ...options}`` runs the engine of the 1.4 read for ``what``
(``node_info``, ``parm_get``, ``network_describe``, ``geo_info`` / ``geo_read``,
``usd_stage``, ``problems``, ``node_type_info``; 2.1 removed them as tools) or the
``events`` and ``job`` tools (:func:`_impl`), so the read code exists once. The result is
``{etag, ...the 1.4 result}`` projected for 2.0 (:func:`project`): the caller knows its
``what`` and ``target``, so they are not echoed; ``node`` rows leave out ``session_id``;
``outline`` leaves out ``format`` and, per row, ``name`` when it is the path's last
segment, ``errors: 0``, and ``inputs`` unless ``wiring: true``; and ``node``, ``parms``,
``outline``, ``geo``, ``problems`` and ``type`` leave out what is default or empty (spec-2.0
M4 "read shapes"), unless ``detail: full`` asks for the 1.4 shape.

Registered with ``main_thread=False`` because two of its reads must not hold the main
thread (``events`` and ``job`` run off it in 1.4); the others run on it through the
executor, in one main-thread step together with their etag, as the 1.4 tool would.

The etag (spec-2.0 §2.7) is ``"<pid>:<scene_generation>:<h>"``, ``h`` the first 16 hex
digits of a BLAKE2b digest of the canonical JSON of the result body (sorted keys, compact
separators; :func:`hocuspocus.host.resources.content_etag`). The host builds the body
anyway, so the etag moves exactly when the answer does: a recook that changes nothing (a
``look``, a ``cook`` elsewhere) keeps it, and a resource read with ``If-None-Match`` answers
``not_modified``. ``scene_generation`` moves on every hip load, clear and merge.
"""

from __future__ import annotations

import fnmatch
from collections.abc import Callable
from typing import Any

from ..dispatch import _CALL, call_timeout, current_request_id
from ..resources import content_etag
from ._common import bad_arg, get_node, reference_hint
from .registry import HostContext, tool
from .types import COMPACT_HINT

WHATS: tuple[str, ...] = (
    "node", "parms", "network", "outline", "geo", "image", "stage", "problems", "type",
    "events", "jobs", "guide", "tool",
)  # fmt: skip
"""``what`` values, in the order of spec-2.0 §2.3; ``guide`` and ``tool`` (2.1) are the
bridge's (:data:`BRIDGE_WHATS`)."""

BRIDGE_WHATS = frozenset({"guide", "tool"})
"""``inspect`` reads the bridge answers itself, without a Houdini (2.1, D51): the guide
and one tool's reference, for clients that cannot read MCP resources."""

GEO_READ_OPTIONS = frozenset({"class", "attribs", "start", "count", "group", "stats", "cursor"})

OPTIONS: dict[str, frozenset[str]] = {
    "node": frozenset(
        {"paths", "include", "include_defaults", "recurse_locked", "full_strings", "detail"}
    ),
    "parms": frozenset(
        {
            "paths",
            "frame",
            "include",
            "full_strings",
            "include_defaults",
            "parms",
            "folder",
            "detail",
        }
    ),
    "network": frozenset(
        {"depth", "include_defaults", "include_positions", "recurse_locked", "cursor"}
    ),
    "outline": frozenset({"depth", "recurse_locked", "cursor", "wiring", "detail"}),
    "geo": frozenset({"frame", "attributes", "rows", "detail"}) | GEO_READ_OPTIONS,
    "image": frozenset({"frame"}),
    "stage": frozenset(
        {"prim", "depth", "include", "attribs", "summary", "time", "limit", "cursor"}
    ),
    "problems": frozenset(
        {
            "include_warnings",
            "cook_uncooked",
            "recurse_locked",
            "timeout_s",
            "limit",
            "cursor",
            "detail",
        }
    ),  # fmt: skip
    "type": frozenset({"category", "include_parms", "include_help", "folder", "parms", "detail"}),
    "events": frozenset({"since", "limit"}),
    "jobs": frozenset({"job_id"}),
}
"""The options each ``what`` takes: the arguments of its 1.4 tool (spec ``notes``), plus
(2.1) ``full_strings`` for ``node`` and ``folder`` for ``parms``."""

LENIENT = frozenset(
    {"include_defaults", "recurse_locked", "full_strings", "detail", "include_positions", "wiring"}
)
"""Options that only shape an answer (D48): a ``what`` that does not take one ignores it
with a note, since the read is the same without it. An option that chooses what is read
(``frame``, ``paths``, ``cursor``, ``class``, ...) stays ``invalid_argument``: ignoring it
would answer another question."""

LENIENT_WHY = {
    "recurse_locked": "it reads inside locked assets anyway",
    "include_defaults": "it reads the parms named",
}
"""Why a lenient option changes nothing, per option, where that is not obvious."""

TARGET_REQUIRED = frozenset({"network", "geo", "image", "stage", "type"})
NO_TARGET = frozenset({"events", "jobs"})


# -- running a 1.4 read -------------------------------------------------------------------


def _impl(name: str) -> Callable[[dict[str, Any], HostContext], Any]:
    """The read ``inspect`` runs for a 1.4 name: the engine function of that 1.4 tool
    (2.1: none of them is a tool), or the ``events`` and ``job`` tools'. Imported here, at
    call time, because those modules import this package's helpers."""
    from . import cook, events, geo, network, nodes, parms, state, types, usd

    return {
        "node_info": nodes.node_info,
        "parm_get": parms.parm_get,
        "network_describe": network.network_describe,
        "geo_info": geo.geo_info,
        "geo_read": geo.geo_read,
        "usd_stage": usd.usd_stage,
        "problems": cook.problems,
        "node_type_info": types.node_type_info,
        "events": events.events,
        "job": state.job,
    }[name]


def _on_main(ctx: HostContext, fn: Callable[[], Any]) -> Any:
    """``fn()`` on the main thread, with the call's timeout and request id visible to it
    (``call_timeout``, ``current_request_id``) as they are to a main-thread tool."""
    timeout_s = call_timeout(float(getattr(ctx.config, "default_timeout_s", 30.0)))
    request_id = current_request_id()

    def work() -> Any:
        saved = (
            getattr(_CALL, "timeout_s", None),
            getattr(_CALL, "request_id", None),
            getattr(_CALL, "tool", None),
        )
        _CALL.timeout_s, _CALL.request_id, _CALL.tool = timeout_s, request_id, "inspect"
        try:
            return fn()
        finally:
            _CALL.timeout_s, _CALL.request_id, _CALL.tool = saved

    return ctx.executor.run(work, timeout_s)


# -- arguments -----------------------------------------------------------------------------


def _example(what: str) -> str:
    """A placeholder ``target`` for ``what`` in a corrected-call hint."""
    return {
        "type": "Sop/scatter",
        "stage": "/stage/OUT",
        "image": "/img/comp/OUT",
        "parms": "/obj/geo1/box1/size",
    }.get(what, "/obj/geo1")


def ignored_note(what: str, names: list[str]) -> str:
    """The note for lenient options a ``what`` does not take (D48)."""
    why = [LENIENT_WHY[n] for n in names if n in LENIENT_WHY]
    verb = "does" if len(names) == 1 else "do"
    return (
        f"{', '.join(names)} {verb} not apply to what: {what}"
        + (f" ({'; '.join(why)})" if why else "")
        + "; ignored."
    )


def lenient_options(what: str, target: Any, options: dict[str, Any]) -> list[str]:
    """Drop the lenient options (:data:`LENIENT`) ``what`` does not take from ``options``,
    and a ``detail`` value it does not take; returns the notes saying so (D48)."""
    notes: list[str] = []
    allowed = set(OPTIONS[what])
    of_node = False
    if what == "parms":
        import hou

        of_node = isinstance(target, str) and target.startswith("/") and bool(hou.node(target))
        if not of_node:
            allowed.discard("include_defaults")  # parm paths are read whatever their value
    dropped = sorted(k for k in options if k in LENIENT and k not in allowed)
    if dropped:
        for key in dropped:
            options.pop(key)
        notes.append(ignored_note(what, dropped))
    if options.get("detail") == "folders" and not (what == "type" or of_node):
        options.pop("detail")
        notes.append(
            f"detail folders applies to what: type and to parms of a node; read {what} compact."
        )
    return notes


def _check_args(what: str, target: Any, options: dict[str, Any]) -> None:
    allowed = OPTIONS[what] | LENIENT
    extra = sorted(set(options) - allowed)
    paths = options.get("paths")
    if "paths" in extra and what not in NO_TARGET and isinstance(paths, list) and paths:
        # Review 25 papercut 2: one path is target for every what but node and parms.
        first = paths[0] if isinstance(paths[0], str) else "<path>"
        raise bad_arg(
            f"what: {what} takes one path as target, not paths.",
            hint=f'inspect {{what: "{what}", target: "{first}"}}'
            + ("; one inspect per path." if len(paths) > 1 else "."),
        )
    if extra:
        raise bad_arg(
            f"what: {what} does not take {', '.join(extra)}.",
            hint=f"{what} takes {', '.join(sorted(OPTIONS[what])) or 'no options'} (notes: "
            f"{reference_hint('inspect')}).",
        )
    if what in NO_TARGET and target is not None:
        raise bad_arg(f"what: {what} takes no target.", hint="Leave target out.")
    if target is not None and (not isinstance(target, str) or not target):
        raise bad_arg("'target' must be a non-empty path string.")
    if what in TARGET_REQUIRED and target is None:
        noun = "a node type such as Sop/scatter" if what == "type" else "a node path"
        raise bad_arg(
            f"what: {what} needs target ({noun}).",
            hint=f'inspect {{what: "{what}", target: "{_example(what)}"}}',
        )
    if what in ("node", "parms"):
        if target is None and options.get("paths") is None:
            raise bad_arg(
                f"what: {what} needs target or paths.",
                hint=f'inspect {{what: "{what}", target: "{_example(what)}"}}, or paths: '
                "[...] for several.",
            )
        if target is not None and options.get("paths") is not None:
            raise bad_arg("Pass target or paths, not both.")
    if what != "type" and options.get("detail", "compact") not in (*DETAILS, "folders"):
        raise bad_arg(
            f"what: {what} takes detail compact or full; got {options['detail']!r}.",
            hint="detail: full returns the 1.4 shape; folders is for what: type and parms "
            "of a node.",
        )
    if what == "outline" and not isinstance(options.get("wiring", False), bool):
        raise bad_arg("'wiring' must be a boolean.")
    if what == "geo":
        rows = options.get("rows", False)
        if not isinstance(rows, bool):
            raise bad_arg("'rows' must be a boolean.")
        wrong = sorted(set(options) & (frozenset({"attributes"}) if rows else GEO_READ_OPTIONS))
        if wrong:
            mode = "rows: true" if rows else "the geo summary (without rows)"
            raise bad_arg(
                f"{', '.join(wrong)} {'is' if len(wrong) == 1 else 'are'} not an option of {mode}.",
                hint="rows: true reads values (class, attribs, start, count, group, stats, "
                "cursor); without it the summary takes attributes.",
            )


def _glob_match(text: str, pattern: str) -> bool:
    return any(
        fnmatch.fnmatchcase(text.lower(), alt.strip().lower())
        for alt in pattern.split("|")
        if alt.strip()
    )


def _node_parm_paths(node: Any, pattern: Any, include_defaults: bool) -> list[str]:
    """The parm tuple paths of ``node`` that ``what: parms`` reads: those whose name or
    label matches ``pattern`` (a glob, ``a|b``), else the non-default ones (all with
    ``include_defaults``). Valueless templates (folders, separators, labels, buttons) are
    left out, as node_info leaves them out."""
    import hou

    from . import nodes

    names = getattr(nodes, "_VALUELESS_TEMPLATES", ("Folder", "FolderSet", "Separator", "Label"))
    skip = {getattr(hou.parmTemplateType, n) for n in names if hasattr(hou.parmTemplateType, n)}
    is_block = getattr(nodes, "_is_multiparm_block", lambda template: False)
    if pattern is not None and (not isinstance(pattern, str) or not pattern.strip()):
        raise bad_arg("'parms' must be a non-empty glob such as *seed* or size|t.")
    paths = []
    for parm_tuple in node.parmTuples():
        try:
            template = parm_tuple.parmTemplate()
            if template.type() in skip and not is_block(template):
                continue
            if pattern is not None:
                if not (
                    _glob_match(parm_tuple.name(), pattern)
                    or _glob_match(template.label() or "", pattern)
                ):
                    continue
            elif not include_defaults and parm_tuple.isAtDefault():
                continue
        except Exception:
            continue
        paths.append(f"{node.path()}/{parm_tuple.name()}")
    return paths


def _parms_args(target: Any, options: dict[str, Any]) -> dict[str, Any] | None:
    """``parm_get`` arguments (``None`` when a node has no parm to read)."""
    import hou

    node_only = ("parms", "include_defaults", "paths", "folder")
    rest = {k: v for k, v in options.items() if k not in node_only}
    node = hou.node(target) if isinstance(target, str) and target.startswith("/") else None
    if node is None:
        if "parms" in options or "folder" in options:
            raise bad_arg(
                "parms and folder apply when target is a node.",
                hint="Pass the node's path as target, or parm paths without them.",
            )
        paths = options.get("paths") if target is None else [target]
        return {"paths": paths, **rest}
    include_defaults = options.get("include_defaults", False)
    if not isinstance(include_defaults, bool):
        raise bad_arg("'include_defaults' must be a boolean.")
    paths = _node_parm_paths(node, options.get("parms"), include_defaults)
    if options.get("folder") is not None:
        names = set(_folder_parms(node, options["folder"]))
        if options.get("parms") is None:  # a folder lists its parms, defaults or not
            paths = _node_parm_paths(node, None, True)
        paths = [p for p in paths if p.rsplit("/", 1)[-1] in names]
    return {"paths": paths, **rest} if paths else None


def _node_template_rows(node: Any, folder: Any = None) -> tuple[list[dict[str, Any]], list[str]]:
    """The rows and folders of ``node``'s own parm template group (spare parms included),
    as ``inspect what: type`` lists a type's (2.1, D48)."""
    from .types import parm_template_rows

    return parm_template_rows(node.parmTemplateGroup(), folder=folder)


def _folder_parms(node: Any, folder: Any) -> list[str]:
    """The parm names in ``folder`` of ``node`` (a label or ``A / B`` path, any case;
    ``""`` or ``(no folder)`` the top level), or ``invalid_argument`` naming its folders."""
    from .types import NO_FOLDER, folder_counts

    if not isinstance(folder, str):
        raise bad_arg("'folder' must be a string.")
    wanted = "" if folder.strip().lower() in ("", NO_FOLDER) else folder
    rows, _folders = _node_template_rows(node, wanted)
    if not rows:
        every, folders = _node_template_rows(node)
        raise bad_arg(
            f"No folder {folder!r} on {node.path()}.",
            hint="Pass one folder from candidates, or a single segment of one.",
            candidates=[row["folder"] for row in folder_counts(every, folders)],
        )
    return [row["name"] for row in rows]


def node_folders(node: Any) -> dict[str, Any]:
    """``inspect what: parms`` of a node with ``detail: folders``: ``{folders: [{folder,
    parms}]}`` for the node's own parm interface, spare parms included (2.1, D48)."""
    from .types import folder_counts

    rows, folders = _node_template_rows(node)
    return {
        "folders": folder_counts(rows, folders),
        "hint": "Pass folder with one of these to read its parms.",
    }


def _image_check(target: str) -> None:
    from .visual import cop_image_node, is_cop_network

    node = get_node(target, field="target")
    if cop_image_node(node) is None and not is_cop_network(node):
        raise bad_arg(
            f"{node.path()} is not a Cop node or COP network.",
            hint="what: image reads Copernicus images; what: geo reads SOP geometry.",
        )


# -- etag ----------------------------------------------------------------------------------


def make_etag(ctx: HostContext, body: Any) -> str:
    """``<pid>:<scene_generation>:<16 hex>`` of the canonical body (without its etag)."""
    return content_etag(ctx.scene.generation, body, pid=ctx.pid)


# -- 2.0 projections ---------------------------------------------------------------------
#
# spec-2.0 M4 "read shapes": each read leaves out what is default or empty, says a plain
# value as a value, and keeps a full row only where something beyond the value matters.
# ``detail: full`` returns the 1.4 shape (only ``etag`` added; ``node`` rows still leave
# out ``session_id``, ``outline`` keeps its 2.0 trims). Pure functions over the 1.4
# result, so the resources (which run ``inspect``) share them.


INSPECT_ONLY = frozenset({"wiring", "detail"})
"""Options ``inspect`` takes itself (except for ``type``, whose ``detail`` is
``node_type_info``'s); they are not passed to the 1.4 read."""

DETAILS = ("compact", "full")
"""``detail`` of the projected reads; ``type`` also takes ``folders``."""

PROJECTED = frozenset({"node", "parms", "outline", "geo", "problems", "type"})

PLAIN_PARM_TYPES = frozenset({"float", "int", "string", "toggle"})
"""Parm types a compact parm row leaves out: the JSON value already says them."""

DEFAULT_LANGUAGE = "hscript"


def _numbers_equal(raw: Any, value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, int | float) or not isinstance(raw, str):
        return False
    try:
        return float(raw) == float(value)
    except ValueError:
        return False


def _no_keys(keyframes: Any) -> bool:
    if not isinstance(keyframes, dict):
        return False
    if not keyframes or keyframes.get("count") == 0:
        return True
    return all(isinstance(v, dict) and v.get("count") == 0 for v in keyframes.values())


def _raw_says_nothing(raw: Any, value: Any, expression: Any, expressions: Any) -> bool:
    """``raw`` repeats the expression (a parm) or, per component, an expression or the
    value (a tuple)."""
    if not isinstance(raw, list):
        return expression is not None and raw == expression
    if not isinstance(value, list) or len(value) != len(raw) or not isinstance(expressions, dict):
        return False
    texts = [e.get("expression") for e in expressions.values() if isinstance(e, dict)]
    return all(r in texts or _numbers_equal(r, v) for r, v in zip(raw, value, strict=True))


def compact_parm(row: dict[str, Any]) -> Any:
    """A parm row (``node_info``'s or ``parm_get``'s) as its value, or as ``{value, ...}``
    with only what matters beyond the value: an expression (``language`` when not
    hscript), keys, a lock, a menu token unlike the value, ``raw`` unlike the value and
    the expression, a type the value does not say, and any ``include`` section."""
    out: dict[str, Any] = {}
    value = row.get("value")
    expression = row.get("expression")
    expressions = row.get("expressions")
    for key, item in row.items():
        if key in ("path", "name", "kind", "tuple", "component_names", "is_default"):
            continue
        if key == "type" and item in PLAIN_PARM_TYPES:
            continue
        if key in ("locked", "hda_locked") and item is False:
            continue
        if key == "language" and item == DEFAULT_LANGUAGE:
            continue
        if key == "menu_token" and item == value:
            continue
        if key == "keyframes" and _no_keys(item):
            continue
        if key == "raw" and _raw_says_nothing(item, value, expression, expressions):
            continue
        if key == "expressions" and isinstance(item, dict):
            item = {
                comp: e["expression"]
                if isinstance(e, dict) and e.get("language") == DEFAULT_LANGUAGE
                else e
                for comp, e in item.items()
            }
        out[key] = item
    if set(out) == {"value"} and not isinstance(value, dict):
        return value
    return out


def compact_parms(rows: Any, key: str) -> Any:
    """Parm rows as ``{row[key]: value or row}`` in their order (the rows unchanged when
    two share a key)."""
    if not rows or not isinstance(rows, list):
        return rows  # parms: [] says there are none
    if not all(isinstance(r, dict) and key in r for r in rows):
        return rows
    if len({row[key] for row in rows}) != len(rows):
        return rows
    return {row[key]: compact_parm(row) for row in rows}


def _input_ref(source: Any) -> Any:
    if (
        isinstance(source, dict)
        and source.get("output", 0) == 0
        and set(source)
        <= {
            "path",
            "output",
        }
    ):
        return source.get("path")
    return source


def compact_inputs(rows: Any) -> Any:
    """``[{index, name, label, from}]`` as positional sources: a path (output 0), ``{path,
    output}``, or null; trailing unconnected inputs left out."""
    if not isinstance(rows, list) or not all(isinstance(r, dict) and "from" in r for r in rows):
        return rows
    refs = [_input_ref(row["from"]) for row in rows]
    while refs and refs[-1] is None:
        refs.pop()
    return refs


def compact_outputs(rows: Any) -> Any:
    """``[{index, name, to: [{path, input}]}]`` as positional lists of destinations (a path
    for input 0, else ``{path, input}``)."""
    if not isinstance(rows, list) or not all(isinstance(r, dict) and "to" in r for r in rows):
        return rows
    return [
        [d["path"] if isinstance(d, dict) and d.get("input") == 0 else d for d in row["to"]]
        for row in rows
    ]


def _type_name(block: dict[str, Any]) -> str:
    category = block.get("category")
    return f"{category}/{block['name']}" if category else str(block["name"])


_UNSET = object()
NODE_DEFAULTS: dict[str, Any] = {
    "errors": [],
    "warnings": [],
    "messages": [],
    "cook_state": "cooked",
    "children_count": 0,
}
"""``node_info`` values a compact row leaves out."""


def compact_node(row: dict[str, Any]) -> dict[str, Any]:
    """A ``node_info`` row without the defaults: ``name`` when it is the path's last
    segment, ``type`` as ``Category/name``, flags as the list of those on, inputs and
    outputs positional, parms as ``{name: value}``, and no empty errors, warnings or
    messages, ``cook_state: cooked`` or ``children_count: 0``."""
    out: dict[str, Any] = {}
    path = row.get("path")
    for key, value in row.items():
        if key == "session_id":
            continue
        if key == "name" and isinstance(path, str) and value == path.rsplit("/", 1)[-1]:
            continue
        if key == "type" and isinstance(value, dict) and "name" in value:
            value = _type_name(value)
        elif key == "flags" and isinstance(value, dict):
            value = [name for name, on in value.items() if on]
            if not value:
                continue
        elif key == "inputs":
            value = compact_inputs(value)
            if value == []:
                continue
        elif key == "outputs":
            value = compact_outputs(value)
        elif key == "parms":
            value = compact_parms(value, "name")
            if value in ([], {}):
                continue
        elif NODE_DEFAULTS.get(key, _UNSET) == value:
            continue
        out[key] = value
    return out


def _attribute_type(row: dict[str, Any]) -> str:
    """``{type, size, type_info}`` as ``"float3"``, ``"float3:color"``, ``"int[]"``."""
    kind = str(row.get("type", ""))
    array = kind.endswith("[]")
    base = kind[:-2] if array else kind
    size = row.get("size", 1)
    text = base + ("" if size in (1, None) else str(size)) + ("[]" if array else "")
    info = row.get("type_info")
    return f"{text}:{info}" if info else text


def _detail_value(value: Any) -> Any:
    if isinstance(value, dict) and "elided" in value and isinstance(value.get("keys"), list):
        return {"elided": value["elided"], "key_count": len(value["keys"])}
    return value


def compact_attributes(attributes: Any) -> Any:
    """Per class ``{name: "float3:color"}`` (detail ``{name: {type, value}}``), or the
    names list (``attributes: names``); empty classes left out."""
    if not isinstance(attributes, dict):
        return attributes
    out: dict[str, Any] = {}
    for cls, rows in attributes.items():
        if not rows:
            continue
        if not isinstance(rows, list) or not all(isinstance(r, dict) and "name" in r for r in rows):
            out[cls] = rows
            continue
        entries: dict[str, Any] = {}
        for row in rows:
            kind = _attribute_type(row)
            if "value" in row:
                entries[row["name"]] = {"type": kind, "value": _detail_value(row["value"])}
            else:
                entries[row["name"]] = kind
        out[cls] = entries
    return out


def compact_groups(groups: Any) -> Any:
    """Per class ``{name: count}``; empty classes left out (``None`` when all are)."""
    if not isinstance(groups, dict):
        return groups
    out: dict[str, Any] = {}
    for cls, rows in groups.items():
        if not rows:
            continue
        if isinstance(rows, list) and all(isinstance(r, dict) and "name" in r for r in rows):
            out[cls] = {r["name"]: r.get("count") for r in rows}
        else:
            out[cls] = rows
    return out or None


def compact_intrinsics(intrinsics: Any) -> Any:
    """Volume and VDB rows (``<kind>_columns``, ``<kind>``) with every column that has one
    value in all rows (resolution, voxel size, class) said once in ``<kind>_common``."""
    if not isinstance(intrinsics, dict):
        return intrinsics
    out = dict(intrinsics)
    for kind in ("volume", "vdb"):
        columns, rows = out.get(f"{kind}_columns"), out.get(kind)
        if not isinstance(columns, list) or not isinstance(rows, list) or len(rows) < 2:
            continue
        if not all(isinstance(r, list) and len(r) == len(columns) for r in rows):
            continue
        same = [
            i
            for i, name in enumerate(columns)
            if name not in ("name", "prim") and all(r[i] == rows[0][i] for r in rows)
        ]
        if not same:
            continue
        keep = [i for i in range(len(columns)) if i not in same]
        common = {columns[i]: rows[0][i] for i in same}
        rebuilt: dict[str, Any] = {}
        for key, value in out.items():
            if key == f"{kind}_columns":
                rebuilt[key] = [columns[i] for i in keep]
                rebuilt[f"{kind}_common"] = common
            elif key == kind:
                rebuilt[key] = [[r[i] for i in keep] for r in rows]
            else:
                rebuilt[key] = value
        out = rebuilt
    return out


INTERNAL_NOTE = "solver-internal attribute(s) left out"
"""The ``geo_info`` note that ``internal_attribute_count`` already says."""


def compact_geo(result: dict[str, Any]) -> dict[str, Any]:
    """A ``geo_info`` summary: compact attributes and groups, volume columns shared by
    every row said once, no ``bbox.center`` (the middle of min and max), no note
    repeating ``internal_attribute_count``. Images and
    ``rows: true`` reads are already columnar and stay as they are."""
    if result.get("kind") == "image" or "columns" in result:
        return result
    out: dict[str, Any] = {}
    for key, value in result.items():
        if key == "attributes":
            value = compact_attributes(value)
            if not value:
                continue
        elif key == "groups":
            value = compact_groups(value)
            if value is None:
                continue
        elif key == "bbox" and isinstance(value, dict):
            value = {k: v for k, v in value.items() if k != "center"}
        elif key == "intrinsics":
            value = compact_intrinsics(value)
        elif key == "notes" and isinstance(value, list):
            value = [n for n in value if not (isinstance(n, str) and INTERNAL_NOTE in n)]
            if not value:
                continue
        out[key] = value
    return out


def _compact_outline(rows: Any, wiring: bool) -> None:
    for row in rows if isinstance(rows, list) else ():
        if not isinstance(row, dict):
            continue
        path = row.get("path")
        if isinstance(path, str) and row.get("name") == path.rsplit("/", 1)[-1]:
            del row["name"]
        if row.get("errors") == 0:
            del row["errors"]
        if row.get("children_count") == 0:
            del row["children_count"]
        if not wiring:
            row.pop("inputs", None)
        _compact_outline(row.get("children"), wiring)


def _drop_listed_counts(rows: Any) -> None:
    """``children_count`` where ``children`` lists exactly that many."""
    for row in rows if isinstance(rows, list) else ():
        if not isinstance(row, dict):
            continue
        children = row.get("children")
        if isinstance(children, list) and row.get("children_count") == len(children):
            del row["children_count"]
        _drop_listed_counts(children)


def compact_problems(result: dict[str, Any]) -> dict[str, Any]:
    """``problems`` without empty ``counts`` or a zero ``nodes_with_problems`` (``total``
    and the ``problems`` list, empty or not, say it)."""
    return {
        k: v
        for k, v in result.items()
        if not (k == "counts" and not v) and not (k == "nodes_with_problems" and v == 0)
    }


DEFAULT_OUTPUTS = [{"index": 0, "name": "output1", "label": "Output 1"}]


def compact_type(result: dict[str, Any], options: dict[str, Any]) -> dict[str, Any]:
    """``node_type_info`` (compact or folders): no ``is_current_version: true``, empty
    ``version``, ``detail: compact`` echo and its constant hint, or ``inputs_count``
    (kept with detail: folders); inputs and outputs as their labels, outputs left out when there is only
    the default one."""
    folders = options.get("detail") == "folders"
    out: dict[str, Any] = {}
    for key, value in result.items():
        if key == "is_current_version" and value is True:
            continue
        if key == "version" and value in ("", None):
            continue
        if key == "detail" and value == "compact":
            continue
        if key == "hint" and value == COMPACT_HINT:  # constant; the spec notes say it
            continue
        if key == "inputs_count" and not folders:
            continue
        if key == "outputs" and value == DEFAULT_OUTPUTS:
            continue
        labelled = isinstance(value, list) and all(
            isinstance(r, dict) and "label" in r for r in value
        )
        if key in ("inputs", "outputs") and labelled:
            value = [r["label"] or r.get("name") for r in value]
        out[key] = value
    return out


def project(what: str, result: dict[str, Any], options: dict[str, Any]) -> dict[str, Any]:
    """The 2.0 shape of a 1.4 read (``result`` may be changed in place): what the caller
    already knows or did not ask for, and what is default or empty, is left out;
    ``detail: full`` keeps the 1.4 shape apart from the trims every 2.0 read has."""
    if what == "node":
        for row in result.get("nodes") or ():
            if isinstance(row, dict):
                row.pop("session_id", None)
    elif what == "outline":
        result.pop("format", None)
        _compact_outline(result.get("nodes"), options.get("wiring") is True)
    if what not in PROJECTED or options.get("detail") == "full":
        return result
    if what == "node":
        nodes = result.get("nodes")
        if isinstance(nodes, list):
            result["nodes"] = [compact_node(r) if isinstance(r, dict) else r for r in nodes]
        return result
    if what == "parms":
        if "parms" in result:
            key = "name" if options.get("by_name") else "path"
            result["parms"] = compact_parms(result["parms"], key)
        return result
    if what == "outline":
        _drop_listed_counts(result.get("nodes"))
        return result
    if what == "geo":
        return compact_geo(result)
    if what == "problems":
        return compact_problems(result)
    return compact_type(result, options)


# -- the tool ------------------------------------------------------------------------------


def _scene_read(
    ctx: HostContext, what: str, target: Any, options: dict[str, Any]
) -> dict[str, Any]:
    """One main-thread step: the 1.4 read, projected for 2.0, with its etag."""
    shape_options = options
    if what != "type":  # detail is node_type_info's own; for the others it is inspect's
        options = {k: v for k, v in options.items() if k != "detail"}
    if what == "node":
        paths = options.get("paths") if target is None else [target]
        args = {"paths": paths, **{k: v for k, v in options.items() if k != "paths"}}
        result = _impl("node_info")(args, ctx)
    elif what == "parms":
        import hou

        if shape_options.get("detail") == "folders":
            return _with_etag(ctx, node_folders(get_node(target, field="target")))
        parm_args = _parms_args(target, options)
        result = {"parms": []} if parm_args is None else _impl("parm_get")(parm_args, ctx)
        if isinstance(target, str) and target.startswith("/") and hou.node(target) is not None:
            shape_options = {**shape_options, "by_name": True}  # a node's parms by name
    elif what in ("network", "outline"):
        root = target if target is not None else "/"
        fmt = "data" if what == "network" else "outline"
        passed = {k: v for k, v in options.items() if k not in INSPECT_ONLY}
        result = _impl("network_describe")({"root": root, "format": fmt, **passed}, ctx)
    elif what == "geo":
        rows = options.get("rows", False)
        args = {"path": target, **{k: v for k, v in options.items() if k != "rows"}}
        result = _impl("geo_read" if rows else "geo_info")(args, ctx)
    elif what == "image":
        _image_check(target)
        result = _impl("geo_info")({"path": target, **options}, ctx)
    elif what == "stage":
        result = _impl("usd_stage")({"lop_path": target, **options}, ctx)
    elif what == "problems":
        args = dict(options) if target is None else {"root": target, **options}
        result = _impl("problems")(args, ctx)
    else:  # type
        result = _impl("node_type_info")({"type": target, **options}, ctx)
    return _with_etag(ctx, project(what, result, shape_options))


def _with_etag(ctx: HostContext, body: dict[str, Any]) -> dict[str, Any]:
    return {"etag": make_etag(ctx, body), **body}


@tool("inspect", main_thread=False)
def inspect(args: dict[str, Any], ctx: HostContext) -> dict[str, Any]:
    what = args.get("what")
    if what not in WHATS:
        raise bad_arg(
            f"'what' must be one of {', '.join(WHATS)}; got {what!r}.",
            candidates=list(WHATS),
        )
    target = args.get("target")
    options = {k: v for k, v in args.items() if k not in ("what", "target")}
    if what in BRIDGE_WHATS:
        raise bad_arg(
            f"what: {what} is answered by the bridge (hocuspocus-mcp), not by Houdini.",
            hint="Call inspect through the MCP server.",
        )
    _check_args(what, target, options)
    if what in NO_TARGET:
        notes = lenient_options(what, target, options) if set(options) & LENIENT else []
        if what == "events":
            result = _impl("events")(options, ctx)
        else:
            job_id = options.get("job_id")
            call = {"action": "list"} if job_id is None else {"action": "status", "job_id": job_id}
            result = _impl("job")(call, ctx)
        return _noted(_with_etag(ctx, result), notes)

    def read() -> dict[str, Any]:
        notes = lenient_options(what, target, options)
        return _noted(_scene_read(ctx, what, target, options), notes)

    return _on_main(ctx, read)


def _noted(result: dict[str, Any], notes: list[str]) -> dict[str, Any]:
    """``result`` with the ignored-option ``notes`` first in its ``notes`` (D48); the etag
    is the answer's, so an ignored option does not change it."""
    if notes:
        result["notes"] = [*notes, *(result.get("notes") or [])]
    return result

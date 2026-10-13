"""The HocusPocus tool catalogue: the single source of truth for the tool surface.

Stdlib only. Imported by the host (inside Houdini) to map names to implementations,
by the bridge (outside Houdini) to register MCP tools, and by the docs generator.
See docs/BIBLE.md §3.5 and §4.

Schemas are JSON Schema 2020-12. ``$schema`` is omitted from each schema because MCP
defines 2020-12 as the default dialect and the bytes count against the tools/list cap.
Output schemas never set ``additionalProperties: false`` and only require keys present
in every successful result, so the host may add fields without breaking clients.

Choices made where the bible is silent are marked ``# bible-silent:``; arguments added
from a §4.1 convention that a §4.x table row omits are marked ``# §4.1:``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Profile = Literal["core", "full"]

HP_RPC_VERSION = 1
"""Host RPC contract version (the ``v1`` in ``/hp/v1/...``)."""

TOOLS_LIST_MAX_BYTES = 48_000
"""Hard cap on model-visible ``tools/list`` text (≈12k tokens). Enforced by a unit test."""

DESCRIPTION_MAX_WORDS = 60
"""1.2 (BIBLE §4.1): argument-level detail goes in ``ToolSpec.notes``, not the description."""


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """One MCP tool as the bridge advertises it and the host implements it."""

    name: str
    description: str
    input_schema: dict[str, Any]
    notes: str = ""
    """Argument-level detail rendered into docs/tools.md and ``hocuspocus://guide`` but kept
    out of ``tools/list`` (BIBLE §4.1 budget): what the schema cannot say and the model
    needs only when it uses that argument."""
    output_schema: dict[str, Any] | None = None
    read_only: bool = False
    destructive: bool = False
    idempotent: bool = False
    profile: Profile = "core"
    headless_ok: bool = True
    bridge_local: bool = False
    """True when the bridge answers this tool itself (``houdini_status``, ``houdini_connect``)."""
    examples: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    """Example argument objects; rendered into docs/tools.md and validated by a unit test."""

    def annotations(self) -> dict[str, Any]:
        """MCP ToolAnnotations as a plain dict."""
        return {
            "readOnlyHint": self.read_only,
            "destructiveHint": self.destructive if not self.read_only else False,
            "idempotentHint": self.idempotent,
            "openWorldHint": False,
        }

    def wire_annotations(self) -> dict[str, Any]:
        """:meth:`annotations` as sent in ``tools/list``: hints equal to the MCP default
        (readOnlyHint false, idempotentHint false) are left out, and so are destructiveHint
        and idempotentHint on a read-only tool, where the spec says they are not meaningful.
        A client applying the spec's defaults reads the same values (BIBLE §4.1 budget)."""
        full = self.annotations()
        if self.read_only:
            return {"readOnlyHint": True, "openWorldHint": False}
        wire = {"destructiveHint": full["destructiveHint"], "openWorldHint": False}
        if self.idempotent:
            wire["idempotentHint"] = True
        return wire


# ---------------------------------------------------------------------------
# Schema helpers (plain dict builders; every call returns a fresh dict)
# ---------------------------------------------------------------------------

CATEGORIES: tuple[str, ...] = (
    "Chop", "ChopNet", "Cop", "Cop2", "CopNet", "Data", "Director", "Dop", "Driver",
    "Lop", "Manager", "Object", "Shop", "Sop", "Top", "TopNet", "Vop", "VopNet",
)  # fmt: skip
"""All 18 Houdini node type categories (bible §5.15)."""


def _obj(
    properties: dict[str, Any], required: tuple[str, ...] = (), **extra: Any
) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = list(required)
    schema["additionalProperties"] = False
    schema.update(extra)
    return schema


def _typed(type_: str, description: str | None, extra: dict[str, Any]) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": type_, **extra}
    if description:
        schema["description"] = description
    return schema


def _s(description: str | None = None, **extra: Any) -> dict[str, Any]:
    return _typed("string", description, extra)


def _i(description: str | None = None, **extra: Any) -> dict[str, Any]:
    return _typed("integer", description, extra)


def _n(description: str | None = None, **extra: Any) -> dict[str, Any]:
    return _typed("number", description, extra)


def _b(default: bool, description: str | None = None) -> dict[str, Any]:
    return _typed("boolean", description, {"default": default})


def _enum(
    values: tuple[str, ...], default: str | None = None, description: str | None = None
) -> dict[str, Any]:
    extra: dict[str, Any] = {"enum": list(values)}
    if default is not None:
        extra["default"] = default
    return _typed("string", description, extra)


def _arr(items: dict[str, Any], description: str | None = None, **extra: Any) -> dict[str, Any]:
    return _typed("array", description, {"items": items, **extra})


def _paths(description: str = "Node paths.") -> dict[str, Any]:
    return _arr({"type": "string"}, description, minItems=1)


def _limit(default: int = 50) -> dict[str, Any]:
    return _i(None, minimum=1, maximum=1000, default=default)


def _cursor() -> dict[str, Any]:
    return _s("next_cursor from the previous page.")


def _frame(description: str = "Default current frame.") -> dict[str, Any]:
    return _n(description)


def _xy(description: str) -> dict[str, Any]:
    return _arr({"type": "number"}, description, minItems=2, maxItems=2)


def _flags(*extra: str) -> dict[str, Any]:
    names = ("display", "render", "bypass", "template", *extra)
    return _obj({name: {"type": "boolean"} for name in names})


def _partial() -> dict[str, Any]:
    # §4.1: batch tools roll back on the first failing item unless partial is true.
    return _b(False, "Keep successful items.")


def _return() -> dict[str, Any]:
    # Review 11 B5: lean mutation echoes (the 1.1 default); identical errors are reported once.
    return _enum(("full", "summary"), "summary")


def _scalar() -> dict[str, Any]:
    return {"type": ["string", "number", "boolean"]}


def _literal_value() -> dict[str, Any]:
    return {"anyOf": [_scalar(), {"type": "array", "items": _scalar()}]}


def _parm_value() -> dict[str, Any]:
    """node_create parms: a literal scalar/array, the short expression ``{expr, lang}``, or
    one parm_set item without ``path`` (``{expression, language}``, ``{keyframes}``,
    ``{channel_ref}``, ``{ramp}``, ``{multiparm_count}``...), as ``set_parm_items`` takes."""
    literal = _literal_value()
    languages = ("hscript", "python")
    literal["anyOf"].append(_obj({"expr": _s(), "lang": _enum(languages, "hscript")}, ("expr",)))
    # The item fields' own shapes are parm_set's (and checked by the host); listing the
    # names keeps typos caught here without repeating every sub-schema in tools/list.
    item = {
        "value": {},
        "expression": _s(),
        "language": _enum(languages),
        "keyframe": {"type": "object"},
        "keyframes": {"type": "array"},
        "channel_ref": _s(),
        "ramp": {"type": "object"},
        "multiparm_count": {"type": "integer"},
        "revert_to_default": {"type": "boolean"},
        "press": {"type": "boolean"},
        "animation": _enum(("replace", "key", "keep")),
    }
    literal["anyOf"].append(_obj(item))
    return literal


# Output-schema fragments ------------------------------------------------------


def _out(properties: dict[str, Any], required: tuple[str, ...] = ()) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = list(required)
    return schema


def _t(type_: str | list[str]) -> dict[str, Any]:
    return {"type": type_}


def _nullable(schema: dict[str, Any]) -> dict[str, Any]:
    return {**schema, "type": [schema["type"], "null"]}


def _list(item_type: str = "string") -> dict[str, Any]:
    return {"type": "array", "items": {"type": item_type}}


def _objs() -> dict[str, Any]:
    return {"type": "array", "items": {"type": "object"}}


def _problems() -> dict[str, Any]:
    return {"errors": _list(), "warnings": _list(), "messages": _list()}


def _tuple_animation() -> dict[str, Any]:
    """Parm animation keys: a single parm has ``keyed: true``; a tuple has per-component
    ``expressions`` (component name -> {expression, language}) and ``keyed`` as a list of
    component names. The tool descriptions say so; no schema descriptions (tools/list cap)."""
    return {
        "expressions": _t("object"),
        "keyed": {"type": ["boolean", "array"], "items": {"type": "string"}},
    }


def _image() -> dict[str, Any]:
    """An image the bridge moved into MCP image content (the base64 is removed)."""
    return _out(
        {
            "mime_type": _t("string"),
            "width": _t("integer"),
            "height": _t("integer"),
            "attached": _t("boolean"),  # true: sent as MCP image content
        }
    )


_JOB_STATES = ["running", "done", "failed", "cancelled"]


def _connected_block() -> dict[str, Any]:
    return _out(
        {
            "pid": _t("integer"),
            "port": _t("integer"),
            "label": _t("string"),
            "houdini": _t("string"),
            "ui": _t("boolean"),
            "hip": _out(
                {
                    "path": _t("string"),
                    "name": _t("string"),
                    "dirty": _t("boolean"),
                    "is_new": _t("boolean"),
                    "recent": _list(),
                    "note": _t("string"),
                }
            ),
            "time": _out({"frame": _t("number"), "fps": _t("number"), "range": _list("number")}),
            "env": _out({"HIP": _t("string"), "JOB": _t("string"), "HIPNAME": _t("string")}),
            "scene_generation": _t("integer"),
            "host_version": _t("string"),
        }
    )


# ---------------------------------------------------------------------------
# §4.2 Session and instances (bridge-local)
# ---------------------------------------------------------------------------

_SESSION: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="houdini_status",
        description=(
            "Start here. Reports the connected Houdini (pid, version, GUI or headless, hip path and"
            " dirty state, $HIP/$JOB, frame, recent files, scene_generation), every live instance "
            "and the bridge settings. Works with no Houdini running (connected: null)."
        ),
        notes=(
            "Also reports $HIPNAME, fps, the frame range, and the bridge's profile, read_only and "
            "allow_python. An untitled scene's hip carries a note that $HIP is the launch directory"
            " until hip_save."
        ),
        input_schema=_obj({}),
        output_schema=_out(
            {
                "connected": {"anyOf": [_connected_block(), _t("null")]},
                "instances": {
                    "type": "array",
                    "items": _out(
                        {
                            "pid": _t("integer"),
                            "label": _t("string"),
                            "houdini": _t("string"),
                            "ui": _t("boolean"),
                            "hip": _t("string"),
                            "started": _t("string"),
                            "launched_by": _t(["integer", "null"]),
                        }
                    ),
                },
                "bridge_version": _t("string"),
                "profile": {"type": "string", "enum": ["core", "full"]},
                "read_only": _t("boolean"),
                "allow_python": _t("boolean"),
            },
            ("connected", "instances", "bridge_version"),
        ),
        read_only=True,
        bridge_local=True,
        examples=({},),
    ),
    ToolSpec(
        name="houdini_connect",
        description=(
            "Choose the Houdini this session drives: pid attaches, launch starts one (gui or "
            "headless, optional hip), disconnect drops the selection, quit closes it (on_unsaved "
            "as hip_new). A launched Houdini usually closes with this server "
            "(launched.outlives_server says); `hocuspocus launch` starts one that outlives it."
        ),
        notes=(
            "launch waits up to wait_s seconds for the new host to register. A launched Houdini "
            "starts in HOCUSPOCUS_WORK_DIR (default: the home directory), which is the untitled "
            "scene's $HIP and $JOB. quit closes the selected Houdini (or pid) through its host: "
            "with unsaved changes on_unsaved fail (default) refuses with unsaved_changes, save "
            "saves first, discard drops them. It returns {quit, pid, exited, saved?} and forgets "
            "the registry entry. To keep one alive across sessions, start it with `hocuspocus "
            "launch` and attach by pid."
        ),
        input_schema=_obj(
            {
                "pid": _i("Live instance to attach to."),
                "launch": _obj(
                    {
                        "mode": _enum(("gui", "headless")),
                        "hip": _s("Hip file to open."),
                        "wait_s": _n(None, minimum=1, default=90),
                    },
                    ("mode",),
                ),
                "disconnect": _b(False),
                "quit": _b(False),
                "on_unsaved": _enum(("fail", "save", "discard")),
            }
        ),
        bridge_local=True,
        examples=(
            {"pid": 12345},
            {"launch": {"mode": "headless", "hip": "C:/work/shot.hip"}},
            {"quit": True, "on_unsaved": "save"},
        ),
    ),
)


# ---------------------------------------------------------------------------
# §4.3 Hip file
# ---------------------------------------------------------------------------


def _on_unsaved() -> dict[str, Any]:
    return _enum(("fail", "save", "discard"), "fail")


_HIP: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="hip_new",
        description=(
            "Clear to a new untitled scene; bumps scene_generation. on_unsaved protects unsaved "
            "work: fail returns unsaved_changes, save saves first (an untitled scene needs hip_save"
            " with path instead), discard drops the changes."
        ),
        input_schema=_obj({"on_unsaved": _on_unsaved()}),
        # bible-silent: result shape. Report the new scene and whether unsaved work was saved.
        output_schema=_out(
            {
                "path": _t("string"),
                "name": _t("string"),
                "dirty": _t("boolean"),
                "is_new": _t("boolean"),
                "saved_first": _t("boolean"),
                "scene_generation": _t("integer"),
            },
            ("path", "saved_first", "scene_generation"),
        ),
        destructive=True,
        examples=({}, {"on_unsaved": "save"}),
    ),
    ToolSpec(
        name="hip_open",
        description=(
            "Load a hip file, replacing the current scene; on_unsaved as in hip_new. Load warnings "
            "are returned in warnings, not raised, unless ignore_load_warnings is false. hip_merge "
            "adds nodes instead."
        ),
        input_schema=_obj(
            {
                "path": _s("Hip file."),
                "on_unsaved": _on_unsaved(),
                "ignore_load_warnings": _b(True),
            },
            ("path",),
        ),
        output_schema=_out(
            {"path": _t("string"), "warnings": _list(), "scene_generation": _t("integer")},
            ("path", "warnings", "scene_generation"),
        ),
        destructive=True,
        examples=(
            {"path": "C:/work/shot.hip"},
            {"path": "$JOB/shot_v002.hip", "on_unsaved": "discard"},
        ),
    ),
    ToolSpec(
        name="hip_save",
        description=(
            "Save the hip file. path saves as (creating directories; an untitled scene needs it); "
            "increment saves to the next version number in the file name; backup keeps a backup "
            "copy. Returns the real saved path, dirty after save, and bytes."
        ),
        input_schema=_obj(
            {
                "path": _s("Save-as target."),
                "increment": _b(False),
                "backup": _b(False),
            }
        ),
        output_schema=_out(
            {"path": _t("string"), "dirty": _t("boolean"), "bytes": _t("integer")},
            ("path", "dirty"),
        ),
        examples=({}, {"path": "C:/work/shot_v002.hip"}, {"increment": True}),
    ),
    ToolSpec(
        name="hip_merge",
        description=(
            "Merge the nodes matching node_pattern from another hip file into the current scene. "
            "dry_run only reports collisions (no undo step, allowed read-only). Colliding nodes are"
            " renamed unless overwrite_on_conflict."
        ),
        input_schema=_obj(
            {
                "path": _s("Hip file to merge."),
                "node_pattern": _s(None, default="*"),
                "overwrite_on_conflict": _b(False),
                "dry_run": _b(False),
            },
            ("path",),
        ),
        # bible-silent: result keys besides collisions.
        output_schema=_out(
            {
                "path": _t("string"),
                "dry_run": _t("boolean"),
                "collisions": _list(),
                "merged": _list(),
                "scene_generation": _t("integer"),
            },
            ("collisions",),
        ),
        examples=(
            {"path": "C:/lib/rig.hip", "dry_run": True},
            {"path": "C:/lib/rig.hip", "node_pattern": "/obj/rig*"},
        ),
    ),
)


# ---------------------------------------------------------------------------
# §4.4 Nodes and networks
# ---------------------------------------------------------------------------

_NODE_INFO_SECTIONS: tuple[str, ...] = (
    "parms", "inputs", "outputs", "children", "errors", "flags", "hda", "comment", "position",
    "userdata",
)  # fmt: skip


def _input_link() -> dict[str, Any]:
    return _obj(
        {
            "index": _i(None, minimum=0),
            "name": _s("Input name."),
            "from": _s("Source node."),
            "output": _i(None, minimum=0, default=0),
        },
        ("from",),
        oneOf=[{"required": ["index"]}, {"required": ["name"]}],
    )


_NODES: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="node_find",
        description=(
            "Search a subtree for nodes (name and type globs, category, flags, has_errors). Rows: "
            "path, type, category, flags, input_count, child_count, has_errors. Locked HDAs are not"
            " entered unless recurse_locked. Paged by limit and cursor."
        ),
        input_schema=_obj(
            {
                "root": _s(None, default="/"),
                "pattern": _s("Name glob.", default="*"),
                "type": _s("Type name glob."),
                "category": _enum(CATEGORIES),
                "flags": _flags("locked"),
                "has_errors": {"type": "boolean"},
                "recurse_locked": _b(False),
                "limit": _limit(),
                "cursor": _cursor(),
            }
        ),
        read_only=True,
        examples=({"root": "/obj", "type": "*file*"}, {"has_errors": True, "limit": 20}),
    ),
    ToolSpec(
        name="node_info",
        description=(
            "Read nodes in detail: type, flags, inputs with names and sources, non-default parms "
            "(value, raw, expression; long strings elided), errors, warnings, cook state. parm_get "
            "reads keyframes, menus and templates; network_describe a whole network."
        ),
        notes=(
            "Default include: parms, inputs, errors, flags. Parm rows are name, value, raw (only "
            "when it differs), expression, keyed, locked, menu_token; strings over 200 characters "
            "come as {elided, head}. hda_locked is true at or inside a locked asset."
        ),
        input_schema=_obj(
            {
                "paths": _paths(),
                "include": _arr(
                    _enum(_NODE_INFO_SECTIONS), default=["parms", "inputs", "errors", "flags"]
                ),
                "include_defaults": _b(False),
                # §4.1: node_info does not descend into locked HDAs unless recurse_locked.
                "recurse_locked": _b(False),
            },
            ("paths",),
        ),
        output_schema=_out(
            {
                "nodes": {
                    "type": "array",
                    "items": _out(
                        {
                            "path": _t("string"),
                            "name": _t("string"),
                            "session_id": _t("integer"),
                            # {name, category, version, description, help_url}
                            "type": _t("object"),
                            "flags": _t("object"),
                            "inputs": _objs(),
                            "outputs": _objs(),
                            "parms": _objs(),
                            **_problems(),
                            "cook_state": _t("string"),
                            "children_count": _t("integer"),
                            "hda_locked": _t("boolean"),
                            "hda": _t(["object", "null"]),
                            "position": _list("number"),
                            "comment": _t("string"),
                            "color": _list("number"),
                        },
                        ("path", "type"),
                    ),
                }
            },
            ("nodes",),
        ),
        read_only=True,
        examples=(
            {"paths": ["/obj/geo1/box1"]},
            {"paths": ["/obj/geo1"], "include": ["children", "flags"]},
        ),
    ),
    ToolSpec(
        name="node_create",
        description=(
            "Create nodes in one undo step. type resolves like createNode (box gets the current "
            "version; exact_type disables). Items may wire to earlier items; a block_end pairs with"
            " its block_begin (paired_with). Returns path, type and problems per node. "
            "network_build suits whole graphs."
        ),
        notes=(
            "A parms value is a literal, {expression, language} (short form {expr, lang}), or any "
            "parm_set item without path. An input is {index or name, from, output (default 0)}. "
            "layout good_position places new nodes. return full gives node_info blocks listing only"
            " the parms the call set, with strings over 200 characters as {elided, head}; identical"
            " error lists after the first become errors_same_as."
        ),
        input_schema=_obj(
            {
                "items": _arr(
                    _obj(
                        {
                            "parent": _s(),
                            "type": _s(),
                            "name": _s(),
                            "parms": {
                                "type": "object",
                                "additionalProperties": _parm_value(),
                                "description": (
                                    "Parm name to a value or a parm_set item without path."
                                ),
                            },
                            "inputs": _arr(_input_link()),
                            "flags": _flags(),
                            "position": _xy("[x, y]"),
                        },
                        ("parent", "type"),
                    ),
                    minItems=1,
                ),
                "layout": _enum(("good_position", "none"), "good_position"),
                "exact_type": _b(False),
                "partial": _partial(),
                "return": _return(),
            },
            ("items",),
        ),
        examples=(
            {"items": [{"parent": "/obj", "type": "geo", "name": "terrain"}]},
            {
                "items": [
                    {
                        "parent": "/obj/terrain",
                        "type": "grid",
                        "parms": {"size": [10, 10], "rows": 100, "cols": 100},
                    },
                    {
                        "parent": "/obj/terrain",
                        "type": "mountain",
                        "inputs": [{"index": 0, "from": "/obj/terrain/grid1"}],
                        "parms": {"height": {"expression": "ch('../grid1/sizex') * 0.1"}},
                        "flags": {"display": True, "render": True},
                    },
                ]
            },
        ),
    ),
    ToolSpec(
        name="node_delete",
        description=(
            "Delete nodes in one undo step and return the deleted paths. keep_connections "
            "reconnects input 0 to the deleted node's outputs where possible, like deleting in the "
            "network editor."
        ),
        input_schema=_obj({"paths": _paths(), "keep_connections": _b(True)}, ("paths",)),
        destructive=True,
        examples=(
            {"paths": ["/obj/geo1/box1"]},
            {"paths": ["/obj/geo1"], "keep_connections": False},
        ),
    ),
    ToolSpec(
        name="node_edit",
        description=(
            "Change node properties in one undo step: rename, flags, bypass, color, comment, "
            "position, lock (false allows editing a locked HDA's contents). spare_parms adds {name,"
            " type: float|int|string|toggle|menu|button|vector|color, label, default, size, min, "
            "max, menu_items [{token, label}], value_type, folder, help} or removes spare parms by "
            "name. Menu value_type string (default): chs() gives the token; int: ch() gives the "
            "item index."
        ),
        notes=(
            "A rename returns old_path and path; spare_parms returns the added and removed parm "
            "paths. Only spare parms can be removed; a name already on the node fails with "
            "name_collision; nodes inside a locked asset are refused with locked. A folder label is"
            " created when missing. value_type is for menus only: string makes a menu parm whose "
            "value is the token (VEX chs(); ch() gives the item index); int makes an int parm with "
            "that menu whose value is the item index (ch() or chi(); chs() gives the index as "
            "text). A menu default is a token or an item index; a number that is no index but "
            'equals a token\'s text (-1 for token "-1") picks that token.'
        ),
        input_schema=_obj(
            {
                "items": _arr(
                    _obj(
                        {
                            "path": _s(),
                            "name": _s("New name."),
                            "flags": _flags(),
                            "color": _arr(
                                {"type": "number"}, "[r, g, b] 0-1", minItems=3, maxItems=3
                            ),
                            "comment": _s(),
                            "position": _xy("[x, y]"),
                            "lock": {"type": "boolean"},
                            "bypass": {"type": "boolean"},
                            # Review 11 B9; entries are validated by the host (parms.py).
                            "spare_parms": _obj(
                                {"add": _arr(_t("object")), "remove": _arr(_t("string"))}
                            ),
                        },
                        ("path",),
                    ),
                    minItems=1,
                ),
                "partial": _partial(),
            },
            ("items",),
        ),
        idempotent=True,
        examples=(
            {"items": [{"path": "/obj/geo1/box1", "name": "base_box"}]},
            {"items": [{"path": "/obj/geo1/null1", "color": [1, 0, 0], "comment": "OUT"}]},
            {
                "items": [
                    {
                        "path": "/obj/geo1/wrangle1",
                        "spare_parms": {
                            "add": [{"name": "glue", "type": "float", "default": 1, "max": 10}]
                        },
                    }
                ]
            },
        ),
    ),
    ToolSpec(
        name="node_copy",
        description=(
            "Copy nodes into to_parent, which may be their own network. names renames the copies in"
            " paths order; with_inputs keeps wiring among copied nodes; position_offset shifts "
            "them. Returns the new paths and per copy path, type and problems."
        ),
        notes=("return full adds flags to each row."),
        input_schema=_obj(
            {
                "paths": _paths(),
                "to_parent": _s(),
                "names": _arr({"type": "string"}),
                "with_inputs": _b(True),
                "position_offset": _xy("[dx, dy]"),
                "return": _return(),
            },
            ("paths", "to_parent"),
        ),
        examples=({"paths": ["/obj/geo1/box1"], "to_parent": "/obj/geo2"},),
    ),
    ToolSpec(
        name="node_connect",
        description=(
            "Wire inputs in one undo step: each item connects output from_output of from into to's "
            'to_input (an index, an input name, or "next" for the next free input of merge-style '
            "nodes); from null disconnects."
        ),
        notes=("A bad input fails with invalid_input, and the hint lists the node's input labels."),
        input_schema=_obj(
            {
                "items": _arr(
                    _obj(
                        {
                            "from": {
                                "type": ["string", "null"],
                                "description": "Source node or null.",
                            },
                            "from_output": _i(None, minimum=0, default=0),
                            "to": _s(),
                            # bible-silent: to_input default; 0 is the common case.
                            "to_input": {
                                "type": ["integer", "string"],
                                "default": 0,
                                "description": 'Index, input name, or "next".',
                            },
                        },
                        ("from", "to"),
                    ),
                    minItems=1,
                ),
                "partial": _partial(),
            },
            ("items",),
        ),
        idempotent=True,
        examples=(
            {"items": [{"from": "/obj/geo1/box1", "to": "/obj/geo1/merge1", "to_input": "next"}]},
            {"items": [{"from": None, "to": "/obj/geo1/xform1", "to_input": 0}]},
        ),
    ),
    ToolSpec(
        name="node_layout",
        description=(
            "Tidy a network. mode children lays out the children of parent, or only paths; "
            "good_position moves each node in paths to a free spot near its inputs."
        ),
        input_schema=_obj(
            {
                "parent": _s(),
                "paths": _arr({"type": "string"}, "Subset of children."),
                "mode": _enum(("children", "good_position"), "children"),
            },
            ("parent",),
        ),
        examples=({"parent": "/obj/geo1"},),
    ),
    ToolSpec(
        name="network_describe",
        description=(
            "Read a whole network as Houdini's hou.data childrenAsData (types, non-default parms, "
            "expressions, wiring, flags) to depth; data feeds network_build. format outline is a "
            "compact tree (type, display node, error count, input sources, flags that are on); "
            "python is asCode for one node. Locked HDAs stay closed unless recurse_locked. Pages "
            "end at the response budget (next_cursor)."
        ),
        notes=(
            "depth defaults to 1, and to 2 for outline. A locked HDA appears as {type, hda_locked}."
            " Outline rows: path, name, type, children_count (left out at 0), display, errors, "
            "inputs (source path per input slot, null for an empty slot before a wired one; left "
            'out when nothing is wired), flags (only the ones that are on, e.g. ["display", '
            '"render"]; left out when none), and hda_locked only for locked assets not shipped with'
            " Houdini. Truncated pages carry truncated and next_cursor."
        ),
        input_schema=_obj(
            {
                "root": _s(),
                "depth": _i(None, minimum=1),
                "include_defaults": _b(False),
                "include_positions": _b(False),
                "recurse_locked": _b(False),
                "format": _enum(("data", "python", "outline"), "data"),
                "cursor": _cursor(),
            },
            ("root",),
        ),
        read_only=True,
        examples=(
            {"root": "/obj/geo1"},
            {"root": "/obj/geo1", "depth": 2, "include_positions": True},
            {"root": "/", "format": "outline"},
        ),
    ),
    ToolSpec(
        name="network_build",
        description=(
            "Build or update a network under parent from Houdini's hou.data childrenAsData format "
            "(what network_describe returns) in one undo step. Types and inputs are validated "
            "first; dry_run stops there. Returns created paths and per node path, type and "
            "problems."
        ),
        notes=(
            "Input entries are {from, from_index, to_index}; a missing to_index is the entry's "
            "position in the list. return full adds flags. tag is stored as the userData "
            "hocuspocus:tag."
        ),
        input_schema=_obj(
            {
                "parent": _s(),
                # Inner shape is Houdini's own hou.data format (bible D6); left open on purpose.
                # setChildrenFromData itself puts inputs without to_index on input 0; the host
                # fills to_index from the list position first (bible §5.10).
                "data": {"type": "object", "description": "hou.data childrenAsData dict."},
                "on_name_collision": _enum(("error", "rename", "replace"), "error"),
                "layout": _b(True),
                "dry_run": _b(False),
                # bible §5.14: the only userData HocusPocus may write into a scene.
                "tag": _s("Stored as userData hocuspocus:tag."),
                "return": _return(),
            },
            ("parent", "data"),
        ),
        examples=(
            {
                "parent": "/obj/geo1",
                "data": {
                    "box1": {"type": "box"},
                    "sphere1": {"type": "sphere"},
                    "merge1": {
                        "type": "merge",
                        "inputs": [
                            {"from": "box1", "from_index": 0, "to_index": 0},
                            {"from": "sphere1", "from_index": 0, "to_index": 1},
                        ],
                        "flags": {"display": True},
                    },
                },
                "dry_run": True,
            },
        ),
    ),
)


# ---------------------------------------------------------------------------
# §4.5 Parms
# ---------------------------------------------------------------------------


def _key() -> dict[str, Any]:
    return _obj({"frame": _n(), "value": _n()}, ("value",))


_PARMS: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="parm_get",
        description=(
            "Read parms by parm (.../tx), tuple (.../t: all components) or component path: value at"
            " frame, raw if different, expression, is_default, locked (parm lock), hda_locked. "
            "Strings over 200 chars are {elided, head} unless full_strings. Tuples add "
            "per-component expressions and keyed names."
        ),
        notes=(
            "frame defaults to the current frame. template is {label, type, default, min, max, "
            "help}; menu items are capped at 50; keys is {count, first, last}. On a LOP a USD "
            "attribute name (.../inputs:intensity) reads Houdini's encoded parm "
            "(xn__inputsintensity_i0a), named in path and name."
        ),
        input_schema=_obj(
            {
                "paths": _paths("Parm or tuple paths."),
                "frame": _frame(),
                "include": _arr(
                    _enum(("keys", "menu", "template", "ramp", "multiparm")), default=[]
                ),
                "full_strings": _b(False),
            },
            ("paths",),
        ),
        output_schema=_out(
            {
                "parms": {
                    "type": "array",
                    "items": _out(
                        {
                            "path": _t("string"),
                            "name": _t("string"),
                            "tuple": _t("string"),
                            "component_names": _list(),
                            "type": _t("string"),
                            "value": {},
                            "raw": {},
                            "expression": _t("string"),
                            "language": _t("string"),
                            **_tuple_animation(),
                            "is_default": _t("boolean"),
                            "locked": _t("boolean"),
                            "hda_locked": _t("boolean"),
                            # {count, first, last}; per component for a tuple.
                            "keyframes": _t("object"),
                            "menu": _t("object"),
                            "ramp": _t("object"),
                            "multiparm": _t("object"),
                            "template": _t("object"),
                        },
                        ("path", "name", "value"),
                    ),
                }
            },
            ("parms",),
        ),
        read_only=True,
        examples=(
            {"paths": ["/obj/geo1/box1/size"]},
            {"paths": ["/obj/geo1/xform1/tx"], "frame": 24, "include": ["keys"]},
        ),
    ),
    ToolSpec(
        name="parm_set",
        description=(
            "Set parms in one undo step. Each item takes one of value, expression, keyframe(s), "
            "channel_ref, ramp, multiparm_count, revert_to_default, press. Tuple paths take lists, "
            "component paths scalars; menus take token or label. animation replace clears keys and "
            "expressions first; key keys at frame; keep is plain set. Returns value, raw, "
            "wrote_keyframe, node errors."
        ),
        notes=(
            "With animation replace a single keyframe only adds or replaces its own key. press "
            "clicks a button parm. raw is left out when it equals value, and long strings are "
            "elided as in parm_get. Tuples report per-component expressions and the keyed component"
            " names. Type mismatches fail with invalid_value naming the template type and range. "
            "On a LOP a USD attribute name (inputs:intensity) sets Houdini's encoded parm "
            "(xn__inputsintensity_i0a), here and in node_create parms; path is the resolved one."
        ),
        input_schema=_obj(
            {
                "items": _arr(
                    _obj(
                        {
                            "path": _s("Parm, tuple or component path."),
                            "value": _literal_value(),
                            "expression": _s(),
                            "language": _enum(("hscript", "python"), "hscript"),
                            "keyframe": _key(),
                            "keyframes": _arr(_key()),
                            "channel_ref": _s("Parm path to reference."),
                            "ramp": _obj(
                                {
                                    "basis": {
                                        "type": ["string", "array"],
                                        "items": {"type": "string"},
                                        "description": "One basis, or one per key.",
                                    },
                                    "keys": _arr({"type": "number"}),
                                    "values": _arr(
                                        {"type": ["number", "array"], "items": {"type": "number"}}
                                    ),
                                },
                                ("keys", "values"),
                            ),
                            "multiparm_count": _i(None, minimum=0),
                            "revert_to_default": {"type": "boolean"},
                            "press": {"type": "boolean", "description": "Press a button parm."},
                            "animation": _enum(("replace", "key", "keep"), "replace"),
                        },
                        ("path",),
                    ),
                    minItems=1,
                ),
                "frame": _frame(),
                "partial": _partial(),
            },
            ("items",),
        ),
        output_schema=_out(
            {
                "results": {
                    "type": "array",
                    "items": _out(
                        {
                            "path": _t("string"),
                            "value": {},
                            "raw": {},
                            "expression": _t("string"),
                            "language": _t("string"),
                            **_tuple_animation(),
                            "wrote_keyframe": _t("boolean"),
                            "is_default": _t("boolean"),
                            "errors": _list(),
                            "warnings": _list(),
                        },
                        ("path", "wrote_keyframe"),
                    ),
                }
            },
            ("results",),
        ),
        idempotent=True,
        examples=(
            {"items": [{"path": "/obj/geo1/box1/size", "value": [2, 1, 2]}]},
            {"items": [{"path": "/obj/geo1/xform1/ry", "expression": "$F * 3"}]},
            {
                "items": [
                    {
                        "path": "/obj/geo1/xform1/ty",
                        "keyframe": {"frame": 1, "value": 0},
                        "animation": "key",
                    }
                ]
            },
        ),
    ),
)


# ---------------------------------------------------------------------------
# §4.6 Cook, problems, geometry
# ---------------------------------------------------------------------------

_COOK: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="cook",
        description=(
            "Cook nodes and report per node ok, errors, warnings, cook_time_ms (its own cook; "
            "cached inputs are not recooked). profile force-cooks each input chain: chain (top 10 "
            "by cost), total_ms, attribution; for-each loop bodies show their cost over all "
            "iterations (loops). frame_range cooks frame by frame (sims advance); summary bbox adds"
            " per-frame bbox. Past the job threshold returns job_id for job."
        ),
        notes=(
            "frame_range is [start, end, step] and cannot be combined with profile or frame; the "
            "current frame is restored afterwards. Errors left from before a fix are rechecked "
            "unless the last cook took over 2 s (hint: force). With profile, results[].cook_time_ms"
            " is the named node's profiled cook. attribution is per_node, or perf_monitor when a "
            "block_end was cooked under Houdini's performance monitor: each loop body row then has "
            "in_loop, cooks, per_iteration_ms and cook_time_ms over all iterations, and loops lists"
            " {block_end, block_begin, iterations, total_ms}. loop-level means the monitor was "
            "unavailable (another profile was recording) and body rows show one standalone cook. "
            "total_ms counts each loop once, at its block_end. In a GUI session the profile stays "
            "in the Performance Monitor's list."
        ),
        input_schema=_obj(
            {
                "paths": _paths(),
                "force": _b(False),
                "frame": _frame(),
                "timeout_s": _n(None, minimum=1, default=30),
                "profile": _b(False),
                "frame_range": _arr({"type": "number"}, None, minItems=2, maxItems=3),
                "summary": _enum(("none", "bbox"), "none"),
            },
            ("paths",),
        ),
        output_schema=_out(
            {
                "ok": _t("boolean"),
                "chain": _objs(),
                "attribution": _t("string"),
                "loops": _objs(),
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
    ),
    ToolSpec(
        name="problems",
        description=(
            "Explain red nodes: lists nodes in a subtree with errors or warnings, broken channel "
            "references, missing files, unconnected required inputs; errored nodes changed since "
            "their last cook are recooked first. cook_uncooked cooks never-cooked nodes too. Paged "
            "by limit and cursor."
        ),
        notes=(
            "A TOP node with failed work items is a failed_work_items row with count, work_item "
            "{id, index} and the first item's error in message. "
            "Locked HDAs are skipped unless recurse_locked. A scan budget (10 s, or half of "
            "timeout_s) can end a page early with incomplete: true and a next_cursor that continues"
            " the walk without losing rows."
        ),
        input_schema=_obj(
            {
                "root": _s(None, default="/"),
                "include_warnings": _b(True),
                "cook_uncooked": _b(False),
                "recurse_locked": _b(False),
                "timeout_s": _n(None, minimum=1, default=30),
                "limit": _limit(),
                # §4.1: list tools take limit and cursor; the §4.6 row lists only limit.
                "cursor": _cursor(),
            }
        ),
        read_only=True,
        examples=({"root": "/obj/geo1"}, {"include_warnings": False, "cook_uncooked": True}),
    ),
    ToolSpec(
        name="geo_info",
        description=(
            "Summarise the geometry of a SOP (or an OBJ's display SOP) in about 1 KB: point, prim "
            "and vertex counts, bounding box, primitive types, attributes per class with type and "
            "size, detail attribute values, groups with counts. geo_read reads per-element values."
        ),
        input_schema=_obj({"path": _s("SOP or OBJ path."), "frame": _frame()}, ("path",)),
        output_schema=_out(
            {
                "path": _t("string"),
                "point_count": _t("integer"),
                "prim_count": _t("integer"),
                "vertex_count": _t("integer"),
                "bbox": _nullable(
                    _out({k: _list("number") for k in ("min", "max", "size", "center")})
                ),
                "prim_types": {"type": "object", "additionalProperties": _t("integer")},
                "attributes": _out({k: _objs() for k in ("point", "vertex", "prim", "detail")}),
                "groups": _out({k: _objs() for k in ("point", "prim", "edge", "vertex")}),
                "intrinsics": _t("object"),
            },
            ("point_count", "prim_count", "vertex_count"),
        ),
        read_only=True,
        examples=({"path": "/obj/geo1/OUT"}, {"path": "/obj/geo1", "frame": 1}),
    ),
    ToolSpec(
        name="geo_read",
        description=(
            "Read attribute values like the geometry spreadsheet: count rows of one class from "
            "start, with a columns header, optionally within group. stats adds min/max/mean and "
            "unique strings over the whole class. Page by passing next_cursor as cursor."
        ),
        input_schema=_obj(
            {
                "path": _s("SOP or OBJ path."),
                # bible-silent: class default; point matches the spreadsheet's default.
                "class": _enum(("point", "prim", "vertex", "detail"), "point"),
                "attribs": _arr({"type": "string"}),
                "start": _i(None, minimum=0, default=0),
                "count": _i(None, minimum=1, maximum=10000, default=50),
                "group": _s(),
                "stats": _b(False),
                # §4.1: cursors are opaque strings everywhere; overrides start.
                "cursor": _cursor(),
            },
            ("path",),
        ),
        output_schema=_out(
            {
                "path": _t("string"),
                "class": _t("string"),
                "columns": _list(),
                "rows": {"type": "array", "items": {"type": "array"}},
                "start": _t("integer"),
                "total": _t("integer"),
                "next_cursor": _t("string"),
                "truncated": _t("boolean"),
                "stats": _t("object"),
            },
            ("columns", "rows", "total"),
        ),
        read_only=True,
        examples=(
            {"path": "/obj/geo1/OUT", "attribs": ["P", "Cd"], "count": 10},
            {"path": "/obj/geo1/OUT", "class": "prim", "stats": True},
        ),
    ),
)


# ---------------------------------------------------------------------------
# §4.7 Visual feedback, code, types, state, contexts
# ---------------------------------------------------------------------------

_VISUAL: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="viewport_capture",
        description=(
            "Look at /obj or a LOP stage: a PNG (long side at most 1024), path, size, "
            "camera_used, scene. camera: OBJ or LOP camera, or camera prim (lop_path). auto: the "
            "GUI viewer if present and no camera, else an OpenGL ROP (headless too) framed per "
            "fit. Leaves no nodes, undo step or dirty flag."
        ),
        notes=(
            "fit none reuses the last framing. The viewer source captures the view as it is unless "
            "fit is passed: then it frames all or selected for the grab and puts the view back, as "
            "it does after looking through camera; context is the viewer's network, and notes say "
            "when that is not the captured scene. Without camera or lop_path the stage's display "
            "LOP is captured when /obj displays nothing; otherwise a note names it. A stage renders "
            "through the OpenGL ROP's LOP source (scene: stage, lop_path). Lights are refused as "
            "cameras; camera errors list the scene's cameras. path also writes the PNG there. Both "
            "files are "
            "opaque, on the same grey as the image (the OpenGL ROP itself writes a transparent "
            "background). image.attached is true when the PNG went out as MCP image content."
        ),
        input_schema=_obj(
            {
                "camera": _s(),
                "lop_path": _s(),
                "frame": _frame(),
                "resolution": _arr(
                    {"type": "integer", "minimum": 16}, minItems=2, maxItems=2, default=[1024, 768]
                ),
                "fit": _enum(("all", "selected", "none"), "all"),
                "source": _enum(("auto", "viewer", "opengl_rop"), "auto"),
                "path": _s("Also write the PNG here (must end in .png)."),
            }
        ),
        output_schema=_out(
            {
                "image": _image(),
                "path": _t("string"),
                "width": _t("integer"),
                "height": _t("integer"),
                "camera_used": _t("string"),
                "scene": _t("string"),
                "source_used": {"type": "string", "enum": ["viewer", "opengl_rop"]},
                "frame": _t("number"),
                "rendered": _list("integer"),
                "also_written": _t("string"),
                "fit_used": _t("string"),
                "notes": _list(),
            },
            ("path", "width", "height"),
        ),
        # Not read_only: in the GUI the opengl_rop source creates a temporary camera and ROP
        # (deleted afterwards, outside undo) and Houdini may mark the hip modified (§4.7).
        idempotent=True,
        examples=({}, {"camera": "/obj/cam1", "frame": 48, "source": "opengl_rop"}),
    ),
    ToolSpec(
        name="render",
        description=(
            "Render any ROP (Karma, Mantra, OpenGL, ...) for frames [start, end, inc] (default "
            "current frame), optionally overriding output. Waits up to wait_s (default the job "
            "threshold): if done, returns outputs, a thumbnail image and notes; else job_id and "
            "state to poll with job."
        ),
        notes=(
            "Above 5 outputs only outputs_summary is inline; job result lists them all. Every "
            "expected output is checked against approved_roots. viewport_capture is the quick look."
            " notes warn when the scene has no lights and when the thumbnail is nearly black. "
            "thumbnail.image.attached is true when the image went out as MCP image content. The "
            "thumbnail is inline only, flattened onto grey; the ROP's own output files are left as "
            "written, alpha included. USD render ROPs (Lop usdrender_rop, Driver usdrender): "
            "outputs come from outputimage, else the RenderProduct productName of the render "
            "settings the ROP uses (EXR thumbnails too), never lopoutput; output overrides "
            "outputimage; a note says when nothing resolves; a husk failure carries the end of "
            "its log in detail.log_tail."
        ),
        input_schema=_obj(
            {
                "rop_path": _s(),
                "frames": _arr(
                    {"type": "number"}, "[start, end] or [start, end, inc]", minItems=2, maxItems=3
                ),
                "output": _s("Output path override."),
                "wait_s": _n(None, minimum=0),
                "thumbnail": _b(True),
            },
            ("rop_path",),
        ),
        output_schema=_out(
            {
                "job_id": _t("string"),
                "state": {"type": "string", "enum": _JOB_STATES},
                "rop_path": _t("string"),
                "frames": _list("number"),
                "outputs": _list(),
                "outputs_summary": _t("object"),
                "missing": _list(),
                "thumbnail": _out(
                    {
                        "path": _t("string"),
                        "width": _t("integer"),
                        "height": _t("integer"),
                        "image": _image(),
                    }
                ),
                "thumbnail_error": _t("string"),
                "notes": _list(),
            },
            ("job_id", "state"),
        ),
        examples=(
            {"rop_path": "/out/karma1"},
            {"rop_path": "/out/karma1", "frames": [1, 24], "wait_s": 0},
        ),
    ),
    ToolSpec(
        name="houdini_python",
        description=(
            "Run Python (hou bound) or HScript on Houdini's main thread in one undo step, for "
            "anything no tool covers. Returns stdout, stderr and result. An uncaught exception "
            "fails with python_exception and is rolled back; code still running near timeout_s is "
            "stopped (houdini_busy)."
        ),
        notes=(
            "result is the value of a trailing expression or a result variable, JSON-serialised "
            "(repr fallback). sys.exit counts as an uncaught exception; stdout, stderr and the "
            "traceback are in detail. Output is capped at the response budget (truncated). Fails "
            "with python_disabled when turned off."
        ),
        input_schema=_obj(
            {
                "code": _s(),
                "timeout_s": _n(None, minimum=1, default=30),
                "language": _enum(("python", "hscript"), "python"),
                "undo_label": _s(),
            },
            ("code",),
        ),
        destructive=True,
        examples=(
            {"code": "len(hou.node('/obj').children())"},
            {"code": "opls /obj", "language": "hscript"},
        ),
    ),
    ToolSpec(
        name="node_type_search",
        description=(
            "Find node types by name, label, description or keyword, in all 18 categories or one. "
            "Rows: name, label, category, version, description (clipped), input range, deprecated. "
            "Current versions only, older ones named in other_versions, unless current_only is "
            "false. Exact names rank first; total counts every match, weak keyword matches "
            "included."
        ),
        notes=(
            "total is the real number of matching types, not a cap: a plain-language query also "
            "matches on single description words, so broad queries can match hundreds of types. "
            "Raise limit (up to 1000) to see them all."
        ),
        input_schema=_obj(
            {
                "query": _s(),
                "category": _enum(CATEGORIES),
                "limit": _limit(20),
                "include_hidden": _b(False),
                "current_only": _b(True),
            },
            ("query",),
        ),
        output_schema=_out(
            {
                "results": {
                    "type": "array",
                    "items": _out(
                        {
                            "name": _t("string"),
                            "label": _t("string"),
                            "category": _t("string"),
                            "version": _t("string"),
                            "description": _t("string"),
                            "other_versions": _list(),
                        },
                        ("name", "category"),
                    ),
                },
                "total": _t("integer"),
            },
            ("results",),
        ),
        read_only=True,
        examples=({"query": "scatter"}, {"query": "noise", "category": "Vop", "limit": 5}),
    ),
    ToolSpec(
        name="node_type_info",
        description=(
            "Describe one node type: label, version, named inputs and outputs, parms by folder. "
            "detail compact gives name, label, type, default rows; full adds size, range, menu and "
            "folder; folders lists folders with parm counts. folder and parms (globs, a|b) narrow "
            "the parms."
        ),
        notes=(
            'folder takes a label, an "A / B" path, or "" / "(no folder)" for the top-level parms. '
            "include_help adds the first ~2 KB of the node help. With folder or parms the inputs "
            "list becomes inputs_count, and detail full leaves out the folder list."
        ),
        input_schema=_obj(
            {
                "type": _s("Sop/scatter, or scatter with category."),
                "category": _enum(CATEGORIES),
                "include_parms": _b(True),
                "include_help": _b(False),
                "folder": _s(),
                "parms": _s("Name or label glob, e.g. *seed* or dist|inset."),
                "detail": _enum(("compact", "full", "folders"), "compact"),
            },
            ("type",),
        ),
        read_only=True,
        examples=(
            {"type": "Sop/scatter"},
            {"type": "Sop/scatter", "parms": "*seed*"},
            {"type": "Sop/rbdmaterialfracture", "detail": "folders"},
        ),
    ),
)

_STATE: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="undo",
        description=(
            "Undo or redo steps (default 1) and return the labels performed, or list the last 20 "
            "undo labels with history. Every HocusPocus mutation is one step labelled "
            '"HocusPocus: <tool> ...".'
        ),
        input_schema=_obj(
            {
                "action": _enum(("undo", "redo", "history")),
                "steps": _i(None, minimum=1, default=1),
                "include_user_steps": _b(False),
            },
            ("action",),
        ),
        notes=(
            "undo and redo stop at the first step whose label does not start with "
            "\"HocusPocus:\" (the user's or Houdini's own) and name it in blocked_by; "
            "include_user_steps: true crosses such steps and lists them in user_steps."
        ),
        output_schema=_out(
            {
                "performed": _list(),
                "history": _list(),
                "redo": {"type": "array", "items": _t("string"), "description": "history only."},
                "enabled": _t("boolean"),
                "next_undo": _t(["string", "null"]),
                "next_redo": _t(["string", "null"]),
                "undo_count": _t("integer"),
                "redo_count": _t("integer"),
                "dirty": _t("boolean"),
                "scene_generation": _t("integer"),
                "note": _t("string"),
                "blocked_by": _t("string"),
            }
        ),
        # Registered scene=False (performUndo raises inside an undo group); not idempotent.
        examples=({"action": "history"}, {"action": "undo", "steps": 2}),
    ),
    ToolSpec(
        name="time",
        description=(
            "Read or set playbar time. With no arguments returns frame, fps and range. frame sets "
            "the current frame, range [start, end] the frame range, fps the frame rate."
        ),
        input_schema=_obj(
            {
                "frame": _n(),
                "range": _arr({"type": "number"}, "[start, end]", minItems=2, maxItems=2),
                "fps": _n(None, minimum=1),
            }
        ),
        output_schema=_out(
            {"frame": _t("number"), "fps": _t("number"), "range": _list("number")},
            ("frame", "fps", "range"),
        ),
        # Not read_only: setting changes the scene. Reads must not dirty it, so the host
        # registers time with scene=False and marks dirty itself (§4.1).
        idempotent=True,
        examples=({}, {"frame": 24}, {"range": [1, 120], "fps": 24}),
    ),
    ToolSpec(
        name="selection",
        description=(
            "Read or set the node selection. Omit paths to get the selected node paths; pass paths "
            "to select exactly those (an empty list clears the selection)."
        ),
        input_schema=_obj({"paths": _arr({"type": "string"})}),
        output_schema=_out({"selected": _list()}, ("selected",)),
        idempotent=True,
        examples=({}, {"paths": ["/obj/geo1/box1"]}),
    ),
    ToolSpec(
        name="job",
        description=(
            "Long work from render, cook or pdg: status (state, progress, message, elapsed_s), "
            "result (the tool's result once done), cancel, list."
        ),
        notes=(
            "Jobs do not survive a Houdini restart. "
            "A pdg cook job counts the work items of the whole graph in current/total and adds "
            "nodes: {name: 'finished/total'}. A cancelled job's result is the cancelled error, "
            "whose detail holds the last status."
        ),
        input_schema=_obj(
            {
                "action": _enum(("status", "result", "cancel", "list")),
                "job_id": _s("Required except for list."),
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
        examples=({"action": "status", "job_id": "j-3f2a"}, {"action": "list"}),
    ),
)

_FULL: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="hda",
        description=(
            "Digital assets: create turns subnet path into an HDA; save updates the definition from"
            " path, spare parms included; unlock allows editing; match reverts to the definition "
            "and locks; install and reload take library_path; list shows loaded libraries or "
            "library_path's definitions."
        ),
        notes=(
            "create takes name, label (or description), version, library_path and optional "
            "min_inputs/max_inputs. save copies the instance's spare parms into the asset's "
            "interface (promoted lists them; promote_spare_parms: false keeps them on the "
            "instance). list is paged by limit and cursor; install of a loaded library says "
            "already_loaded. node_type_info and node_type_search report the definition's version "
            "and, without help, its label as description."
        ),
        input_schema=_obj(
            {
                "action": _enum(("create", "save", "unlock", "match", "install", "reload", "list")),
                "path": _s("Node path."),
                "library_path": _s(".hda file."),
                "name": _s("Type name."),
                "label": _s(),
                # Houdini's own name for the label (createDigitalAsset description=).
                "description": _s("Same as label."),
                "version": _s(),
                "min_inputs": _i(None, minimum=0, maximum=9999),
                "max_inputs": _i(None, minimum=0, maximum=9999),
                "promote_spare_parms": _b(True),
                "limit": _limit(),
                "cursor": _cursor(),
            },
            ("action",),
        ),
        # Registered scene=False: list must not open an undo group or dirty the scene; the
        # mutating actions open their own group (§4.1).
        profile="full",
        examples=(
            {
                "action": "create",
                "path": "/obj/geo1/subnet1",
                "name": "studio::rock",
                "library_path": "C:/hda/rock.hda",
            },
            {"action": "list"},
        ),
    ),
    ToolSpec(
        name="usd_stage",
        description=(
            "Read a LOP's USD stage: prims (path, type) under prim (path or glob) to depth; "
            "include adds attributes (attribs: name glob), xform, bindings, layers. summary: "
            "type counts, world bbox. Paged (limit, cursor)."
        ),
        notes=(
            "time is a time code (default the current frame). prim globs: * within a path "
            "segment, ** across segments; matches are listed with their subtrees to depth. "
            "Attribute values are authored values at time; arrays up to 4 elements (8 for "
            "strings and tokens) are listed in full, longer ones as {len, first}. xform gives "
            "local, and world only when it differs. total is on every page (counted up to "
            "100000, then total_capped). summary returns {total_prims, counts_by_type, "
            "bbox_world: {min, max, size}} for the whole subtree (default and render purposes). "
            "A render ROP in a LOP network has no stage: the error names its input."
        ),
        input_schema=_obj(
            {
                "lop_path": _s(),
                "prim": _s(None, default="/"),
                "depth": _i(None, minimum=1, default=1),
                "include": _arr(_enum(("attributes", "xform", "bindings", "layers")), default=[]),
                "attribs": _s(),
                "summary": _b(False),
                "time": _n(),
                "limit": _limit(),
                # §4.1: list tools take limit and cursor.
                "cursor": _cursor(),
            },
            ("lop_path",),
        ),
        read_only=True,
        profile="full",
        examples=(
            {"lop_path": "/stage/OUT"},
            {"lop_path": "/stage/OUT", "prim": "/geo", "depth": 3, "include": ["attributes"]},
        ),
    ),
    ToolSpec(
        name="pdg",
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
        profile="full",
        examples=(
            {"action": "cook", "top_path": "/tasks/topnet1/ropfetch1"},
            {"action": "workitems", "top_path": "/tasks/topnet1/ropfetch1", "limit": 20},
        ),
    ),
    ToolSpec(
        name="events",
        description=(
            "What changed since your last call: hip, node (created, renamed, deleted, parms or "
            "flags changed on nodes HocusPocus touched or read) and pdg events with seq and "
            "origin (agent|other). Pass the last seq seen as since."
        ),
        notes=(
            "Watched nodes: those HocusPocus created, edited, read with node_info or listed with"
            " network_describe, and nodes created directly under /obj, /stage, /mat, /out and "
            "/tasks. FlagChanged has detail.flags (flag: new value); a spare parm edit is one "
            "SpareParmsChanged; hda create, match and unlock are one hda_contents_rebuilt per "
            "asset; kind pdg has detail.event cook_start, work_item_failed (id, index, error) or"
            " cook_done (ok, states, cancelled). A call that fails and is rolled back records "
            "nothing, nor does a node created and deleted within one call, a tool's own "
            "set-and-restore, or Houdini's save-time writes on TOP networks."
        ),
        input_schema=_obj({"since": _i(None, minimum=0, default=0), "limit": _limit()}),
        read_only=True,
        profile="full",
        examples=({}, {"since": 42, "limit": 20}),
    ),
)


TOOLS: tuple[ToolSpec, ...] = (
    *_SESSION,
    *_HIP,
    *_NODES,
    *_PARMS,
    *_COOK,
    *_VISUAL,
    *_STATE,
    *_FULL,
)
"""All tools, in the order of BIBLE §4.2–§4.7 (deterministic ``tools/list``)."""


def get(name: str) -> ToolSpec | None:
    for spec in TOOLS:
        if spec.name == name:
            return spec
    return None


def for_profile(profile: Profile) -> tuple[ToolSpec, ...]:
    if profile == "full":
        return TOOLS
    return tuple(spec for spec in TOOLS if spec.profile == "core")

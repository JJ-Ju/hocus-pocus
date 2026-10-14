"""Schema helpers and the :class:`ToolSpec` record shared by every spec module.

Stdlib only (the host imports the catalogue inside Houdini). Every builder returns a fresh
dict. Schemas are JSON Schema 2020-12. ``$schema`` is omitted from each schema because MCP
defines 2020-12 as the default dialect and the bytes count against the tools/list cap.
Output schemas never set ``additionalProperties: false`` and only require keys present
in every successful result, so the host may add fields without breaking clients.

Choices made where the bible is silent are marked ``# bible-silent:``; arguments added
from a §4.1 convention that a §4.x table row omits are marked ``# §4.1:``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from ..profiles import COMPAT_1X, PROFILES, PROFILES_2X  # noqa: F401 - re-exported

Profile = Literal["minimal", "core", "full", "compat_1x"]

HP_RPC_VERSION = 1
"""Host RPC contract version (the ``v1`` in ``/hp/v1/...``)."""

TOOLS_LIST_MAX_BYTES = 48_000
"""Hard cap on model-visible ``tools/list`` text (≈12k tokens). Enforced by a unit test."""

DESCRIPTION_MAX_WORDS = 60
"""1.2 (BIBLE §4.1): argument-level detail goes in ``ToolSpec.notes``, not the description."""

ARGUMENT_DESCRIPTION_MAX_WORDS = 12
"""1.3 (BIBLE §4.1): an argument's schema ``description`` is a short phrase; anything longer
(shapes, edge cases, interactions) goes in the spec's ``notes``, outside ``tools/list``."""


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
    profiles: tuple[Profile, ...] = ()
    """The profiles that list this tool (spec-2.0 §2, §8; ``hocuspocus.tools.profiles``):
    its 2.0 profiles, a suffix of ``("minimal", "core", "full")`` since they nest, plus
    ``"compat_1x"`` for a 1.4 tool. A 1.4 tool that 2.0 removes is ``("compat_1x",)``
    and names its replacement in ``hocuspocus.tools.migration``; a 2.0-only tool has no
    ``compat_1x``. A unit test checks every spec against these rules."""
    headless_ok: bool = True
    bridge_local: bool = False
    """True when the bridge answers this tool itself (``houdini_status``, ``houdini_connect``)."""
    examples: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    """Example argument objects; rendered into docs/tools.md and validated by a unit test."""
    v2_extra: dict[str, Any] = field(default_factory=dict)
    """What the 2.0 profiles add to a 1.4 tool (spec-2.0 §2.1, §2.5): ``{"input": overlay,
    "output": overlay}``, each a partial schema deep-merged into ``input_schema`` /
    ``output_schema`` (dicts merge key by key, anything else replaces) by
    ``catalog.for_profile`` for every 2.0 profile. ``compat_1x`` lists the spec without it,
    so its ``tools/list`` bytes stay those of 1.4's ``full``; the argument's detail goes in
    ``notes``. A 2.0-only tool never needs one."""

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

ROLES: tuple[str, ...] = ("editor", "worker")
"""Instance roles (spec-2.0 §2.1, §3): ``editor`` by default for a GUI Houdini, ``worker``
for a headless one; ``houdini_connect {role}`` changes it."""


def _on() -> dict[str, Any]:
    """``on`` (v2): the instance a ``cook``/``render``/``job``/``look`` call runs on."""
    return {"type": ["integer", "string"], "description": "Instance to run on: pid, name or role."}


def _v2_on() -> dict[str, Any]:
    """The ``v2_extra`` of a tool that accepts ``on``."""
    return {"input": {"properties": {"on": _on()}}}


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


def _on_unsaved() -> dict[str, Any]:
    return _enum(("fail", "save", "discard"), "fail")


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


def _key() -> dict[str, Any]:
    return _obj({"frame": _n(), "value": _n()}, ("value",))

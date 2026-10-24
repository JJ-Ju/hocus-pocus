"""The 1.4 tools 2.0 replaced, and what replaces each (spec-2.0 §2.4, §8). Stdlib only.

2.0 served them in the ``compat_1x`` profile only; 2.1 removed that profile and their
specs (BIBLE §13, D46). This table is kept as data: both the host's refusal and the
bridge's unknown-tool answer read it, so a 1.4 name always answers ``invalid_argument``
with its 2.0 replacement in ``hint`` (:func:`removed_error`). The read engines behind
``inspect`` and ``search`` keep the 1.4 names as host functions; none is a tool.

It is also the one mapping every error hint and message goes through when it names a tool
(review 25 papercut 1): :func:`hint_tool` renders the 2.0 call for a 1.4 name (``node_find
{root}`` is ``search {kind: "nodes", root}``) and leaves out a clause whose tool the call's
profile does not serve (``cook`` on ``minimal``). The host learns the call's profile from
the request envelope and wraps the call in :func:`using_profile`; the bridge passes its
own.
"""

from __future__ import annotations

import contextlib
import contextvars
import json
from collections.abc import Iterator
from typing import Any

from .errors import ToolError
from .profiles import DEFAULT_PROFILE, normalize

REPLACEMENTS: dict[str, str] = {
    "node_find": "search kind: nodes",
    "node_info": "inspect what: node",
    "node_delete": "edit op: delete",
    "node_edit": "edit op: node",
    "node_copy": "edit op: copy",
    "node_connect": "edit op: connect",
    "node_layout": "edit op: layout",
    "network_describe": "inspect what: network (or what: outline)",
    "network_build": "edit op: build",
    "parm_get": "inspect what: parms",
    "problems": "inspect what: problems",
    "geo_info": "inspect what: geo",
    "geo_read": "inspect what: geo with rows: true",
    "viewport_capture": "look (quality: draft | lit | final; source: viewer for the GUI view)",
    "node_type_search": "search kind: types",
    "node_type_info": "inspect what: type",
    "selection": "edit op: select to set it (houdini_python hou.selectedNodes() reads it)",
    "usd_stage": "inspect what: stage",
}
"""Removed 1.4 tool -> its 2.0 replacement, in 1.4 catalogue order (BIBLE Appendix A,
``docs/migration-2.0.md`` §1)."""


def replacement(tool: str) -> str | None:
    """The 2.0 replacement of a removed 1.4 tool, or ``None``."""
    return REPLACEMENTS.get(tool)


REMOVED_IN = "2.1"
"""The release that removed the 1.4 tools, with the ``compat_1x`` profile."""


def hint(tool: str, profile: str | None = None) -> str | None:
    """The hint for a removed 1.4 tool, or ``None`` for any other name. The ``selection``
    note names ``houdini_python`` only where ``profile`` serves it (``minimal`` does not)."""
    use = REPLACEMENTS.get(tool)
    if use is None:
        return None
    if tool == "selection" and profile is not None and not served("houdini_python", profile):
        use = use.split(" (", 1)[0]
    return f"Use {use}. docs/migration-2.0.md maps every 1.4 call to its 2.0 form."


def removed_error(tool: str, profile: str) -> ToolError:
    """The ``invalid_argument`` a removed 1.4 tool answers with, on every profile."""
    return ToolError(
        "invalid_argument",
        f"{tool} is a 1.4 tool; HocusPocus {REMOVED_IN} removed it.",
        hint=hint(tool, profile),
        detail={"tool": tool, "replacement": REPLACEMENTS.get(tool), "profile": profile},
    )


# -- profile-aware hints (review 25 papercut 1) ------------------------------------------

HINT_FORMS: dict[str, tuple[str, dict[str, Any], dict[str, str]]] = {
    "node_find": ("search", {"kind": "nodes"}, {"type": "query"}),
    "node_info": ("inspect", {"what": "node"}, {"paths": "target", "path": "target"}),
    "node_delete": ("edit", {"op": "delete"}, {}),
    "node_edit": ("edit", {"op": "node"}, {}),
    "node_copy": ("edit", {"op": "copy"}, {}),
    "node_connect": ("edit", {"op": "connect"}, {}),
    "node_layout": ("edit", {"op": "layout"}, {}),
    "network_describe": ("inspect", {"what": "network"}, {"root": "target"}),
    "network_build": ("edit", {"op": "build"}, {}),
    "parm_get": ("inspect", {"what": "parms"}, {"paths": "target", "path": "target"}),
    "problems": ("inspect", {"what": "problems"}, {"root": "target"}),
    "geo_info": ("inspect", {"what": "geo"}, {"path": "target"}),
    "geo_read": ("inspect", {"what": "geo", "rows": True}, {"path": "target"}),
    "viewport_capture": ("look", {}, {"lop_path": "target", "cop_path": "target"}),
    "node_type_search": ("search", {"kind": "types"}, {}),
    "node_type_info": ("inspect", {"what": "type"}, {"type": "target"}),
    "selection": ("edit", {"op": "select"}, {}),
    "usd_stage": ("inspect", {"what": "stage"}, {"lop_path": "target"}),
    "node_create": ("edit", {"op": "create"}, {}),
    "parm_set": ("edit", {"op": "set"}, {}),
}
"""1.4 tool -> ``(2.0 tool, fixed arguments, 1.4 argument -> 2.0 argument)``: the call a
hint names for it (:func:`hint_tool`). ``node_create`` and ``parm_set`` stay in
every profile, but a hint about one op names the ``edit`` op it maps to, which is what an
agent writes. ``edit`` forms render as ``edit {ops: [{op: ..., ...}]}``."""

BATCH_TOOLS = frozenset({"node_create", "parm_set", "node_edit", "node_connect"})
"""1.4 tools whose arguments are one item of ``items``: a hint renders ``{items: [...]}``."""

BARE: Any = None
"""An argument value :func:`hint_tool` renders as a bare key (``{path}``): the agent fills
it in."""

_PROFILE: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "hocuspocus_hint_profile", default=None
)


def current_profile() -> str:
    """The profile of the call being answered (:func:`using_profile`): the bridge's, sent in
    the host envelope, else the host's own. ``full`` outside a call (unit code, a thread
    started without the call's context)."""
    return _PROFILE.get() or "full"


@contextlib.contextmanager
def using_profile(profile: Any) -> Iterator[str]:
    """Answer hints for ``profile`` inside the block (aliases resolved; an unknown name is
    the default). The host's dispatcher wraps every call in it; the executor and the job
    manager carry it to the main thread and to job threads (``contextvars``)."""
    resolved = normalize(profile) or DEFAULT_PROFILE
    token = _PROFILE.set(resolved)
    try:
        yield resolved
    finally:
        _PROFILE.reset(token)


def served(tool: str, profile: str | None = None) -> bool:
    """Whether ``profile`` (default: :func:`current_profile`) lists ``tool``."""
    from .catalog import for_profile  # lazily: the host's config imports this module early

    return any(spec.name == tool for spec in for_profile(profile or current_profile()))


def _value(value: Any) -> str:
    if isinstance(value, dict):
        return _render(value)
    if isinstance(value, list):
        return "[" + ", ".join(_value(v) for v in value) + "]"
    return json.dumps(value, ensure_ascii=False)


def _render(args: dict[str, Any]) -> str:
    """``{a: "x", b}``: JSON values, bare keys, and a bare key for :data:`BARE`."""
    parts = [key if value is BARE else f"{key}: {_value(value)}" for key, value in args.items()]
    return "{" + ", ".join(parts) + "}"


def hint_tool(tool: str, profile: str | None = None, /, **args: Any) -> str | None:
    """The call a hint or message names for ``tool`` on ``profile`` (default: the current
    call's), with ``args`` in ``tool``'s own 1.4 argument names (:data:`BARE` renders a
    bare key). A 1.4 tool becomes its 2.0 form (:data:`HINT_FORMS`):
    ``hint_tool("node_find", "core", root="/obj")`` is ``search {kind: "nodes", root:
    "/obj"}``. Without ``args`` a tool renders as its bare name. ``None`` when the profile
    serves neither ``tool`` nor its replacement (``cook`` on ``minimal``), so the caller
    leaves that clause out (:func:`hint_join`)."""
    resolved = normalize(profile or current_profile()) or DEFAULT_PROFILE
    form = HINT_FORMS.get(tool)
    if form is not None:
        name, fixed, renames = form
        if not served(name, resolved):
            return None
        mapped = dict(fixed)
        for key, value in args.items():
            key = renames.get(key, key)
            if key == "target" and isinstance(value, list) and len(value) == 1:
                value = value[0]  # node_info {paths: [p]} -> inspect {target: p}
            mapped[key] = value
        if name == "edit":
            return f"edit {{ops: [{_render(mapped)}]}}"
        return f"{name} {_render(mapped)}"
    if not served(tool, resolved):
        return None
    if args and tool in BATCH_TOOLS:
        return f"{tool} {{items: [{_render(args)}]}}"
    return f"{tool} {_render(args)}" if args else tool


def hint_join(*parts: str | None, sep: str = " ") -> str:
    """``parts`` without the ``None`` ones (clauses whose tool the profile lacks)."""
    return sep.join(part for part in parts if part)

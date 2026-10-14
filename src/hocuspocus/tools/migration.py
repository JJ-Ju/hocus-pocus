"""The 1.4 tools 2.0 removes from its profiles, and what replaces each (spec-2.0 §2.4, §8).
Stdlib only. The one table both the host's refusal and the bridge's unknown-tool answer
read, so a 1.4 name called on a 2.0 profile always names its 2.0 replacement.

The removed tools stay implemented and are listed by ``compat_1x`` only (their specs'
``profiles`` is ``("compat_1x",)``); a unit test checks this table names exactly those.
"""

from __future__ import annotations

from .errors import ToolError
from .profiles import COMPAT_1X

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
"""Removed 1.4 tool -> its 2.0 replacement, in 1.4 catalogue order."""


def replacement(tool: str) -> str | None:
    """The 2.0 replacement of a removed 1.4 tool, or ``None``."""
    return REPLACEMENTS.get(tool)


def hint(tool: str) -> str | None:
    """The hint a 2.0 profile gives for a removed 1.4 tool, or ``None`` for any other name."""
    use = REPLACEMENTS.get(tool)
    if use is None:
        return None
    return (
        f"In 2.0 use {use}. A 1.4 client script can keep calling {tool} with "
        f'profile = "{COMPAT_1X}" in hocuspocus.toml (or HOCUSPOCUS_PROFILE={COMPAT_1X}) for '
        "the 2.0.x releases."
    )


def removed_error(tool: str, profile: str) -> ToolError:
    """The ``invalid_argument`` a 2.0 profile answers a removed 1.4 tool with."""
    return ToolError(
        "invalid_argument",
        f"{tool} is a 1.4 tool that the 2.0 {profile} profile does not serve.",
        hint=hint(tool),
        detail={"tool": tool, "replacement": REPLACEMENTS.get(tool), "profile": profile},
    )

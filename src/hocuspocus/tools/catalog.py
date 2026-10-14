"""The HocusPocus tool catalogue: the single source of truth for the tool surface.

Stdlib only. Imported by the host (inside Houdini) to map names to implementations,
by the bridge (outside Houdini) to register MCP tools, and by the docs generator.
See docs/BIBLE.md §3.5 and §4.

Profiles nest, smallest first: ``minimal ⊂ core ⊂ full ⊂ v2``. ``v2`` (spec-2.0 §7 M1)
is ``full`` plus the 2.0 tools (spec ``profile="v2"``), served alongside the 1.4 names.

2.0 (spec-2.0 §5.1): each tool is defined in its own module under
``hocuspocus/tools/spec/`` (``spec/<tool>.py`` exports ``SPEC``), built with the schema
helpers in ``spec/_helpers.py``. This module is the loader: it re-exports the specs in
catalogue order and owns the profile membership.
"""

from __future__ import annotations

import copy
import dataclasses

from .spec import TOOLS
from .spec._helpers import (
    ARGUMENT_DESCRIPTION_MAX_WORDS,
    CATEGORIES,
    DESCRIPTION_MAX_WORDS,
    HP_RPC_VERSION,
    PROFILES,
    TOOLS_LIST_MAX_BYTES,
    Profile,
    ToolSpec,
)

__all__ = [
    "ARGUMENT_DESCRIPTION_MAX_WORDS",
    "CATEGORIES",
    "DESCRIPTION_MAX_WORDS",
    "HP_RPC_VERSION",
    "MINIMAL_TOOLS",
    "PROFILES",
    "TOOLS",
    "TOOLS_LIST_MAX_BYTES",
    "Profile",
    "ToolSpec",
    "for_profile",
    "get",
    "in_profile",
    "profile_of",
]


def get(name: str) -> ToolSpec | None:
    for spec in TOOLS:
        if spec.name == name:
            return spec
    return None


MINIMAL_TOOLS: frozenset[str] = frozenset(
    {
        "houdini_status", "houdini_connect", "hip_open", "hip_save",
        "node_find", "node_info", "node_create", "node_connect",
        "parm_get", "parm_set", "cook", "geo_info", "viewport_capture", "houdini_python",
    }
)  # fmt: skip
"""The ``minimal`` profile (1.3, BIBLE §4.1): 14 core tools for clients with a small context.
``houdini_python`` covers what the others leave out."""


def profile_of(spec: ToolSpec) -> str:
    """The smallest profile that lists ``spec``."""
    return "minimal" if spec.name in MINIMAL_TOOLS else spec.profile


def in_profile(spec: ToolSpec, profile: str) -> bool:
    """Whether ``profile`` lists ``spec``; an unknown profile reads as ``core``."""
    rank = PROFILES.index(profile) if profile in PROFILES else PROFILES.index("core")
    return PROFILES.index(profile_of(spec)) <= rank


def _v2_status(spec: ToolSpec) -> ToolSpec:
    """``houdini_status`` as the ``v2`` profile lists it: its ``profile`` output field may
    also be ``v2``. The 1.x profiles keep the 1.4 schema (and so their ``tools/list``
    bytes); only the v2 listing names the fourth profile."""
    schema = copy.deepcopy(spec.output_schema)
    field = (schema or {}).get("properties", {}).get("profile")
    if not isinstance(field, dict) or "enum" not in field:
        return spec
    field["enum"] = list(PROFILES)
    return dataclasses.replace(spec, output_schema=schema)


_V2_TOOLS: tuple[ToolSpec, ...] = tuple(
    _v2_status(spec) if spec.name == "houdini_status" else spec for spec in TOOLS
)


def for_profile(profile: Profile) -> tuple[ToolSpec, ...]:
    """The tools ``profile`` lists, in catalogue order. ``v2`` lists every tool."""
    if profile == "v2":
        return _V2_TOOLS
    return tuple(spec for spec in TOOLS if in_profile(spec, profile))

"""The HocusPocus tool catalogue: the single source of truth for the tool surface.

Stdlib only. Imported by the host (inside Houdini) to map names to implementations,
by the bridge (outside Houdini) to register MCP tools, and by the docs generator.
See docs/BIBLE.md §3.5 and §4.

2.0 (spec-2.0 §5.1): each tool is defined in its own module under
``hocuspocus/tools/spec/`` (``spec/<tool>.py`` exports ``SPEC``), built with the schema
helpers in ``spec/_helpers.py``. This module is the loader: it re-exports the specs in
catalogue order and owns the profile membership.
"""

from __future__ import annotations

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


def for_profile(profile: Profile) -> tuple[ToolSpec, ...]:
    """The tools ``profile`` lists, in catalogue order."""
    return tuple(spec for spec in TOOLS if in_profile(spec, profile))

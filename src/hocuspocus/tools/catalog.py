"""The HocusPocus tool catalogue: the single source of truth for the tool surface.

Stdlib only. Imported by the host (inside Houdini) to map names to implementations,
by the bridge (outside Houdini) to register MCP tools, and by the docs generator.
See docs/BIBLE.md §3.5 and §4.

Each tool is defined in its own module under ``hocuspocus/tools/spec/`` (``spec/<tool>.py``
exports ``SPEC``, spec-2.0 §5.1), built with the schema helpers in ``spec/_helpers.py``.
This module is the loader: it re-exports the specs in catalogue order and answers which
profile lists which tool.

Profiles (spec-2.0 §2; :mod:`hocuspocus.tools.profiles`): each spec names the profiles
that list it in its ``profiles`` tuple, so a tool's surface is read in one file. The
profiles nest, ``minimal`` (10) ⊂ ``core`` (19, the default; 2.1 adds ``hda``, D47) ⊂ ``full`` (21). The 1.4
tools 2.0 replaced have no spec since 2.1; :mod:`hocuspocus.tools.migration` names each
one's replacement.
"""

from __future__ import annotations

from .profiles import DEFAULT_PROFILE, PROFILES, normalize
from .spec import TOOLS
from .spec._helpers import (
    ARGUMENT_DESCRIPTION_MAX_WORDS,
    CATEGORIES,
    DESCRIPTION_MAX_WORDS,
    HP_RPC_VERSION,
    TOOLS_LIST_MAX_BYTES,
    Profile,
    ToolSpec,
)

__all__ = [
    "ARGUMENT_DESCRIPTION_MAX_WORDS",
    "CATEGORIES",
    "DEFAULT_PROFILE",
    "DESCRIPTION_MAX_WORDS",
    "HP_RPC_VERSION",
    "PROFILES",
    "TOOLS",
    "TOOLS_LIST_MAX_BYTES",
    "Profile",
    "ToolSpec",
    "for_profile",
    "get",
    "in_profile",
    "normalize",
    "profile_of",
]


def get(name: str) -> ToolSpec | None:
    for spec in TOOLS:
        if spec.name == name:
            return spec
    return None


def profile_of(spec: ToolSpec) -> str:
    """The smallest profile that lists ``spec``."""
    for profile in PROFILES:
        if profile in spec.profiles:
            return profile
    return PROFILES[-1]


def in_profile(spec: ToolSpec, profile: str) -> bool:
    """Whether ``profile`` lists ``spec``; an unknown name reads as the default, ``core``."""
    return (normalize(profile) or DEFAULT_PROFILE) in spec.profiles


_LISTINGS: dict[str, tuple[ToolSpec, ...]] = {
    profile: tuple(spec for spec in TOOLS if profile in spec.profiles) for profile in PROFILES
}


def for_profile(profile: str) -> tuple[ToolSpec, ...]:
    """The tools ``profile`` lists, in catalogue order; an unknown name reads as ``core``."""
    return _LISTINGS[normalize(profile) or DEFAULT_PROFILE]

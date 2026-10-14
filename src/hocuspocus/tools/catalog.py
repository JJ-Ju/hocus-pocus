"""The HocusPocus tool catalogue: the single source of truth for the tool surface.

Stdlib only. Imported by the host (inside Houdini) to map names to implementations,
by the bridge (outside Houdini) to register MCP tools, and by the docs generator.
See docs/BIBLE.md §3.5 and §4.

Each tool is defined in its own module under ``hocuspocus/tools/spec/`` (``spec/<tool>.py``
exports ``SPEC``, spec-2.0 §5.1), built with the schema helpers in ``spec/_helpers.py``.
This module is the loader: it re-exports the specs in catalogue order and answers which
profile lists which tool.

Profiles (spec-2.0 §2, §8; :mod:`hocuspocus.tools.profiles`): each spec names the profiles
that list it in its ``profiles`` tuple, so a tool's surface is read in one file. The 2.0
profiles nest, ``minimal`` (10) ⊂ ``core`` (18, the default) ⊂ ``full`` (21), and list a
1.4 tool with its ``v2_extra`` overlay merged in (``on``, ``role``, ``recent``).
``compat_1x`` lists the 35 1.4 tools with their 1.4 schemas, byte for byte 1.4's ``full``
``tools/list``. ``v2`` is read as ``full``.
"""

from __future__ import annotations

import copy
import dataclasses
from typing import Any

from .profiles import ALIASES, COMPAT_1X, DEFAULT_PROFILE, PROFILES, PROFILES_2X, normalize
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
    "ALIASES",
    "ARGUMENT_DESCRIPTION_MAX_WORDS",
    "CATEGORIES",
    "COMPAT_1X",
    "DEFAULT_PROFILE",
    "DESCRIPTION_MAX_WORDS",
    "HP_RPC_VERSION",
    "PROFILES",
    "PROFILES_2X",
    "TOOLS",
    "TOOLS_LIST_MAX_BYTES",
    "Profile",
    "ToolSpec",
    "for_profile",
    "get",
    "host_accepts",
    "in_profile",
    "normalize",
    "profile_of",
    "v2_spec",
]


def get(name: str) -> ToolSpec | None:
    for spec in TOOLS:
        if spec.name == name:
            return spec
    return None


def profile_of(spec: ToolSpec) -> str:
    """The smallest 2.0 profile that lists ``spec``, or ``compat_1x`` for a 1.4 tool that
    2.0 removed."""
    for profile in PROFILES_2X:
        if profile in spec.profiles:
            return profile
    return COMPAT_1X


def in_profile(spec: ToolSpec, profile: str) -> bool:
    """Whether ``profile`` lists ``spec``. Aliases are resolved (``v2`` is ``full``); an
    unknown name reads as the default, ``core``."""
    return (normalize(profile) or DEFAULT_PROFILE) in spec.profiles


def host_accepts(spec: ToolSpec, profile: str) -> bool:
    """Whether a host on ``profile`` runs ``spec``: what the profile lists, and on
    ``compat_1x`` also the 2.0 tools (the 1.4 tools run on the 2.0 engines, and a
    ``compat_1x`` host never refuses what a ``full`` one runs)."""
    resolved = normalize(profile) or DEFAULT_PROFILE
    if resolved == COMPAT_1X:
        return COMPAT_1X in spec.profiles or "full" in spec.profiles
    return resolved in spec.profiles


def _merge(base: Any, overlay: Any) -> Any:
    """``overlay`` deep-merged into a copy of ``base``: dicts merge key by key (new keys
    last, so the 1.x key order is kept), anything else replaces."""
    if not isinstance(base, dict) or not isinstance(overlay, dict):
        return copy.deepcopy(overlay)
    out = copy.deepcopy(base)
    for key, value in overlay.items():
        out[key] = _merge(out[key], value) if key in out else copy.deepcopy(value)
    return out


def v2_spec(spec: ToolSpec) -> ToolSpec:
    """``spec`` as the 2.0 profiles list it: its ``v2_extra`` overlays merged into its
    input and output schemas (spec-2.0 §2.1, §2.5: ``on``, ``role``, ``recent``). A spec
    without overlays is returned as is. ``compat_1x`` lists the plain spec, so its
    ``tools/list`` bytes stay those of 1.4."""
    extra = spec.v2_extra
    if not extra:
        return spec
    changes: dict[str, Any] = {}
    if extra.get("input"):
        changes["input_schema"] = _merge(spec.input_schema, extra["input"])
    if extra.get("output") and spec.output_schema is not None:
        changes["output_schema"] = _merge(spec.output_schema, extra["output"])
    return dataclasses.replace(spec, **changes) if changes else spec


_LISTINGS: dict[str, tuple[ToolSpec, ...]] = {
    **{
        profile: tuple(v2_spec(spec) for spec in TOOLS if profile in spec.profiles)
        for profile in PROFILES_2X
    },
    COMPAT_1X: tuple(spec for spec in TOOLS if COMPAT_1X in spec.profiles),
}


def for_profile(profile: str) -> tuple[ToolSpec, ...]:
    """The tools ``profile`` lists, in catalogue order, as that profile lists them (the
    2.0 profiles with ``v2_extra`` merged in). Aliases resolve; an unknown name reads as
    ``core``."""
    return _LISTINGS[normalize(profile) or DEFAULT_PROFILE]

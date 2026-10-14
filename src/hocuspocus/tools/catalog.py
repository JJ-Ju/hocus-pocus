"""The HocusPocus tool catalogue: the single source of truth for the tool surface.

Stdlib only. Imported by the host (inside Houdini) to map names to implementations,
by the bridge (outside Houdini) to register MCP tools, and by the docs generator.
See docs/BIBLE.md §3.5 and §4.

Profiles nest, smallest first: ``minimal ⊂ core ⊂ full ⊂ v2``. ``v2`` (spec-2.0 §7 M1)
is ``full`` plus the 2.0 tools (spec ``profile="v2"``), served alongside the 1.4 names.
A 1.x tool that gains 2.0 arguments in ``v2`` (``on``, ``role``; spec-2.0 §7 M2) carries
them as a ``v2_extra`` schema overlay, merged in by :func:`v2_spec` for the ``v2`` listing
only, so the 1.x profiles keep their 1.4 ``tools/list`` bytes.

2.0 (spec-2.0 §5.1): each tool is defined in its own module under
``hocuspocus/tools/spec/`` (``spec/<tool>.py`` exports ``SPEC``), built with the schema
helpers in ``spec/_helpers.py``. This module is the loader: it re-exports the specs in
catalogue order and owns the profile membership.
"""

from __future__ import annotations

import copy
import dataclasses
from typing import Any

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
    "v2_spec",
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
    """``spec`` as the ``v2`` profile lists it: its ``v2_extra`` overlays merged into its
    input and output schemas (spec-2.0 §7 M2: ``on``, ``role``, ``recent``, the ``v2``
    profile name). A spec without overlays is returned as is. The 1.x profiles list the
    plain spec, so their ``tools/list`` bytes stay those of 1.4."""
    extra = spec.v2_extra
    if not extra:
        return spec
    changes: dict[str, Any] = {}
    if extra.get("input"):
        changes["input_schema"] = _merge(spec.input_schema, extra["input"])
    if extra.get("output") and spec.output_schema is not None:
        changes["output_schema"] = _merge(spec.output_schema, extra["output"])
    return dataclasses.replace(spec, **changes) if changes else spec


_V2_TOOLS: tuple[ToolSpec, ...] = tuple(v2_spec(spec) for spec in TOOLS)


def for_profile(profile: Profile) -> tuple[ToolSpec, ...]:
    """The tools ``profile`` lists, in catalogue order. ``v2`` lists every tool."""
    if profile == "v2":
        return _V2_TOOLS
    return tuple(spec for spec in TOOLS if in_profile(spec, profile))

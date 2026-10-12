"""The HocusPocus tool catalogue: the single source of truth for the tool surface.

Stdlib only. Imported by the host (inside Houdini) to map names to implementations,
by the bridge (outside Houdini) to register MCP tools, and by the docs generator.
See docs/BIBLE.md §3.5 and §4.

Status: skeleton. The M0 "catalog" task fills ``TOOLS`` with every entry from the bible.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Profile = Literal["core", "full"]

HP_RPC_VERSION = 1
"""Host RPC contract version (the ``v1`` in ``/hp/v1/...``)."""

TOOLS_LIST_MAX_BYTES = 48_000
"""Hard cap on model-visible ``tools/list`` text (≈12k tokens). Enforced by a unit test."""

DESCRIPTION_MAX_WORDS = 80


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """One MCP tool as the bridge advertises it and the host implements it."""

    name: str
    description: str
    input_schema: dict[str, Any]
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


TOOLS: tuple[ToolSpec, ...] = ()
"""All tools, in deterministic order. Filled by the catalog task."""


def get(name: str) -> ToolSpec | None:
    for spec in TOOLS:
        if spec.name == name:
            return spec
    return None


def for_profile(profile: Profile) -> tuple[ToolSpec, ...]:
    if profile == "full":
        return TOOLS
    return tuple(spec for spec in TOOLS if spec.profile == "core")

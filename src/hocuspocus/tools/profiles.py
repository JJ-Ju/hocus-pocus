"""Profile names (spec-2.0 §2, §8; BIBLE §3.5). Stdlib only and import-free, so the host's
config can read it at Houdini startup without loading the catalogue.

The 2.0 profiles nest, smallest first: ``minimal`` (10 tools) ⊂ ``core`` (18, the default) ⊂
``full`` (21). ``compat_1x`` is the 1.4 ``full`` catalogue (35 tools, 1.4 schemas) for a 1.x
client script, served for the 2.0.x releases and removed in 2.1. ``v2``, the M1-M2 preview
of the 2.0 surface, is read as ``full`` for 2.0.x. Which tools a profile lists is each
spec's ``profiles`` tuple (``tools/spec/<tool>.py``).
"""

from __future__ import annotations

from typing import Any

PROFILES_2X: tuple[str, ...] = ("minimal", "core", "full")
"""The 2.0 profiles, nested, smallest first."""

COMPAT_1X = "compat_1x"
"""The 1.4 catalogue: every 1.4 tool with its 1.4 schema (spec-2.0 §8)."""

PROFILES: tuple[str, ...] = (*PROFILES_2X, COMPAT_1X)
"""Every profile name ``hocuspocus.toml`` and ``HOCUSPOCUS_PROFILE`` accept (plus
:data:`ALIASES`)."""

DEFAULT_PROFILE = "core"

ALIASES: dict[str, str] = {"v2": "full"}
"""Old names read as a current profile; ``v2`` is kept for 2.0.x only."""


def normalize(raw: Any) -> str | None:
    """``raw`` as a profile name (case and whitespace ignored, aliases resolved); ``None``
    when it names no profile. An empty value is :data:`DEFAULT_PROFILE`."""
    value = str(raw if raw is not None else "").strip().lower()
    if not value:
        return DEFAULT_PROFILE
    value = ALIASES.get(value, value)
    return value if value in PROFILES else None


def is_2x(profile: str) -> bool:
    """Whether ``profile`` serves the 2.0 surface (roles, ``on``, resources, ledger job
    ids); ``compat_1x`` serves the 1.4 one."""
    return profile != COMPAT_1X

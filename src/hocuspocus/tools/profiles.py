"""Profile names (spec-2.0 §2; BIBLE §3.5, §4.1). Stdlib only and import-free, so the host's
config can read it at Houdini startup without loading the catalogue.

The profiles nest, smallest first: ``minimal`` (10 tools) ⊂ ``core`` (18, the default) ⊂
``full`` (21). Which tools a profile lists is each spec's ``profiles`` tuple
(``tools/spec/<tool>.py``).

2.1 removed ``compat_1x`` (the 1.4 catalogue, served for 2.0.x) and ``v2`` (the M1-M2
preview name of ``full``). Configured anyway, either is read as ``full`` with a warning
(:data:`REMOVED`, :func:`removed_warning`; BIBLE D45): both processes resolve it the same
way, so host and bridge still agree, and a removed 1.4 tool answers ``invalid_argument``
with its 2.0 replacement (``tools/migration.py``).
"""

from __future__ import annotations

from typing import Any

PROFILES: tuple[str, ...] = ("minimal", "core", "full")
"""Every profile name ``hocuspocus.toml`` and ``HOCUSPOCUS_PROFILE`` accept, nested,
smallest first."""

DEFAULT_PROFILE = "core"

REMOVED: dict[str, str] = {"compat_1x": "full", "v2": "full"}
"""Profile names 2.1 removed -> the profile they are read as, with a warning (BIBLE D45).
``compat_1x`` served 1.4's ``full`` catalogue and ``v2`` was read as ``full`` in 2.0.x, so
``full`` is the 2.0 profile closest to what each served."""


def _key(raw: Any) -> str:
    return str(raw if raw is not None else "").strip().lower()


def normalize(raw: Any) -> str | None:
    """``raw`` as a profile name (case and whitespace ignored); ``None`` when it names no
    profile, a removed one included (:func:`resolve` reads those). An empty value is
    :data:`DEFAULT_PROFILE`."""
    value = _key(raw)
    if not value:
        return DEFAULT_PROFILE
    return value if value in PROFILES else None


def removed_warning(raw: Any) -> str | None:
    """The warning for a removed profile name (:data:`REMOVED`), or ``None`` for any other
    value."""
    value = _key(raw)
    if value not in REMOVED:
        return None
    use = REMOVED[value]
    was = (
        "the 1.4 catalogue for 2.0.x"
        if value == "compat_1x"
        else "the 2.0 preview name of full, read as full in 2.0.x"
    )
    return (
        f'profile = "{value}" ({was}) was removed in HocusPocus 2.1; using "{use}". '
        "A 1.4 tool name answers invalid_argument with its 2.0 replacement "
        '(docs/migration-2.0.md). Set profile = "minimal", "core" or "full".'
    )


def resolve(raw: Any) -> tuple[str | None, str | None]:
    """``(profile, warning)`` for a configured value: a profile name as :func:`normalize`
    reads it, or for a removed one (:data:`REMOVED`) the profile it is read as and the
    warning to log. ``(None, None)`` when ``raw`` names nothing."""
    warning = removed_warning(raw)
    if warning is not None:
        return REMOVED[_key(raw)], warning
    return normalize(raw), None

"""Bridge configuration from ``HOCUSPOCUS_*`` environment variables. See docs/BIBLE.md §3.7.

The bridge has no config file: the MCP client launches it with an environment, and
everything has a default. Host-side settings (``allow_python``, ``read_only``, …) live in
the host and are reported by ``houdini_status``.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass

log = logging.getLogger(__name__)

DEFAULT_MAX_RESPONSE_BYTES = 16_384
DEFAULT_TIMEOUT_S = 30.0
PROFILES = ("core", "full")


@dataclass(frozen=True, slots=True)
class BridgeConfig:
    profile: str = "core"
    max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES
    default_timeout_s: float = DEFAULT_TIMEOUT_S
    hfs: str = ""
    """Explicit Houdini install dir for launching; empty means auto-detect."""

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> BridgeConfig:
        env = os.environ if environ is None else environ
        profile = env.get("HOCUSPOCUS_PROFILE", "core").strip().lower() or "core"
        if profile not in PROFILES:
            log.warning("HOCUSPOCUS_PROFILE=%r is not one of %s; using 'core'", profile, PROFILES)
            profile = "core"
        return cls(
            profile=profile,
            max_response_bytes=_positive(
                env, "HOCUSPOCUS_MAX_RESPONSE_BYTES", DEFAULT_MAX_RESPONSE_BYTES, int
            ),
            default_timeout_s=_positive(
                env, "HOCUSPOCUS_DEFAULT_TIMEOUT_S", DEFAULT_TIMEOUT_S, float
            ),
            hfs=env.get("HOCUSPOCUS_HFS", "").strip(),
        )


def _positive(env: Mapping[str, str], key: str, default, kind):
    raw = env.get(key, "").strip()
    if not raw:
        return default
    try:
        value = kind(raw)
    except ValueError:
        log.warning("%s=%r is not a valid %s; using %r", key, raw, kind.__name__, default)
        return default
    if value <= 0:
        log.warning("%s must be positive; using %r", key, default)
        return default
    return value

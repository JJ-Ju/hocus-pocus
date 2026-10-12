"""Bridge configuration. See docs/BIBLE.md §3.7.

One ``hocuspocus.toml`` serves host and bridge. The bridge reads the keys it uses
(``profile``, ``max_response_bytes``, ``default_timeout_s``, ``hfs``) from the same file
the host reads, ``<prefs>/hocuspocus.toml``, and ``HOCUSPOCUS_*`` environment variables
override it. Host-only keys (``allow_python``, ``read_only``, …) are ignored here; the
host reports them through ``houdini_status``.

The bridge starts on every MCP client launch, so it cannot ask hython for
``hou.homeHoudiniDirectory()`` the way ``hocuspocus install-houdini`` does. It finds the
pref dir with cheap lookups, first hit wins:

1. ``HOUDINI_USER_PREF_DIR`` (``__HVER__`` expanded to ``22.0``);
2. the ``prefs`` recorded in ``<state_dir>/install.json`` by ``install-houdini``;
3. the platform default locations, the first one that holds a ``hocuspocus.toml``.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..host.config import CONFIG_FILE_NAME, read_config_file
from ..tools import paths

log = logging.getLogger(__name__)

DEFAULT_MAX_RESPONSE_BYTES = 16_384
DEFAULT_TIMEOUT_S = 30.0
PROFILES = ("core", "full")
HOUDINI_MAJOR_MINOR = "22.0"
INSTALL_STATE_FILE = "install.json"
"""Written by ``hocuspocus install-houdini`` into the state dir: ``{"prefs": ...}``."""


@dataclass(frozen=True, slots=True)
class BridgeConfig:
    profile: str = "core"
    max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES
    default_timeout_s: float = DEFAULT_TIMEOUT_S
    hfs: str = ""
    """Explicit Houdini install dir for launching; empty means auto-detect."""
    config_file: str = ""
    """The ``hocuspocus.toml`` that was read, or empty when none was found."""

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> BridgeConfig:
        """Environment only (no file). Kept for callers that want no file lookup."""
        return cls.load(environ, read_file=False)

    @classmethod
    def load(
        cls,
        environ: Mapping[str, str] | None = None,
        *,
        pref_dir: str | os.PathLike[str] | None = None,
        read_file: bool = True,
    ) -> BridgeConfig:
        """Defaults → ``<prefs>/hocuspocus.toml`` → ``HOCUSPOCUS_*`` environment."""
        env = os.environ if environ is None else environ
        values: dict[str, Any] = {}
        config_file = ""
        if read_file:
            found = find_config_file(env, pref_dir=pref_dir)
            if found is not None:
                config_file = str(found)
                data = read_config_file(found)
                values.update({k: data[k] for k in _KEYS if k in data})
        for key in _KEYS:
            raw = env.get(f"HOCUSPOCUS_{key.upper()}", "").strip()
            if raw:
                values[key] = raw
        return cls(
            profile=_profile(values.get("profile")),
            max_response_bytes=_positive(
                values, "max_response_bytes", DEFAULT_MAX_RESPONSE_BYTES, int
            ),
            default_timeout_s=_positive(values, "default_timeout_s", DEFAULT_TIMEOUT_S, float),
            hfs=str(values.get("hfs") or "").strip(),
            config_file=config_file,
        )


_KEYS = ("profile", "max_response_bytes", "default_timeout_s", "hfs")


# -- locating hocuspocus.toml ---------------------------------------------------------


def _expand_hver(path: str) -> str:
    return path.replace("__HVER__", HOUDINI_MAJOR_MINOR)


def default_pref_dirs(environ: Mapping[str, str] | None = None) -> list[Path]:
    """Where Houdini 22.0 puts the user pref dir when nothing overrides it."""
    env = os.environ if environ is None else environ
    if sys.platform == "win32":
        home = Path(env.get("USERPROFILE") or Path.home())
        name = f"houdini{HOUDINI_MAJOR_MINOR}"
        return [home / name, home / "Documents" / name]
    if sys.platform == "darwin":
        return [Path.home() / "Library" / "Preferences" / "houdini" / HOUDINI_MAJOR_MINOR]
    return [Path.home() / f"houdini{HOUDINI_MAJOR_MINOR}"]


def installed_pref_dir(state_dir: Path | None = None) -> Path | None:
    """The pref dir ``install-houdini`` recorded, if any."""
    path = (state_dir or paths.state_dir()) / INSTALL_STATE_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    prefs = data.get("prefs") if isinstance(data, dict) else None
    return Path(prefs) if isinstance(prefs, str) and prefs else None


def resolve_pref_dir(
    environ: Mapping[str, str] | None = None, *, pref_dir: str | os.PathLike[str] | None = None
) -> tuple[Path | None, str]:
    """``(pref_dir, source)`` from explicit → env → install.json; ``(None, "")`` if none."""
    env = os.environ if environ is None else environ
    if pref_dir:
        return Path(pref_dir), "argument"
    from_env = env.get("HOUDINI_USER_PREF_DIR", "").strip()
    if from_env:
        return Path(_expand_hver(from_env)).expanduser(), "HOUDINI_USER_PREF_DIR"
    state = env.get("HOCUSPOCUS_STATE_DIR")
    installed = installed_pref_dir(Path(state) if state else None)
    if installed is not None:
        return installed, INSTALL_STATE_FILE
    return None, ""


def find_config_file(
    environ: Mapping[str, str] | None = None, *, pref_dir: str | os.PathLike[str] | None = None
) -> Path | None:
    """The ``hocuspocus.toml`` the bridge reads, or ``None``.

    A pref dir from the environment or ``install.json`` is authoritative even when it has
    no toml (the host would see none either); only the platform defaults are probed.
    """
    resolved, _source = resolve_pref_dir(environ, pref_dir=pref_dir)
    if resolved is not None:
        candidate = resolved / CONFIG_FILE_NAME
        return candidate if candidate.is_file() else None
    for directory in default_pref_dirs(environ):
        candidate = directory / CONFIG_FILE_NAME
        if candidate.is_file():
            return candidate
    return None


# -- value parsing ----------------------------------------------------------------------


def _profile(raw: Any) -> str:
    profile = str(raw or "core").strip().lower() or "core"
    if profile not in PROFILES:
        log.warning("profile=%r is not one of %s; using 'core'", raw, PROFILES)
        return "core"
    return profile


def _positive(values: Mapping[str, Any], key: str, default, kind):
    raw = values.get(key)
    if raw is None or raw == "":
        return default
    if isinstance(raw, bool):
        log.warning("%s=%r is not a valid %s; using %r", key, raw, kind.__name__, default)
        return default
    try:
        value = kind(raw.strip() if isinstance(raw, str) else raw)
    except (TypeError, ValueError):
        log.warning("%s=%r is not a valid %s; using %r", key, raw, kind.__name__, default)
        return default
    if value <= 0:
        log.warning("%s must be positive; using %r", key, default)
        return default
    return value

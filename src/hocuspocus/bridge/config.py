"""Bridge configuration. See docs/BIBLE.md §3.7.

One ``hocuspocus.toml`` serves host and bridge. The bridge reads the keys it uses
(``profile``, ``max_response_bytes``, ``default_timeout_s``, ``hfs``, ``result_content``)
from the same file
the host reads, ``<prefs>/hocuspocus.toml``, and ``HOCUSPOCUS_*`` environment variables
override it. Host-only keys (``allow_python``, ``read_only``, …) are ignored here; the
host reports them through ``houdini_status``.

The bridge starts on every MCP client launch, so it cannot ask hython for
``hou.homeHoudiniDirectory()`` the way ``hocuspocus install-houdini`` does. It finds the
pref dir with cheap lookups:

1. ``HOUDINI_USER_PREF_DIR`` (``__HVER__`` expanded to ``22.0``), authoritative: Houdini
   itself uses it whenever it is set;
2. otherwise the first candidate that holds a ``hocuspocus.toml``: the ``pref_dirs``
   recorded in ``<state_dir>/install.json`` by ``install-houdini``, in order, then the
   platform default locations. On Windows Houdini's pref dir depends on whether ``HOME``
   is set (``%HOME%/houdini22.0``) or not (``%USERPROFILE%/Documents/houdini22.0``),
   so there can be more than one.
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
from ..tools.profiles import DEFAULT_PROFILE, PROFILES
from ..tools.profiles import resolve as resolve_profile

log = logging.getLogger(__name__)

DEFAULT_MAX_RESPONSE_BYTES = 16_384
DEFAULT_TIMEOUT_S = 30.0
RESULT_CONTENT = ("text", "both", "structured")
"""``result_content`` values; the first is the default (BIBLE §4.1)."""
HOUDINI_MAJOR_MINOR = "22.0"
INSTALL_STATE_FILE = "install.json"
"""Written by ``hocuspocus install-houdini`` into the state dir: ``{"pref_dirs": [...],
"prefs": <the first>, ...}`` (1.2.0 and earlier wrote ``prefs`` only)."""


@dataclass(frozen=True, slots=True)
class BridgeConfig:
    profile: str = DEFAULT_PROFILE
    """``minimal``, ``core`` (the default) or ``full`` (:mod:`hocuspocus.tools.profiles`).
    ``compat_1x`` and ``v2``, removed in 2.1, are read as ``full`` (BIBLE D45)."""
    max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES
    default_timeout_s: float = DEFAULT_TIMEOUT_S
    hfs: str = ""
    """Explicit Houdini install dir for launching; empty means auto-detect."""
    result_content: str = RESULT_CONTENT[0]
    """Where tool results go: ``text`` (compact JSON in the text block only), ``both``
    (text and ``structuredContent``) or ``structured`` (data in ``structuredContent``,
    a one-line summary in the text block)."""
    config_file: str = ""
    """The ``hocuspocus.toml`` that was read, or empty when none was found."""
    profile_warning: str = ""
    """Why ``profile`` is not what the configuration said: a removed profile name
    (``compat_1x``, ``v2``) read as ``full``. ``houdini_status`` repeats it in
    ``warnings``."""

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
        profile, profile_warning = _profile(values.get("profile"))
        return cls(
            profile=profile,
            max_response_bytes=_positive(
                values, "max_response_bytes", DEFAULT_MAX_RESPONSE_BYTES, int
            ),
            default_timeout_s=_positive(values, "default_timeout_s", DEFAULT_TIMEOUT_S, float),
            hfs=str(values.get("hfs") or "").strip(),
            result_content=_choice(values.get("result_content"), "result_content", RESULT_CONTENT),
            config_file=config_file,
            profile_warning=profile_warning,
        )


_KEYS = ("profile", "max_response_bytes", "default_timeout_s", "hfs", "result_content")


# -- locating hocuspocus.toml ---------------------------------------------------------


def _expand_hver(path: str) -> str:
    return path.replace("__HVER__", HOUDINI_MAJOR_MINOR)


def _home_dirs(env: Mapping[str, str], platform: str) -> list[Path]:
    if platform == "win32":
        homes = [Path(env.get("USERPROFILE") or Path.home())]
        if env.get("HOME"):
            homes.append(Path(env["HOME"]))
        return homes
    return [Path(env.get("HOME") or Path.home())]


def default_pref_dirs(
    environ: Mapping[str, str] | None = None,
    *,
    major_minor: str = HOUDINI_MAJOR_MINOR,
    platform: str | None = None,
) -> list[Path]:
    """Where Houdini puts the user pref dir when ``HOUDINI_USER_PREF_DIR`` is not set.

    On Windows that is ``<home>/houdiniX.Y`` or ``<home>/Documents/houdiniX.Y``, for
    ``%USERPROFILE%`` and, when set, ``%HOME%``: which one Houdini uses depends on how it
    was started, so every one may be in use.
    """
    env = os.environ if environ is None else environ
    platform = platform or sys.platform
    if platform == "darwin":
        return [_home_dirs(env, platform)[0] / "Library" / "Preferences" / "houdini" / major_minor]
    name = f"houdini{major_minor}"
    found: list[Path] = []
    for home in _home_dirs(env, platform):
        options = [home / name, home / "Documents" / name] if platform == "win32" else [home / name]
        found.extend(options)
    return dedupe_dirs(found)


def same_dir_key(path: Path) -> str:
    """A key equal for two spellings of one directory (links resolved, case folded on Windows)."""
    try:
        resolved = path.expanduser().resolve()
    except (OSError, RuntimeError):
        resolved = path.absolute()
    return os.path.normcase(str(resolved))


def dedupe_dirs(dirs: list[Path]) -> list[Path]:
    """``dirs`` without later spellings of a directory already listed."""
    seen: set[str] = set()
    out: list[Path] = []
    for path in dirs:
        key = same_dir_key(path)
        if key not in seen:
            seen.add(key)
            out.append(path)
    return out


def installed_pref_dirs(state_dir: Path | None = None) -> list[Path]:
    """The pref dirs ``install-houdini`` recorded, in order (``prefs`` alone before 1.2.1)."""
    path = (state_dir or paths.state_dir()) / INSTALL_STATE_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(data, dict):
        return []
    raw = data.get("pref_dirs")
    entries = raw if isinstance(raw, list) else []
    if not entries and isinstance(data.get("prefs"), str):
        entries = [data["prefs"]]
    return dedupe_dirs([Path(e) for e in entries if isinstance(e, str) and e])


def installed_pref_dir(state_dir: Path | None = None) -> Path | None:
    """The first pref dir ``install-houdini`` recorded, if any."""
    recorded = installed_pref_dirs(state_dir)
    return recorded[0] if recorded else None


def _state_dir_from(env: Mapping[str, str]) -> Path | None:
    state = env.get("HOCUSPOCUS_STATE_DIR")
    return Path(state) if state else None


def resolve_pref_dir(
    environ: Mapping[str, str] | None = None, *, pref_dir: str | os.PathLike[str] | None = None
) -> tuple[Path | None, str]:
    """``(pref_dir, source)`` from explicit → env → the first recorded one; ``(None, "")``."""
    env = os.environ if environ is None else environ
    if pref_dir:
        return Path(pref_dir), "argument"
    from_env = env.get("HOUDINI_USER_PREF_DIR", "").strip()
    if from_env:
        return Path(_expand_hver(from_env)).expanduser(), "HOUDINI_USER_PREF_DIR"
    installed = installed_pref_dir(_state_dir_from(env))
    if installed is not None:
        return installed, INSTALL_STATE_FILE
    return None, ""


def pref_dir_candidates(
    environ: Mapping[str, str] | None = None, *, pref_dir: str | os.PathLike[str] | None = None
) -> list[Path]:
    """Every pref dir the bridge considers, in order.

    An explicit ``pref_dir`` or ``HOUDINI_USER_PREF_DIR`` is the only candidate (Houdini
    uses it whenever it is set). Otherwise: the ``pref_dirs`` recorded in
    ``install.json``, in order, then the platform default locations.
    """
    env = os.environ if environ is None else environ
    resolved, source = resolve_pref_dir(env, pref_dir=pref_dir)
    if resolved is not None and source != INSTALL_STATE_FILE:
        return [resolved]
    return dedupe_dirs(installed_pref_dirs(_state_dir_from(env)) + default_pref_dirs(env))


def find_config_file(
    environ: Mapping[str, str] | None = None, *, pref_dir: str | os.PathLike[str] | None = None
) -> Path | None:
    """The ``hocuspocus.toml`` the bridge reads, or ``None``: the first candidate that has one.

    A pref dir given explicitly or through ``HOUDINI_USER_PREF_DIR`` is authoritative even
    when it has no toml (the host would see none either).
    """
    for directory in pref_dir_candidates(environ, pref_dir=pref_dir):
        candidate = directory / CONFIG_FILE_NAME
        if candidate.is_file():
            return candidate
    return None


# -- value parsing ----------------------------------------------------------------------


def _profile(raw: Any) -> tuple[str, str]:
    """``(profile, warning)``: a removed name (``compat_1x``, ``v2``) is read as ``full``
    with a warning (BIBLE D45), any other unknown one as the default."""
    profile, warning = resolve_profile(raw)
    if profile is None:
        log.warning("profile=%r is not one of %s; using %r", raw, PROFILES, DEFAULT_PROFILE)
        return DEFAULT_PROFILE, ""
    if warning:
        log.warning("%s", warning)
    return profile, warning or ""


def _choice(raw: Any, key: str, choices: tuple[str, ...]) -> str:
    """``raw`` normalised and checked against ``choices``; the first choice by default."""
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return choices[0]
    value = str(raw).strip().lower()
    if value not in choices:
        log.warning("%s=%r is not one of %s; using %r", key, raw, choices, choices[0])
        return choices[0]
    return value


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

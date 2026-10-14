"""Host configuration. Stdlib only. See docs/BIBLE.md §3.7.

Precedence (later wins): dataclass defaults → ``$HOUDINI_USER_PREF_DIR/hocuspocus.toml``
→ ``HOCUSPOCUS_*`` environment variables → explicit keyword arguments (CLI flags).
Unknown keys and values of the wrong type are logged and ignored, never fatal.
"""

from __future__ import annotations

import logging
import os
import sys
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field, fields, replace
from pathlib import Path
from typing import Any

log = logging.getLogger("hocuspocus.host.config")

CONFIG_FILE_NAME = "hocuspocus.toml"
ENV_PREFIX = "HOCUSPOCUS_"

_PROFILES = ("minimal", "core", "full", "v2")
BRIDGE_ONLY_KEYS = frozenset({"hfs", "result_content"})
"""Keys of the shared ``hocuspocus.toml`` that only the bridge reads; the host skips
them without the "unknown key" warning."""
_LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


@dataclass
class HostConfig:
    """Everything has a default; the config file is optional."""

    autostart: bool = True
    allow_python: bool = True
    read_only: bool = False
    approved_roots: list[str] = field(default_factory=list)
    max_response_bytes: int = 16384
    default_timeout_s: float = 30.0
    job_threshold_s: float = 10.0
    profile: str = "core"
    log_level: str = "INFO"
    # Host-only settings (CLI flags / env; not part of the documented toml surface).
    port: int = 0
    state_dir: str = ""
    """Overrides ``hocuspocus.tools.paths.state_dir()`` when non-empty."""
    label: str = ""
    """Instance label in the registry; defaults to the executable name (houdinifx, hython)."""
    pref_dir: str = ""
    """Resolved Houdini user pref dir (where ``hocuspocus.toml`` and ``file.history`` live)."""

    def with_overrides(self, **overrides: Any) -> HostConfig:
        return _apply(self, overrides, source="arguments")


_FIELD_TYPES: dict[str, type] = {
    "autostart": bool,
    "allow_python": bool,
    "read_only": bool,
    "approved_roots": list,
    "max_response_bytes": int,
    "default_timeout_s": float,
    "job_threshold_s": float,
    "profile": str,
    "log_level": str,
    "port": int,
    "state_dir": str,
    "label": str,
    "pref_dir": str,
}

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off", ""}


def _coerce(name: str, value: Any, *, from_env: bool) -> Any:
    """Return ``value`` converted to the field's type, or raise ``ValueError``."""
    kind = _FIELD_TYPES[name]
    if kind is bool:
        if isinstance(value, bool):
            return value
        if from_env and isinstance(value, str) and value.strip().lower() in _TRUE | _FALSE:
            return value.strip().lower() in _TRUE
        raise ValueError(f"expected a boolean, got {value!r}")
    if kind is int:
        if isinstance(value, bool):
            raise ValueError(f"expected an integer, got {value!r}")
        if isinstance(value, int):
            return value
        if from_env and isinstance(value, str):
            return int(value.strip())
        raise ValueError(f"expected an integer, got {value!r}")
    if kind is float:
        if isinstance(value, bool):
            raise ValueError(f"expected a number, got {value!r}")
        if isinstance(value, int | float):
            return float(value)
        if from_env and isinstance(value, str):
            return float(value.strip())
        raise ValueError(f"expected a number, got {value!r}")
    if kind is list:
        if from_env and isinstance(value, str):
            return [part for part in value.split(os.pathsep) if part.strip()]
        if isinstance(value, list | tuple) and all(isinstance(v, str) for v in value):
            return list(value)
        raise ValueError(f"expected a list of strings, got {value!r}")
    if isinstance(value, str):
        return value
    raise ValueError(f"expected a string, got {value!r}")


def _validate(name: str, value: Any) -> Any:
    if name == "profile" and value not in _PROFILES:
        raise ValueError(f"must be one of {_PROFILES}")
    if name == "log_level":
        value = str(value).upper()
        if value not in _LOG_LEVELS:
            raise ValueError(f"must be one of {_LOG_LEVELS}")
    if name in ("max_response_bytes",) and value < 1024:
        raise ValueError("must be >= 1024")
    if name in ("default_timeout_s", "job_threshold_s") and value <= 0:
        raise ValueError("must be > 0")
    if name == "port" and not 0 <= value <= 65535:
        raise ValueError("must be 0..65535")
    return value


def _apply(
    config: HostConfig, values: Mapping[str, Any], *, source: str, from_env: bool = False
) -> HostConfig:
    updates: dict[str, Any] = {}
    for key, raw in values.items():
        if key in BRIDGE_ONLY_KEYS:
            continue
        if key not in _FIELD_TYPES:
            log.warning("hocuspocus config: ignoring unknown key %r from %s", key, source)
            continue
        if raw is None:
            continue
        try:
            updates[key] = _validate(key, _coerce(key, raw, from_env=from_env))
        except (TypeError, ValueError) as exc:
            log.warning("hocuspocus config: ignoring %s=%r from %s: %s", key, raw, source, exc)
    return replace(config, **updates) if updates else config


def resolve_pref_dir(explicit: str | os.PathLike[str] | None = None) -> Path | None:
    """Best-effort Houdini user pref dir.

    Inside Houdini ``hou.homeHoudiniDirectory()`` is authoritative (it expands
    ``__HVER__``). Outside, ``HOUDINI_USER_PREF_DIR`` is used when it has no
    unexpanded ``__HVER__`` token. Never imports ``hou`` unless it is already loaded.
    """
    if explicit:
        return Path(explicit)
    hou = sys.modules.get("hou")
    if hou is not None:
        try:
            return Path(hou.homeHoudiniDirectory())
        except Exception:  # pragma: no cover - defensive
            pass
    env = os.environ.get("HOUDINI_USER_PREF_DIR", "")
    if env and "__HVER__" not in env:
        return Path(env)
    return None


def read_config_file(path: Path) -> dict[str, Any]:
    try:
        with open(path, "rb") as handle:
            data = tomllib.load(handle)
    except FileNotFoundError:
        return {}
    except (OSError, tomllib.TOMLDecodeError) as exc:
        log.warning("hocuspocus config: cannot read %s: %s", path, exc)
        return {}
    # Allow an optional [hocuspocus] table as well as top-level keys.
    table = data.get("hocuspocus")
    if isinstance(table, dict):
        merged = {k: v for k, v in data.items() if k != "hocuspocus"}
        merged.update(table)
        return merged
    return data


def env_values(environ: Mapping[str, str] | None = None) -> dict[str, str]:
    environ = os.environ if environ is None else environ
    values: dict[str, str] = {}
    for f in fields(HostConfig):
        key = ENV_PREFIX + f.name.upper()
        if key in environ:
            values[f.name] = environ[key]
    return values


def load_config(
    pref_dir: str | os.PathLike[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    **overrides: Any,
) -> HostConfig:
    """Build a :class:`HostConfig` from file, environment and explicit overrides."""
    environ = os.environ if environ is None else environ
    resolved = resolve_pref_dir(pref_dir or overrides.get("pref_dir") or None)
    config = HostConfig()
    if resolved is not None:
        config = replace(config, pref_dir=str(resolved))
        config = _apply(
            config,
            read_config_file(resolved / CONFIG_FILE_NAME),
            source=str(resolved / CONFIG_FILE_NAME),
        )
    config = _apply(config, env_values(environ), source="environment", from_env=True)
    return _apply(config, overrides, source="arguments")

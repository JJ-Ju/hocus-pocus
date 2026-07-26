"""Settings loader for HocusPocus."""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import paths

try:
    import tomllib  # type: ignore[attr-defined]
except ModuleNotFoundError:  # pragma: no cover - local Python 3.10 fallback
    import tomli as tomllib  # type: ignore[no-redef]

DEFAULT_POLICY_PROFILE = "local-dev"


def available_policy_profiles() -> dict[str, dict[str, Any]]:
    output_root = str(paths.output_dir())
    return {
        "safe": {
            "description": "Read-only profile for cautious local inspection.",
            "read_only": True,
            "allow_scene_edit": False,
            "allow_file_write": False,
            "enable_exec_tools": False,
            "enable_stdio_bridge": True,
            "approved_roots": [],
        },
        "local-dev": {
            "description": "Default local development profile with scene and file edits enabled.",
            "read_only": False,
            "allow_scene_edit": True,
            "allow_file_write": True,
            "enable_exec_tools": False,
            "enable_stdio_bridge": True,
            "approved_roots": [],
        },
        "pipeline": {
            "description": "Pipeline-friendly profile with writes limited to managed output roots by default.",
            "read_only": False,
            "allow_scene_edit": True,
            "allow_file_write": True,
            "enable_exec_tools": False,
            "enable_stdio_bridge": True,
            "approved_roots": [output_root],
        },
    }


def resolve_policy_profile(name: str | None) -> tuple[str, dict[str, Any]]:
    profiles = available_policy_profiles()
    candidate = str(name or DEFAULT_POLICY_PROFILE).strip() or DEFAULT_POLICY_PROFILE
    if candidate not in profiles:
        candidate = DEFAULT_POLICY_PROFILE
    return candidate, dict(profiles[candidate])


@dataclass(slots=True)
class ServerSettings:
    host: str = "127.0.0.1"
    port: int = 37219
    mcp_route: str = "/hocuspocus/mcp"
    health_route: str = "/hocuspocus/healthz"
    token_mode: str = "generated"
    token: str = ""
    auto_start: bool = False
    log_level: str = "INFO"
    request_timeout_seconds: float = 30.0
    policy_profile: str = DEFAULT_POLICY_PROFILE
    policy_profile_source: str = "default"
    read_only: bool = False
    allow_scene_edit: bool = True
    allow_file_write: bool = True
    approved_roots: list[str] = field(default_factory=list)
    enable_exec_tools: bool = False
    enable_stdio_bridge: bool = True
    feature_flags: dict[str, bool] = field(default_factory=dict)
    config_path: str = ""

    def resolved_token(self) -> str:
        if self.token_mode == "disabled":
            return ""
        if self.token:
            return self.token
        token_file = paths.runtime_token_path()
        if token_file.exists():
            return token_file.read_text(encoding="utf-8").strip()
        token = secrets.token_urlsafe(24)
        token_file.parent.mkdir(parents=True, exist_ok=True)
        token_file.write_text(token, encoding="utf-8")
        return token

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def mcp_url(self) -> str:
        return f"{self.base_url}{self.normalized_mcp_route}"

    @property
    def health_url(self) -> str:
        return f"{self.base_url}{self.normalized_health_route}"

    @property
    def normalized_mcp_route(self) -> str:
        return _normalize_route(self.mcp_route, "/hocuspocus/mcp")

    @property
    def normalized_health_route(self) -> str:
        return _normalize_route(self.health_route, "/hocuspocus/healthz")

    def effective_policy_payload(self) -> dict[str, Any]:
        return {
            "profile": self.policy_profile,
            "profileSource": self.policy_profile_source,
            "readOnly": self.read_only,
            "allowSceneEdit": self.allow_scene_edit and not self.read_only,
            "allowFileWrite": self.allow_file_write and not self.read_only,
            "enableExecTools": self.enable_exec_tools,
            "enableStdioBridge": self.enable_stdio_bridge,
            "approvedRoots": list(self.approved_roots),
        }

    def available_policy_profiles_payload(self) -> list[dict[str, Any]]:
        payload: list[dict[str, Any]] = []
        for name, profile in available_policy_profiles().items():
            payload.append(
                {
                    "name": name,
                    "description": profile["description"],
                    "effectivePolicy": {
                        "readOnly": bool(profile["read_only"]),
                        "allowSceneEdit": bool(profile["allow_scene_edit"] and not profile["read_only"]),
                        "allowFileWrite": bool(profile["allow_file_write"] and not profile["read_only"]),
                        "enableExecTools": bool(profile["enable_exec_tools"]),
                        "enableStdioBridge": bool(profile["enable_stdio_bridge"]),
                        "approvedRoots": list(profile["approved_roots"]),
                    },
                }
            )
        return payload


def _normalize_route(value: str, default: str) -> str:
    route = str(value or "").strip()
    if not route:
        route = default
    if not route.startswith("/"):
        route = "/" + route
    return route


def _load_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("rb") as handle:
        return tomllib.load(handle)


def _coerce_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


_POLICY_FIELDS = (
    "read_only",
    "allow_scene_edit",
    "allow_file_write",
    "approved_roots",
    "enable_exec_tools",
    "enable_stdio_bridge",
)
_ENV_FIELDS = {
    "host": "HOCUSPOCUS_HOST",
    "port": "HOCUSPOCUS_PORT",
    "mcp_route": "HOCUSPOCUS_MCP_ROUTE",
    "health_route": "HOCUSPOCUS_HEALTH_ROUTE",
    "token_mode": "HOCUSPOCUS_TOKEN_MODE",
    "token": "HOCUSPOCUS_TOKEN",
    "auto_start": "HOCUSPOCUS_AUTO_START",
    "log_level": "HOCUSPOCUS_LOG_LEVEL",
    "request_timeout_seconds": "HOCUSPOCUS_REQUEST_TIMEOUT_SECONDS",
    "read_only": "HOCUSPOCUS_READ_ONLY",
    "allow_scene_edit": "HOCUSPOCUS_ALLOW_SCENE_EDIT",
    "allow_file_write": "HOCUSPOCUS_ALLOW_FILE_WRITE",
    "enable_exec_tools": "HOCUSPOCUS_ENABLE_EXEC_TOOLS",
    "enable_stdio_bridge": "HOCUSPOCUS_ENABLE_STDIO_BRIDGE",
}
_BOOL_FIELDS = {
    "auto_start",
    "read_only",
    "allow_scene_edit",
    "allow_file_write",
    "enable_exec_tools",
    "enable_stdio_bridge",
}


def _apply_policy_values(settings: ServerSettings, values: dict[str, Any]) -> None:
    for key in _POLICY_FIELDS:
        if key not in values:
            continue
        value = values[key]
        if key == "approved_roots":
            value = [str(item) for item in value]
        else:
            value = bool(value)
        setattr(settings, key, value)


def _apply_environment(settings: ServerSettings) -> None:
    for key, variable in _ENV_FIELDS.items():
        value = os.environ.get(variable)
        if value is None:
            continue
        if key == "port":
            resolved: Any = int(value)
        elif key == "request_timeout_seconds":
            resolved = float(value)
        elif key in _BOOL_FIELDS:
            resolved = _coerce_bool(value)
        else:
            resolved = value
        setattr(settings, key, resolved)


def load_settings(config_path: str | Path | None = None) -> ServerSettings:
    path = Path(config_path) if config_path else paths.config_path()
    payload = _load_toml(path)
    policy_overrides = payload.get("policy_overrides", {})
    if not isinstance(policy_overrides, dict):
        policy_overrides = {}
    env_profile = os.environ.get("HOCUSPOCUS_POLICY_PROFILE")
    profile_explicit = "policy_profile" in payload or env_profile is not None
    profile_name, profile_defaults = resolve_policy_profile(
        env_profile if env_profile is not None else payload.get("policy_profile")
    )

    feature_flags = {
        key: bool(value)
        for key, value in payload.get("feature_flags", {}).items()
    }

    settings = ServerSettings(
        host=str(payload.get("host", "127.0.0.1")),
        port=int(payload.get("port", 37219)),
        mcp_route=str(payload.get("mcp_route", "/hocuspocus/mcp")),
        health_route=str(payload.get("health_route", "/hocuspocus/healthz")),
        token_mode=str(payload.get("token_mode", "generated")),
        token=str(payload.get("token", "")),
        auto_start=bool(payload.get("auto_start", False)),
        log_level=str(payload.get("log_level", "INFO")),
        request_timeout_seconds=float(payload.get("request_timeout_seconds", 30.0)),
        policy_profile=profile_name,
        policy_profile_source="environment" if env_profile is not None else ("config" if profile_explicit else "default"),
        read_only=bool(profile_defaults["read_only"]),
        allow_scene_edit=bool(profile_defaults["allow_scene_edit"]),
        allow_file_write=bool(profile_defaults["allow_file_write"]),
        approved_roots=[str(item) for item in profile_defaults["approved_roots"]],
        enable_exec_tools=bool(profile_defaults["enable_exec_tools"]),
        enable_stdio_bridge=bool(profile_defaults["enable_stdio_bridge"]),
        feature_flags=feature_flags,
        config_path=str(path),
    )

    if not profile_explicit:
        _apply_policy_values(settings, payload)
    _apply_policy_values(settings, policy_overrides)
    _apply_environment(settings)

    roots_override = os.environ.get("HOCUSPOCUS_APPROVED_ROOTS")
    if roots_override:
        settings.approved_roots = [
            item.strip()
            for item in roots_override.split(os.pathsep)
            if item.strip()
        ]

    return settings
